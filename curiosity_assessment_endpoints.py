from flask import Blueprint, jsonify, request, current_app
import os
import json
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import curiosity_assessment_data
from auth import authorize
from database import get_db, metadata

curiosity_assessment = Blueprint('curiosity_assessment', __name__, url_prefix='/curiosity-assessment')


# ── Route 1 — /getCuriosityAssessmentsList (GET) ───────────────────────────────────────

@curiosity_assessment.route('/getCuriosityAssessmentsList', methods=['GET']) # gets list of all Assessments
@authorize
def getCuriosityAssessmentsList(user):
    user_id = user.get('user_id')

    # ── GET — Library list ────────────────────────────────────────────────────
    if request.method == 'GET':
        status       = request.args.get('status')
        subject_code = request.args.get('subject_code')
        section_id   = request.args.get('section_id')
        q            = request.args.get('q')
        if section_id is not None:
            section_id = int(section_id)

        try:
            db   = get_db()
            data = curiosity_assessment_data.getAssessments(user_id, db, metadata, status, subject_code, section_id, q)
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})

        except Exception as e:
            subject = "server:- {}, Error in /getCuriosityAssessmentsList".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/getCuriosityAssessmentsList - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})


# ── Route — /getCuriosityAssessmentsFilters (GET) ────────────────────────────────────

