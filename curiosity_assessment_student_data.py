import json
from sqlalchemy import select, and_, update, func
from datetime import datetime, timezone
from redis_client import redis_client
from curiosity_assessment_evaluation import update_topic_coverage

_REDIS_SESSION_TTL = 7200   # 2 hours


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _redis_session_key(ca_id, student_id):
    return "ca_session:{}:{}".format(ca_id, student_id)


def _default_session_state():
    return {
        "current_topic":               "",
        "same_topic_streak":           0,
        "is_deepening":                False,
        "previous_scaffold":           {"strategy": "", "parameters": []},
        "previous_bloom":              0,
        "previous_depth":              0,
        "bridging_bonus_total":        0,
        "question_count":              0,
        "consecutive_low_score_count": 0,
        "topic_map":                   [],
        "question_topic_history":      [],
        "previous_questions":          [],
    }


def _apply_session_mutations(session_state, question_text, eval_result):
    """Pure Python — mutates session_state in place with one question's eval result."""
    scores    = eval_result.get("scores", {})
    new_topic = eval_result.get("current_topic", "")
    old_topic = session_state.get("current_topic", "")
    composite = float(scores.get("composite_score", 0.0))
    new_bloom = int(scores.get("bloom_b", 0))
    new_depth = int(scores.get("depth_d", 0))

    if new_topic and new_topic == old_topic:
        session_state["same_topic_streak"] = session_state.get("same_topic_streak", 0) + 1
    else:
        session_state["same_topic_streak"] = 0
    session_state["current_topic"] = new_topic

    session_state["is_deepening"] = new_bloom > session_state.get("previous_bloom", 0)

    if composite < 3.5:
        session_state["consecutive_low_score_count"] = session_state.get("consecutive_low_score_count", 0) + 1
    else:
        session_state["consecutive_low_score_count"] = 0

    scaffold = eval_result.get("scaffold_assigned", {})
    if scaffold.get("strategy") not in ("encouragement", "yield"):
        session_state["previous_scaffold"] = scaffold

    session_state["previous_bloom"]       = new_bloom
    session_state["previous_depth"]       = new_depth
    session_state["bridging_bonus_total"] = session_state.get("bridging_bonus_total", 0) + int(scores.get("bridging_bonus", 0))
    session_state["question_count"]       = session_state.get("question_count", 0) + 1

    prev_qs = session_state.setdefault("previous_questions", [])
    prev_qs.append({
        "text":             question_text,
        "relevance_r":      float(scores.get("relevance_r", 0.0)),
        "bloom_b":          new_bloom,
        "depth_d":          new_depth,
        "current_topic":    new_topic,
        "question_reframe": eval_result.get("reframed_question"),
    })
    if len(prev_qs) > 10:
        session_state["previous_questions"] = prev_qs[-10:]

    update_topic_coverage(session_state, {
        "topics": eval_result.get("topics", []),
        "bloom":  new_bloom,
    })


