from flask import Blueprint, jsonify, request, current_app
import os
import curiosity_assessment_data
from auth import authorize
from database import get_db, metadata

curiosity_assessment = Blueprint('curiosity_assessment', __name__)

# ---------------------------------------------------------------------------
# LIBRARY
# ---------------------------------------------------------------------------

@curiosity_assessment.route('/assessments', methods=['GET'])
@authorize
def getAssessments(user):
    user_id      = user.get('user_id')
    status       = request.args.get('status')        # all|live|scheduled|draft|ended  (optional)
    subject_code = request.args.get('subject_code')  # optional filter
    section_id   = request.args.get('section_id')    # optional filter
    section_id   = int(section_id) if section_id else None

    try:
        db   = get_db()
        data = curiosity_assessment_data.getAssessments(user_id, db, metadata, status, subject_code, section_id)
        # Empty list is a valid result (empty state) — return 200 with []
        if data is not None:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('GET /assessments - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/assessments/<int:assmt_id>', methods=['DELETE'])
@authorize
def deleteAssessment(user, assmt_id):
    user_id = user.get('user_id')

    try:
        db   = get_db()
        data = curiosity_assessment_data.deleteAssessment(user_id, db, metadata, assmt_id)
        if data:
            return jsonify({"status": 200, "message": "Successfully deleted", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('DELETE /assessments/{} - EXCEPTION: {}'.format(assmt_id, e))
        return jsonify({"status": 500, "message": "Failure"})


# ---------------------------------------------------------------------------
# COMPOSE — shared across New Assessment and Edit Assessment
# ---------------------------------------------------------------------------

@curiosity_assessment.route('/subjects', methods=['GET'])
@authorize
def getSubjects(user):
    user_id = user.get('user_id')

    try:
        db   = get_db()
        data = curiosity_assessment_data.getSubjects(user_id, db, metadata)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('GET /subjects - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/sections', methods=['GET'])
@authorize
def getSections(user):
    user_id = user.get('user_id')
    role    = request.args.get('role')  # faculty|hod|principal

    if not role:
        return jsonify({"status": 422, "message": "role is missing"})

    try:
        db   = get_db()
        data = curiosity_assessment_data.getSections(user_id, db, metadata, role)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('GET /sections - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/semesters', methods=['GET'])
@authorize
def getSemesters(user):
    user_id         = user.get('user_id')
    role            = request.args.get('role')             # faculty|hod|principal
    department_code = request.args.get('department_code')  # optional, principal only

    if not role:
        return jsonify({"status": 422, "message": "role is missing"})

    try:
        db   = get_db()
        data = curiosity_assessment_data.getSemesters(user_id, db, metadata, role, department_code)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('GET /semesters - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/departments', methods=['GET'])
@authorize
def getDepartments(user):
    user_id = user.get('user_id')

    try:
        db   = get_db()
        data = curiosity_assessment_data.getDepartments(user_id, db, metadata)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('GET /departments - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/students', methods=['GET'])
@authorize
def getStudents(user):
    user_id    = user.get('user_id')
    role       = request.args.get('role')        # faculty|hod|principal
    section_id = request.args.get('section_id')  # optional
    q          = request.args.get('q')           # optional name/roll search
    section_id = int(section_id) if section_id else None

    if not role:
        return jsonify({"status": 422, "message": "role is missing"})

    try:
        db   = get_db()
        data = curiosity_assessment_data.getStudents(user_id, db, metadata, role, section_id, q)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('GET /students - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/assessments/documents', methods=['POST'])
@authorize
def uploadDocument(user):
    user_id = user.get('user_id')
    file    = request.files.get('file')

    if not file:
        return jsonify({"status": 422, "message": "file is missing"})

    try:
        db   = get_db()
        data = curiosity_assessment_data.uploadDocument(user_id, db, metadata, file)
        if data:
            return jsonify({"status": 200, "message": "Successfully uploaded", "data": data})
        else:
            return jsonify({"status": 400, "message": "Upload Failed"})
    except Exception as e:
        current_app.logger.error('POST /assessments/documents - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/assessments', methods=['POST'])
@authorize
def createAssessment(user):
    user_id = user.get('user_id')
    body    = request.get_json()

    if not body:
        return jsonify({"status": 422, "message": "Request body is missing"})

    title            = body.get('title')
    description      = body.get('description')
    source_kind      = body.get('source_kind')      # document|topic
    document_id      = body.get('document_id')      # required when source_kind == document
    topic_ids        = body.get('topic_ids', [])    # required when source_kind == topic
    subject_code     = body.get('subject_code')     # required when source_kind == topic
    recipients       = body.get('recipients', [])
    question_count   = body.get('question_count')
    duration_minutes = body.get('duration_minutes')
    start_time       = body.get('start_time')
    end_time         = body.get('end_time')
    rubric           = body.get('rubric')           # { relevance, blooms, depth } — must sum to 10
    status           = body.get('status', 'draft')  # draft|scheduled|live

    if not title:
        return jsonify({"status": 422, "message": "title is missing"})
    if not source_kind:
        return jsonify({"status": 422, "message": "source_kind is missing"})
    if source_kind == 'document' and not document_id:
        return jsonify({"status": 422, "message": "document_id is required for document source"})
    if source_kind == 'topic' and not topic_ids:
        return jsonify({"status": 422, "message": "topic_ids are required for topic source"})
    if not recipients:
        return jsonify({"status": 422, "message": "recipients is missing"})
    if not question_count:
        return jsonify({"status": 422, "message": "question_count is missing"})
    if not duration_minutes:
        return jsonify({"status": 422, "message": "duration_minutes is missing"})
    if not rubric:
        return jsonify({"status": 422, "message": "rubric is missing"})

    try:
        db   = get_db()
        data = curiosity_assessment_data.createAssessment(
            user_id, db, metadata,
            title, description, source_kind, document_id, topic_ids,
            subject_code, recipients, question_count, duration_minutes,
            start_time, end_time, rubric, status
        )
        if data:
            return jsonify({"status": 200, "message": "Successfully created", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('POST /assessments - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/assessments/<int:assmt_id>', methods=['PATCH'])
@authorize
def updateAssessment(user, assmt_id):
    user_id = user.get('user_id')
    body    = request.get_json()

    if not body:
        return jsonify({"status": 422, "message": "Request body is missing"})

    # All fields optional — data layer applies only what is present (partial update)
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
    # Allowed transitions enforced in data layer:
    # draft → draft | scheduled | live
    # scheduled → draft | scheduled | live

    try:
        db   = get_db()
        data = curiosity_assessment_data.updateAssessment(
            user_id, db, metadata, assmt_id,
            title, description, source_kind, document_id,
            topic_ids, subject_code, recipients, question_count, duration_minutes,
            start_time, end_time, rubric, status
        )
        if data:
            return jsonify({"status": 200, "message": "Successfully updated", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('PATCH /assessments/{} - EXCEPTION: {}'.format(assmt_id, e))
        return jsonify({"status": 500, "message": "Failure"})


# ---------------------------------------------------------------------------
# MONITOR — Live view
# ---------------------------------------------------------------------------

@curiosity_assessment.route('/assessments/<int:assmt_id>/stats', methods=['GET'])
@authorize
def getAssessmentStats(user, assmt_id):
    user_id = user.get('user_id')

    try:
        db   = get_db()
        data = curiosity_assessment_data.getAssessmentStats(user_id, db, metadata, assmt_id)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('GET /assessments/{}/stats - EXCEPTION: {}'.format(assmt_id, e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/assessments/<int:assmt_id>/roster', methods=['GET'])
@authorize
def getAssessmentRoster(user, assmt_id):
    user_id = user.get('user_id')
    status  = request.args.get('status')  # all|submitted|writing|not-started
    sort    = request.args.get('sort')    # score-desc|score-asc|name-asc|name-desc|time-asc

    try:
        db   = get_db()
        data = curiosity_assessment_data.getAssessmentRoster(user_id, db, metadata, assmt_id, status, sort)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('GET /assessments/{}/roster - EXCEPTION: {}'.format(assmt_id, e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/assessments/<int:assmt_id>/students/<int:student_id>/questions', methods=['GET'])
@authorize
def getStudentQuestions(user, assmt_id, student_id):
    """
    Shared — Monitor (live drill-down) and Ended (review drawer).
    Returns per-question scores, AI feedback, and any faculty feedback already sent.
    """
    user_id = user.get('user_id')

    try:
        db   = get_db()
        data = curiosity_assessment_data.getStudentQuestions(user_id, db, metadata, assmt_id, student_id)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('GET /assessments/{}/students/{}/questions - EXCEPTION: {}'.format(assmt_id, student_id, e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/assessments/<int:assmt_id>/document', methods=['GET'])
@authorize
def getAssessmentDocument(user, assmt_id):
    """
    Shared — Monitor and Ended Reading drawer. Document-mode assessments only.
    """
    user_id = user.get('user_id')

    try:
        db   = get_db()
        data = curiosity_assessment_data.getAssessmentDocument(user_id, db, metadata, assmt_id)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('GET /assessments/{}/document - EXCEPTION: {}'.format(assmt_id, e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/assessments/<int:assmt_id>/topics', methods=['GET'])
@authorize
def getAssessmentTopics(user, assmt_id):
    """
    Shared — Monitor and Ended Topics drawer. Topic-mode assessments only.
    """
    user_id = user.get('user_id')

    try:
        db   = get_db()
        data = curiosity_assessment_data.getAssessmentTopics(user_id, db, metadata, assmt_id)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('GET /assessments/{}/topics - EXCEPTION: {}'.format(assmt_id, e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/assessments/<int:assmt_id>/students/<int:student_id>/feedback', methods=['POST'])
@authorize
def sendStudentFeedback(user, assmt_id, student_id):
    """
    Shared — Monitor (inline feedback during live) and Ended (review drawer post-hoc feedback).
    """
    user_id      = user.get('user_id')
    body         = request.get_json()

    if not body:
        return jsonify({"status": 422, "message": "Request body is missing"})

    message_text = body.get('message')
    if not message_text:
        return jsonify({"status": 422, "message": "message is missing"})

    try:
        db   = get_db()
        data = curiosity_assessment_data.sendStudentFeedback(user_id, db, metadata, assmt_id, student_id, message_text)
        if data:
            return jsonify({"status": 200, "message": "Feedback sent successfully", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('POST /assessments/{}/students/{}/feedback - EXCEPTION: {}'.format(assmt_id, student_id, e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/assessments/<int:assmt_id>/end', methods=['PATCH'])
@authorize
def endAssessment(user, assmt_id):
    # No body required — transitions status: live → ended
    user_id = user.get('user_id')

    try:
        db   = get_db()
        data = curiosity_assessment_data.endAssessment(user_id, db, metadata, assmt_id)
        if data:
            return jsonify({"status": 200, "message": "Assessment ended successfully", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('PATCH /assessments/{}/end - EXCEPTION: {}'.format(assmt_id, e))
        return jsonify({"status": 500, "message": "Failure"})


# ---------------------------------------------------------------------------
# ENDED — Results view
# ---------------------------------------------------------------------------

@curiosity_assessment.route('/assessments/<int:assmt_id>/overview', methods=['GET'])
@authorize
def getAssessmentOverview(user, assmt_id):
    user_id = user.get('user_id')

    try:
        db   = get_db()
        data = curiosity_assessment_data.getAssessmentOverview(user_id, db, metadata, assmt_id)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('GET /assessments/{}/overview - EXCEPTION: {}'.format(assmt_id, e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/assessments/<int:assmt_id>/top-questions', methods=['GET'])
@authorize
def getTopQuestions(user, assmt_id):
    user_id = user.get('user_id')

    try:
        db   = get_db()
        data = curiosity_assessment_data.getTopQuestions(user_id, db, metadata, assmt_id)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('GET /assessments/{}/top-questions - EXCEPTION: {}'.format(assmt_id, e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/assessments/<int:assmt_id>/students', methods=['GET'])
@authorize
def getEndedAssessmentStudents(user, assmt_id):
    user_id    = user.get('user_id')
    status     = request.args.get('status')      # all|submitted|absent
    score_band = request.args.get('score_band')  # e.g. "8-9", "7-8"
    sort       = request.args.get('sort')        # score-desc|score-asc|name-asc|name-desc|roll-asc

    try:
        db   = get_db()
        data = curiosity_assessment_data.getEndedAssessmentStudents(
            user_id, db, metadata, assmt_id, status, score_band, sort
        )
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('GET /assessments/{}/students - EXCEPTION: {}'.format(assmt_id, e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/assessments/<int:assmt_id>/questions/<int:question_id>/similar', methods=['GET'])
@authorize
def getSimilarQuestions(user, assmt_id, question_id):
    user_id = user.get('user_id')

    try:
        db   = get_db()
        data = curiosity_assessment_data.getSimilarQuestions(user_id, db, metadata, assmt_id, question_id)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('GET /assessments/{}/questions/{}/similar - EXCEPTION: {}'.format(assmt_id, question_id, e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/assessments/<int:assmt_id>/export', methods=['GET'])
@authorize
def exportAssessment(user, assmt_id):
    user_id = user.get('user_id')
    fmt     = request.args.get('format')          # csv|xlsx|pdf
    columns = request.args.getlist('columns[]')   # repeated: ?columns[]=name&columns[]=roll&...

    if not fmt:
        return jsonify({"status": 422, "message": "format is missing"})

    try:
        db   = get_db()
        data = curiosity_assessment_data.exportAssessment(user_id, db, metadata, assmt_id, fmt, columns)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('GET /assessments/{}/export - EXCEPTION: {}'.format(assmt_id, e))
        return jsonify({"status": 500, "message": "Failure"})


@curiosity_assessment.route('/assessments/<int:assmt_id>/share', methods=['POST'])
@authorize
def shareAssessment(user, assmt_id):
    user_id = user.get('user_id')
    body    = request.get_json()

    if not body:
        return jsonify({"status": 422, "message": "Request body is missing"})

    scope  = body.get('scope')       # faculty|department|hod|college
    emails = body.get('emails', [])  # optional list of additional email addresses

    if not scope:
        return jsonify({"status": 422, "message": "scope is missing"})

    try:
        db   = get_db()
        data = curiosity_assessment_data.shareAssessment(user_id, db, metadata, assmt_id, scope, emails)
        if data:
            return jsonify({"status": 200, "message": "Shared successfully", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})
    except Exception as e:
        current_app.logger.error('POST /assessments/{}/share - EXCEPTION: {}'.format(assmt_id, e))
        return jsonify({"status": 500, "message": "Failure"})