@curiosity_assessment.route('/getCuriosityAssessmentsFilters', methods=['GET']) # getSection&SubjectFilters
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
        subject = "server:- {}, Error in /getCuriosityAssessmentsFilters".format(os.environ.get('FLASK_ENV'))
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
        except Exception:
            pass
        current_app.logger.error('/getCuriosityAssessmentsFilters - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})

@curiosity_assessment.route('/getCuriosityAssessmentsbyID', methods=['GET']) # get Assessment By ID
@authorize
def getAssessmentByID(user):
    user_id       = user.get('user_id')
    assessment_id = request.args.get('assessment_id')
    if not assessment_id:
        return jsonify({"status": 422, "message": "assessment_id is missing"})
    try:
        assessment_id = int(assessment_id)
    except ValueError:
        return jsonify({"status": 422, "message": "assessment_id must be an integer"})

    try:
        db   = get_db()
        data = curiosity_assessment_data.getAssessmentByID(user_id, db, metadata, assessment_id)

        if data is None:
            return jsonify({"status": 404, "message": "Assessment not found"})

        if '_status_error' in data:
            return jsonify({"status": 400, "message": "Assessment is {} — only draft and scheduled assessments can be opened".format(data['_status_error'])})

        return jsonify({"status": 200, "message": "Success", "data": data})

    except Exception as e:
        subject = "server:- {}, Error in /getCuriosityAssessmentsbyID".format(os.environ.get('FLASK_ENV'))
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
        except Exception:
            pass
        current_app.logger.error('/getCuriosityAssessmentsbyID - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


# ── Route — /getCuriosityAssessmentsSimilarQuestions (GET) ───────────────────────────────────────

@curiosity_assessment.route('/getCuriosityAssessmentsSimilarQuestions', methods=['GET'])
@authorize
def getCuriosityAssessmentsSimilarQuestions(user):
    q_id = request.args.get('q_id')
    if not q_id:
        return jsonify({"status": 422, "message": "q_id is missing"})
    try:
        q_id = int(q_id)
    except ValueError:
        return jsonify({"status": 422, "message": "q_id must be an integer"})

    try:
        db   = get_db()
        data = curiosity_assessment_data.getSimilarQuestions(db, metadata, q_id)

        if data is None:
            return jsonify({"status": 404, "message": "Question not found"})

        return jsonify({"status": 200, "message": "Success", "data": {"q_id": q_id, "similar_questions": data}})

    except Exception as e:
        subject = "server:- {}, Error in /getCuriosityAssessmentsSimilarQuestions".format(os.environ.get('FLASK_ENV'))
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
        except Exception:
            pass
        current_app.logger.error('/getCuriosityAssessmentsSimilarQuestions - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


# ── Route 2 — /createOrUpdateCuriosityAssessments/<int:assessment_id> (POST, PATCH) ──────────────

@curiosity_assessment.route('/createOrUpdateCuriosityAssessments', methods=['POST', 'PATCH']) # create or update Assessment
@authorize
def createOrUpdateAssessment(user):
    user_id = user.get('user_id')

    if request.method == 'POST':
        # ── POST — Create assessment ──────────────────────────────────────────────
        title            = request.form.get('title')
        source_kind      = request.form.get('source_kind')
        topic_ids_raw    = request.form.get('topic_ids')
        recipients_raw   = request.form.get('recipients')
        question_count   = request.form.get('question_count')
        duration_minutes = request.form.get('duration_minutes')
        rubric_raw       = request.form.get('rubric')
        description      = request.form.get('description')
        subject_code     = request.form.get('subject_code')
        start_time       = request.form.get('start_time')
        end_time         = request.form.get('end_time')
        status           = request.form.get('status', 'draft')

        topic_ids  = json.loads(topic_ids_raw)  if topic_ids_raw  else None
        recipients = json.loads(recipients_raw) if recipients_raw else None
        rubric     = json.loads(rubric_raw)     if rubric_raw     else None

        if not title:            return jsonify({"status": 422, "message": "title is missing"})
        if not source_kind:      return jsonify({"status": 422, "message": "source_kind is missing"})
        if source_kind == 'document' and not request.files.get('file'):
            return jsonify({"status": 422, "message": "file is required when source_kind is document"})
        if source_kind == 'topic' and not topic_ids:
            return jsonify({"status": 422, "message": "topic_ids is required when source_kind is topic"})
        if not recipients:       return jsonify({"status": 422, "message": "recipients is missing"})
        if not question_count:   return jsonify({"status": 422, "message": "question_count is missing"})
        if not duration_minutes: return jsonify({"status": 422, "message": "duration_minutes is missing"})
        if not rubric:           return jsonify({"status": 422, "message": "rubric is missing"})

        question_count   = int(question_count)
        duration_minutes = int(duration_minutes)

        try:
            db = get_db()
            document_id = None
            if source_kind == 'document':
                upload_result = curiosity_assessment_data.uploadDocument(user_id, db, metadata, request.files.get('file'))
                document_id = upload_result['document_id']

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
            subject = "server:- {}, Error in /createOrUpdateCuriosityAssessments POST".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/createOrUpdateCuriosityAssessments POST - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    # ── PATCH — Update ─────────────────────────────────────────
    if request.method == 'PATCH':
        assessment_id_raw = request.form.get('assessment_id')
        if not assessment_id_raw:
            return jsonify({"status": 422, "message": "assessment_id is missing"})
        assessment_id = int(assessment_id_raw)

        title            = request.form.get('title')
        description      = request.form.get('description')
        source_kind      = request.form.get('source_kind')
        topic_ids_raw    = request.form.get('topic_ids')
        recipients_raw   = request.form.get('recipients')
        subject_code     = request.form.get('subject_code')
        question_count   = request.form.get('question_count')
        duration_minutes = request.form.get('duration_minutes')
        start_time       = request.form.get('start_time')
        end_time         = request.form.get('end_time')
        rubric_raw       = request.form.get('rubric')
        status           = request.form.get('status')

        topic_ids  = json.loads(topic_ids_raw)  if topic_ids_raw  else None
        recipients = json.loads(recipients_raw) if recipients_raw else None
        rubric     = json.loads(rubric_raw)     if rubric_raw     else None

        question_count   = int(question_count)   if question_count   else None
        duration_minutes = int(duration_minutes) if duration_minutes else None

        try:
            db = get_db()
            document_id = None
            if request.files.get('file'):
                upload_result = curiosity_assessment_data.uploadDocument(user_id, db, metadata, request.files.get('file'))
                document_id = upload_result['document_id']

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
            subject = "server:- {}, Error in /createOrUpdateCuriosityAssessments PATCH".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/createOrUpdateCuriosityAssessments PATCH - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/deleteCuriosityAssessments', methods=['PATCH']) # deleteAssessment
@authorize
# ── DELETE — Soft delete ───────────────────────────────────────
def deleteAssessment(user):
    user_id = user.get('user_id')
    body = request.get_json()
    if not body:
        return jsonify({"status": 422, "message": "Request body is missing"})
    assessment_id = body.get('assessment_id')
    if not assessment_id:
        return jsonify({"status": 422, "message": "assessment_id is missing"})
    assessment_id = int(assessment_id)
    if request.method == 'PATCH':
        try:
            db   = get_db()
            data = curiosity_assessment_data.deleteAssessment(user_id, db, metadata, assessment_id)
            if data:
                return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
            else:
                return jsonify({"status": 400, "message": "No Data Found!!"})

        except Exception as e:
            subject = "server:- {}, Error in /deleteCuriosityAssessments/<int:assessment_id>".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/deleteCuriosityAssessments/<int:assessment_id> - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})


# ── Route 3 (duplicate) — /assessments/<assessment_id>/duplicate (POST) ─────
@curiosity_assessment.route('/duplicateCuriosityAssessments', methods=['POST']) # duplicateAssessment
@authorize
def duplicateAssessment(user):
    user_id = user.get('user_id')

    body = request.get_json()
    if not body:
        return jsonify({"status": 422, "message": "Request body is missing"})
    assessment_id = body.get('assessment_id')
    if not assessment_id:
        return jsonify({"status": 422, "message": "assessment_id is missing"})
    assessment_id = int(assessment_id)

    try:
        db   = get_db()
        data = curiosity_assessment_data.duplicateAssessment(user_id, db, metadata, assessment_id)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})

    except Exception as e:
        subject = "server:- {}, Error in /duplicateCuriosityAssessments/<int:assessment_id>".format(os.environ.get('FLASK_ENV'))
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
        except Exception:
            pass
        current_app.logger.error('/assessments/<assessment_id>/duplicate - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/endCuriosityAssessments', methods=['PATCH']) # end a Curiosity Assessment