# ── /getCuriosityAssessmentDetailsAndLiveQuestionCards ────────────────────────
# Returns:
#   (200, message, data)   on success
#   (4xx, message, None)   on business-rule failure
#
# Side effect on first call only: records started_at and flips status →
# 'writing' in ca_has_students, anchoring the server-side countdown timer.
# Every subsequent call recomputes seconds_remaining from that anchor, so the
# timer survives page refreshes and reconnections.
# ─────────────────────────────────────────────────────────────────────────────
def getLiveAssessmentDetailsAndQuestionCards(student_id, ca_id, db, metadata):
    curiosity_assessment    = metadata.tables['curiosity_assessment']
    ca_has_students         = metadata.tables['ca_has_students']
    ca_question_submissions = metadata.tables['ca_question_submissions']

    # 1. Fetch assessment row
    assmt = db.execute(
        select(curiosity_assessment).where(
            and_(
                curiosity_assessment.c.assmt_id == ca_id,
                curiosity_assessment.c.is_deleted == 0
            )
        )
    ).mappings().fetchone()

    if not assmt:
        return 400, "Assessment not found", None

    if assmt['status'] != 'live':
        return 400, "Assessment is not currently live", None

    # 2. Confirm student is enrolled
    student_row = db.execute(
        select(ca_has_students).where(
            and_(
                ca_has_students.c.ca_id      == ca_id,
                ca_has_students.c.student_id == student_id
            )
        )
    ).mappings().fetchone()

    if not student_row:
        return 403, "Student is not enrolled in this assessment", None

    if student_row['status'] == 'submitted':
        return 400, "Assessment already submitted", None

    # 3. Timer anchor: set started_at on first entry, recompute on re-entry
    now = _utcnow()
    if student_row['started_at'] is None:
        db.execute(
            update(ca_has_students).where(
                and_(
                    ca_has_students.c.ca_id      == ca_id,
                    ca_has_students.c.student_id == student_id
                )
            ).values(started_at=now, status='writing')
        )
        db.commit()
        started_at = now
    else:
        started_at = student_row['started_at']

    total_seconds    = assmt['duration_minutes'] * 60
    elapsed          = int((now - started_at).total_seconds())
    seconds_remaining = max(0, total_seconds - elapsed)

    # 4. Fetch previously scored question cards for this student
    q_rows = db.execute(
        select(
            ca_question_submissions.c.q_id,
            ca_question_submissions.c.question_number,
            ca_question_submissions.c.question,
            ca_question_submissions.c.r_score,
            ca_question_submissions.c.b_score,
            ca_question_submissions.c.d_score,
            ca_question_submissions.c.composite_score,
            ca_question_submissions.c.verdict
        ).where(
            and_(
                ca_question_submissions.c.ca_id      == ca_id,
                ca_question_submissions.c.student_id == student_id
            )
        ).order_by(ca_question_submissions.c.question_number)
    ).mappings().all()

    # 5. Build response
    # doc_url is None when source_kind = 'topic'; S3 generation for topic-based
    # passages is handled asynchronously before the test starts (handled separately).
    data = {
        "assessment": {
            "ca_id":            assmt['assmt_id'],
            "title":            assmt['assmt_title'],
            "subject_code":     assmt['subject_code'],
            "question_count":   assmt['question_count'],
            "duration_minutes": assmt['duration_minutes'],
            "source_kind":     assmt['source_kind'],
            "doc_name":         assmt['doc_name'],
            "doc_url":          assmt['doc_storage_url']
        },
        "attempt": {
            "status":            "writing",
            "seconds_remaining": seconds_remaining
        },
        "question_cards": [
            {
                "q_id":            q['q_id'],
                "question_number": q['question_number'],
                "question":        q['question'],
                "r_score":         float(q['r_score'])         if q['r_score']         is not None else None,
                "b_score":         float(q['b_score'])         if q['b_score']         is not None else None,
                "d_score":         float(q['d_score'])         if q['d_score']         is not None else None,
                "composite_score": float(q['composite_score']) if q['composite_score'] is not None else None,
                "verdict":         q['verdict']
            }
            for q in q_rows
        ]
    }

    return 200, "Successfully fetched Data", data


