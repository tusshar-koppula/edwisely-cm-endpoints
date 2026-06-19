import json
import os
from flask import Blueprint, Response, jsonify, request, current_app, stream_with_context
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import curiosity_assessment_student_data
from auth import authorize
from database import get_db, metadata
from curiosity_assessment_evaluation import call_evaluator_streaming

curiosity_student = Blueprint('curiosity_student', __name__, url_prefix='/curiosity-student')


# ── Route — /getCuriosityAssessmentDetailsAndLiveQuestionCards (GET) ──────────

@curiosity_student.route('/getCuriosityAssessmentDetailsAndLiveQuestionCards', methods=['GET'])
@authorize
def getCuriosityAssessmentDetailsAndLiveQuestionCards(user):
    student_id = user.get('user_id')
    ca_id      = request.args.get('ca_id')

    if not ca_id:
        return jsonify({"status": 422, "message": "ca_id is missing"})
    try:
        ca_id = int(ca_id)
    except ValueError:
        return jsonify({"status": 422, "message": "ca_id must be an integer"})

    try:
        db = get_db()
        status, message, data = curiosity_assessment_student_data.getLiveAssessmentDetailsAndQuestionCards(
            student_id, ca_id, db, metadata
        )
        if data is not None:
            return jsonify({"status": status, "message": message, "data": data})
        else:
            return jsonify({"status": status, "message": message})

    except Exception as e:
        subject = "server:- {}, Error in /curiosity-student/getCuriosityAssessmentDetailsAndLiveQuestionCards".format(
            os.environ.get('FLASK_ENV')
        )
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(
                from_email='noreply@edwisely.com',
                to_emails='alerts@edwisely.com',
                subject=subject,
                plain_text_content=str(e)
            ))
        except Exception:
            pass
        current_app.logger.error(
            '/curiosity-student/getCuriosityAssessmentDetailsAndLiveQuestionCards - EXCEPTION: {}'.format(e)
        )
        return jsonify({"status": 500, "message": str(e)})


# ── Route — /getCuriosityAssessmentEndResults (GET) ───────────────────────────

@curiosity_student.route('/getCuriosityAssessmentEndResults', methods=['GET'])
@authorize
def getCuriosityAssessmentEndResults(user):
    student_id = user.get('user_id')
    ca_id      = request.args.get('ca_id')

    if not ca_id:
        return jsonify({"status": 422, "message": "ca_id is missing"})
    try:
        ca_id = int(ca_id)
    except ValueError:
        return jsonify({"status": 422, "message": "ca_id must be an integer"})

    try:
        db = get_db()
        status, message, data = curiosity_assessment_student_data.getCuriosityAssessmentEndResults(
            student_id, ca_id, db, metadata
        )
        if data is not None:
            return jsonify({"status": status, "message": message, "data": data})
        else:
            return jsonify({"status": status, "message": message})

    except Exception as e:
        subject = "server:- {}, Error in /curiosity-student/getCuriosityAssessmentEndResults".format(
            os.environ.get('FLASK_ENV')
        )
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(
                from_email='noreply@edwisely.com',
                to_emails='alerts@edwisely.com',
                subject=subject,
                plain_text_content=str(e)
            ))
        except Exception:
            pass
        current_app.logger.error(
            '/curiosity-student/getCuriosityAssessmentEndResults - EXCEPTION: {}'.format(e)
        )
        return jsonify({"status": 500, "message": str(e)})


# ── Route — /evaluateCuriosityAssessmentQuestions (POST, SSE) ─────────────────

@curiosity_student.route('/evaluateCuriosityAssessmentQuestions', methods=['POST'])
@authorize
def evaluateCuriosityAssessmentQuestions(user):
    student_id    = user.get('user_id')
    body          = request.get_json(silent=True) or {}
    ca_id         = body.get('ca_id')
    question_text = (body.get('question') or '').strip()

    if not ca_id:
        return jsonify({"status": 422, "message": "ca_id is missing"})
    if not question_text:
        return jsonify({"status": 422, "message": "question is missing"})
    try:
        ca_id = int(ca_id)
    except (ValueError, TypeError):
        return jsonify({"status": 422, "message": "ca_id must be an integer"})

    # Validate and load context before opening the stream — a normal JSON error
    # response is still possible here since no SSE headers have been sent yet
    try:
        db = get_db()
        status, message, ctx = curiosity_assessment_student_data.getEvaluationContext(
            student_id, ca_id, db, metadata
        )
    except Exception as e:
        subject = "server:- {}, Error in /curiosity-student/evaluateCuriosityAssessmentQuestions [context]".format(
            os.environ.get('FLASK_ENV')
        )
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(
                from_email='noreply@edwisely.com',
                to_emails='alerts@edwisely.com',
                subject=subject,
                plain_text_content=str(e)
            ))
        except Exception:
            pass
        current_app.logger.error(
            '/curiosity-student/evaluateCuriosityAssessmentQuestions [context] - EXCEPTION: {}'.format(e)
        )
        return jsonify({"status": 500, "message": str(e)})

    if status != 200:
        return jsonify({"status": status, "message": message})

    def generate():
        eval_result = {}
        try:
            for chunk in call_evaluator_streaming(
                student_question    = question_text,
                vector_store_id     = ctx['vector_store_id'],
                session_state       = ctx['session_state'],
                skip_bridging_bonus = ctx['skip_bridging_bonus'],
            ):
                # Accumulate all non-terminal chunks so saveQuestionEvaluation
                # receives a single merged dict with scores + coaching fields
                if chunk.get("stage") != "done":
                    eval_result.update(chunk)
                yield "data: {}\n\n".format(json.dumps(chunk))

            # Stream complete — persist question, update averages, flush Redis
            curiosity_assessment_student_data.saveQuestionEvaluation(
                student_id      = student_id,
                ca_id           = ca_id,
                question_text   = question_text,
                question_number = ctx['question_number'],
                eval_result     = eval_result,
                session_state   = ctx['session_state'],
                db              = db,
                metadata        = metadata,
            )
        except Exception as e:
            subject = "server:- {}, Error in /curiosity-student/evaluateCuriosityAssessmentQuestions [stream]".format(
                os.environ.get('FLASK_ENV')
            )
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(
                    from_email='noreply@edwisely.com',
                    to_emails='alerts@edwisely.com',
                    subject=subject,
                    plain_text_content=str(e)
                ))
            except Exception:
                pass
            current_app.logger.error(
                '/curiosity-student/evaluateCuriosityAssessmentQuestions [stream] - EXCEPTION: {}'.format(e)
            )
            yield "data: {}\n\n".format(json.dumps({
                "stage":   "error",
                "message": "An error occurred during evaluation",
            }))

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={"Cache-Control": "no-cache"},
    )


