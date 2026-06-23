from collections import OrderedDict
from sqlalchemy import select, and_, or_, func, distinct, case, text, update
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import time
import uuid
import io
import threading
import boto3
from pypdf import PdfReader
from openai import OpenAI
from redis_client import redis_client

log = logging.getLogger(__name__)

_VS_READY_TTL  = 86400   # 24 h — matches practical vector store lifetime
_VS_FAILED_TTL = 3600    # 1 h  — allow retry after transient failure

_s3 = boto3.client(
    's3',
    region_name          = os.environ.get('AWS_REGION'),
    aws_access_key_id    = os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key= os.environ.get('AWS_SECRET_ACCESS_KEY')
)
_S3_BUCKET = os.environ.get('S3_BUCKET_NAME')

_openai = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))


def _presign_doc(s3_key, expiry=86400):
    """Return a 24-hour presigned GET URL for a private S3 object, or None if no key."""
    if not s3_key:
        return None
    return _s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': _S3_BUCKET, 'Key': s3_key},
        ExpiresIn=expiry,
    )


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


# ------------------------------------------------------------
# HELPER — expand a recipients list into (section_ids, individual_student_ids)
#
# Four recipient kinds are supported:
#   section    → used directly
#   department → expanded to active sections via college_department_section_new
#   semester   → expanded to active sections via subject-section mapping
#   student    → returned as individual_ids (inserted straight into ca_has_students)
#
# section_ids includes all sections from direct selection, departments, and
# semesters — stored in ca_has_sections so future updates without re-specifying
# recipients can still re-expand to students correctly.
# ------------------------------------------------------------
def _expand_recipients(recipients, db, metadata):
    section_ids    = list({r['id'] for r in recipients if r.get('kind') == 'section'})
    department_ids = list({r['id'] for r in recipients if r.get('kind') == 'department'})
    semester_ids   = list({r['id'] for r in recipients if r.get('kind') == 'semester'})
    individual_ids = list({r['id'] for r in recipients if r.get('kind') == 'student'})

    college_department_section_new                         = metadata.tables['college_department_section_new']
    college_account_subject_college_department_section_new = metadata.tables['college_account_subject_college_department_section_new']
    college_subject_mapping                                = metadata.tables['college_subject_mapping']

    if department_ids:
        rows = db.execute(
            select(college_department_section_new.c.id)
            .where(and_(
                college_department_section_new.c.department_id.in_(department_ids),
                college_department_section_new.c.active == 1,
                college_department_section_new.c.test   == 0,
            ))
        ).mappings().all()
        section_ids = list({*section_ids, *(r['id'] for r in rows)})

    if semester_ids:
        rows = db.execute(
            select(college_account_subject_college_department_section_new.c.college_department_section_id)
            .join(college_subject_mapping,
                college_subject_mapping.c.id == college_account_subject_college_department_section_new.c.college_subject_mapping_id)
            .join(college_department_section_new,
                college_department_section_new.c.id == college_account_subject_college_department_section_new.c.college_department_section_id)
            .where(and_(
                college_subject_mapping.c.semester_id.in_(semester_ids),
                college_account_subject_college_department_section_new.c.inactive == 0,
                college_department_section_new.c.active == 1,
                college_department_section_new.c.test   == 0,
            ))
            .distinct()
        ).mappings().all()
        section_ids = list({*section_ids, *(r['college_department_section_id'] for r in rows)})

    return section_ids, individual_ids


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
    curiosity_assessment = metadata.tables['curiosity_assessment']
    ca_has_sections      = metadata.tables['ca_has_sections']
    ca_has_students      = metadata.tables['ca_has_students']
    ca_has_topics        = metadata.tables['ca_has_topics']

    topic_count_subq = (
        select(func.count(ca_has_topics.c.topic_id))
        .where(ca_has_topics.c.ca_id == curiosity_assessment.c.assmt_id)
        .correlate(curiosity_assessment)
        .scalar_subquery()
    )

    # Base query — owned by this faculty, not deleted
    query = (
        select(
            curiosity_assessment.c.assmt_id,
            curiosity_assessment.c.assmt_title,
            curiosity_assessment.c.assmt_brief,
            curiosity_assessment.c.source_kind,
            curiosity_assessment.c.subject_code,
            curiosity_assessment.c.question_count,
            curiosity_assessment.c.duration_minutes,
            curiosity_assessment.c.rubric_relevance_limit,
            curiosity_assessment.c.rubric_blooms_limit,
            curiosity_assessment.c.rubric_depth_limit,
            curiosity_assessment.c.status,
            curiosity_assessment.c.start_time,
            curiosity_assessment.c.end_time,
            curiosity_assessment.c.created_at,
            curiosity_assessment.c.updated_at,
            func.count(distinct(ca_has_students.c.student_id)).label('total_students'),
            func.sum(
                case((ca_has_students.c.status == 'submitted', 1), else_=0)
            ).label('submitted_count'),
            curiosity_assessment.c.avg_composite_score.label('avg_score'),
            curiosity_assessment.c.doc_name,
            curiosity_assessment.c.doc_pages,
            topic_count_subq.label('topic_count'),
        )
        .select_from(
            curiosity_assessment
            .outerjoin(ca_has_students,
                ca_has_students.c.ca_id == curiosity_assessment.c.assmt_id)
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
        source_kind = row['source_kind']

        entry['assmt_id']         = row['assmt_id']
        entry['title']            = row['assmt_title']
        entry['description']      = row['assmt_brief']
        entry['source_kind']      = source_kind
        entry['subject_code']     = row['subject_code']
        if source_kind == 'document':
            entry['doc_name']  = row['doc_name']
            entry['doc_pages'] = row['doc_pages']
        elif source_kind == 'topic':
            entry['topic_count'] = int(row['topic_count'] or 0)
        entry['question_count']   = row['question_count']
        entry['duration_minutes'] = row['duration_minutes']
        entry['rubric']           = {
            'relevance': row['rubric_relevance_limit'],
            'blooms':    row['rubric_blooms_limit'],
            'depth':     row['rubric_depth_limit']
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

    if not _checkAccess(user_id, assmt_id, db, metadata): # change the logic to have the access for the faculty who created it
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
                source_kind     = src['source_kind'],
                assmt_title      = src['assmt_title'] + ' (Copy)',
                assmt_brief      = src['assmt_brief'],
                question_count   = src['question_count'],
                duration_minutes = src['duration_minutes'],
                subject_code     = src['subject_code'],
                doc_name         = src['doc_name'],
                doc_s3_key       = src['doc_s3_key'],
                doc_storage_url  = src['doc_storage_url'],
                doc_pages        = src['doc_pages'],
                doc_size_bytes   = src['doc_size_bytes'],
                vector_store_id  = src['vector_store_id'],
                rubric_relevance_limit = src['rubric_relevance_limit'],
                rubric_blooms_limit    = src['rubric_blooms_limit'],
                rubric_depth_limit     = src['rubric_depth_limit'],
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

    # For document-mode assessments: copy the S3 file and spin up a fresh vector
    # store so the duplicate is fully independent of the source.
    if src['source_kind'] == 'document' and src['doc_s3_key']:
        try:
            doc_name   = src['doc_name'] or 'document.pdf'
            new_s3_key = 'ca_documents/{}/{}__{}'.format(user_id, new_id, doc_name)

            _s3.copy_object(
                CopySource={'Bucket': _S3_BUCKET, 'Key': src['doc_s3_key']},
                Bucket=_S3_BUCKET,
                Key=new_s3_key,
            )

            new_vs = _openai.vector_stores.create(
                name='ca_doc_{}'.format(uuid.uuid4().hex[:8]),
                expires_after={'anchor': 'last_active_at', 'days': 365},
            )

            db.execute(
                curiosity_assessment.update()
                .where(curiosity_assessment.c.assmt_id == new_id)
                .values(doc_s3_key=new_s3_key, vector_store_id=new_vs.id)
            )
            db.commit()

            file_bytes = _s3.get_object(Bucket=_S3_BUCKET, Key=new_s3_key)['Body'].read()
            log.info(
                "Vector store indexing started for duplicate | assmt_id=%d vector_store_id=%s filename=%s",
                new_id, new_vs.id, doc_name,
            )
            threading.Thread(
                target=_ingest_to_vector_store,
                args=(new_vs.id, file_bytes, doc_name),
                daemon=True,
            ).start()
        except Exception as exc:
            log.error("Failed to copy document for duplicate assmt_id=%d: %s", new_id, exc)

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
                    college_department_section_new.c.department_id == department_new.c.id,
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


def _ingest_to_vector_store(vector_store_id, file_bytes, filename):
    t0 = time.perf_counter()
    try:
        # upload_and_poll uploads the file, attaches it to the vector store, and
        # blocks until OpenAI signals status='completed' or 'failed' — no manual
        # polling loop needed; the SDK handles the retry/backoff internally.
        batch = _openai.vector_stores.file_batches.upload_and_poll(
            vector_store_id=vector_store_id,
            files=[(filename, io.BytesIO(file_bytes), 'application/pdf')],
        )
        elapsed = time.perf_counter() - t0
        if batch.status == 'completed':
            log.info(
                "TIMING | vector_store_indexing=%.3fs status=completed file_counts=%s",
                elapsed, batch.file_counts,
            )
            redis_client.set("ca_vs_ready:{}".format(vector_store_id), "1", ex=_VS_READY_TTL)
        else:
            log.error(
                "TIMING | vector_store_indexing=%.3fs status=%s file_counts=%s",
                elapsed, batch.status, batch.file_counts,
            )
            redis_client.set("ca_vs_ready:{}".format(vector_store_id), "failed", ex=_VS_FAILED_TTL)
    except Exception as e:
        elapsed = time.perf_counter() - t0
        log.error("TIMING | vector_store_indexing=%.3fs EXCEPTION: %s", elapsed, e)
        redis_client.set("ca_vs_ready:{}".format(vector_store_id), "failed", ex=_VS_FAILED_TTL)


def uploadDocument(user_id, db, metadata, file, assmt_id=None):
    filename   = file.filename
    file_bytes = file.read()
    size_bytes = len(file_bytes)

    pages  = len(PdfReader(io.BytesIO(file_bytes)).pages)
    # assmt_id is the stable unique identifier per document (1 doc per assessment).
    # Falls back to UUID only on initial creation (POST) when assmt_id is not yet known.
    identifier = assmt_id if assmt_id else uuid.uuid4().hex
    s3_key = 'ca_documents/{}/{}__{}'.format(user_id, identifier, filename)

    _s3.upload_fileobj(
        io.BytesIO(file_bytes),
        _S3_BUCKET,
        s3_key,
        ExtraArgs={'ContentType': 'application/pdf'}
    )
    storage_url = 'https://{}.s3.{}.amazonaws.com/{}'.format(
        _S3_BUCKET, os.environ.get('AWS_REGION'), s3_key
    )

    # Create vector store synchronously (fast API call) — get ID to persist in DB
    vs = _openai.vector_stores.create(
        name='ca_doc_{}'.format(uuid.uuid4().hex[:8]),
        expires_after={'anchor': 'last_active_at', 'days': 365},
    )
    vector_store_id = vs.id

    log.info(
        "Vector store indexing started | vector_store_id=%s filename=%s size_bytes=%d",
        vector_store_id, filename, size_bytes,
    )
    # Upload PDF content to vector store in background — chunking/indexing takes time
    threading.Thread(
        target=_ingest_to_vector_store,
        args=(vector_store_id, file_bytes, filename),
        daemon=True
    ).start()

    return OrderedDict([
        ('doc_name',        filename),
        ('doc_s3_key',      s3_key),
        ('doc_storage_url', storage_url),
        ('doc_pages',       pages),
        ('doc_size_bytes',  size_bytes),
        ('vector_store_id', vector_store_id)
    ])


def createAssessment(user_id, db, metadata,
                     title, description, source_kind, doc_info, topic_ids,
                     subject_code, recipients, question_count, duration_minutes,
                     start_time, end_time, rubric, status):

    curiosity_assessment    = metadata.tables['curiosity_assessment']
    ca_has_sections         = metadata.tables['ca_has_sections']
    ca_has_topics           = metadata.tables['ca_has_topics']
    ca_has_students         = metadata.tables['ca_has_students']
    student_section_mapping = metadata.tables['student_section_mapping']

    # Parse ISO strings to datetime if provided
    start_dt = datetime.fromisoformat(start_time) if start_time else None
    end_dt   = datetime.fromisoformat(end_time)   if end_time   else None

    if start_dt is not None and end_dt is not None and start_dt >= end_dt:
        raise ValueError("start_time must be before end_time, start_time: {}, end_time: {}".format(start_time, end_time))

    now = _utcnow()

    try:
        result = db.execute(
            curiosity_assessment.insert().values(
                created_by       = user_id,
                source_kind     = source_kind,
                assmt_title      = title,
                assmt_brief      = description,
                question_count   = question_count,
                duration_minutes = duration_minutes,
                subject_code     = subject_code if source_kind == 'topic' else None,
                doc_name         = doc_info['doc_name']        if source_kind == 'document' and doc_info else None,
                doc_s3_key       = doc_info['doc_s3_key']      if source_kind == 'document' and doc_info else None,
                doc_storage_url  = doc_info['doc_storage_url'] if source_kind == 'document' and doc_info else None,
                doc_pages        = doc_info['doc_pages']       if source_kind == 'document' and doc_info else None,
                doc_size_bytes   = doc_info['doc_size_bytes']  if source_kind == 'document' and doc_info else None,
                vector_store_id  = doc_info['vector_store_id'] if source_kind == 'document' and doc_info else None,
                rubric_relevance_limit = rubric['relevance'] if rubric else None,
                rubric_blooms_limit    = rubric['blooms']    if rubric else None,
                rubric_depth_limit     = rubric['depth']     if rubric else None,
                status           = status,
                start_time       = start_dt,
                end_time         = end_dt,
                is_deleted       = 0,
                created_at       = now,
                updated_at       = now
            )
        )
        assmt_id = result.lastrowid

        section_ids, individual_ids = _expand_recipients(recipients, db, metadata) if recipients else ([], [])

        # Persist all sections (direct + department-expanded + semester-expanded) for future re-expansion
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

        # Always persist individual recipients so draft→live transition without re-passing recipients works
        if individual_ids:
            db.execute(
                ca_has_students.insert(),
                [{'ca_id': assmt_id, 'student_id': sid, 'status': 'not_started', 'added_at': now}
                 for sid in individual_ids]
            )

        # If launching live: expand sections → students and insert any not already enrolled
        if status == 'live' and section_ids:
            section_students = {
                r['student_id'] for r in db.execute(
                    select(student_section_mapping.c.student_id)
                    .where(student_section_mapping.c.section_id.in_(section_ids))
                ).mappings().all()
            }
            new_from_sections = section_students - set(individual_ids)
            if new_from_sections:
                db.execute(
                    ca_has_students.insert(),
                    [{'ca_id': assmt_id, 'student_id': sid, 'status': 'not_started', 'added_at': now}
                     for sid in new_from_sections]
                )

        db.commit()
    except Exception:
        db.rollback()
        raise

    return _fetchAssessmentById(assmt_id, db, metadata)


def updateAssessment(user_id, db, metadata, assmt_id,
                     title, description, source_kind, doc_info, topic_ids,
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
        select(
            curiosity_assessment.c.status,
            curiosity_assessment.c.start_time,
            curiosity_assessment.c.end_time,
            curiosity_assessment.c.source_kind,
            curiosity_assessment.c.doc_s3_key,
            curiosity_assessment.c.vector_store_id,
            curiosity_assessment.c.subject_code,
            curiosity_assessment.c.question_count,
            curiosity_assessment.c.duration_minutes,
            curiosity_assessment.c.rubric_relevance_limit,
        )
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
    old_s3_key     = current['doc_s3_key']

    # Detect if the existing document will be orphaned after this update:
    # — new file uploaded (doc_info provided), or
    # — switching source_kind to 'topic' (doc columns cleared to None)
    will_orphan_doc = old_s3_key is not None and (
        doc_info is not None or source_kind == 'topic'
    )

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
    if source_kind      is not None: values['source_kind']     = source_kind
    if doc_info is not None:
        values['doc_name']        = doc_info['doc_name']
        values['doc_s3_key']      = doc_info['doc_s3_key']
        values['doc_storage_url'] = doc_info['doc_storage_url']
        values['doc_pages']       = doc_info['doc_pages']
        values['doc_size_bytes']  = doc_info['doc_size_bytes']
        values['vector_store_id'] = doc_info['vector_store_id']
    if subject_code     is not None: values['subject_code']     = subject_code
    if question_count   is not None: values['question_count']   = question_count
    if duration_minutes is not None: values['duration_minutes'] = duration_minutes
    if start_time       is not None: values['start_time']       = datetime.fromisoformat(start_time)
    if end_time         is not None: values['end_time']         = datetime.fromisoformat(end_time)
    if status           is not None: values['status']           = status
    if rubric           is not None:
        values['rubric_relevance_limit'] = rubric['relevance']
        values['rubric_blooms_limit']    = rubric['blooms']
        values['rubric_depth_limit']     = rubric['depth']

    # When switching source_kind, clear the opposing fields so stale data doesn't persist
    if source_kind == 'document':
        values['subject_code'] = None
    elif source_kind == 'topic':
        values['doc_name']        = None
        values['doc_s3_key']      = None
        values['doc_storage_url'] = None
        values['doc_pages']       = None
        values['doc_size_bytes']  = None
        values['vector_store_id'] = None

    # Validate effective time window — compare incoming values against existing DB times
    effective_start = values.get('start_time', current['start_time'])
    effective_end   = values.get('end_time',   current['end_time'])
    if effective_start is not None and effective_end is not None and effective_start >= effective_end:
        raise ValueError("start_time must be before end_time, start_time: {}, end_time: {}".format(effective_start, effective_end))

    # Completeness check when transitioning to live/scheduled — merge incoming with current DB state
    if status in ('live', 'scheduled'):
        eff_source_kind    = values.get('source_kind',          current['source_kind'])
        eff_doc_s3_key     = values.get('doc_s3_key',            current['doc_s3_key'])
        eff_subject_code   = values.get('subject_code',          current['subject_code'])
        eff_question_count = values.get('question_count',        current['question_count'])
        eff_duration       = values.get('duration_minutes',      current['duration_minutes'])
        eff_rubric         = values.get('rubric_relevance_limit', current['rubric_relevance_limit'])

        missing = []
        if not eff_source_kind:                                    missing.append('source_kind')
        if eff_source_kind == 'document' and not eff_doc_s3_key:  missing.append('file/document')
        if eff_source_kind == 'topic':
            if not eff_subject_code:                              missing.append('subject_code')
            has_topics = topic_ids or db.execute(
                select(ca_has_topics.c.topic_id)
                .where(ca_has_topics.c.ca_id == assmt_id)
                .limit(1)
            ).mappings().first()
            if not has_topics:                                    missing.append('topic_ids')
        if not eff_question_count:                                missing.append('question_count')
        if not eff_duration:                                      missing.append('duration_minutes')
        if not eff_rubric:                                        missing.append('rubric')
        has_sections = recipients or db.execute(
            select(ca_has_sections.c.section_id)
            .where(ca_has_sections.c.ca_id == assmt_id)
            .limit(1)
        ).mappings().first()
        if not has_sections:                                      missing.append('recipients')

        if missing:
            raise ValueError("Missing required fields for {} status: {}".format(status, ', '.join(missing)))

    try:
        db.execute(
            update(curiosity_assessment)
            .where(curiosity_assessment.c.assmt_id == assmt_id)
            .values(**values)
        )

        # Re-sync sections and enroll students if recipients changed
        if recipients is not None:
            new_section_ids, new_individual_ids = _expand_recipients(recipients, db, metadata)

            db.execute(ca_has_sections.delete().where(ca_has_sections.c.ca_id == assmt_id))
            if new_section_ids:
                db.execute(
                    ca_has_sections.insert(),
                    [{'ca_id': assmt_id, 'section_id': sid} for sid in new_section_ids]
                )

            # Always sync individual students (draft or live) so draft→live transition works without re-passing recipients.
            # Mirror ca_has_sections: remove students no longer in individual_ids, add new ones.
            # Only touch rows with status='not_started' to avoid removing students who already started.
            existing_individual = {r['student_id'] for r in db.execute(
                select(ca_has_students.c.student_id)
                .where(ca_has_students.c.ca_id == assmt_id)
            ).mappings().all()}
            to_remove = existing_individual - set(new_individual_ids)
            if to_remove:
                db.execute(
                    ca_has_students.delete()
                    .where(and_(
                        ca_has_students.c.ca_id == assmt_id,
                        ca_has_students.c.student_id.in_(to_remove),
                        ca_has_students.c.status == 'not_started',
                    ))
                )
            to_add_individual = set(new_individual_ids) - existing_individual
            if to_add_individual:
                db.execute(
                    ca_has_students.insert(),
                    [{'ca_id': assmt_id, 'student_id': sid, 'status': 'not_started', 'added_at': _utcnow()}
                     for sid in to_add_individual]
                )

            if status == 'live' and new_section_ids:
                section_students = {
                    r['student_id'] for r in db.execute(
                        select(student_section_mapping.c.student_id)
                        .where(student_section_mapping.c.section_id.in_(new_section_ids))
                    ).mappings().all()
                }
                already = {r['student_id'] for r in db.execute(
                    select(ca_has_students.c.student_id)
                    .where(ca_has_students.c.ca_id == assmt_id)
                ).mappings().all()}
                new_from_sections = section_students - already
                if new_from_sections:
                    db.execute(
                        ca_has_students.insert(),
                        [{'ca_id': assmt_id, 'student_id': sid, 'status': 'not_started', 'added_at': _utcnow()}
                         for sid in new_from_sections]
                    )

        # If going live without changing recipients, re-expand from existing sections
        # (departments/semesters were already flattened to section_ids in ca_has_sections)
        elif status == 'live':
            existing_section_ids = [r['section_id'] for r in db.execute(
                select(ca_has_sections.c.section_id)
                .where(ca_has_sections.c.ca_id == assmt_id)
            ).mappings().all()]
            if existing_section_ids:
                enrolled = {r['student_id'] for r in db.execute(
                    select(student_section_mapping.c.student_id)
                    .where(student_section_mapping.c.section_id.in_(existing_section_ids))
                ).mappings().all()}
                if enrolled:
                    already = {r['student_id'] for r in db.execute(
                        select(ca_has_students.c.student_id)
                        .where(ca_has_students.c.ca_id == assmt_id)
                    ).mappings().all()}
                    new_students = enrolled - already
                    if new_students:
                        db.execute(
                            ca_has_students.insert(),
                            [{'ca_id': assmt_id, 'student_id': sid, 'status': 'not_started', 'added_at': _utcnow()}
                             for sid in new_students]
                        )

        # Re-sync topics if changed, or purge if switching to document mode
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
        elif source_kind == 'document':
            db.execute(
                ca_has_topics.delete()
                .where(ca_has_topics.c.ca_id == assmt_id)
            )

        db.commit()
    except Exception:
        db.rollback()
        raise

    # S3 + vector store deletes are best-effort after commit — orphaned objects are
    # acceptable; a failed DB commit with already-deleted resources is not.
    if old_s3_key:
        try:
            _s3.delete_object(Bucket=_S3_BUCKET, Key=old_s3_key)
        except Exception:
            pass

    old_vector_store_id = current['vector_store_id']
    if old_vector_store_id and (doc_info is not None or source_kind == 'topic'):
        try:
            _openai.vector_stores.delete(old_vector_store_id)
        except Exception:
            pass

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
    result['source_kind']      = row['source_kind']
    result['subject_code']     = row['subject_code']
    result['doc_name']         = row['doc_name']
    result['doc_s3_key']       = row['doc_s3_key']
    result['doc_storage_url']  = _presign_doc(row['doc_s3_key'])
    result['doc_pages']        = row['doc_pages']
    result['doc_size_bytes']   = row['doc_size_bytes']
    result['question_count']   = row['question_count']
    result['duration_minutes'] = row['duration_minutes']
    result['rubric']           = {
        'relevance': row['rubric_relevance_limit'],
        'blooms':    row['rubric_blooms_limit'],
        'depth':     row['rubric_depth_limit']
    }
    result['status']           = row['status']
    result['start_time']       = row['start_time'].isoformat()  if row['start_time'] else None
    result['end_time']         = row['end_time'].isoformat()    if row['end_time']   else None
    result['section_ids']      = [s['section_id'] for s in section_rows]
    result['created_at']       = row['created_at'].isoformat()
    result['updated_at']       = row['updated_at'].isoformat()
    return result


# ============================================================
# GET ASSESSMENT BY ID — draft / scheduled edit view
# ============================================================

def getAssessmentByID(user_id, db, metadata, assmt_id):
    curiosity_assessment           = metadata.tables['curiosity_assessment']
    ca_has_sections                = metadata.tables['ca_has_sections']
    college_department_section_new = metadata.tables['college_department_section_new']
    student_section_mapping        = metadata.tables['student_section_mapping']
    ca_has_topics                  = metadata.tables['ca_has_topics']
    subject_topic_mappings         = metadata.tables['subject_topic_mappings']

    if not _checkAccess(user_id, assmt_id, db, metadata):
        return None

    # Correlated scalar subquery: total students enrolled in each section.
    student_count_subq = (
        select(func.count(student_section_mapping.c.id))
        .where(student_section_mapping.c.section_id == college_department_section_new.c.id)
        .correlate(college_department_section_new)
        .scalar_subquery()
    )

    # Query 1 — assessment + sections + document (document join adds 0 extra rows: 1-to-1).
    # For topic-mode assessments, doc columns will all be NULL.
    rows = db.execute(
        select(
            curiosity_assessment.c.assmt_id,
            curiosity_assessment.c.assmt_title,
            curiosity_assessment.c.assmt_brief,
            curiosity_assessment.c.source_kind,
            curiosity_assessment.c.subject_code,
            curiosity_assessment.c.question_count,
            curiosity_assessment.c.duration_minutes,
            curiosity_assessment.c.rubric_relevance_limit,
            curiosity_assessment.c.rubric_blooms_limit,
            curiosity_assessment.c.rubric_depth_limit,
            curiosity_assessment.c.status,
            curiosity_assessment.c.start_time,
            curiosity_assessment.c.created_at,
            curiosity_assessment.c.updated_at,
            college_department_section_new.c.id.label('section_id'),
            college_department_section_new.c.section_name,
            student_count_subq.label('section_student_count'),
            curiosity_assessment.c.doc_name,
            curiosity_assessment.c.doc_size_bytes,
            curiosity_assessment.c.doc_pages,
            curiosity_assessment.c.doc_s3_key,
            curiosity_assessment.c.doc_storage_url.label('doc_url'),
        )
        .select_from(
            curiosity_assessment
            .outerjoin(ca_has_sections,
                ca_has_sections.c.ca_id == curiosity_assessment.c.assmt_id)
            .outerjoin(college_department_section_new,
                college_department_section_new.c.id == ca_has_sections.c.section_id)
        )
        .where(
            and_(
                curiosity_assessment.c.assmt_id == assmt_id,
                curiosity_assessment.c.is_deleted == 0
            )
        )
        .order_by(college_department_section_new.c.section_name.asc())
    ).mappings().all()

    if not rows:
        return None

    first        = rows[0]
    status       = first['status']
    source_kind = first['source_kind']

    # Guard: only draft / scheduled can be opened for editing
    if status not in ('draft', 'scheduled'):
        return {'_status_error': status}

    # Build sections list from repeated assessment rows
    sections = []
    for r in rows:
        if r['section_id'] is not None:
            sections.append(OrderedDict([
                ('section_id',    r['section_id']),
                ('section_name',  r['section_name']),
                ('student_count', r['section_student_count'] or 0),
            ]))

    # Build syllabus — document mode: already in query 1 (no extra roundtrip)
    if source_kind == 'document':
        syllabus = OrderedDict([
            ('name',        first['doc_name']),
            ('size_bytes',  first['doc_size_bytes']),
            ('pages',       first['doc_pages']),
            ('url',         _presign_doc(first['doc_s3_key'])),
        ]) if first['doc_name'] else None

    elif source_kind == 'topic':
        # topic mode — Query 2: join ca_has_topics → subject_topic_mappings directly.
        # No user/subject chain needed: topics were validated at creation time.
        topic_rows = db.execute(
            select(
                subject_topic_mappings.c.unit_id,
                subject_topic_mappings.c.unit_name,
                subject_topic_mappings.c.topic_id,
                subject_topic_mappings.c.topic_name,
                subject_topic_mappings.c.topic_code,
            )
            .select_from(
                ca_has_topics
                .join(subject_topic_mappings,
                    subject_topic_mappings.c.topic_id == ca_has_topics.c.topic_id)
            )
            .where(ca_has_topics.c.ca_id == assmt_id)
            .order_by(
                subject_topic_mappings.c.unit_id,
                subject_topic_mappings.c.topic_id
            )
        ).mappings().all()

        units_dict = OrderedDict()
        for r in topic_rows:
            uid = r['unit_id']
            if uid not in units_dict:
                units_dict[uid] = OrderedDict([
                    ('unit_id',   uid),
                    ('unit_name', r['unit_name']),
                    ('topics',    []),
                ])
            units_dict[uid]['topics'].append(OrderedDict([
                ('topic_id',   r['topic_id']),
                ('topic_name', r['topic_name']),
                ('topic_code', r['topic_code']),
            ]))
        syllabus = list(units_dict.values())

    else:
        # source_kind not yet set — title-only draft
        syllabus = None

    return OrderedDict([
        ('assmt_id',         first['assmt_id']),
        ('title',            first['assmt_title']),
        ('description',      first['assmt_brief']),
        ('source_kind',      source_kind),
        ('subject_code',     first['subject_code']),
        ('question_count',   first['question_count']),
        ('duration_minutes', first['duration_minutes']),
        ('rubric', OrderedDict([
            ('relevance', first['rubric_relevance_limit']),
            ('blooms',    first['rubric_blooms_limit']),
            ('depth',     first['rubric_depth_limit']),
        ])),
        ('status',      status),
        ('start_time',  first['start_time'].isoformat() if first['start_time'] else None),
        ('sections',    sections),
        ('syllabus',    syllabus),
        ('created_at',  first['created_at'].isoformat()),
        ('updated_at',  first['updated_at'].isoformat()),
    ])


# ============================================================
# MONITOR — Live view
# ============================================================

def getAssessmentStats(user_id, db, metadata, assmt_id, sort=None):
    curiosity_assessment           = metadata.tables['curiosity_assessment']
    ca_has_students                = metadata.tables['ca_has_students']
    ca_question_submissions        = metadata.tables['ca_question_submissions']
    college_account_new            = metadata.tables['college_account_new']
    ca_has_sections                = metadata.tables['ca_has_sections']
    college_department_section_new = metadata.tables['college_department_section_new']
    ca_has_topics                  = metadata.tables['ca_has_topics']
    subject_topic_mappings         = metadata.tables['subject_topic_mappings']
    college_subject_mapping        = metadata.tables['college_subject_mapping']
    subject_semester_new           = metadata.tables['subject_semester_new']
    subject_master                 = metadata.tables['subject_master']

    if not _checkAccess(user_id, assmt_id, db, metadata):
        return None

    # Total questions asked across all students (scalar subquery)
    total_q_subq = (
        select(func.count(ca_question_submissions.c.q_id))
        .where(ca_question_submissions.c.ca_id == assmt_id)
        .scalar_subquery()
    )

    # Per-student question count (correlated scalar subquery)
    student_q_subq = (
        select(func.count(ca_question_submissions.c.q_id))
        .where(
            and_(
                ca_question_submissions.c.ca_id == assmt_id,
                ca_question_submissions.c.student_id == ca_has_students.c.student_id
            )
        )
        .correlate(ca_has_students)
        .scalar_subquery()
    )

    sort_map = {
        'score-desc': ca_has_students.c.avg_composite_score.desc(),
        'score-asc':  ca_has_students.c.avg_composite_score.asc(),
        'name-asc':   college_account_new.c.name.asc(),
        'name-desc':  college_account_new.c.name.desc(),
        'time-asc':   ca_has_students.c.submitted_at.asc()
    }
    order = sort_map.get(sort, college_account_new.c.name.asc())

    rows = db.execute(
        select(
            curiosity_assessment.c.assmt_id,
            curiosity_assessment.c.assmt_title,
            curiosity_assessment.c.source_kind,
            curiosity_assessment.c.subject_code,
            curiosity_assessment.c.doc_name,
            curiosity_assessment.c.doc_s3_key,
            curiosity_assessment.c.doc_storage_url,
            curiosity_assessment.c.doc_pages,
            curiosity_assessment.c.question_count,
            curiosity_assessment.c.duration_minutes,
            curiosity_assessment.c.status,
            curiosity_assessment.c.end_time,
            curiosity_assessment.c.avg_composite_score,
            curiosity_assessment.c.avg_r_score,
            curiosity_assessment.c.avg_b_score,
            curiosity_assessment.c.avg_d_score,
            curiosity_assessment.c.median_time_seconds,
            total_q_subq.label('total_questions_asked'),
            ca_has_students.c.student_id,
            ca_has_students.c.status.label('student_status'),
            ca_has_students.c.submitted_at,
            ca_has_students.c.avg_composite_score.label('student_score'),
            ca_has_students.c.avg_r_score.label('student_r'),
            ca_has_students.c.avg_b_score.label('student_b'),
            ca_has_students.c.avg_d_score.label('student_d'),
            college_account_new.c.name.label('student_name'),
            college_account_new.c.roll_number.label('roll'),
            student_q_subq.label('student_q_count'),
            ca_has_students.c.started_at
        )
        .select_from(
            curiosity_assessment
            .outerjoin(ca_has_students,
                ca_has_students.c.ca_id == curiosity_assessment.c.assmt_id)
            .outerjoin(college_account_new,
                college_account_new.c.id == ca_has_students.c.student_id)
        )
        .where(curiosity_assessment.c.assmt_id == assmt_id)
        .order_by(order)
    ).mappings().all()

    if not rows:
        return None

    # Assessment fields are identical across all rows — read from first
    first        = rows[0]
    view_status  = first['status']
    source_kind = first['source_kind']
    avg_score    = round(float(first['avg_composite_score']), 2) if first['avg_composite_score'] else None

    # Single pass over rows — counts, top_score, and student list together
    counts        = {'submitted': 0, 'writing': 0, 'not_started': 0}
    top_score     = None
    students      = []
    elapsed_times = []

    for row in rows:
        if row['student_id'] is None:
            continue  # assessment exists but no students enrolled yet

        st = row['student_status']
        counts[st] = counts.get(st, 0) + 1

        if st == 'submitted':
            submission_time = row['submitted_at'].strftime('%H:%M') if row['submitted_at'] else None
        elif st == 'writing':
            submission_time = 'Writing...'
        else:
            submission_time = 'Not Started'

        score = round(float(row['student_score']), 2) if row['student_score'] else None
        if score is not None and (top_score is None or score > top_score):
            top_score = score

        if st in ('submitted', 'writing') and row['started_at'] is not None:
            if st == 'submitted' and row['submitted_at'] is not None:
                secs = (row['submitted_at'] - row['started_at']).total_seconds()
            else:
                secs = (_utcnow() - row['started_at']).total_seconds()
            if secs > 0:
                elapsed_times.append(secs)

        if view_status == 'live':
            students.append(OrderedDict([
                ('student_id',      row['student_id']),
                ('student_name',    row['student_name']),
                ('roll',            row['roll']),
                ('status',          st),
                ('submission_time', submission_time),
                ('question_count',  int(row['student_q_count'] or 0)),
                ('score',           score)
            ]))
        else:
            students.append(OrderedDict([
                ('student_id',      row['student_id']),
                ('student_name',    row['student_name']),
                ('roll',            row['roll']),
                ('status',          'absent' if st == 'not_started' else st),
                ('submission_time', submission_time),
                ('question_count',  int(row['student_q_count'] or 0)),
                ('score',           score),
                ('dims', OrderedDict([
                    ('relevance', round(float(row['student_r']), 2) if row['student_r'] else None),
                    ('blooms',    round(float(row['student_b']), 2) if row['student_b'] else None),
                    ('depth',     round(float(row['student_d']), 2) if row['student_d'] else None)
                ]))
            ]))

    total_enrolled   = sum(counts.values())
    avg_elapsed_secs = sum(elapsed_times) / len(elapsed_times) if elapsed_times else None
    avg_time_elapsed = _format_duration(avg_elapsed_secs) if avg_elapsed_secs else None

    # Sections assigned to this assessment
    section_rows = db.execute(
        select(college_department_section_new.c.section_name)
        .select_from(
            ca_has_sections
            .join(college_department_section_new,
                college_department_section_new.c.id == ca_has_sections.c.section_id)
        )
        .where(ca_has_sections.c.ca_id == assmt_id)
        .order_by(college_department_section_new.c.section_name)
    ).mappings().all()
    sections = [r['section_name'] for r in section_rows]

    # Syllabus block — shape depends on source_kind
    if source_kind == 'document':
        syllabus = OrderedDict([
            ('source_kind', 'document'),
            ('name',        first['doc_name']),
            ('url',         _presign_doc(first['doc_s3_key'])),
            ('pages',       first['doc_pages'])
        ])

    else:
        # Topic mode — subject name + unit/topic breakdown
        subject_row = db.execute(
            select(subject_master.c.name.label('subject_name'))
            .select_from(
                college_subject_mapping
                .join(subject_semester_new,
                    subject_semester_new.c.id == college_subject_mapping.c.subject_semester_id)
                .join(subject_master,
                    subject_master.c.id == subject_semester_new.c.subject_master_id)
            )
            .where(college_subject_mapping.c.subject_code == first['subject_code'])
        ).mappings().first()

        topic_rows = db.execute(
            select(
                subject_topic_mappings.c.unit_id,
                subject_topic_mappings.c.unit_name,
                subject_topic_mappings.c.topic_name
            )
            .select_from(
                ca_has_topics
                .join(subject_topic_mappings,
                    subject_topic_mappings.c.topic_id == ca_has_topics.c.topic_id)
            )
            .where(ca_has_topics.c.ca_id == assmt_id)
            .order_by(subject_topic_mappings.c.unit_id, subject_topic_mappings.c.topic_id)
        ).mappings().all()

        units_dict = OrderedDict()
        for r in topic_rows:
            uid = r['unit_id']
            if uid not in units_dict:
                units_dict[uid] = OrderedDict([
                    ('unit_name', r['unit_name']),
                    ('topics',    [])
                ])
            units_dict[uid]['topics'].append(r['topic_name'])

        topic_count = sum(len(u['topics']) for u in units_dict.values())

        syllabus = OrderedDict([
            ('source_kind',  'topic'),
            ('subject_name', subject_row['subject_name'] if subject_row else None),
            ('topic_count',  topic_count),
            ('units',        list(units_dict.values()))
        ])

    assessment_block = OrderedDict([
        ('assmt_id',         first['assmt_id']),
        ('title',            first['assmt_title']),
        ('question_count',   first['question_count']),
        ('duration_minutes', first['duration_minutes']),
        ('status',           view_status),
        ('total_enrolled',   total_enrolled),
        ('sections',         sections),
        ('syllabus',         syllabus)
    ])

    if view_status == 'live':
        prev_row = db.execute(
            select(curiosity_assessment.c.avg_composite_score.label('prev_avg'))
            .where(
                and_(
                    curiosity_assessment.c.created_by == user_id, # the same creator
                    curiosity_assessment.c.status == 'ended', # must be a finished assessment
                    curiosity_assessment.c.assmt_id != assmt_id, # not the current assessment
                    curiosity_assessment.c.avg_composite_score.isnot(None) # must have an avg composite score
                )
            )
            .order_by(curiosity_assessment.c.updated_at.desc()) 
            .limit(1) # fetches the latest ended assessment (of that creator)
        ).mappings().first()

        if prev_row and avg_score is not None:
            prev_avg = round(float(prev_row['prev_avg']), 2)
            delta    = round(avg_score - prev_avg, 2)
            score_vs_last = OrderedDict([
                ('previous_avg', prev_avg),
                ('delta',        delta),
                #('direction',    'up' if delta > 0 else ('down' if delta < 0 else 'same'))
            ])
        else:
            score_vs_last = None

        return OrderedDict([
            ('assessment', assessment_block),
            ('summary', OrderedDict([
                ('submitted_count',   counts['submitted']),
                ('writing_count',     counts['writing']),
                ('not_started_count', counts['not_started']),
                ('avg_score',         avg_score),
                ('avg_time_elapsed',  avg_time_elapsed),
                ('score_vs_last',     score_vs_last),
                ('closes_in',         _closes_in_label(first['end_time']))
            ])),
            ('students', students)
        ])

    return OrderedDict([
        ('assessment', assessment_block),
        ('summary', OrderedDict([
            ('submitted_count',       counts['submitted']),
            ('missed_count',          counts['not_started']),
            ('total_questions_asked', int(first['total_questions_asked'] or 0)),
            ('avg_score',             avg_score),
            ('avg_score_pct',         round(avg_score / 10 * 100, 2) if avg_score else None),
            ('avg_time_elapsed',      avg_time_elapsed),
            ('top_score',             top_score),
            ('top_score_pct',         round(top_score / 10 * 100, 2) if top_score else None),
            ('median_time',           _format_duration(first['median_time_seconds'])),
            ('by_dimension', OrderedDict([
                ('relevance', round(float(first['avg_r_score']), 2) if first['avg_r_score'] else None),
                ('blooms',    round(float(first['avg_b_score']), 2) if first['avg_b_score'] else None),
                ('depth',     round(float(first['avg_d_score']), 2) if first['avg_d_score'] else None)
            ]))
        ])),
        ('students', students)
    ])


def getStudentQuestions(user_id, db, metadata, assmt_id, student_id):
    curiosity_assessment    = metadata.tables['curiosity_assessment']
    ca_question_submissions = metadata.tables['ca_question_submissions']
    ca_faculty_feedback     = metadata.tables['ca_faculty_feedback']
    ca_has_students         = metadata.tables['ca_has_students']

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
            ca_question_submissions.c.question_reframe,
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

    # Fetch student's aggregate scores for this assessment
    student_row = db.execute(
        select(
            ca_has_students.c.avg_composite_score,
            ca_has_students.c.avg_r_score,
            ca_has_students.c.avg_b_score,
            ca_has_students.c.avg_d_score,
        )
        .where(
            and_(
                ca_has_students.c.ca_id == assmt_id,
                ca_has_students.c.student_id == student_id
            )
        )
    ).mappings().first()

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
            ('q_id',             row['q_id']),
            ('question_number',  row['question_number']),
            ('question_text',    row['question']),
            ('r_score',          float(row['r_score'])         if row['r_score']         is not None else None),
            ('b_score',          float(row['b_score'])         if row['b_score']         is not None else None),
            ('d_score',          float(row['d_score'])         if row['d_score']         is not None else None),
            ('composite_score',  float(row['composite_score']) if row['composite_score'] is not None else None),
            ('ai_feedback',      row['ai_feedback']),
            ('question_reframe', row['question_reframe']),
            ('submitted_at',     row['submitted_at'].isoformat())
        ]))

    feedback = [
        OrderedDict([
            ('feedback_id', row['feedback_id']),
            ('message',     row['message']),
            ('sent_at',     row['sent_at'].isoformat())
        ])
        for row in feedback_rows
    ]

    questions_submitted = len(questions)
    top_score = max(
        (q['composite_score'] for q in questions if q['composite_score'] is not None),
        default=None
    )

    avg_scores = None
    if student_row:
        avg_scores = OrderedDict([
            ('avg_composite_score', float(student_row['avg_composite_score']) if student_row['avg_composite_score'] is not None else None),
            ('avg_r_score',         float(student_row['avg_r_score'])         if student_row['avg_r_score']         is not None else None),
            ('avg_b_score',         float(student_row['avg_b_score'])         if student_row['avg_b_score']         is not None else None),
            ('avg_d_score',         float(student_row['avg_d_score'])         if student_row['avg_d_score']         is not None else None),
        ])

    return OrderedDict([
        ('student_id',          student_id),
        ('questions_submitted', questions_submitted),
        ('top_score',           top_score),
        ('avg_scores',          avg_scores),
        ('questions',           questions),
        ('feedback',            feedback)
    ])


def getTopQuestions(user_id, db, metadata, assmt_id):
    ca_question_submissions = metadata.tables['ca_question_submissions']

    if not _checkAccess(user_id, assmt_id, db, metadata):
        return None
    
    limit = 6
    rows = db.execute(
        select(
            ca_question_submissions.c.q_id,
            ca_question_submissions.c.question,
            ca_question_submissions.c.r_score,
            ca_question_submissions.c.b_score,
            ca_question_submissions.c.d_score,
            ca_question_submissions.c.composite_score,
        )
        .where(
            and_(
                ca_question_submissions.c.ca_id == assmt_id,
                ca_question_submissions.c.composite_score.isnot(None)
            )
        )
        .order_by(ca_question_submissions.c.composite_score.desc())
        .limit(limit)
    ).mappings().all()

    return [
        OrderedDict([
            ('q_id',            row['q_id']),
            ('question',        row['question']),
            ('composite_score', round(float(row['composite_score']), 2)),
            ('r_score',         round(float(row['r_score']), 2) if row['r_score'] else None),
            ('b_score',         round(float(row['b_score']), 2) if row['b_score'] else None),
            ('d_score',         round(float(row['d_score']), 2) if row['d_score'] else None),
        ])
        for row in rows
    ]


def getAssessmentTopics(db, metadata, assmt_id):
    curiosity_assessment   = metadata.tables['curiosity_assessment']
    ca_has_topics          = metadata.tables['ca_has_topics']
    subject_topic_mappings = metadata.tables['subject_topic_mappings']

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
            curiosity_assessment.c.source_kind,
            curiosity_assessment.c.created_by
        )
        .where(curiosity_assessment.c.assmt_id == assmt_id)
    ).mappings().first()

    if not assmt or not _checkAccess(user_id, assmt_id, db, metadata, created_by=assmt['created_by']):
        return None

    if assmt['source_kind'] == 'document':
        doc_row = db.execute(
            select(
                curiosity_assessment.c.doc_name,
                curiosity_assessment.c.doc_size_bytes,
                curiosity_assessment.c.doc_pages,
                curiosity_assessment.c.doc_s3_key
            )
            .where(curiosity_assessment.c.assmt_id == assmt_id)
        ).mappings().first()
        if not doc_row or not doc_row['doc_name']:
            return None
        return OrderedDict([
            ('name',       doc_row['doc_name']),
            ('size_bytes', doc_row['doc_size_bytes']),
            ('pages',      doc_row['doc_pages']),
            ('url',        _presign_doc(doc_row['doc_s3_key']))
        ])
    return getAssessmentTopics(db, metadata, assmt_id)


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
    ca_has_students      = metadata.tables['ca_has_students']

    if not _checkAccess(user_id, assmt_id, db, metadata):
        return None

    assmt = db.execute(
        select(curiosity_assessment.c.status)
        .where(curiosity_assessment.c.assmt_id == assmt_id)
    ).mappings().first()

    if not assmt or assmt['status'] != 'live':
        return None

    # Single query — fetch both fields needed for median and score distribution
    submitted_rows = db.execute(
        select(
            ca_has_students.c.time_elapsed_seconds,
            ca_has_students.c.avg_composite_score
        )
        .where(
            and_(
                ca_has_students.c.ca_id == assmt_id,
                ca_has_students.c.status == 'submitted'
            )
        )
    ).mappings().all()

    # Median time
    elapsed = sorted(
        int(r['time_elapsed_seconds'])
        for r in submitted_rows
        if r['time_elapsed_seconds'] is not None
    )
    if elapsed:
        mid = len(elapsed) // 2
        median_seconds = elapsed[mid] if len(elapsed) % 2 != 0 \
            else (elapsed[mid - 1] + elapsed[mid]) // 2
    else:
        median_seconds = None

    # Score distribution — bands 5-6 … 9-10, computed once and stored
    _BANDS = ['5-6', '6-7', '7-8', '8-9', '9-10']
    dist = {b: 0 for b in _BANDS}
    for r in submitted_rows:
        s = r['avg_composite_score']
        if s is not None and float(s) >= 5:
            dist[_BANDS[min(int(float(s)) - 5, 4)]] += 1
    score_dist = json.dumps([{'band': b, 'count': dist[b]} for b in _BANDS])

    db.execute(
        update(curiosity_assessment)
        .where(curiosity_assessment.c.assmt_id == assmt_id)
        .values(
            status='ended',
            median_time_seconds=median_seconds,
            score_distribution=score_dist,
            updated_at=_utcnow()
        )
    )
    db.commit()

    return {'assmt_id': assmt_id, 'status': 'ended'}