# ── /getCuriosityAssessmentEndResults ────────────────────────────────────────
# Returns:
#   (200, message, data)   on success
#   (4xx, message, None)   on business-rule failure
#
# 3 queries total:
#   1. JOIN curiosity_assessment + ca_has_students; scalar subquery for
#      subject_name (correlated, LIMIT 1 — avoids row multiplication).
#      Pre-stored aggregates in ca_has_students are used directly.
#   2. ca_question_submissions — all coaching fields unlocked post-submission.
#   3. ca_faculty_feedback — per-student messages ordered by sent_at.
#
# best_score and questions_submitted are derived in Python from query-2 results
# rather than adding extra DB aggregation.
# ─────────────────────────────────────────────────────────────────────────────
def getCuriosityAssessmentEndResults(student_id, ca_id, db, metadata):
    curiosity_assessment    = metadata.tables['curiosity_assessment']
    ca_has_students         = metadata.tables['ca_has_students']
    ca_question_submissions = metadata.tables['ca_question_submissions']
    ca_faculty_feedback     = metadata.tables['ca_faculty_feedback']
    college_subject_mapping = metadata.tables['college_subject_mapping']
    subject_semester_new    = metadata.tables['subject_semester_new']
    subject_master          = metadata.tables['subject_master']

    # Correlated scalar subquery — resolves subject_code → subject name
    subject_name_sub = (
        select(subject_master.c.name)
        .select_from(
            college_subject_mapping
            .join(subject_semester_new, subject_semester_new.c.id == college_subject_mapping.c.subject_semester_id)
            .join(subject_master, subject_master.c.id == subject_semester_new.c.subject_master_id)
        )
        .where(college_subject_mapping.c.subject_code == curiosity_assessment.c.subject_code)
        .limit(1)
        .correlate(curiosity_assessment)
        .scalar_subquery()
    )

    # Query 1: assessment + student summary (single row)
    row = db.execute(
        select(
            curiosity_assessment.c.assmt_id,
            curiosity_assessment.c.assmt_title,
            curiosity_assessment.c.subject_code,
            curiosity_assessment.c.question_count,
            curiosity_assessment.c.duration_minutes,
            curiosity_assessment.c.source_kind,
            curiosity_assessment.c.doc_name,
            curiosity_assessment.c.doc_storage_url,
            ca_has_students.c.status,
            ca_has_students.c.avg_r_score,
            ca_has_students.c.avg_b_score,
            ca_has_students.c.avg_d_score,
            ca_has_students.c.avg_composite_score,
            ca_has_students.c.time_elapsed_seconds,
            ca_has_students.c.submitted_at,
            subject_name_sub.label('subject_name')
        )
        .join(ca_has_students, and_(
            ca_has_students.c.ca_id      == curiosity_assessment.c.assmt_id,
            ca_has_students.c.student_id == student_id
        ))
        .where(and_(
            curiosity_assessment.c.assmt_id == ca_id,
            curiosity_assessment.c.is_deleted == 0
        ))
    ).mappings().fetchone()

    if not row:
        return 400, "Assessment not found or student not enrolled", None

    if row['status'] != 'submitted':
        return 400, "Results are only available after submitting the assessment", None

    # Query 2: all question cards (coaching fields unlocked post-submission)
    q_rows = db.execute(
        select(
            ca_question_submissions.c.q_id,
            ca_question_submissions.c.question_number,
            ca_question_submissions.c.question,
            ca_question_submissions.c.r_score,
            ca_question_submissions.c.b_score,
            ca_question_submissions.c.d_score,
            ca_question_submissions.c.composite_score,
            ca_question_submissions.c.verdict,
            ca_question_submissions.c.ai_feedback,
            ca_question_submissions.c.question_reframe,
            ca_question_submissions.c.nudge
        )
        .where(and_(
            ca_question_submissions.c.ca_id      == ca_id,
            ca_question_submissions.c.student_id == student_id
        ))
        .order_by(ca_question_submissions.c.question_number)
    ).mappings().all()

    # Query 3: faculty feedback
    fb_rows = db.execute(
        select(
            ca_faculty_feedback.c.feedback_id,
            ca_faculty_feedback.c.message,
            ca_faculty_feedback.c.sent_at
        )
        .where(and_(
            ca_faculty_feedback.c.ca_id      == ca_id,
            ca_faculty_feedback.c.student_id == student_id
        ))
        .order_by(ca_faculty_feedback.c.sent_at)
    ).mappings().all()

    # Derived from q_rows — no extra DB call
    scores              = [float(q['composite_score']) for q in q_rows if q['composite_score'] is not None]
    best_score          = max(scores) if scores else None
    questions_submitted = len(q_rows)

    data = {
        "assessment": {
            "ca_id":            row['assmt_id'],
            "title":            row['assmt_title'],
            "subject_code":     row['subject_code'],
            "subject_name":     row['subject_name'],
            "question_count":   row['question_count'],
            "duration_minutes": row['duration_minutes'],
            "source_kind":     row['source_kind'],
            "doc_name":         row['doc_name'],
            "doc_url":          row['doc_storage_url']
        },
        "attempt_summary": {
            "questions_submitted":  questions_submitted,
            "best_score":           best_score,
            "avg_composite_score":  float(row['avg_composite_score']) if row['avg_composite_score'] is not None else None,
            "avg_r_score":          float(row['avg_r_score'])         if row['avg_r_score']         is not None else None,
            "avg_b_score":          float(row['avg_b_score'])         if row['avg_b_score']         is not None else None,
            "avg_d_score":          float(row['avg_d_score'])         if row['avg_d_score']         is not None else None,
            "time_elapsed_seconds": row['time_elapsed_seconds'],
            "submitted_at":         row['submitted_at'].isoformat() if row['submitted_at'] else None
        },
        "question_cards": [
            {
                "q_id":             q['q_id'],
                "question_number":  q['question_number'],
                "question":         q['question'],
                "r_score":          float(q['r_score'])         if q['r_score']         is not None else None,
                "b_score":          float(q['b_score'])         if q['b_score']         is not None else None,
                "d_score":          float(q['d_score'])         if q['d_score']         is not None else None,
                "composite_score":  float(q['composite_score']) if q['composite_score'] is not None else None,
                "verdict":          q['verdict'],
                "ai_feedback":      q['ai_feedback'],
                "question_reframe": q['question_reframe'],
                "nudge":            q['nudge']
            }
            for q in q_rows
        ],
        "faculty_feedback": [
            {
                "feedback_id": fb['feedback_id'],
                "message":     fb['message'],
                "sent_at":     fb['sent_at'].isoformat() if fb['sent_at'] else None
            }
            for fb in fb_rows
        ]
    }

    return 200, "Successfully fetched Data", data