@authorize
def endCuriosityAssessment(user):
    user_id = user.get('user_id')
    assessment_id = request.args.get('assessment_id')
    if not assessment_id:
        return jsonify({"status": 422, "message": "assessment_id is missing"})
    assessment_id = int(assessment_id)
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


@curiosity_assessment.route('/getCuriosityAssessmentsStats', methods=['GET']) # get assessment stats for Live Monitoring dashboard
@authorize
def getAssessmentStats(user):
    user_id = user.get('user_id')
    assessment_id = request.args.get('assessment_id')
    if not assessment_id:
        return jsonify({"status": 422, "message": "assessment_id is missing"})
    assessment_id = int(assessment_id)
    score_band    = request.args.get('score_band')
    status_filter = request.args.get('status')
    try:
        db   = get_db()
        data = curiosity_assessment_data.getAssessmentStats(user_id, db, metadata, assessment_id, score_band, status_filter)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})

    except Exception as e:
        subject = "server:- {}, Error in /getCuriosityAssessmentsStats".format(os.environ.get('FLASK_ENV'))
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
        except Exception:
            pass
        current_app.logger.error('/getCuriosityAssessmentsStats - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/getCuriosityAssessmentsScorebands', methods=['GET'])
@authorize
def getAssessmentScorebands(user):
    user_id = user.get('user_id')
    assessment_id = request.args.get('assessment_id')
    if not assessment_id:
        return jsonify({"status": 422, "message": "assessment_id is missing"})
    assessment_id = int(assessment_id)
    try:
        db   = get_db()
        data = curiosity_assessment_data.getAssessmentScorebands(user_id, db, metadata, assessment_id)
        if data is not None:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})

    except Exception as e:
        subject = "server:- {}, Error in /getCuriosityAssessmentsScorebands".format(os.environ.get('FLASK_ENV'))
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
        except Exception:
            pass
        current_app.logger.error('/getCuriosityAssessmentsScorebands - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


# ── Route 3a — /assessments/<assessment_id>/students/<student_id>/stats (GET) ─
# Used when faculty clicks on a student in the Ended Students list.
# returns that student's attempt data (questions, answers, scores, dimension breakdown, feedback etc.) for the selected assessment.
@curiosity_assessment.route('/getCuriosityAssessmentsStudentSubmissionStats', methods=['GET'])
@authorize
def getStudentStats(user):
    user_id = user.get('user_id')
    assessment_id = request.args.get('assessment_id')
    student_id    = request.args.get('student_id')  
    if not assessment_id:
        return jsonify({"status": 422, "message": "assessment_id is missing"})
    if not student_id:
        return jsonify({"status": 422, "message": "student_id is missing"})
    assessment_id = int(assessment_id)
    student_id    = int(student_id)

    try:
        db   = get_db()
        data = curiosity_assessment_data.getStudentQuestions(user_id, db, metadata, assessment_id, student_id)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})

    except Exception as e:
        subject = "server:- {}, Error in /getCuriosityAssessmentsStudentSubmissionStats".format(os.environ.get('FLASK_ENV'))
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
        except Exception:
            pass
        current_app.logger.error('/getCuriosityAssessmentsStudentSubmissionStats - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


# ── Route 3b — /sendCuriosityAssessmentsFeedback/<int:assessment_id>/students/<int:student_id> (POST) ─
#Allow faculty to send feedback to students on their assessment attempt.
#Called when faculty submits feedback form in the End Assessment view.
@curiosity_assessment.route('/writeCuriosityAssessmentsStudentFeedback', methods=['POST'])
@authorize
def sendStudentFeedback(user):
    user_id = user.get('user_id')

    assessment_id = request.args.get('assessment_id')
    student_id    = request.args.get('student_id')
    message       = request.form.get('message')
    if not assessment_id:
        return jsonify({"status": 422, "message": "assessment_id is missing"})
    if not student_id:
        return jsonify({"status": 422, "message": "student_id is missing"})
    if not message:
        return jsonify({"status": 422, "message": "message is missing"})
    assessment_id = int(assessment_id)
    student_id    = int(student_id)

    try:
        db   = get_db()
        data = curiosity_assessment_data.sendStudentFeedback(user_id, db, metadata, assessment_id, student_id, message)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})

    except Exception as e:
        subject = "server:- {}, Error in /sendCuriosityAssessmentsStudentFeedback/<int:assessment_id>/students/<int:student_id>".format(os.environ.get('FLASK_ENV'))
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
        except Exception:
            pass
        current_app.logger.error('/sendCuriosityAssessmentsStudentFeedback/<int:assessment_id>/students/<int:student_id> - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


# ── Route 4 — /composeCuriosityAssessmentsExaminees (GET) — audience selection filters ────────────
#
#
#   filter_type access rules:
#     sections    — faculty (own sections), hod (dept sections), principal (all)
#     semesters   — hod, principal only
#     departments — principal only
#     students    — faculty (own sections), hod (dept sections), principal (all)

@curiosity_assessment.route('/composeCuriosityAssessmentsExaminees', methods=['GET'])
@authorize
def getCuriosityAssessmentsExaminees(user):
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
            subject = "server:- {}, Error in /composeCuriosityAssessmentsExaminees".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/composeCuriosityAssessmentsExaminees - EXCEPTION: {}'.format(e))
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
            subject = "server:- {}, Error in /composeCuriosityAssessmentsExaminees".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/composeCuriosityAssessmentsExaminees - EXCEPTION: {}'.format(e))
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
            subject = "server:- {}, Error in /composeCuriosityAssessmentsExaminees".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/composeCuriosityAssessmentsExaminees - EXCEPTION: {}'.format(e))
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
            subject = "server:- {}, Error in /composeCuriosityAssessmentsExaminees".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/composeCuriosityAssessmentsExaminees - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    return jsonify({"status": 422, "message": "unrecognised filter_type param"})


# ── Route 5 — /composeCuriosityAssessmentsSyllabus (GET) — subjects list + lazy topics load ─────
# loads the subjects for the dropdown in the syllabus drawer, and the topics when a subject is selected(both are separated).
# Polled when user opens the syllabus drawer in the Create/Edit Assessment view, and when they select a subject from the dropdown in the syllabus drawer.
@curiosity_assessment.route('/composeCuriosityAssessmentsSyllabus', methods=['GET'])
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
            subject = "server:- {}, Error in /composeCuriosityAssessmentsSyllabus".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/composeCuriosityAssessmentsSyllabus - EXCEPTION: {}'.format(e))
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
            subject = "server:- {}, Error in /composeCuriosityAssessmentsSyllabus".format(os.environ.get('FLASK_ENV'))
            try:
                sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
            except Exception:
                pass
            current_app.logger.error('/composeCuriosityAssessmentsSyllabus - EXCEPTION: {}'.format(e))
            return jsonify({"status": 500, "message": "Failure"})

    return jsonify({"status": 422, "message": "unrecognised type param"})

@curiosity_assessment.route('/getCuriosityAssessmentsTopQuestions', methods=['GET'])
@authorize
def getTopQuestions(user):
    user_id = user.get('user_id')
    assessment_id = request.args.get('assessment_id')
    if not assessment_id:
        return jsonify({"status": 422, "message": "assessment_id is missing"})
    assessment_id = int(assessment_id)
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

@curiosity_assessment.route('/getCuriosityAssessmentsScoreBands', methods=['GET'])
@authorize
def getCuriosityAssessmentScoreBands(user):
    user_id = user.get('user_id')
    assessment_id = request.args.get('assessment_id')
    if not assessment_id:
        return jsonify({"status": 422, "message": "assessment_id is missing"})
    assessment_id = int(assessment_id)


@curiosity_assessment.route('/exportCuriosityAssessmentsResults', methods=['GET'])
@authorize
def exportCuriosityAssessmentResults(user):
    user_id = user.get('user_id')
    assessment_id = request.args.get('assessment_id')
    if not assessment_id:
        return jsonify({"status": 422, "message": "assessment_id is missing"})
    assessment_id = int(assessment_id)
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


@curiosity_assessment.route('/shareCuriosityAssessmentsResults', methods=['POST'])
@authorize
def shareAssessmentResults(user):
    user_id = user.get('user_id')
    assessment_id = request.args.get('assessment_id')
    if not assessment_id:
        return jsonify({"status": 422, "message": "assessment_id is missing"})
    assessment_id = int(assessment_id)
    body = request.get_json()
    if not body:
        return jsonify({"status": 422, "message": "Request body is missing"})
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
        subject = "server:- {}, Error in /shareCuriosityAssessmentsResults".format(os.environ.get('FLASK_ENV'))
        try:
            sg_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg_client.send(Mail(from_email='noreply@edwisely.com', to_emails='alerts@edwisely.com', subject=subject, plain_text_content=str(e)))
        except Exception:
            pass
        current_app.logger.error('/shareCuriosityAssessmentsResults - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})
