from flask import Blueprint, jsonify, request, current_app
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import curiosity_assessment_data
from auth import authorize
from database import get_db, metadata

curiosity_assessment = Blueprint('curiosity_assessment', __name__)


# ── Route 1 — /assessments (GET, POST) ───────────────────────────────────────

@curiosity_assessment.route('/assessments', methods=['GET', 'POST'])
@authorize
def handleAssessments(user):
    user_id = user.get('user_id')

    # ── GET — Library list ────────────────────────────────────────────────────
    if request.method == 'GET':
        status       = request.args.get('status')
        subject_code = request.args.get('subject_code')
        section_id   = request.args.get('section_id')
        if section_id is not None:
            section_id = int(section_id)

        try:
            db   = get_db()
            data = curiosity_assessment_data.getAssessments(user_id, db, metadata, status, subject_code, section_id)
            if data is not None:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /assessments".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/assessments - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    # ── POST — Create assessment ──────────────────────────────────────────────
    body = request.get_json()
    if not body:
        return jsonify({"status": 422, "message": "Request body is missing"})

    title            = body.get('title')
    source_kind      = body.get('source_kind')
    document_id      = body.get('document_id')
    topic_ids        = body.get('topic_ids')
    recipients       = body.get('recipients')
    question_count   = body.get('question_count')
    duration_minutes = body.get('duration_minutes')
    rubric           = body.get('rubric')
    description      = body.get('description')
    subject_code     = body.get('subject_code')
    start_time       = body.get('start_time')
    end_time         = body.get('end_time')
    status           = body.get('status', 'draft')

    if not title:            return jsonify({"status": 422, "message": "title is missing"})
    if not source_kind:      return jsonify({"status": 422, "message": "source_kind is missing"})
    if source_kind == 'document' and not document_id:
        return jsonify({"status": 422, "message": "document_id is required when source_kind is document"})
    if source_kind == 'topic' and not topic_ids:
        return jsonify({"status": 422, "message": "topic_ids is required when source_kind is topic"})
    if not recipients:       return jsonify({"status": 422, "message": "recipients is missing"})
    if not question_count:   return jsonify({"status": 422, "message": "question_count is missing"})
    if not duration_minutes: return jsonify({"status": 422, "message": "duration_minutes is missing"})
    if not rubric:           return jsonify({"status": 422, "message": "rubric is missing"})

    try:
        db   = get_db()
        data = curiosity_assessment_data.createAssessment(
            user_id, db, metadata,
            title, description, source_kind, document_id, topic_ids,
            subject_code, recipients, question_count, duration_minutes,
            start_time, end_time, rubric, status
        )
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})

    except Exception as e:
        subject = "server:- {}, Error in /assessments".format(os.environ.get('FLASK_ENV'))
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
        except Exception:
            pass
        current_app.logger.error('/assessments - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


# ── Route 1a — /assessments/filters (GET) ────────────────────────────────────

@curiosity_assessment.route('/assessments/filters', methods=['GET'])
@authorize
def getAssessmentFilters(user):
    user_id = user.get('user_id')

    try:
        db   = get_db()
        data = curiosity_assessment_data.getAssessmentFilters(user_id, db, metadata)
        if data is not None:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})

    except Exception as e:
        subject = "server:- {}, Error in /assessments/filters".format(os.environ.get('FLASK_ENV'))
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
        except Exception:
            pass
        current_app.logger.error('/assessments/filters - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


# ── Route 2 — /assessments/<assessment_id> (GET, PATCH, DELETE) ──────────────

@curiosity_assessment.route('/assessments/<int:assessment_id>', methods=['GET', 'PATCH', 'DELETE'])
@authorize
def handleAssessment(user, assessment_id):
    user_id = user.get('user_id')

    # ── DELETE — Soft delete / discard ───────────────────────────────────────
    if request.method == 'DELETE':
        try:
            db   = get_db()
            data = curiosity_assessment_data.deleteAssessment(user_id, db, metadata, assessment_id)
            if data:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /assessments/<assessment_id>".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/assessments/<assessment_id> - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    # ── PATCH — Update / end / share ─────────────────────────────────────────
    if request.method == 'PATCH':
        body = request.get_json()
        if not body:
            return jsonify({"status": 422, "message": "Request body is missing"})

        action = body.get('action')

        if action == 'end':
            try:
                db   = get_db()
                data = curiosity_assessment_data.endAssessment(user_id, db, metadata, assessment_id)
                if data:
                    return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
                else:
                    return jsonify({"status": 400, "message": "No Data Found!!"})

            except Exception as e:
                subject = "server:- {}, Error in /assessments/<assessment_id>".format(os.environ.get('FLASK_ENV'))
                try:
                    sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                    sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
                except Exception:
                    pass
                current_app.logger.error('/assessments/<assessment_id> - EXCEPTION: {}'.format(e))
                return jsonify({"status": 500, "message": "Failure"})

        if action == 'share':
            scope  = body.get('scope')
            emails = body.get('emails', [])

            if not scope: return jsonify({"status": 422, "message": "scope is missing"})

            try:
                db   = get_db()
                data = curiosity_assessment_data.shareAssessment(user_id, db, metadata, assessment_id, scope, emails)
                if data:
                    return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
                else:
                    return jsonify({"status": 400, "message": "No Data Found!!"})

            except Exception as e:
                subject = "server:- {}, Error in /assessments/<assessment_id>".format(os.environ.get('FLASK_ENV'))
                try:
                    sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                    sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
                except Exception:
                    pass
                current_app.logger.error('/assessments/<assessment_id> - EXCEPTION: {}'.format(e))
                return jsonify({"status": 500, "message": "Failure"})

        # No action — partial field update
        title            = body.get('title')
        description      = body.get('description')
        source_kind      = body.get('source_kind')
        document_id      = body.get('document_id')
        topic_ids        = body.get('topic_ids')
        subject_code     = body.get('subject_code')
        recipients       = body.get('recipients')
        question_count   = body.get('question_count')
        duration_minutes = body.get('duration_minutes')
        start_time       = body.get('start_time')
        end_time         = body.get('end_time')
        rubric           = body.get('rubric')
        status           = body.get('status')

        try:
            db   = get_db()
            data = curiosity_assessment_data.updateAssessment(
                user_id, db, metadata, assessment_id,
                title, description, source_kind, document_id, topic_ids,
                subject_code, recipients, question_count, duration_minutes,
                start_time, end_time, rubric, status
            )
            if data:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /assessments/<assessment_id>".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/assessments/<assessment_id> - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    # ── GET — All assessment reads (view param gates which query runs) ─────────
    view = request.args.get('view')
    if not view:
        return jsonify({"status": 422, "message": "view param is required"})

    # FIRST — stats (polled every ~5s, must return immediately)
    # For the Live Monitoring dashboard, polled every ~5s, must return immediately with pre-aggregated data
    if view == 'stats':
        try:
            db   = get_db()
            data = curiosity_assessment_data.getAssessmentStats(user_id, db, metadata, assessment_id)
            if data:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /assessments/<assessment_id>".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/assessments/<assessment_id> - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})
        
    # Live roster — polled during active assessment, lightweight (status + progress only)
    if view == 'roster':
        status = request.args.get('status')
        sort   = request.args.get('sort')

        try:
            db   = get_db()
            data = curiosity_assessment_data.getAssessmentRoster(
                user_id, db, metadata, assessment_id, status, sort
            )
            if data is not None:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /assessments/<assessment_id>".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/assessments/<assessment_id> - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    # Ended student list — heavy, includes scores + dimension breakdown + filters
    if view == 'students':
        status     = request.args.get('status')
        sort       = request.args.get('sort')
        score_band = request.args.get('score_band')

        try:
            db   = get_db()
            data = curiosity_assessment_data.getEndedAssessmentStudents(
                user_id, db, metadata, assessment_id, status, score_band, sort
            )
            if data is not None:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /assessments/<assessment_id>".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/assessments/<assessment_id> - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    # Syllabus drawer — returns document metadata or topic list depending on source_kind
    if view == 'syllabus':
        try:
            db   = get_db()
            data = curiosity_assessment_data.getAssessmentSyllabus(user_id, db, metadata, assessment_id)
            if data:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /assessments/<assessment_id>".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/assessments/<assessment_id> - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})


    if view == 'overview':
        try:
            db   = get_db()
            data = curiosity_assessment_data.getAssessmentOverview(user_id, db, metadata, assessment_id)
            if data:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /assessments/<assessment_id>".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/assessments/<assessment_id> - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    if view == 'top_questions':
        try:
            db   = get_db()
            data = curiosity_assessment_data.getTopQuestions(user_id, db, metadata, assessment_id)
            if data is not None:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /assessments/<assessment_id>".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/assessments/<assessment_id> - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    if view == 'similar':
        question_id = request.args.get('question_id')

        if not question_id: return jsonify({"status": 422, "message": "question_id is missing"})
        question_id = int(question_id)

        try:
            db   = get_db()
            data = curiosity_assessment_data.getSimilarQuestions(user_id, db, metadata, assessment_id, question_id)
            if data is not None:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /assessments/<assessment_id>".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/assessments/<assessment_id> - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    if view == 'export':
        fmt     = request.args.get('format')
        columns = request.args.getlist('columns[]')

        if not fmt: return jsonify({"status": 422, "message": "format is missing"})

        try:
            db   = get_db()
            data = curiosity_assessment_data.exportAssessment(user_id, db, metadata, assessment_id, fmt, columns)
            if data:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /assessments/<assessment_id>".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/assessments/<assessment_id> - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    return jsonify({"status": 422, "message": "unrecognised view param"})


# ── Route 3 (duplicate) — /assessments/<assessment_id>/duplicate (POST) ─────

@curiosity_assessment.route('/assessments/<int:assessment_id>/duplicate', methods=['POST'])
@authorize
def duplicateAssessment(user, assessment_id):
    user_id = user.get('user_id')

    try:
        db   = get_db()
        data = curiosity_assessment_data.duplicateAssessment(user_id, db, metadata, assessment_id)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})

    except Exception as e:
        subject = "server:- {}, Error in /assessments/<assessment_id>/duplicate".format(os.environ.get('FLASK_ENV'))
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
        except Exception:
            pass
        current_app.logger.error('/assessments/<assessment_id>/duplicate - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


# ── Route 3a — /assessments/<assessment_id>/students/<student_id>/stats (GET) ─

@curiosity_assessment.route('/assessments/<int:assessment_id>/students/<int:student_id>/stats', methods=['GET'])
@authorize
def getStudentStats(user, assessment_id, student_id):
    user_id = user.get('user_id')

    try:
        db   = get_db()
        data = curiosity_assessment_data.getStudentQuestions(user_id, db, metadata, assessment_id, student_id)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})

    except Exception as e:
        subject = "server:- {}, Error in /assessments/<assessment_id>/students/<student_id>/stats".format(os.environ.get('FLASK_ENV'))
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
        except Exception:
            pass
        current_app.logger.error('/assessments/<assessment_id>/students/<student_id>/stats - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


# ── Route 3b — /assessments/<assessment_id>/students/<student_id>/feedback (POST) ─

@curiosity_assessment.route('/assessments/<int:assessment_id>/students/<int:student_id>/feedback', methods=['POST'])
@authorize
def sendStudentFeedback(user, assessment_id, student_id):
    user_id = user.get('user_id')

    body = request.get_json()
    if not body:
        return jsonify({"status": 422, "message": "Request body is missing"})

    message = body.get('message')

    if not message: return jsonify({"status": 422, "message": "message is missing"})

    try:
        db   = get_db()
        data = curiosity_assessment_data.sendStudentFeedback(user_id, db, metadata, assessment_id, student_id, message)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})

    except Exception as e:
        subject = "server:- {}, Error in /assessments/<assessment_id>/students/<student_id>/feedback".format(os.environ.get('FLASK_ENV'))
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
        except Exception:
            pass
        current_app.logger.error('/assessments/<assessment_id>/students/<student_id>/feedback - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


# ── Route 4 — /compose-audience (GET) — audience selection filters ────────────
#
#   filter_type access rules:
#     sections    — faculty (own sections), hod (dept sections), principal (all)
#     semesters   — hod, principal only
#     departments — principal only
#     students    — faculty (own sections), hod (dept sections), principal (all)

@curiosity_assessment.route('/compose-audience', methods=['GET'])
@authorize
def getComposeAudience(user):
    user_id = user.get('user_id')

    role        = request.args.get('role')
    filter_type = request.args.get('filter_type')

    if not role:        return jsonify({"status": 422, "message": "role is missing"})
    if not filter_type: return jsonify({"status": 422, "message": "filter_type is missing"})

    if filter_type == 'sections':
        try:
            db   = get_db()
            data = curiosity_assessment_data.getSections(user_id, db, metadata, role)
            if data is not None:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /compose-audience".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/compose-audience - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    if filter_type == 'semesters':
        if role == 'faculty':
            return jsonify({"status": 403, "message": "Access denied"})

        department_code = request.args.get('department_code')

        try:
            db   = get_db()
            data = curiosity_assessment_data.getSemesters(user_id, db, metadata, role, department_code)
            if data is not None:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /compose-audience".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/compose-audience - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    if filter_type == 'departments':
        if role != 'principal':
            return jsonify({"status": 403, "message": "Access denied"})

        try:
            db   = get_db()
            data = curiosity_assessment_data.getDepartments(user_id, db, metadata)
            if data is not None:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /compose-audience".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/compose-audience - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    if filter_type == 'students':
        section_id = request.args.get('section_id')
        q          = request.args.get('q')
        if section_id is not None:
            section_id = int(section_id)

        try:
            db   = get_db()
            data = curiosity_assessment_data.getStudents(user_id, db, metadata, role, section_id, q)
            if data is not None:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /compose-audience".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/compose-audience - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    return jsonify({"status": 422, "message": "unrecognised filter_type param"})


# ── Route 5 — /compose-syllabus (GET) — subjects list + lazy topics load ─────

@curiosity_assessment.route('/compose-syllabus', methods=['GET'])
@authorize
def getComposeSyllabus(user):
    user_id = user.get('user_id')

    type_ = request.args.get('type')

    if not type_: return jsonify({"status": 422, "message": "type is missing"})

    if type_ == 'subjects':
        try:
            db   = get_db()
            data = curiosity_assessment_data.getSubjects(user_id, db, metadata)
            if data is not None:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /compose-syllabus".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/compose-syllabus - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    if type_ == 'topics':
        subject_code = request.args.get('subject_code')

        if not subject_code: return jsonify({"status": 422, "message": "subject_code is missing"})

        try:
            db   = get_db()
            data = curiosity_assessment_data.getTopics(user_id, db, metadata, subject_code)
            if data is not None:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /compose-syllabus".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/compose-syllabus - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    return jsonify({"status": 422, "message": "unrecognised type param"})


# ── Route 6 — /documents (POST) ──────────────────────────────────────────────

@curiosity_assessment.route('/documents', methods=['POST'])
@authorize
def uploadDocument(user):
    user_id = user.get('user_id')

    file = request.files.get('file')

    if not file: return jsonify({"status": 422, "message": "file is missing"})

    try:
        db   = get_db()
        data = curiosity_assessment_data.uploadDocument(user_id, db, metadata, file)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})

    except Exception as e:
        subject = "server:- {}, Error in /documents".format(os.environ.get('FLASK_ENV'))
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
        except Exception:
            pass
        current_app.logger.error('/documents - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})