# ── /evaluateCuriosityAssessmentQuestions — context loader ────────────────────
# Validates the assessment and student state, loads the Redis session, and
# returns everything the streaming evaluator needs in one round-trip.
#
# Returns:
#   (200, "ok", {vector_store_id, session_state, question_number, skip_bridging_bonus})
#   (4xx/503, message, None)  on any business-rule failure
# ─────────────────────────────────────────────────────────────────────────────
def getEvaluationContext(student_id, ca_id, db, metadata):
    curiosity_assessment    = metadata.tables['curiosity_assessment']
    ca_has_students         = metadata.tables['ca_has_students']
    ca_question_submissions = metadata.tables['ca_question_submissions']

    # Single JOIN — assessment + student enrolment in one query
    row = db.execute(
        select(
            curiosity_assessment.c.status,
            curiosity_assessment.c.source_kind,
            curiosity_assessment.c.vector_store_id,
            curiosity_assessment.c.question_count,
            ca_has_students.c.status.label('student_status'),
        )
        .join(ca_has_students, and_(
            ca_has_students.c.ca_id      == curiosity_assessment.c.assmt_id,
            ca_has_students.c.student_id == student_id,
        ))
        .where(and_(
            curiosity_assessment.c.assmt_id   == ca_id,
            curiosity_assessment.c.is_deleted == 0,
        ))
    ).mappings().fetchone()

    if not row:
        return 400, "Assessment not found or student not enrolled", None
    if row['status'] != 'live':
        return 400, "Assessment is not currently live", None
    if row['source_kind'] != 'document':
        return 400, "AI evaluation is only available for document-based assessments", None
    if not row['vector_store_id']:
        return 503, "Document is still being indexed — please try again shortly", None
    if row['student_status'] == 'submitted':
        return 400, "Assessment already submitted", None
    if row['student_status'] == 'not_started':
        return 400, "Assessment has not been started — open the assessment before submitting questions", None

    # Count questions already scored for this student in this assessment
    count_row = db.execute(
        select(func.count(ca_question_submissions.c.q_id).label('cnt'))
        .where(and_(
            ca_question_submissions.c.ca_id      == ca_id,
            ca_question_submissions.c.student_id == student_id,
        ))
    ).mappings().fetchone()

    current_count = int(count_row['cnt']) if count_row else 0
    if current_count >= int(row['question_count']):
        return 400, "Maximum number of questions reached for this assessment", None

    # Load Redis session state; fall back to blank defaults if key is missing/corrupt
    raw_state = redis_client.get(_redis_session_key(ca_id, student_id))
    if raw_state:
        try:
            session_state = json.loads(raw_state)
        except Exception:
            session_state = _default_session_state()
    else:
        session_state = _default_session_state()

    return 200, "ok", {
        "vector_store_id":     row['vector_store_id'],
        "session_state":       session_state,
        "question_number":     current_count + 1,
        "skip_bridging_bonus": current_count == 0,   # no prior context on first question
    }


