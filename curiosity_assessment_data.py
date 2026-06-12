from collections import OrderedDict
from sqlalchemy import select, and_, or_, func, distinct, case, text, update
from datetime import datetime, timezone
import hashlib
import os


# ============================================================
# NOTE ON db / metadata
# These are injected by the route layer (same pattern as
# sampleCodeForQuery.py).  Each function receives:
#   db       — active SQLAlchemy session / connection
#   metadata — MetaData object with all reflected tables
# ============================================================


# ------------------------------------------------------------
# HELPER — naive UTC datetime (MySQL-compatible, Py 3.12+ safe)
# ------------------------------------------------------------
def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ------------------------------------------------------------
# HELPER — formats seconds into "Xh Ym" or "Xm" string
# ------------------------------------------------------------
def _format_duration(seconds):
    if seconds is None:
        return None
    seconds = int(seconds)
    h, m = divmod(seconds // 60, 60)
    if h:
        return "{}h {}m".format(h, m)
    return "{}m".format(m)


# ------------------------------------------------------------
# HELPER — computes "closes in" label from a future datetime
# ------------------------------------------------------------
def _closes_in_label(end_time):
    if end_time is None:
        return None
    diff = end_time - _utcnow()
    total_seconds = int(diff.total_seconds())
    if total_seconds <= 0:
        return "Closed"
    return _format_duration(total_seconds)


# ------------------------------------------------------------
# HELPER — 3-tier access check for assessment-scoped operations
#   principal → blanket access
#   hod       → own assessments OR assessments whose sections
#               fall within the HOD's department
#   faculty   → own assessments only
# ------------------------------------------------------------
def _checkAccess(user_id, assmt_id, db, metadata, created_by=None):
    college_account_new                      = metadata.tables['college_account_new']
    college_university_degree_department_new = metadata.tables['college_university_degree_department_new']
    university_degree_department_new         = metadata.tables['university_degree_department_new']
    department_new                           = metadata.tables['department_new']
    ca_has_sections                          = metadata.tables['ca_has_sections']
    college_department_section_new           = metadata.tables['college_department_section_new']

    user = db.execute(
        select(college_account_new.c.role)
        .where(college_account_new.c.id == user_id)
    ).mappings().first()

    if not user:
        return False

    role = user['role']

    if role == 'principal':
        return True

    if created_by is None:
        curiosity_assessment = metadata.tables['curiosity_assessment']
        assmt_row = db.execute(
            select(curiosity_assessment.c.created_by)
            .where(curiosity_assessment.c.assmt_id == assmt_id)
        ).mappings().first()
        if not assmt_row:
            return False
        created_by = assmt_row['created_by']

    if role == 'faculty':
        return created_by == user_id

    if role == 'hod':
        if created_by == user_id:
            return True

        # Check if any of the assessment's sections fall in the HOD's department
        dept_row = db.execute(
            select(department_new.c.id.label('department_id'))
            .select_from(
                college_account_new
                .join(college_university_degree_department_new,
                    college_university_degree_department_new.c.id
                    == college_account_new.c.college_university_degree_department_id)
                .join(university_degree_department_new,
                    university_degree_department_new.c.id
                    == college_university_degree_department_new.c.university_degree_department_id)
                .join(department_new,
                    department_new.c.id == university_degree_department_new.c.department_id)
            )
            .where(college_account_new.c.id == user_id)
        ).mappings().first()

        if not dept_row:
            return False

        match = db.execute(
            select(ca_has_sections.c.section_id)
            .select_from(
                ca_has_sections
                .join(college_department_section_new,
                    college_department_section_new.c.id == ca_has_sections.c.section_id)
            )
            .where(
                and_(
                    ca_has_sections.c.ca_id == assmt_id,
                    college_department_section_new.c.department_id == dept_row['department_id']
                )
            )
        ).mappings().first()

        return match is not None

    return False


# ============================================================
# LIBRARY
# ============================================================

def getAssessmentFilters(user_id, db, metadata):
    curiosity_assessment           = metadata.tables['curiosity_assessment']
    ca_has_sections                = metadata.tables['ca_has_sections']
    college_department_section_new = metadata.tables['college_department_section_new']

    subject_rows = db.execute(
        select(curiosity_assessment.c.subject_code)
        .where(
            and_(
                curiosity_assessment.c.created_by == user_id,
                curiosity_assessment.c.is_deleted == 0,
                curiosity_assessment.c.subject_code.isnot(None)
            )
        )
        .distinct()
        .order_by(curiosity_assessment.c.subject_code)
    ).mappings().all()

    section_rows = db.execute(
        select(
            college_department_section_new.c.id.label('section_id'),
            college_department_section_new.c.section_name
        )
        .select_from(
            ca_has_sections
            .join(curiosity_assessment,
                curiosity_assessment.c.assmt_id == ca_has_sections.c.ca_id)
            .join(college_department_section_new,
                college_department_section_new.c.id == ca_has_sections.c.section_id)
        )
        .where(
            and_(
                curiosity_assessment.c.created_by == user_id,
                curiosity_assessment.c.is_deleted == 0
            )
        )
        .distinct()
        .order_by(college_department_section_new.c.section_name)
    ).mappings().all()

    return OrderedDict([
        ('subjects', [{'subject_code': r['subject_code']} for r in subject_rows]),
        ('sections', [
            OrderedDict([
                ('section_id',   r['section_id']),
                ('section_name', r['section_name'])
            ])
            for r in section_rows
        ])
    ])


def getAssessments(user_id, db, metadata, status=None, subject_code=None, section_id=None, q=None):
    curiosity_assessment    = metadata.tables['curiosity_assessment']
    ca_has_sections         = metadata.tables['ca_has_sections']
    ca_has_students         = metadata.tables['ca_has_students']
    ca_question_submissions = metadata.tables['ca_question_submissions']

    # Base query — owned by this faculty, not deleted
    query = (
        select(
            curiosity_assessment.c.assmt_id,
            curiosity_assessment.c.assmt_title,
            curiosity_assessment.c.assmt_brief,
            curiosity_assessment.c.topic_source,
            curiosity_assessment.c.subject_code,
            curiosity_assessment.c.document_id,
            curiosity_assessment.c.question_count,
            curiosity_assessment.c.duration_minutes,
            curiosity_assessment.c.rubric_relevance,
            curiosity_assessment.c.rubric_blooms,
            curiosity_assessment.c.rubric_depth,
            curiosity_assessment.c.status,
            curiosity_assessment.c.start_time,
            curiosity_assessment.c.end_time,
            curiosity_assessment.c.created_at,
            curiosity_assessment.c.updated_at,
            func.count(distinct(ca_has_students.c.student_id)).label('total_students'),
            func.sum(
                case((ca_has_students.c.status == 'submitted', 1), else_=0)
            ).label('submitted_count'),
            func.avg(ca_question_submissions.c.composite_score).label('avg_score')
        )
        .select_from(
            curiosity_assessment
            .outerjoin(ca_has_students,
                ca_has_students.c.ca_id == curiosity_assessment.c.assmt_id)
            .outerjoin(ca_question_submissions,
                and_(
                    ca_question_submissions.c.ca_id == curiosity_assessment.c.assmt_id,
                    ca_question_submissions.c.student_id == ca_has_students.c.student_id
                ))
            .outerjoin(ca_has_sections,
                ca_has_sections.c.ca_id == curiosity_assessment.c.assmt_id)
        )
        .where(
            and_(
                curiosity_assessment.c.created_by == user_id,
                curiosity_assessment.c.is_deleted == 0
            )
        )
        .group_by(curiosity_assessment.c.assmt_id)
        .order_by(curiosity_assessment.c.updated_at.desc())
    )

    # Optional filters
    if status and status != 'all':
        query = query.where(curiosity_assessment.c.status == status)
    if subject_code:
        query = query.where(curiosity_assessment.c.subject_code == subject_code)
    if section_id:
        query = query.where(ca_has_sections.c.section_id == section_id)
    if q:
        query = query.where(curiosity_assessment.c.assmt_title.like('%{}%'.format(q)))

    rows = db.execute(query).mappings().all()
    if not rows:
        return OrderedDict([
            ('assessments', []),
            ('filters',     getAssessmentFilters(user_id, db, metadata))
        ])

    # Fetch section ids for each assessment in one query
    section_query = (
        select(
            ca_has_sections.c.ca_id,
            ca_has_sections.c.section_id
        )
        .where(ca_has_sections.c.ca_id.in_([r['assmt_id'] for r in rows]))
    )
    section_rows = db.execute(section_query).mappings().all()
    sections_by_assmt = {}
    for s in section_rows:
        sections_by_assmt.setdefault(s['ca_id'], []).append(s['section_id'])

    assessments = []
    for row in rows:
        submitted   = int(row['submitted_count'] or 0)
        total       = int(row['total_students'] or 0)
        avg         = round(float(row['avg_score']), 2) if row['avg_score'] else None
        section_ids = sections_by_assmt.get(row['assmt_id'], [])

        entry = OrderedDict()
        entry['assmt_id']         = row['assmt_id']
        entry['title']            = row['assmt_title']
        entry['description']      = row['assmt_brief']
        entry['source_kind']      = row['topic_source']
        entry['subject_code']     = row['subject_code']
        entry['document_id']      = row['document_id']
        entry['question_count']   = row['question_count']
        entry['duration_minutes'] = row['duration_minutes']
        entry['rubric']           = {
            'relevance': row['rubric_relevance'],
            'blooms':    row['rubric_blooms'],
            'depth':     row['rubric_depth']
        }
        entry['status']           = row['status']
        entry['start_time']       = row['start_time'].isoformat() if row['start_time'] else None
        entry['end_time']         = row['end_time'].isoformat() if row['end_time'] else None
        entry['section_ids']      = section_ids
        entry['total_students']   = total
        entry['submitted_count']  = submitted
        entry['avg_score']        = avg
        entry['closes_in']        = _closes_in_label(row['end_time']) if row['status'] == 'live' else None
        entry['created_at']       = row['created_at'].isoformat()
        entry['updated_at']       = row['updated_at'].isoformat()
        assessments.append(entry)

    return OrderedDict([
        ('assessments', assessments),
        ('filters',     getAssessmentFilters(user_id, db, metadata))
    ])


def deleteAssessment(user_id, db, metadata, assmt_id):
    curiosity_assessment = metadata.tables['curiosity_assessment']

    if not _checkAccess(user_id, assmt_id, db, metadata):
        return None

    check = db.execute(
        select(curiosity_assessment.c.assmt_id)
        .where(
            and_(
                curiosity_assessment.c.assmt_id == assmt_id,
                curiosity_assessment.c.is_deleted == 0
            )
        )
    ).mappings().first()

    if not check:
        return None

    db.execute(
        update(curiosity_assessment)
        .where(curiosity_assessment.c.assmt_id == assmt_id)
        .values(is_deleted=1, updated_at=_utcnow())
    )
    db.commit()
    return {'assmt_id': assmt_id}


def duplicateAssessment(user_id, db, metadata, assmt_id):
    curiosity_assessment = metadata.tables['curiosity_assessment']
    ca_has_topics        = metadata.tables['ca_has_topics']
    ca_has_sections      = metadata.tables['ca_has_sections']
    ca_has_students      = metadata.tables['ca_has_students']

    if not _checkAccess(user_id, assmt_id, db, metadata):
        return None

    src = db.execute(
        select(curiosity_assessment)
        .where(
            and_(
                curiosity_assessment.c.assmt_id == assmt_id,
                curiosity_assessment.c.is_deleted == 0
            )
        )
    ).mappings().first()

    if not src:
        return None

    now = _utcnow()

    try:
        result = db.execute(
            curiosity_assessment.insert().values(
                created_by       = user_id,
                topic_source     = src['topic_source'],
                assmt_title      = src['assmt_title'] + ' (Copy)',
                assmt_brief      = src['assmt_brief'],
                question_count   = src['question_count'],
                duration_minutes = src['duration_minutes'],
                subject_code     = src['subject_code'],
                document_id      = src['document_id'],
                rubric_relevance = src['rubric_relevance'],
                rubric_blooms    = src['rubric_blooms'],
                rubric_depth     = src['rubric_depth'],
                status           = 'draft',
                start_time       = None,
                end_time         = None,
                is_deleted       = 0,
                created_at       = now,
                updated_at       = now
            )
        )
        new_id = result.lastrowid

        # Copy topics
        topic_rows = db.execute(
            select(ca_has_topics.c.topic_id)
            .where(ca_has_topics.c.ca_id == assmt_id)
        ).mappings().all()
        if topic_rows:
            db.execute(
                ca_has_topics.insert(),
                [{'ca_id': new_id, 'topic_id': r['topic_id']} for r in topic_rows]
            )

        # Copy sections
        section_rows = db.execute(
            select(ca_has_sections.c.section_id)
            .where(ca_has_sections.c.ca_id == assmt_id)
        ).mappings().all()
        if section_rows:
            db.execute(
                ca_has_sections.insert(),
                [{'ca_id': new_id, 'section_id': r['section_id']} for r in section_rows]
            )

        # Copy audience — student statuses reset to not_started for the new draft
        student_rows = db.execute(
            select(ca_has_students.c.student_id)
            .where(ca_has_students.c.ca_id == assmt_id)
        ).mappings().all()
        if student_rows:
            db.execute(
                ca_has_students.insert(),
                [
                    {
                        'ca_id':      new_id,
                        'student_id': r['student_id'],
                        'status':     'not_started',
                        'added_at':   now
                    }
                    for r in student_rows
                ]
            )

        db.commit()
    except Exception:
        db.rollback()
        raise

    return _fetchAssessmentById(new_id, db, metadata)


# ============================================================
# COMPOSE — shared across New Assessment and Edit Assessment
# ============================================================

def getSubjects(user_id, db, metadata):
    college_account_new    = metadata.tables['college_account_new']
    college_account_subject_college_department_section_new = metadata.tables[
        'college_account_subject_college_department_section_new']
    college_subject_mapping = metadata.tables['college_subject_mapping']
    subject_semester_new    = metadata.tables['subject_semester_new']
    subject_master          = metadata.tables['subject_master']

    query = (
        select(
            subject_master.c.id.label('subject_master_id'),
            subject_master.c.name.label('subject_name'),
            college_subject_mapping.c.subject_code,
            subject_semester_new.c.id.label('subject_semester_id')
        )
        .select_from(
            college_account_new
            .join(college_account_subject_college_department_section_new,
                college_account_subject_college_department_section_new.c.college_account_id
                == college_account_new.c.id)
            .join(college_subject_mapping,
                college_subject_mapping.c.id
                == college_account_subject_college_department_section_new.c.college_subject_mapping_id)
            .join(subject_semester_new,
                subject_semester_new.c.id == college_subject_mapping.c.subject_semester_id)
            .join(subject_master,
                subject_master.c.id == subject_semester_new.c.subject_master_id)
        )
        .where(
            and_(
                college_account_new.c.id == user_id,
                college_account_subject_college_department_section_new.c.inactive == 0
            )
        )
        .distinct()
    )

    rows = db.execute(query).mappings().all()
    if not rows:
        return None

    seen = set()
    subjects = []
    for row in rows:
        sid = row['subject_master_id']
        if sid not in seen:
            seen.add(sid)
            subjects.append(OrderedDict([
                ('subject_master_id',   sid),
                ('subject_name',        row['subject_name']),
                ('subject_code',        row['subject_code']),
                ('subject_semester_id', row['subject_semester_id'])
            ]))

    return subjects


def getTopics(user_id, db, metadata, subject_code):
    college_account_new    = metadata.tables['college_account_new']
    college_account_subject_college_department_section_new = metadata.tables[
        'college_account_subject_college_department_section_new']
    college_subject_mapping = metadata.tables['college_subject_mapping']
    subject_topic_mappings  = metadata.tables['subject_topic_mappings']

    query = (
        select(
            subject_topic_mappings.c.unit_id,
            subject_topic_mappings.c.unit_name,
            subject_topic_mappings.c.topic_id,
            subject_topic_mappings.c.topic_name,
            subject_topic_mappings.c.topic_code,
            subject_topic_mappings.c.topic_type
        )
        .select_from(
            college_account_new
            .join(college_account_subject_college_department_section_new,
                college_account_subject_college_department_section_new.c.college_account_id
                == college_account_new.c.id)
            .join(college_subject_mapping,
                college_subject_mapping.c.id
                == college_account_subject_college_department_section_new.c.college_subject_mapping_id)
            .join(subject_topic_mappings,
                subject_topic_mappings.c.college_subject_mapping_id == college_subject_mapping.c.id)
        )
        .where(
            and_(
                college_account_new.c.id == user_id,
                college_account_subject_college_department_section_new.c.inactive == 0,
                college_subject_mapping.c.subject_code == subject_code
            )
        )
        .distinct()
        .order_by(subject_topic_mappings.c.unit_id, subject_topic_mappings.c.topic_id)
    )

    rows = db.execute(query).mappings().all()

    if not rows:
        return None

    units_dict = OrderedDict()
    for row in rows:
        uid = row['unit_id']
        if uid not in units_dict:
            units_dict[uid] = OrderedDict([
                ('unit_id',   uid),
                ('unit_name', row['unit_name']),
                ('topics',    [])
            ])
        units_dict[uid]['topics'].append(OrderedDict([
            ('topic_id',   row['topic_id']),
            ('topic_name', row['topic_name']),
            ('topic_code', row['topic_code']),
            ('topic_type', row['topic_type'])
        ]))

    return OrderedDict([
        ('subject_code', subject_code),
        ('units', list(units_dict.values()))
    ])


def getSections(user_id, db, metadata, role):
    college_account_new    = metadata.tables['college_account_new']
    college_account_subject_college_department_section_new = metadata.tables[
        'college_account_subject_college_department_section_new']
    college_subject_mapping        = metadata.tables['college_subject_mapping']
    college_department_section_new = metadata.tables['college_department_section_new']
    college_university_degree_department_new = metadata.tables[
        'college_university_degree_department_new']

    if role == 'faculty':
        # Only sections this faculty is directly assigned to
        query = (
            select(
                college_department_section_new.c.id.label('section_id'),
                college_department_section_new.c.section_name,
                college_subject_mapping.c.subject_code,
                func.count(distinct(
                    college_account_subject_college_department_section_new.c.id
                )).label('student_count')
            )
            .select_from(
                college_account_new
                .join(college_account_subject_college_department_section_new,
                    college_account_subject_college_department_section_new.c.college_account_id
                    == college_account_new.c.id)
                .join(college_subject_mapping,
                    college_subject_mapping.c.id
                    == college_account_subject_college_department_section_new.c.college_subject_mapping_id)
                .join(college_department_section_new,
                    college_department_section_new.c.id
                    == college_account_subject_college_department_section_new.c.college_department_section_id)
            )
            .where(
                and_(
                    college_account_new.c.id == user_id,
                    college_account_subject_college_department_section_new.c.inactive == 0,
                    college_department_section_new.c.active == 1,
                    college_department_section_new.c.test == 0
                )
            )
            .group_by(
                college_department_section_new.c.id,
                college_department_section_new.c.section_name,
                college_subject_mapping.c.subject_code
            )
        )

    else:
        # HOD / Principal — scope by department or college
        cudd_query = (
            select(college_university_degree_department_new.c.college_id)
            .join(college_account_new,
                college_account_new.c.college_university_degree_department_id
                == college_university_degree_department_new.c.id)
            .where(college_account_new.c.id == user_id)
        )
        cudd_row = db.execute(cudd_query).mappings().first()
        if not cudd_row:
            return None

        where_clause = and_(
            college_department_section_new.c.active == 1,
            college_department_section_new.c.test == 0
        )

        if role == 'hod':
            # Restrict to sections within the HOD's department
            department_new = metadata.tables['department_new']
            university_degree_department_new = metadata.tables['university_degree_department_new']
            dept_query = (
                select(department_new.c.id.label('department_id'))
                .select_from(
                    college_account_new
                    .join(college_university_degree_department_new,
                        college_university_degree_department_new.c.id
                        == college_account_new.c.college_university_degree_department_id)
                    .join(university_degree_department_new,
                        university_degree_department_new.c.id
                        == college_university_degree_department_new.c.university_degree_department_id)
                    .join(department_new,
                        department_new.c.id
                        == university_degree_department_new.c.department_id)
                )
                .where(college_account_new.c.id == user_id)
            )
            dept_row = db.execute(dept_query).mappings().first()
            if not dept_row:
                return None
            where_clause = and_(where_clause,
                college_department_section_new.c.department_id == dept_row['department_id'])

        query = (
            select(
                college_department_section_new.c.id.label('section_id'),
                college_department_section_new.c.section_name
            )
            .select_from(college_department_section_new)
            .where(where_clause)
            .order_by(college_department_section_new.c.section_name)
        )

    rows = db.execute(query).mappings().all()
    if not rows:
        return None

    sections = []
    for row in rows:
        entry = OrderedDict()
        entry['section_id']   = row['section_id']
        entry['section_name'] = row['section_name']
        if role == 'faculty':
            entry['subject_code']  = row.get('subject_code')
            entry['student_count'] = int(row.get('student_count') or 0)
        sections.append(entry)

    return sections


def getSemesters(user_id, db, metadata, role, department_code=None):
    # Semesters are shown only to HOD and Principal
    if role == 'faculty':
        return None

    college_account_new = metadata.tables['college_account_new']
    college_university_degree_department_new = metadata.tables[
        'college_university_degree_department_new']
    college_academic_years   = metadata.tables['college_academic_years']
    academic_years           = metadata.tables['academic_years']
    regulation_batch_mapping = metadata.tables['regulation_batch_mapping']
    college_subject_mapping  = metadata.tables['college_subject_mapping']
    department_new           = metadata.tables['department_new']
    university_degree_department_new = metadata.tables['university_degree_department_new']

    # Resolve college_id for this user
    cudd_query = (
        select(
            college_university_degree_department_new.c.college_id,
            college_university_degree_department_new.c.id.label('cudd_id')
        )
        .join(college_account_new,
            college_account_new.c.college_university_degree_department_id
            == college_university_degree_department_new.c.id)
        .where(college_account_new.c.id == user_id)
    )
    cudd_row = db.execute(cudd_query).mappings().first()
    if not cudd_row:
        return None

    college_id = cudd_row['college_id']

    base_where = college_university_degree_department_new.c.college_id == college_id

    if role == 'hod':
        dept_query = (
            select(department_new.c.id.label('department_id'))
            .select_from(
                college_account_new
                .join(college_university_degree_department_new,
                    college_university_degree_department_new.c.id
                    == college_account_new.c.college_university_degree_department_id)
                .join(university_degree_department_new,
                    university_degree_department_new.c.id
                    == college_university_degree_department_new.c.university_degree_department_id)
                .join(department_new,
                    department_new.c.id == university_degree_department_new.c.department_id)
            )
            .where(college_account_new.c.id == user_id)
        )
        dept_row = db.execute(dept_query).mappings().first()
        if dept_row:
            base_where = and_(base_where,
                university_degree_department_new.c.department_id == dept_row['department_id'])

    if department_code and role == 'principal':
        base_where = and_(base_where, department_new.c.name == department_code)

    query = (
        select(
            college_subject_mapping.c.semester_id,
            academic_years.c.id.label('academic_year_id'),
            academic_years.c.name.label('academic_year_name'),
            func.count(distinct(college_subject_mapping.c.id)).label('subject_count')
        )
        .select_from(
            college_university_degree_department_new
            .join(college_subject_mapping,
                college_subject_mapping.c.college_university_degree_department_id
                == college_university_degree_department_new.c.id)
            .join(regulation_batch_mapping,
                regulation_batch_mapping.c.id == college_subject_mapping.c.regulation_batch_mapping_id)
            .join(college_academic_years,
                and_(
                    college_academic_years.c.regulation_batch_mapping_id
                    == college_subject_mapping.c.regulation_batch_mapping_id,
                    or_(
                        college_academic_years.c.start_semester == college_subject_mapping.c.semester_id,
                        college_academic_years.c.end_semester == college_subject_mapping.c.semester_id
                    )
                ))
            .join(academic_years,
                academic_years.c.id == college_academic_years.c.academic_year_id)
            .join(university_degree_department_new,
                university_degree_department_new.c.id
                == college_university_degree_department_new.c.university_degree_department_id)
            .join(department_new,
                department_new.c.id == university_degree_department_new.c.department_id)
        )
        .where(base_where)
        .group_by(college_subject_mapping.c.semester_id, academic_years.c.id)
        .order_by(college_subject_mapping.c.semester_id)
    )

    rows = db.execute(query).mappings().all()
    if not rows:
        return None

    return [
        OrderedDict([
            ('semester_id',        row['semester_id']),
            ('academic_year_id',   row['academic_year_id']),
            ('academic_year_name', row['academic_year_name']),
            ('subject_count',      int(row['subject_count']))
        ])
        for row in rows
    ]


def getDepartments(user_id, db, metadata):
    college_account_new = metadata.tables['college_account_new']
    college_university_degree_department_new = metadata.tables[
        'college_university_degree_department_new']
    university_degree_department_new = metadata.tables['university_degree_department_new']
    department_new = metadata.tables['department_new']
    college_department_section_new = metadata.tables['college_department_section_new']

    # Resolve college_id
    cudd_query = (
        select(college_university_degree_department_new.c.college_id)
        .join(college_account_new,
            college_account_new.c.college_university_degree_department_id
            == college_university_degree_department_new.c.id)
        .where(college_account_new.c.id == user_id)
    )
    cudd_row = db.execute(cudd_query).mappings().first()
    if not cudd_row:
        return None

    college_id = cudd_row['college_id']

    query = (
        select(
            department_new.c.id.label('department_id'),
            department_new.c.name.label('department_name'),
            department_new.c.full_name.label('department_full_name'),
            func.count(distinct(college_department_section_new.c.id)).label('section_count')
        )
        .select_from(
            college_university_degree_department_new
            .join(university_degree_department_new,
                university_degree_department_new.c.id
                == college_university_degree_department_new.c.university_degree_department_id)
            .join(department_new,
                department_new.c.id == university_degree_department_new.c.department_id)
            .outerjoin(college_department_section_new,
                and_(
                    college_department_section_new.c.active == 1,
                    college_department_section_new.c.test == 0
                ))
        )
        .where(college_university_degree_department_new.c.college_id == college_id)
        .group_by(department_new.c.id)
        .order_by(department_new.c.name)
    )

    rows = db.execute(query).mappings().all()
    if not rows:
        return None

    return [
        OrderedDict([
            ('department_id',        row['department_id']),
            ('department_name',      row['department_name']),
            ('department_full_name', row['department_full_name']),
            ('section_count',        int(row['section_count']))
        ])
        for row in rows
    ]


def getStudents(user_id, db, metadata, role, section_id=None, q=None):
    college_account_new            = metadata.tables['college_account_new']
    college_department_section_new = metadata.tables['college_department_section_new']
    college_university_degree_department_new = metadata.tables[
        'college_university_degree_department_new']
    # student_section_mapping assumed — adjust table name to match actual schema
    student_section_mapping = metadata.tables['student_section_mapping']

    # Validate user exists in the system
    cudd_query = (
        select(college_university_degree_department_new.c.college_id)
        .join(college_account_new,
            college_account_new.c.college_university_degree_department_id
            == college_university_degree_department_new.c.id)
        .where(college_account_new.c.id == user_id)
    )
    cudd_row = db.execute(cudd_query).mappings().first()
    if not cudd_row:
        return None

    base_where = and_(
        college_department_section_new.c.active == 1,
        college_department_section_new.c.test == 0
    )

    if section_id:
        base_where = and_(base_where,
            college_department_section_new.c.id == section_id)

    if q:
        base_where = and_(base_where,
            or_(
                college_account_new.c.name.like('%{}%'.format(q)),
                college_account_new.c.roll_number.like('%{}%'.format(q))
            )
        )

    query = (
        select(
            college_account_new.c.id.label('student_id'),
            college_account_new.c.name.label('student_name'),
            college_account_new.c.roll_number.label('roll'),
            college_department_section_new.c.id.label('section_id'),
            college_department_section_new.c.section_name
        )
        .select_from(
            student_section_mapping
            .join(college_account_new,
                college_account_new.c.id == student_section_mapping.c.student_id)
            .join(college_department_section_new,
                college_department_section_new.c.id == student_section_mapping.c.section_id)
        )
        .where(base_where)
        .order_by(college_department_section_new.c.section_name,
                  college_account_new.c.name)
    )

    rows = db.execute(query).mappings().all()
    if not rows:
        return None

    # Group by section
    sections_dict = OrderedDict()
    for row in rows:
        sid = row['section_id']
        if sid not in sections_dict:
            sections_dict[sid] = {
                'section_id':   sid,
                'section_name': row['section_name'],
                'students':     []
            }
        sections_dict[sid]['students'].append(OrderedDict([
            ('student_id',   row['student_id']),
            ('student_name', row['student_name']),
            ('roll',         row['roll'])
        ]))

    return list(sections_dict.values())


def uploadDocument(user_id, db, metadata, file):
    ca_documents = metadata.tables['ca_documents']

    filename   = file.filename
    file_bytes = file.read()
    size_bytes = len(file_bytes)

    # Count PDF pages via byte marker — replace with pypdf in production
    pages = file_bytes.count(b'/Page ')
    pages = pages if pages > 0 else 1

    # Store file — replace with actual S3 / storage call in production
    storage_url = '/uploads/ca_documents/{}'.format(filename)

    result = db.execute(
        ca_documents.insert().values(
            uploaded_by = user_id,
            name        = filename,
            size_bytes  = size_bytes,
            pages       = pages,
            storage_url = storage_url,
            uploaded_at = _utcnow()
        )
    )
    db.commit()

    doc_id = result.lastrowid
    return OrderedDict([
        ('document_id', doc_id),
        ('name',        filename),
        ('size',        size_bytes),
        ('pages',       pages)
    ])


def createAssessment(user_id, db, metadata,
                     title, description, source_kind, document_id, topic_ids,
                     subject_code, recipients, question_count, duration_minutes,
                     start_time, end_time, rubric, status):

    curiosity_assessment = metadata.tables['curiosity_assessment']
    ca_has_sections      = metadata.tables['ca_has_sections']
    ca_has_topics        = metadata.tables['ca_has_topics']
    ca_has_students      = metadata.tables['ca_has_students']
    # student_section_mapping used to expand section → students
    student_section_mapping = metadata.tables['student_section_mapping']

    # Parse ISO strings to datetime if provided
    start_dt = datetime.fromisoformat(start_time) if start_time else None
    end_dt   = datetime.fromisoformat(end_time)   if end_time   else None

    now = _utcnow()

    try:
        result = db.execute(
            curiosity_assessment.insert().values(
                created_by       = user_id,
                topic_source     = source_kind,
                assmt_title      = title,
                assmt_brief      = description,
                question_count   = question_count,
                duration_minutes = duration_minutes,
                subject_code     = subject_code if source_kind == 'topic' else None,
                document_id      = document_id  if source_kind == 'document' else None,
                rubric_relevance = rubric['relevance'],
                rubric_blooms    = rubric['blooms'],
                rubric_depth     = rubric['depth'],
                status           = status,
                start_time       = start_dt,
                end_time         = end_dt,
                is_deleted       = 0,
                created_at       = now,
                updated_at       = now
            )
        )
        assmt_id = result.lastrowid

        # Collect unique section_ids from recipients
        section_ids = list({r['id'] for r in recipients if r.get('kind') == 'section'})

        # Insert section rows
        if section_ids:
            db.execute(
                ca_has_sections.insert(),
                [{'ca_id': assmt_id, 'section_id': sid} for sid in section_ids]
            )

        # Insert topic rows (topic mode only)
        if source_kind == 'topic' and topic_ids:
            db.execute(
                ca_has_topics.insert(),
                [{'ca_id': assmt_id, 'topic_id': tid} for tid in topic_ids]
            )

        # If launching live now, expand sections into individual student rows
        if status == 'live' and section_ids:
            student_rows = db.execute(
                select(student_section_mapping.c.student_id)
                .where(student_section_mapping.c.section_id.in_(section_ids))
            ).mappings().all()

            if student_rows:
                db.execute(
                    ca_has_students.insert(),
                    [
                        {
                            'ca_id':      assmt_id,
                            'student_id': r['student_id'],
                            'status':     'not_started',
                            'added_at':   now
                        }
                        for r in student_rows
                    ]
                )

        db.commit()
    except Exception:
        db.rollback()
        raise

    return _fetchAssessmentById(assmt_id, db, metadata)


def updateAssessment(user_id, db, metadata, assmt_id,
                     title, description, source_kind, document_id, topic_ids,
                     subject_code, recipients, question_count, duration_minutes,
                     start_time, end_time, rubric, status):

    curiosity_assessment    = metadata.tables['curiosity_assessment']
    ca_has_sections         = metadata.tables['ca_has_sections']
    ca_has_topics           = metadata.tables['ca_has_topics']
    ca_has_students         = metadata.tables['ca_has_students']
    student_section_mapping = metadata.tables['student_section_mapping']

    if not _checkAccess(user_id, assmt_id, db, metadata):
        return None

    current = db.execute(
        select(curiosity_assessment.c.status)
        .where(
            and_(
                curiosity_assessment.c.assmt_id == assmt_id,
                curiosity_assessment.c.is_deleted == 0
            )
        )
    ).mappings().first()

    if not current:
        return None

    current_status = current['status']

    # Validate status transition
    ALLOWED_TRANSITIONS = {
        'draft':     {'draft', 'scheduled', 'live'},
        'scheduled': {'draft', 'scheduled', 'live'}
        # live → ended is handled exclusively by endAssessment()
        # ended → * is terminal, blocked here by omission
    }
    if status is not None:
        allowed = ALLOWED_TRANSITIONS.get(current_status, set())
        if status not in allowed:
            return None  # Invalid transition — caller receives 400

    # Build partial update dict — only include non-None fields
    values = {'updated_at': _utcnow()}
    if title            is not None: values['assmt_title']      = title
    if description      is not None: values['assmt_brief']      = description
    if source_kind      is not None: values['topic_source']     = source_kind
    if document_id      is not None: values['document_id']      = document_id
    if subject_code     is not None: values['subject_code']     = subject_code
    if question_count   is not None: values['question_count']   = question_count
    if duration_minutes is not None: values['duration_minutes'] = duration_minutes
    if start_time       is not None: values['start_time']       = datetime.fromisoformat(start_time)
    if end_time         is not None: values['end_time']         = datetime.fromisoformat(end_time)
    if status           is not None: values['status']           = status
    if rubric           is not None:
        values['rubric_relevance'] = rubric['relevance']
        values['rubric_blooms']    = rubric['blooms']
        values['rubric_depth']     = rubric['depth']
    # If transitioning back to draft, clear window times
    if status == 'draft':
        values['start_time'] = None
        values['end_time']   = None

    try:
        db.execute(
            update(curiosity_assessment)
            .where(curiosity_assessment.c.assmt_id == assmt_id)
            .values(**values)
        )

        # Re-sync sections if recipients changed
        if recipients is not None:
            new_section_ids = list({r['id'] for r in recipients if r.get('kind') == 'section'})
            db.execute(
                ca_has_sections.delete()
                .where(ca_has_sections.c.ca_id == assmt_id)
            )
            if new_section_ids:
                db.execute(
                    ca_has_sections.insert(),
                    [{'ca_id': assmt_id, 'section_id': sid} for sid in new_section_ids]
                )

            # If going live, expand students from updated sections
            if status == 'live' and new_section_ids:
                student_rows = db.execute(
                    select(student_section_mapping.c.student_id)
                    .where(student_section_mapping.c.section_id.in_(new_section_ids))
                ).mappings().all()
                if student_rows:
                    db.execute(
                        ca_has_students.insert(),
                        [
                            {
                                'ca_id':      assmt_id,
                                'student_id': r['student_id'],
                                'status':     'not_started',
                                'added_at':   _utcnow()
                            }
                            for r in student_rows
                        ]
                    )

        # If going live without changing recipients, expand students from existing sections
        elif status == 'live':
            existing_sections = db.execute(
                select(ca_has_sections.c.section_id)
                .where(ca_has_sections.c.ca_id == assmt_id)
            ).mappings().all()
            existing_section_ids = [r['section_id'] for r in existing_sections]
            if existing_section_ids:
                student_rows = db.execute(
                    select(student_section_mapping.c.student_id)
                    .where(student_section_mapping.c.section_id.in_(existing_section_ids))
                ).mappings().all()
                if student_rows:
                    db.execute(
                        ca_has_students.insert(),
                        [
                            {
                                'ca_id':      assmt_id,
                                'student_id': r['student_id'],
                                'status':     'not_started',
                                'added_at':   _utcnow()
                            }
                            for r in student_rows
                        ]
                    )

        # Re-sync topics if changed (topic mode)
        if topic_ids is not None:
            db.execute(
                ca_has_topics.delete()
                .where(ca_has_topics.c.ca_id == assmt_id)
            )
            if topic_ids:
                db.execute(
                    ca_has_topics.insert(),
                    [{'ca_id': assmt_id, 'topic_id': tid} for tid in topic_ids]
                )

        db.commit()
    except Exception:
        db.rollback()
        raise

    return _fetchAssessmentById(assmt_id, db, metadata)


# ------------------------------------------------------------
# SHARED INTERNAL HELPER — fetch a single assessment by id
# Used by createAssessment and updateAssessment to return the
# full object after a write without duplicating select logic.
# ------------------------------------------------------------
def _fetchAssessmentById(assmt_id, db, metadata):
    curiosity_assessment = metadata.tables['curiosity_assessment']
    ca_has_sections      = metadata.tables['ca_has_sections']

    row = db.execute(
        select(curiosity_assessment)
        .where(curiosity_assessment.c.assmt_id == assmt_id)
    ).mappings().first()

    if not row:
        return None

    section_rows = db.execute(
        select(ca_has_sections.c.section_id)
        .where(ca_has_sections.c.ca_id == assmt_id)
    ).mappings().all()

    result = OrderedDict()
    result['assmt_id']         = row['assmt_id']
    result['title']            = row['assmt_title']
    result['description']      = row['assmt_brief']
    result['source_kind']      = row['topic_source']
    result['subject_code']     = row['subject_code']
    result['document_id']      = row['document_id']
    result['question_count']   = row['question_count']
    result['duration_minutes'] = row['duration_minutes']
    result['rubric']           = {
        'relevance': row['rubric_relevance'],
        'blooms':    row['rubric_blooms'],
        'depth':     row['rubric_depth']
    }
    result['status']           = row['status']
    result['start_time']       = row['start_time'].isoformat()  if row['start_time'] else None
    result['end_time']         = row['end_time'].isoformat()    if row['end_time']   else None
    result['section_ids']      = [s['section_id'] for s in section_rows]
    result['created_at']       = row['created_at'].isoformat()
    result['updated_at']       = row['updated_at'].isoformat()
    return result


# ============================================================
# MONITOR — Live view
# ============================================================

def getAssessmentStats(user_id, db, metadata, assmt_id):
    curiosity_assessment    = metadata.tables['curiosity_assessment']
    ca_has_students         = metadata.tables['ca_has_students']
    ca_question_submissions = metadata.tables['ca_question_submissions']

    if not _checkAccess(user_id, assmt_id, db, metadata):
        return None

    assmt = db.execute(
        select(
            curiosity_assessment.c.end_time,
            curiosity_assessment.c.start_time,
            curiosity_assessment.c.status
        )
        .where(curiosity_assessment.c.assmt_id == assmt_id)
    ).mappings().first()

    if not assmt:
        return None

    # Aggregate student statuses
    status_counts = db.execute(
        select(
            ca_has_students.c.status,
            func.count(ca_has_students.c.student_id).label('cnt')
        )
        .where(ca_has_students.c.ca_id == assmt_id)
        .group_by(ca_has_students.c.status)
    ).mappings().all()

    counts = {'submitted': 0, 'writing': 0, 'not_started': 0}
    for row in status_counts:
        counts[row['status']] = int(row['cnt'])

    # Average composite score across all submitted questions
    avg_row = db.execute(
        select(func.avg(ca_question_submissions.c.composite_score).label('avg_score'))
        .where(ca_question_submissions.c.ca_id == assmt_id)
    ).mappings().first()

    avg_score = round(float(avg_row['avg_score']), 2) if avg_row and avg_row['avg_score'] else None

    # Window label
    start = assmt['start_time']
    end   = assmt['end_time']
    window_label = None
    if start and end:
        window_label = '{} → {}'.format(
            start.strftime('%Y-%m-%d %H:%M'),
            end.strftime('%Y-%m-%d %H:%M')
        )

    return OrderedDict([
        ('submitted_count',   counts['submitted']),
        ('writing_count',     counts['writing']),
        ('not_started_count', counts['not_started']),
        ('avg_score',         avg_score),
        ('closes_in',         _closes_in_label(end)),
        ('window_label',      window_label)
    ])


def getAssessmentRoster(user_id, db, metadata, assmt_id, status=None, sort=None):
    curiosity_assessment    = metadata.tables['curiosity_assessment']
    ca_has_students         = metadata.tables['ca_has_students']
    ca_question_submissions = metadata.tables['ca_question_submissions']
    college_account_new     = metadata.tables['college_account_new']

    if not _checkAccess(user_id, assmt_id, db, metadata):
        return None

    # Translate hyphenated frontend value to DB column value before query
    db_status = None
    if status and status != 'all':
        db_status = 'not_started' if status == 'not-started' else status

    query = (
        select(
            ca_has_students.c.student_id,
            ca_has_students.c.status,
            ca_has_students.c.submitted_at,
            college_account_new.c.name.label('student_name'),
            college_account_new.c.roll_number.label('roll'),
            func.count(distinct(ca_question_submissions.c.q_id)).label('q_count'),
            func.avg(ca_question_submissions.c.composite_score).label('avg_score'),
            curiosity_assessment.c.question_count
        )
        .select_from(
            ca_has_students
            .join(college_account_new,
                college_account_new.c.id == ca_has_students.c.student_id)
            .outerjoin(ca_question_submissions,
                and_(
                    ca_question_submissions.c.ca_id == ca_has_students.c.ca_id,
                    ca_question_submissions.c.student_id == ca_has_students.c.student_id
                ))
            .join(curiosity_assessment,
                curiosity_assessment.c.assmt_id == ca_has_students.c.ca_id)
        )
        .where(and_(
            ca_has_students.c.ca_id == assmt_id,
            *([ca_has_students.c.status == db_status] if db_status else [])
        ))
        .group_by(
            ca_has_students.c.student_id,
            ca_has_students.c.status,
            ca_has_students.c.submitted_at,
            college_account_new.c.id,
            curiosity_assessment.c.question_count
        )
    )

    sort_map = {
        'score-desc': func.avg(ca_question_submissions.c.composite_score).desc(),
        'score-asc':  func.avg(ca_question_submissions.c.composite_score).asc(),
        'name-asc':   college_account_new.c.name.asc(),
        'name-desc':  college_account_new.c.name.desc(),
        'time-asc':   ca_has_students.c.submitted_at.asc()
    }
    order = sort_map.get(sort, college_account_new.c.name.asc())
    query = query.order_by(order)

    rows = db.execute(query).mappings().all()
    if not rows:
        return None

    roster = []
    for row in rows:
        total_questions = row['question_count']
        score = round(float(row['avg_score']) * total_questions / 10, 2) \
            if row['avg_score'] else None
        roster.append(OrderedDict([
            ('student_id',   row['student_id']),
            ('student_name', row['student_name']),
            ('roll',         row['roll']),
            ('status',       row['status']),
            ('submitted_at', row['submitted_at'].isoformat() if row['submitted_at'] else None),
            ('q_count',      int(row['q_count'])),
            ('q_total',      total_questions),
            ('score',        score)
        ]))

    return roster


def getStudentQuestions(user_id, db, metadata, assmt_id, student_id):
    curiosity_assessment    = metadata.tables['curiosity_assessment']
    ca_question_submissions = metadata.tables['ca_question_submissions']
    ca_faculty_feedback     = metadata.tables['ca_faculty_feedback']

    assmt = db.execute(
        select(curiosity_assessment.c.assmt_id, curiosity_assessment.c.created_by)
        .where(curiosity_assessment.c.assmt_id == assmt_id)
    ).mappings().first()

    if not assmt or not _checkAccess(user_id, assmt_id, db, metadata, created_by=assmt['created_by']):
        return None

    # Fetch submitted questions ordered by question_number
    q_rows = db.execute(
        select(
            ca_question_submissions.c.q_id,
            ca_question_submissions.c.question_number,
            ca_question_submissions.c.question,
            ca_question_submissions.c.r_score,
            ca_question_submissions.c.b_score,
            ca_question_submissions.c.d_score,
            ca_question_submissions.c.composite_score,
            ca_question_submissions.c.ai_feedback,
            ca_question_submissions.c.submitted_at
        )
        .where(
            and_(
                ca_question_submissions.c.ca_id == assmt_id,
                ca_question_submissions.c.student_id == student_id
            )
        )
        .order_by(ca_question_submissions.c.question_number)
    ).mappings().all()

    # Fetch any faculty feedback for this student in this assessment
    feedback_rows = db.execute(
        select(
            ca_faculty_feedback.c.feedback_id,
            ca_faculty_feedback.c.message,
            ca_faculty_feedback.c.sent_at
        )
        .where(
            and_(
                ca_faculty_feedback.c.ca_id == assmt_id,
                ca_faculty_feedback.c.student_id == student_id
            )
        )
        .order_by(ca_faculty_feedback.c.sent_at)
    ).mappings().all()

    questions = []
    for row in q_rows:
        questions.append(OrderedDict([
            ('q_id',            row['q_id']),
            ('question_number', row['question_number']),
            ('question_text',   row['question']),
            ('r_score',         float(row['r_score'])         if row['r_score']         else None),
            ('b_score',         float(row['b_score'])         if row['b_score']         else None),
            ('d_score',         float(row['d_score'])         if row['d_score']         else None),
            ('composite_score', float(row['composite_score']) if row['composite_score'] else None),
            ('ai_feedback',     row['ai_feedback']),
            ('submitted_at',    row['submitted_at'].isoformat())
        ]))

    feedback = [
        OrderedDict([
            ('feedback_id', row['feedback_id']),
            ('message',     row['message']),
            ('sent_at',     row['sent_at'].isoformat())
        ])
        for row in feedback_rows
    ]

    return OrderedDict([
        ('student_id', student_id),
        ('questions',  questions),
        ('feedback',   feedback)
    ])


def getAssessmentDocument(user_id, db, metadata, assmt_id, created_by=None):
    curiosity_assessment = metadata.tables['curiosity_assessment']
    ca_documents         = metadata.tables['ca_documents']

    if not _checkAccess(user_id, assmt_id, db, metadata, created_by=created_by):
        return None

    row = db.execute(
        select(
            ca_documents.c.doc_id,
            ca_documents.c.name,
            ca_documents.c.size_bytes,
            ca_documents.c.pages,
            ca_documents.c.storage_url
        )
        .select_from(
            curiosity_assessment
            .join(ca_documents,
                ca_documents.c.doc_id == curiosity_assessment.c.document_id)
        )
        .where(curiosity_assessment.c.assmt_id == assmt_id)
    ).mappings().first()

    if not row:
        return None

    return OrderedDict([
        ('document_id',  row['doc_id']),
        ('name',         row['name']),
        ('size',         row['size_bytes']),
        ('pages',        row['pages']),
        ('url',          row['storage_url'])
    ])


def getAssessmentTopics(user_id, db, metadata, assmt_id, created_by=None):
    curiosity_assessment   = metadata.tables['curiosity_assessment']
    ca_has_topics          = metadata.tables['ca_has_topics']
    subject_topic_mappings = metadata.tables['subject_topic_mappings']

    if not _checkAccess(user_id, assmt_id, db, metadata, created_by=created_by):
        return None

    assmt = db.execute(
        select(curiosity_assessment.c.subject_code)
        .where(curiosity_assessment.c.assmt_id == assmt_id)
    ).mappings().first()

    if not assmt:
        return None

    query = (
        select(
            subject_topic_mappings.c.unit_id,
            subject_topic_mappings.c.unit_name,
            subject_topic_mappings.c.topic_id,
            subject_topic_mappings.c.topic_name,
            subject_topic_mappings.c.topic_code
        )
        .select_from(
            ca_has_topics
            .join(subject_topic_mappings,
                subject_topic_mappings.c.topic_id == ca_has_topics.c.topic_id)
        )
        .where(ca_has_topics.c.ca_id == assmt_id)
        .order_by(subject_topic_mappings.c.unit_id, subject_topic_mappings.c.topic_id)
    )

    rows = db.execute(query).mappings().all()

    if not rows:
        return None

    units_dict = OrderedDict()
    for row in rows:
        uid = row['unit_id']
        if uid not in units_dict:
            units_dict[uid] = OrderedDict([
                ('unit_id',   uid),
                ('unit_name', row['unit_name']),
                ('topics',    [])
            ])
        units_dict[uid]['topics'].append(OrderedDict([
            ('topic_id',   row['topic_id']),
            ('topic_name', row['topic_name']),
            ('topic_code', row['topic_code'])
        ]))

    return OrderedDict([
        ('subject_code', assmt['subject_code']),
        ('units',        list(units_dict.values()))
    ])


def getAssessmentSyllabus(user_id, db, metadata, assmt_id):
    curiosity_assessment = metadata.tables['curiosity_assessment']

    assmt = db.execute(
        select(
            curiosity_assessment.c.assmt_id,
            curiosity_assessment.c.topic_source,
            curiosity_assessment.c.created_by
        )
        .where(curiosity_assessment.c.assmt_id == assmt_id)
    ).mappings().first()

    if not assmt or not _checkAccess(user_id, assmt_id, db, metadata, created_by=assmt['created_by']):
        return None

    if assmt['topic_source'] == 'document':
        return getAssessmentDocument(user_id, db, metadata, assmt_id, created_by=assmt['created_by'])
    return getAssessmentTopics(user_id, db, metadata, assmt_id, created_by=assmt['created_by'])


def sendStudentFeedback(user_id, db, metadata, assmt_id, student_id, message_text):
    curiosity_assessment = metadata.tables['curiosity_assessment']
    ca_faculty_feedback  = metadata.tables['ca_faculty_feedback']

    assmt = db.execute(
        select(curiosity_assessment.c.assmt_id, curiosity_assessment.c.created_by)
        .where(curiosity_assessment.c.assmt_id == assmt_id)
    ).mappings().first()

    if not assmt or not _checkAccess(user_id, assmt_id, db, metadata, created_by=assmt['created_by']):
        return None

    sent_at = _utcnow()
    result = db.execute(
        ca_faculty_feedback.insert().values(
            ca_id      = assmt_id,
            student_id = student_id,
            sent_by    = user_id,
            message    = message_text,
            sent_at    = sent_at
        )
    )
    db.commit()

    return OrderedDict([
        ('feedback_id', result.lastrowid),
        ('sent_at',     sent_at.isoformat())
    ])


def discardAssessment(user_id, db, metadata, assmt_id):
    curiosity_assessment = metadata.tables['curiosity_assessment']

    if not _checkAccess(user_id, assmt_id, db, metadata):
        return None

    assmt = db.execute(
        select(curiosity_assessment.c.status)
        .where(
            and_(
                curiosity_assessment.c.assmt_id == assmt_id,
                curiosity_assessment.c.is_deleted == 0
            )
        )
    ).mappings().first()

    if not assmt or assmt['status'] not in ('draft', 'scheduled'):
        return None

    return _fetchAssessmentById(assmt_id, db, metadata)


def endAssessment(user_id, db, metadata, assmt_id):
    curiosity_assessment = metadata.tables['curiosity_assessment']

    if not _checkAccess(user_id, assmt_id, db, metadata):
        return None

    assmt = db.execute(
        select(curiosity_assessment.c.status)
        .where(curiosity_assessment.c.assmt_id == assmt_id)
    ).mappings().first()

    if not assmt or assmt['status'] != 'live':
        return None  # Can only end a live assessment

    db.execute(
        update(curiosity_assessment)
        .where(curiosity_assessment.c.assmt_id == assmt_id)
        .values(status='ended', updated_at=_utcnow())
    )
    db.commit()

    return _fetchAssessmentById(assmt_id, db, metadata)


# ============================================================
# ENDED — Results view
# ============================================================

def getAssessmentOverview(user_id, db, metadata, assmt_id):
    curiosity_assessment    = metadata.tables['curiosity_assessment']
    ca_has_students         = metadata.tables['ca_has_students']
    ca_question_submissions = metadata.tables['ca_question_submissions']

    if not _checkAccess(user_id, assmt_id, db, metadata):
        return None

    assmt = db.execute(
        select(curiosity_assessment.c.question_count)
        .where(curiosity_assessment.c.assmt_id == assmt_id)
    ).mappings().first()

    if not assmt:
        return None

    total_questions = assmt['question_count']

    # Single pass over ca_has_students — compute enrollment counts and median elapsed in Python
    student_rows = db.execute(
        select(
            ca_has_students.c.status,
            ca_has_students.c.time_elapsed_seconds
        )
        .where(ca_has_students.c.ca_id == assmt_id)
    ).mappings().all()

    total_students = len(student_rows)
    submitted      = sum(1 for r in student_rows if r['status'] == 'submitted')
    missed         = total_students - submitted

    elapsed_values = sorted(
        int(r['time_elapsed_seconds'])
        for r in student_rows
        if r['status'] == 'submitted' and r['time_elapsed_seconds'] is not None
    )
    if elapsed_values:
        mid = len(elapsed_values) // 2
        median_seconds = elapsed_values[mid] if len(elapsed_values) % 2 != 0 \
            else (elapsed_values[mid - 1] + elapsed_values[mid]) // 2
    else:
        median_seconds = None

    # Aggregate scores
    score_agg = db.execute(
        select(
            func.avg(ca_question_submissions.c.composite_score).label('avg_score'),
            func.max(ca_question_submissions.c.composite_score).label('top_score'),
            func.count(distinct(ca_question_submissions.c.q_id)).label('total_questions_asked'),
            func.avg(ca_question_submissions.c.r_score).label('avg_relevance'),
            func.avg(ca_question_submissions.c.b_score).label('avg_blooms'),
            func.avg(ca_question_submissions.c.d_score).label('avg_depth')
        )
        .where(ca_question_submissions.c.ca_id == assmt_id)
    ).mappings().first()

    avg_score       = round(float(score_agg['avg_score']),  2) if score_agg['avg_score']  else None
    top_score       = round(float(score_agg['top_score']),  2) if score_agg['top_score']  else None
    questions_asked = int(score_agg['total_questions_asked'] or 0)

    # Score distribution — bin composite scores into integer bands (0-1, 1-2 ... 9-10)
    all_scores_rows = db.execute(
        select(
            func.floor(ca_question_submissions.c.composite_score).label('bin_floor'),
            func.count(ca_question_submissions.c.q_id).label('cnt')
        )
        .where(ca_question_submissions.c.ca_id == assmt_id)
        .group_by(func.floor(ca_question_submissions.c.composite_score))
        .order_by(func.floor(ca_question_submissions.c.composite_score).desc())
    ).mappings().all()

    score_distribution = []
    for row in all_scores_rows:
        low  = int(row['bin_floor'])
        high = low + 1
        score_distribution.append(OrderedDict([
            ('bin',   '{} – {}'.format(low, high)),
            ('count', int(row['cnt']))
        ]))

    by_dimension = OrderedDict([
        ('relevance', round(float(score_agg['avg_relevance']), 2) if score_agg['avg_relevance'] else None),
        ('blooms',    round(float(score_agg['avg_blooms']),    2) if score_agg['avg_blooms']    else None),
        ('depth',     round(float(score_agg['avg_depth']),     2) if score_agg['avg_depth']     else None)
    ])

    return OrderedDict([
        ('submitted_count',    submitted),
        ('missed_count',       missed),
        ('total_students',     total_students),
        ('questions_asked',    questions_asked),
        ('avg_score',          avg_score),
        ('avg_score_pct',      round(avg_score / total_questions * 100, 2) if avg_score else None),
        ('top_score',          top_score),
        ('top_score_pct',      round(top_score / total_questions * 100, 2) if top_score else None),
        ('median_time',        _format_duration(median_seconds)),
        ('score_distribution', score_distribution),
        ('by_dimension',       by_dimension)
    ])


def getTopQuestions(user_id, db, metadata, assmt_id):
    curiosity_assessment    = metadata.tables['curiosity_assessment']
    ca_question_submissions = metadata.tables['ca_question_submissions']
    college_account_new     = metadata.tables['college_account_new']

    assmt = db.execute(
        select(curiosity_assessment.c.assmt_id, curiosity_assessment.c.created_by)
        .where(curiosity_assessment.c.assmt_id == assmt_id)
    ).mappings().first()

    if not assmt or not _checkAccess(user_id, assmt_id, db, metadata, created_by=assmt['created_by']):
        return None

    rows = db.execute(
        select(
            ca_question_submissions.c.q_id,
            ca_question_submissions.c.question,
            ca_question_submissions.c.r_score,
            ca_question_submissions.c.b_score,
            ca_question_submissions.c.d_score,
            ca_question_submissions.c.composite_score,
            college_account_new.c.name.label('student_name')
        )
        .select_from(
            ca_question_submissions
            .join(college_account_new,
                college_account_new.c.id == ca_question_submissions.c.student_id)
        )
        .where(
            and_(
                ca_question_submissions.c.ca_id == assmt_id,
                ca_question_submissions.c.composite_score.isnot(None)
            )
        )
        .order_by(ca_question_submissions.c.composite_score.desc())
        .limit(6)
    ).mappings().all()

    if not rows:
        return None

    return [
        OrderedDict([
            ('rank',         i + 1),
            ('question_id',  row['q_id']),
            ('prompt',       row['question']),
            ('relevance',    float(row['r_score'])         if row['r_score']         else None),
            ('bloom',        float(row['b_score'])         if row['b_score']         else None),
            ('depth',        float(row['d_score'])         if row['d_score']         else None),
            ('avg_score',    round(float(row['composite_score']), 2)),
            ('student_name', row['student_name'])
        ])
        for i, row in enumerate(rows)
    ]


def getEndedAssessmentStudents(user_id, db, metadata, assmt_id,
                                status=None, score_band=None, sort=None):
    curiosity_assessment    = metadata.tables['curiosity_assessment']
    ca_has_students         = metadata.tables['ca_has_students']
    ca_question_submissions = metadata.tables['ca_question_submissions']
    college_account_new     = metadata.tables['college_account_new']

    if not _checkAccess(user_id, assmt_id, db, metadata):
        return None

    query = (
        select(
            ca_has_students.c.student_id,
            ca_has_students.c.status,
            ca_has_students.c.submitted_at,
            ca_has_students.c.time_elapsed_seconds,
            college_account_new.c.name.label('student_name'),
            college_account_new.c.roll_number.label('roll'),
            func.count(distinct(ca_question_submissions.c.q_id)).label('q_count'),
            func.avg(ca_question_submissions.c.composite_score).label('avg_score'),
            func.avg(ca_question_submissions.c.r_score).label('avg_relevance'),
            func.avg(ca_question_submissions.c.b_score).label('avg_blooms'),
            func.avg(ca_question_submissions.c.d_score).label('avg_depth'),
            curiosity_assessment.c.question_count
        )
        .select_from(
            ca_has_students
            .join(college_account_new,
                college_account_new.c.id == ca_has_students.c.student_id)
            .outerjoin(ca_question_submissions,
                and_(
                    ca_question_submissions.c.ca_id == ca_has_students.c.ca_id,
                    ca_question_submissions.c.student_id == ca_has_students.c.student_id
                ))
            .join(curiosity_assessment,
                curiosity_assessment.c.assmt_id == ca_has_students.c.ca_id)
        )
        .where(ca_has_students.c.ca_id == assmt_id)
        .group_by(
            ca_has_students.c.student_id,
            ca_has_students.c.status,
            ca_has_students.c.submitted_at,
            ca_has_students.c.time_elapsed_seconds,
            college_account_new.c.id,
            curiosity_assessment.c.question_count
        )
    )

    # Status filter — 'absent' maps to not_started in the DB
    if status and status != 'all':
        db_status = 'not_started' if status == 'absent' else status
        query = query.where(ca_has_students.c.status == db_status)

    # score_band filter via SQL HAVING (e.g. "8-9" → 8 <= avg < 9)
    if score_band:
        try:
            parts  = score_band.split('-')
            low_b  = float(parts[0])
            high_b = float(parts[1])
            query  = query.having(
                and_(
                    func.avg(ca_question_submissions.c.composite_score) >= low_b,
                    func.avg(ca_question_submissions.c.composite_score) < high_b
                )
            )
        except (ValueError, IndexError):
            pass  # Ignore malformed band — return unfiltered

    # Apply sort in SQL
    sort_map = {
        'score-desc': func.avg(ca_question_submissions.c.composite_score).desc(),
        'score-asc':  func.avg(ca_question_submissions.c.composite_score).asc(),
        'name-asc':   college_account_new.c.name.asc(),
        'name-desc':  college_account_new.c.name.desc(),
        'roll-asc':   college_account_new.c.roll_number.asc()
    }
    order = sort_map.get(sort, college_account_new.c.name.asc())
    query = query.order_by(order)

    rows = db.execute(query).mappings().all()
    if not rows:
        return None

    students = []
    for row in rows:
        avg = round(float(row['avg_score']), 2) if row['avg_score'] else None
        students.append(OrderedDict([
            ('student_id',   row['student_id']),
            ('student_name', row['student_name']),
            ('roll',         row['roll']),
            ('status',       'absent' if row['status'] == 'not_started' else row['status']),
            ('submitted_at', row['submitted_at'].isoformat() if row['submitted_at'] else None),
            ('time',         _format_duration(row['time_elapsed_seconds'])),
            ('q_count',      int(row['q_count'])),
            ('q_total',      row['question_count']),
            ('score',        avg),
            ('dims', OrderedDict([
                ('relevance', round(float(row['avg_relevance']), 2) if row['avg_relevance'] else None),
                ('blooms',    round(float(row['avg_blooms']),    2) if row['avg_blooms']    else None),
                ('depth',     round(float(row['avg_depth']),     2) if row['avg_depth']     else None)
            ]))
        ]))

    return students


def getSimilarQuestions(user_id, db, metadata, assmt_id, question_id):
    curiosity_assessment       = metadata.tables['curiosity_assessment']
    ca_question_submissions    = metadata.tables['ca_question_submissions']
    ca_has_sections            = metadata.tables['ca_has_sections']
    college_account_new        = metadata.tables['college_account_new']
    college_department_section_new = metadata.tables['college_department_section_new']
    student_section_mapping    = metadata.tables['student_section_mapping']

    assmt = db.execute(
        select(curiosity_assessment.c.assmt_id, curiosity_assessment.c.created_by)
        .where(curiosity_assessment.c.assmt_id == assmt_id)
    ).mappings().first()

    if not assmt or not _checkAccess(user_id, assmt_id, db, metadata, created_by=assmt['created_by']):
        return None

    # Fetch reference question's composite score
    ref_q = db.execute(
        select(
            ca_question_submissions.c.composite_score,
            ca_question_submissions.c.question
        )
        .where(
            and_(
                ca_question_submissions.c.q_id == question_id,
                ca_question_submissions.c.ca_id == assmt_id
            )
        )
    ).mappings().first()

    if not ref_q or ref_q['composite_score'] is None:
        return None

    ref_score  = float(ref_q['composite_score'])
    low_bound  = ref_score * 0.85
    high_bound = ref_score * 1.15

    # Find similar questions in this assessment within score range.
    # Join student_section_mapping → ca_has_sections to resolve the
    # student's specific section within this assessment (avoids Cartesian
    # product that would occur if joining ca_has_sections by ca_id alone).
    rows = db.execute(
        select(
            ca_question_submissions.c.q_id,
            ca_question_submissions.c.student_id,
            ca_question_submissions.c.question.label('phrasing'),
            ca_question_submissions.c.composite_score.label('q_score'),
            college_account_new.c.name.label('student_name'),
            college_account_new.c.roll_number.label('roll'),
            college_department_section_new.c.section_name.label('section_label')
        )
        .select_from(
            ca_question_submissions
            .join(college_account_new,
                college_account_new.c.id == ca_question_submissions.c.student_id)
            .join(student_section_mapping,
                student_section_mapping.c.student_id == ca_question_submissions.c.student_id)
            .join(ca_has_sections,
                and_(
                    ca_has_sections.c.section_id == student_section_mapping.c.section_id,
                    ca_has_sections.c.ca_id == assmt_id
                ))
            .join(college_department_section_new,
                college_department_section_new.c.id == ca_has_sections.c.section_id)
        )
        .where(
            and_(
                ca_question_submissions.c.ca_id == assmt_id,
                ca_question_submissions.c.q_id != question_id,
                ca_question_submissions.c.composite_score.between(low_bound, high_bound)
            )
        )
        .order_by(ca_question_submissions.c.composite_score.desc())
    ).mappings().all()

    if not rows:
        return None

    return [
        OrderedDict([
            ('student_id',    row['student_id']),
            ('student_name',  row['student_name']),
            ('roll',          row['roll']),
            ('section_label', row['section_label']),
            ('phrasing',      row['phrasing']),
            ('q_score',       round(float(row['q_score']), 2))
        ])
        for row in rows
    ]


def exportAssessment(user_id, db, metadata, assmt_id, fmt, columns):
    curiosity_assessment       = metadata.tables['curiosity_assessment']
    ca_has_students            = metadata.tables['ca_has_students']
    ca_question_submissions    = metadata.tables['ca_question_submissions']
    college_account_new        = metadata.tables['college_account_new']
    college_department_section_new = metadata.tables['college_department_section_new']
    ca_has_sections            = metadata.tables['ca_has_sections']
    student_section_mapping    = metadata.tables['student_section_mapping']

    assmt = db.execute(
        select(
            curiosity_assessment.c.created_by,
            curiosity_assessment.c.assmt_title,
            curiosity_assessment.c.question_count
        )
        .where(curiosity_assessment.c.assmt_id == assmt_id)
    ).mappings().first()

    if not assmt or not _checkAccess(user_id, assmt_id, db, metadata, created_by=assmt['created_by']):
        return None

    # Fetch full dataset.
    # Join student_section_mapping → ca_has_sections to resolve each
    # student's section within this assessment (avoids Cartesian product).
    rows = db.execute(
        select(
            college_account_new.c.name.label('student_name'),
            college_account_new.c.roll_number.label('roll'),
            college_department_section_new.c.section_name.label('section'),
            ca_has_students.c.status,
            ca_has_students.c.submitted_at,
            ca_has_students.c.time_elapsed_seconds,
            func.avg(ca_question_submissions.c.composite_score).label('total_score'),
            func.avg(ca_question_submissions.c.r_score).label('avg_relevance'),
            func.avg(ca_question_submissions.c.b_score).label('avg_blooms'),
            func.avg(ca_question_submissions.c.d_score).label('avg_depth'),
            func.count(distinct(ca_question_submissions.c.q_id)).label('q_submitted')
        )
        .select_from(
            ca_has_students
            .join(college_account_new,
                college_account_new.c.id == ca_has_students.c.student_id)
            .join(student_section_mapping,
                student_section_mapping.c.student_id == ca_has_students.c.student_id)
            .join(ca_has_sections,
                and_(
                    ca_has_sections.c.section_id == student_section_mapping.c.section_id,
                    ca_has_sections.c.ca_id == assmt_id
                ))
            .join(college_department_section_new,
                college_department_section_new.c.id == ca_has_sections.c.section_id)
            .outerjoin(ca_question_submissions,
                and_(
                    ca_question_submissions.c.ca_id == ca_has_students.c.ca_id,
                    ca_question_submissions.c.student_id == ca_has_students.c.student_id
                ))
        )
        .where(ca_has_students.c.ca_id == assmt_id)
        .group_by(
            ca_has_students.c.student_id,
            ca_has_students.c.status,
            ca_has_students.c.submitted_at,
            ca_has_students.c.time_elapsed_seconds,
            college_account_new.c.id,
            college_department_section_new.c.id
        )
        .order_by(college_account_new.c.name)
    ).mappings().all()

    if not rows:
        return None

    # Column whitelist — maps requested column key to output label + value extractor
    COLUMN_MAP = {
        'name':            ('Name',                lambda r: r['student_name']),
        'roll':            ('Roll',                lambda r: r['roll']),
        'section':         ('Section',             lambda r: r['section']),
        'total_score':     ('Total Score',         lambda r: round(float(r['total_score']), 2) if r['total_score'] else None),
        'relevance_pct':   ('Relevance %',         lambda r: round(float(r['avg_relevance']), 2) if r['avg_relevance'] else None),
        'blooms_level':    ("Bloom's Level",       lambda r: round(float(r['avg_blooms']), 2) if r['avg_blooms'] else None),
        'depth':           ('Depth',               lambda r: round(float(r['avg_depth']), 2) if r['avg_depth'] else None),
        'q_submitted':     ('Questions Submitted', lambda r: int(r['q_submitted'])),
        'submission_time': ('Submission Time',     lambda r: r['submitted_at'].isoformat() if r['submitted_at'] else None)
    }

    # name and roll are always included; merge with requested columns preserving order
    active_columns = ['name', 'roll'] + [c for c in columns if c not in ('name', 'roll') and c in COLUMN_MAP]

    headers = [COLUMN_MAP[c][0] for c in active_columns]
    export_rows = []
    for row in rows:
        export_rows.append(
            {COLUMN_MAP[c][0]: COLUMN_MAP[c][1](row) for c in active_columns}
        )

    safe_title = assmt['assmt_title'].replace(' ', '_')[:40]
    filename   = 'CA_{}_{}.{}'.format(safe_title, assmt_id, fmt)

    return OrderedDict([
        ('filename', filename),
        ('format',   fmt),
        ('headers',  headers),
        ('rows',     export_rows)
    ])


def shareAssessment(user_id, db, metadata, assmt_id, scope, emails):
    curiosity_assessment = metadata.tables['curiosity_assessment']
    ca_share             = metadata.tables['ca_share']

    assmt = db.execute(
        select(curiosity_assessment.c.assmt_id, curiosity_assessment.c.created_by)
        .where(curiosity_assessment.c.assmt_id == assmt_id)
    ).mappings().first()

    if not assmt or not _checkAccess(user_id, assmt_id, db, metadata, created_by=assmt['created_by']):
        return None

    # Generate deterministic share token from assmt_id + a server secret
    secret    = os.environ.get('SHARE_TOKEN_SECRET', 'default_secret')
    token     = hashlib.sha256('{}{}{}'.format(assmt_id, user_id, secret).encode()).hexdigest()[:24]
    share_url = 'https://sastra.ai/assessments/{}/results?token={}'.format(assmt_id, token)

    notified_emails_str = ','.join(emails) if emails else None
    now = _utcnow()

    # Upsert — one share record per assessment
    existing = db.execute(
        select(ca_share.c.ca_id)
        .where(ca_share.c.ca_id == assmt_id)
    ).mappings().first()

    if existing:
        db.execute(
            update(ca_share)
            .where(ca_share.c.ca_id == assmt_id)
            .values(
                scope           = scope,
                share_url       = share_url,
                notified_emails = notified_emails_str,
                updated_at      = now
            )
        )
    else:
        db.execute(
            ca_share.insert().values(
                ca_id           = assmt_id,
                scope           = scope,
                share_url       = share_url,
                notified_emails = notified_emails_str,
                created_by      = user_id,
                created_at      = now,
                updated_at      = now
            )
        )
    db.commit()

    return OrderedDict([
        ('share_url',      share_url),
        ('scope',          scope),
        ('notified_count', len(emails))
    ])