# ============================================================
# ENDED — Results view
# ============================================================

def getAssessmentScorebands(user_id, db, metadata, assmt_id):
    curiosity_assessment = metadata.tables['curiosity_assessment']

    if not _checkAccess(user_id, assmt_id, db, metadata):
        return None

    row = db.execute(
        select(
            curiosity_assessment.c.status,
            curiosity_assessment.c.score_distribution
        )
        .where(curiosity_assessment.c.assmt_id == assmt_id)
    ).mappings().first()

    if not row or row['status'] != 'ended' or not row['score_distribution']:
        return None

    dist = row['score_distribution']
    return dist if not isinstance(dist, str) else json.loads(dist)


def getSimilarQuestions(db, metadata, q_id):
    ca_question_submissions = metadata.tables['ca_question_submissions']
    ca_similar_questions    = metadata.tables['ca_similar_questions']

    # Single query: LEFT JOIN validates q_id existence and fetches similar questions together.
    # 0 rows  → q_id not in ca_question_submissions → caller returns 404.
    # 1 row with question=None → q_id valid, no similar questions seeded yet → [].
    # N rows  → return question texts.
    rows = db.execute(
        select(
            ca_question_submissions.c.q_id.label('exists_flag'),
            ca_similar_questions.c.question
        )
        .select_from(
            ca_question_submissions
            .outerjoin(ca_similar_questions,
                ca_similar_questions.c.source_q_id == ca_question_submissions.c.q_id)
        )
        .where(ca_question_submissions.c.q_id == q_id)
    ).mappings().all()

    if not rows:
        return None  # q_id does not exist

    return [r['question'] for r in rows if r['question'] is not None]


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
        )
        .where(curiosity_assessment.c.assmt_id == assmt_id)
    ).mappings().first()

    if not assmt or not _checkAccess(user_id, assmt_id, db, metadata, created_by=assmt['created_by']):
        return None

    # name and roll always included; strip unknowns and duplicates while preserving order
    VALID_COLS = {'name', 'roll', 'section', 'total_score', 'relevance_pct',
                  'blooms_level', 'depth', 'q_submitted', 'submission_time'}
    active_columns = ['name', 'roll'] + [c for c in columns if c not in ('name', 'roll') and c in VALID_COLS]

    need_q_submitted = 'q_submitted' in active_columns

    # SQLAlchemy expressions for each column key — only the selected ones are projected
    col_exprs = {
        'name':            college_account_new.c.name.label('student_name'),
        'roll':            college_account_new.c.roll_number.label('roll'),
        'section':         college_department_section_new.c.section_name.label('section'),
        'total_score':     ca_has_students.c.avg_composite_score.label('total_score'),
        'relevance_pct':   ca_has_students.c.avg_r_score.label('avg_relevance'),
        'blooms_level':    ca_has_students.c.avg_b_score.label('avg_blooms'),
        'depth':           ca_has_students.c.avg_d_score.label('avg_depth'),
        'q_submitted':     func.count(distinct(ca_question_submissions.c.q_id)).label('q_submitted'),
        'submission_time': ca_has_students.c.submitted_at,
    }

    # Section joins are always included — they're small indexed lookups.
    # Submissions outerjoin is the only conditional: it reads a large table
    # and forces a GROUP BY, so skip it entirely when q_submitted isn't requested.
    from_clause = (
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
    )
    if need_q_submitted:
        from_clause = from_clause.outerjoin(ca_question_submissions,
            and_(
                ca_question_submissions.c.ca_id == ca_has_students.c.ca_id,
                ca_question_submissions.c.student_id == ca_has_students.c.student_id
            ))

    query = (
        select(*[col_exprs[c] for c in active_columns])
        .select_from(from_clause)
        .where(ca_has_students.c.ca_id == assmt_id)
        .order_by(college_account_new.c.name)
    )

    # GROUP BY only needed when q_submitted (aggregate) is selected.
    if need_q_submitted:
        hs_group_cols = {
            'total_score':     ca_has_students.c.avg_composite_score,
            'relevance_pct':   ca_has_students.c.avg_r_score,
            'blooms_level':    ca_has_students.c.avg_b_score,
            'depth':           ca_has_students.c.avg_d_score,
            'submission_time': ca_has_students.c.submitted_at,
        }
        group_cols = [ca_has_students.c.student_id, college_account_new.c.id,
                      college_department_section_new.c.id]
        group_cols += [hs_group_cols[c] for c in active_columns if c in hs_group_cols]
        query = query.group_by(*group_cols)

    rows = db.execute(query).mappings().all()

    if not rows:
        return None

    COLUMN_MAP = {
        'name':            ('Name',                lambda r: r['student_name']),
        'roll':            ('Roll',                lambda r: r['roll']),
        'section':         ('Section',             lambda r: r['section']),
        'total_score':     ('Total Score',         lambda r: round(float(r['total_score']), 2) if r['total_score'] else None),
        'relevance_pct':   ('Relevance %',         lambda r: round(float(r['avg_relevance']), 2) if r['avg_relevance'] else None),
        'blooms_level':    ("Bloom's Level",       lambda r: round(float(r['avg_blooms']), 2) if r['avg_blooms'] else None),
        'depth':           ('Depth',               lambda r: round(float(r['avg_depth']), 2) if r['avg_depth'] else None),
        'q_submitted':     ('Questions Submitted', lambda r: int(r['q_submitted'])),
        'submission_time': ('Submission Time',     lambda r: r['submitted_at'].isoformat() if r['submitted_at'] else None),
    }

    headers    = [COLUMN_MAP[c][0] for c in active_columns]
    export_rows = [
        {COLUMN_MAP[c][0]: COLUMN_MAP[c][1](row) for c in active_columns}
        for row in rows
    ]

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