# ── /evaluateCuriosityAssessmentQuestions — persistence ───────────────────────
# Called by the streaming endpoint after all SSE chunks are exhausted.
# Inserts the scored question, recomputes per-student averages, then flushes
# the updated session state to Redis — all in a single DB transaction.
#
# Gate hard-stops and LLM fallbacks carry skip_history=True; this function
# returns immediately without touching DB or Redis for those cases.
# ─────────────────────────────────────────────────────────────────────────────
def saveQuestionEvaluation(student_id, ca_id, question_text, question_number, eval_result, session_state, db, metadata):
    if eval_result.get("skip_history"):
        return

    ca_question_submissions = metadata.tables['ca_question_submissions']
    ca_has_students         = metadata.tables['ca_has_students']

    scores = eval_result.get("scores", {})
    now    = _utcnow()

    try:
        db.execute(
            ca_question_submissions.insert().values(
                ca_id            = ca_id,
                student_id       = student_id,
                question_number  = question_number,
                question         = question_text,
                r_score          = scores.get("relevance_r"),
                b_score          = scores.get("bloom_b"),
                d_score          = scores.get("depth_d"),
                composite_score  = scores.get("composite_score"),
                verdict          = eval_result.get("verdict") or None,
                ai_feedback      = eval_result.get("feedback") or None,
                question_reframe = eval_result.get("reframed_question") or None,
                nudge            = None,
                submitted_at     = now,
            )
        )

        # Recompute per-student averages over all questions including the one just inserted.
        # The session autoflushes the INSERT before this SELECT executes.
        avg_row = db.execute(
            select(
                func.avg(ca_question_submissions.c.r_score).label('avg_r'),
                func.avg(ca_question_submissions.c.b_score).label('avg_b'),
                func.avg(ca_question_submissions.c.d_score).label('avg_d'),
                func.avg(ca_question_submissions.c.composite_score).label('avg_composite'),
            ).where(and_(
                ca_question_submissions.c.ca_id      == ca_id,
                ca_question_submissions.c.student_id == student_id,
            ))
        ).mappings().fetchone()

        db.execute(
            update(ca_has_students)
            .where(and_(
                ca_has_students.c.ca_id      == ca_id,
                ca_has_students.c.student_id == student_id,
            ))
            .values(
                avg_r_score         = float(avg_row['avg_r'])         if avg_row['avg_r']         is not None else None,
                avg_b_score         = float(avg_row['avg_b'])         if avg_row['avg_b']         is not None else None,
                avg_d_score         = float(avg_row['avg_d'])         if avg_row['avg_d']         is not None else None,
                avg_composite_score = float(avg_row['avg_composite']) if avg_row['avg_composite'] is not None else None,
            )
        )

        db.commit()
    except Exception:
        db.rollback()
        raise

    # Mutate session state and write to Redis after commit — keeps them in sync;
    # a DB failure leaves Redis at the prior clean state rather than ahead of it
    _apply_session_mutations(session_state, question_text, eval_result)
    redis_client.set(
        _redis_session_key(ca_id, student_id),
        json.dumps(session_state),
        ex=_REDIS_SESSION_TTL,
    )
