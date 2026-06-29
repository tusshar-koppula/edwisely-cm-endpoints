from gevent import monkey
monkey.patch_all()  # Must be the very first line.

import json, logging, os
import gevent
from dotenv import load_dotenv
load_dotenv()
import redis as _redis_lib
from flask import Flask, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

REDIS_URL    = os.getenv("REDIS_URL", os.getenv("REDIS_URL", "redis://localhost:6379/1"))
SOCKET_PORT  = int(os.getenv("CA_SOCKET_PORT", "5012"))
CORS_ORIGINS = os.getenv("APP_SOCKET_CORS", "*")

flask_app = Flask(__name__)
CORS(flask_app, origins=CORS_ORIGINS)

socketio = SocketIO(
    flask_app,
    cors_allowed_origins=CORS_ORIGINS,
    async_mode="gevent",
    # message_queue=REDIS_URL,  # re-enable for multi-worker production (gunicorn)
    channel="ca_socketio",  # distinct from "faculty_socketio" in app_socket.py
)

# Pool for regular Redis ops (cache reads, any future writes).
# Separate from the pub/sub connection — pubsub.listen() is blocking and puts
# the connection into subscribe mode, so it cannot be shared with normal ops.
# redis-py silently creates a new connection from the pool if one goes stale,
# giving free recovery for all _conn() callers without any extra retry logic.
_pool = _redis_lib.ConnectionPool.from_url(REDIS_URL, decode_responses=True, max_connections=10) #will be discussed later whether to implement or not.


def _conn():
    return _redis_lib.Redis(connection_pool=_pool) #USE THIS FOR ALL REGULAR REDIS OPS (cache reads, any future writes)


def _sid(): #only used for logs
    return getattr(request, "sid", "?")


def _start_curiosity_listener():
    """
    Background greenlet.
    Subscribes to app:curiosity:live:* and forwards each message to the
    matching /curiosity room so faculty browsers receive it in real time.

    Channel format : app:curiosity:live:assessment:{assessment_id}
    Room format    : live:assessment:{assessment_id}
    SocketIO event : "live"
    """
    while True:
        try:
            r = _redis_lib.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=None, socket_keepalive=True)
            pubsub = r.pubsub()
            pubsub.psubscribe("app:curiosity:live:*")
            log.info("Curiosity live listener subscribed to app:curiosity:live:*")

            for message in pubsub.listen():
                if message["type"] != "pmessage":
                    continue

                # "app:curiosity:live:assessment:{assessment_id}"
                # strip "app:" prefix → "curiosity:live:assessment:{id}"
                # split on ":" max 2 times → ["curiosity", "live", "assessment:{id}"]
                segments = message["channel"][4:].split(":", 2)
                if len(segments) < 3:
                    continue

                event_type = segments[1]  # "live"
                entity_id  = segments[2]  # "assessment:{assessment_id}"

                try:
                    payload = json.loads(message["data"])
                except (ValueError, TypeError):
                    log.warning("Malformed curiosity message on channel %s", message["channel"])
                    continue

                room = f"{event_type}:{entity_id}"  # "live:assessment:{assessment_id}"
                log.info("→ /curiosity room=%s payload_event=%s", room, payload.get("event"))
                socketio.emit(event_type, payload, room=room, namespace="/curiosity")

        except Exception as exc:
            log.error("Curiosity live listener error (reconnecting in 2s): %s", exc)
            gevent.sleep(2)


def _on_curiosity_subscribe(data):
    """
    Faculty browser sends: { "room": "live:assessment:{assessment_id}" }
    Joins the room — will receive all events published to that channel from
    this point forward. No done-cache check: the log is only accessible while
    the assessment is live, so there is no catch-up scenario.
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            data = {}
    room = (data or {}).get("room", "").strip()
    if not room:
        emit("error", {"message": "room is required"})
        return
    join_room(room)
    log.info("Faculty SID %s joined /curiosity room=%s", _sid(), room)


def _on_connect():
    log.info("Client connected:    SID=%s namespace=%s", _sid(), request.namespace)


def _on_disconnect():
    log.info("Client disconnected: SID=%s namespace=%s", _sid(), request.namespace)


socketio.on_event("connect",    _on_connect,             namespace="/curiosity")
socketio.on_event("disconnect", _on_disconnect,          namespace="/curiosity")
socketio.on_event("subscribe",  _on_curiosity_subscribe, namespace="/curiosity")

socketio.start_background_task(_start_curiosity_listener)


# ── REST API publish contract (for reference) ────────────────────────────────
#
# After each student action, publish to Redis:
#
#   redis_client.publish(
#       f"app:curiosity:live:assessment:{assessment_id}",
#       json.dumps({
#           "event":        "<event_type>",   # see table below
#           "student_id":   <int>,
#           "student_name": "<str>",
#           "timestamp":    "<ISO8601>",
#           # event-specific fields:
#           # submitted_question / leading  → question_id, question_number, question
#           # submitted_question_leading    → also includes score
#           # submitted_assessment          → question (last submitted question text)
#           # started_writing               → (no extra fields)
#       })
#   )
#
#   event value                 | trigger point
#   ─────────────────────────── | ──────────────────────────────────────────────
#   submitted_assessment        | after saving final assessment submission
#   submitted_question          | after saving individual question answer
#   started_writing             | after student enters the assessment window in fullscreen
#   submitted_question_leading  | after saving answer AND student is now rank 1
#
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("Curiosity Assessment socket server starting on port %d", SOCKET_PORT)
    socketio.run(flask_app, host="0.0.0.0", port=SOCKET_PORT)
