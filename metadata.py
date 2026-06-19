from sqlalchemy import (
    Table, Column, Integer, String, MetaData, Text, DateTime,
    SmallInteger, DECIMAL, TIMESTAMP, Enum, ForeignKey, JSON
)

metadata = MetaData()

# --- Core Tables (Pre-existing, don't modify) ---

college_subject_mapping = Table('college_subject_mapping', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('subject_semester_id', Integer, nullable=False),
    Column('college_university_degree_department_id', Integer, nullable=False),
    Column('subject_id', Integer, nullable=True),
    Column('subject_code', String(20), nullable=True),
    Column('semester_id', Integer, nullable=True),
    Column('created_at', DateTime, nullable=True),
    Column('updated_at', DateTime, nullable=True)
)

topics = Table('topics', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('name', String(300), nullable=False),
    Column('description', Text, nullable=False),
    Column('subject_id', Integer, nullable=False),
    Column('subject_semester_id', Integer, nullable=True),
    Column('created_at', DateTime, nullable=False),
    Column('modified_at', DateTime, nullable=False)
)

topics_conceptmapping = Table('topics_conceptmapping', metadata,
    Column('topics_id', Integer, nullable=False),
    Column('global_grand_topic_code', Text, nullable=True),
    Column('global_topic_code', Text, nullable=True),
    Column('global_sub_topic_code', Text, nullable=True),
    Column('exam_priority_order', Integer, nullable=True),
    Column('created_at', DateTime, nullable=False),
    Column('modified_at', DateTime, nullable=False),
    Column('mappings_population', SmallInteger, nullable=False, default=0),
    Column('syllabus_name', String(255), nullable=True),
    Column('global_grand_topic_id', Integer, nullable=True),
    Column('global_topic_id', Integer, nullable=True),
    Column('global_sub_topic_id', Integer, nullable=True)
)

subject_co_mappings_cms = Table('subject_co_mappings_cms', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('college_subject_mapping_id', Integer, nullable=True),
    Column('co_code', String(10), nullable=False),
    Column('course_outcome', Text, nullable=False),
    Column('cms_user_id', Integer, nullable=False),
    Column('is_edited', SmallInteger, nullable=False, default=0),
    Column('created_at', DateTime, nullable=False),
    Column('modified_at', DateTime, nullable=False),
    Column('is_active', Integer, nullable=True, default=1)
)

subject_topic_mappings = Table('subject_topic_mappings', metadata,
    Column('college_id', Integer, nullable=False),
    Column('college_name', String(255), nullable=False),
    Column('department_id', Integer, nullable=False),
    Column('department_full_name', String(255), nullable=False),
    Column('department_name', String(20), nullable=False),
    Column('university_degree_department_id', Integer, nullable=False),
    Column('college_university_degree_department_id', Integer, nullable=False),
    Column('regulation_batch_mapping_id', Integer, nullable=False),
    Column('batch_id', Integer, nullable=False),
    Column('batch_name', String(255), nullable=False),
    Column('college_subject_mapping_id', Integer, nullable=False),
    Column('subject_semester_id', Integer, nullable=False),
    Column('subject_master_id', Integer, nullable=False),
    Column('subject_name', String(255), nullable=False),
    Column('semester_id', Integer, nullable=False),
    Column('elective', SmallInteger, nullable=False),
    Column('unit_id', Integer, nullable=False),
    Column('unit_name', String(255), nullable=False),
    Column('topic_id', Integer, nullable=False),
    Column('topic_type', String(20), nullable=False),
    Column('topic_code', String(40), nullable=False),
    Column('topic_name', String(255), nullable=False)
)

topic_co_mappings_cms = Table('topic_co_mappings_cms', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('unit_id', Integer, nullable=False),
    Column('unit', String(255), nullable=False),
    Column('college_subject_mapping_id', Integer, nullable=False),
    Column('topic_id', Integer, nullable=False),
    Column('topic_type', String(255), nullable=False),
    Column('topic_code', String(255), nullable=False),
    Column('topic_name', String(255), nullable=False),
    Column('co_code', String(10), nullable=False),
    Column('relevance_score', DECIMAL(5, 2), nullable=False),
    Column('reason', Text, nullable=True),
    Column('created_at', TIMESTAMP, nullable=True),
    Column('modified_at', TIMESTAMP, nullable=True),
    Column('is_active', Integer, nullable=True, default=1),
    Column('subject_co_mapping_id', Integer, nullable=True),
    Column('unit_co_mapping_id', Integer, nullable=True)
)

# --- Curiosity Assessment Tables ---

curiosity_assessment = Table('curiosity_assessment', metadata,
    Column('assmt_id', Integer, primary_key=True, autoincrement=True),
    Column('created_by', Integer, nullable=False),
    Column('source_kind', Enum('document', 'topic'), nullable=False),
    Column('assmt_title', String(255), nullable=False),
    Column('assmt_brief', Text, nullable=True),
    Column('question_count', SmallInteger, nullable=False, default=3),
    Column('duration_minutes', SmallInteger, nullable=False, default=15),
    Column('subject_code', String(20), nullable=True),
    Column('doc_name', String(255), nullable=True),
    Column('doc_s3_key', String(512), nullable=True),
    Column('doc_storage_url', Text, nullable=True),
    Column('vector_store_id', String(100), nullable=True),
    Column('doc_pages', SmallInteger, nullable=True),
    Column('doc_size_bytes', Integer, nullable=True),
    Column('rubric_relevance_limit', SmallInteger, nullable=False, default=4),
    Column('rubric_blooms_limit', SmallInteger, nullable=False, default=3),
    Column('rubric_depth_limit', SmallInteger, nullable=False, default=3),
    Column('avg_r_score', DECIMAL(4, 2), nullable=True),
    Column('avg_b_score', DECIMAL(3, 2), nullable=True),
    Column('avg_d_score', DECIMAL(3, 2), nullable=True),
    Column('avg_composite_score', DECIMAL(4, 2), nullable=True),
    Column('status', Enum('draft', 'scheduled', 'live', 'ended'), nullable=False, default='draft'),
    Column('start_time', DateTime, nullable=True),
    Column('end_time', DateTime, nullable=True),
    Column('created_at', DateTime, nullable=False),
    Column('updated_at', DateTime, nullable=False),
    Column('median_time_seconds', Integer, nullable=True),
    Column('is_deleted', SmallInteger, nullable=False, default=0),
    Column('score_distribution', JSON, nullable=True)
)

ca_has_topics = Table('ca_has_topics', metadata,
    Column('ca_id', Integer, ForeignKey('curiosity_assessment.assmt_id', ondelete='CASCADE'), nullable=False, primary_key=True),
    Column('topic_id', Integer, nullable=False, primary_key=True)
)

ca_has_sections = Table('ca_has_sections', metadata,
    Column('ca_id', Integer, ForeignKey('curiosity_assessment.assmt_id', ondelete='CASCADE'), nullable=False, primary_key=True),
    Column('section_id', Integer, nullable=False, primary_key=True)
)

ca_has_students = Table('ca_has_students', metadata,
    Column('ca_id', Integer, ForeignKey('curiosity_assessment.assmt_id', ondelete='CASCADE'), nullable=False, primary_key=True),
    Column('student_id', Integer, nullable=False, primary_key=True),
    Column('status', Enum('not_started', 'writing', 'submitted'), nullable=False, default='not_started'),
    Column('avg_r_score', DECIMAL(4, 2), nullable=True),
    Column('avg_b_score', DECIMAL(3, 2), nullable=True),
    Column('avg_d_score', DECIMAL(3, 2), nullable=True),
    Column('avg_composite_score', DECIMAL(4, 2), nullable=True),
    Column('started_at', DateTime, nullable=True),
    Column('submitted_at', DateTime, nullable=True),
    Column('time_elapsed_seconds', Integer, nullable=True),
    Column('added_at', DateTime, nullable=True)
)

ca_question_submissions = Table('ca_question_submissions', metadata,
    Column('q_id', Integer, primary_key=True, autoincrement=True),
    Column('ca_id', Integer, ForeignKey('curiosity_assessment.assmt_id', ondelete='CASCADE'), nullable=False),
    Column('student_id', Integer, nullable=False),
    Column('question_number', SmallInteger, nullable=False),
    Column('question', Text, nullable=False),
    Column('r_score', DECIMAL(4, 2), nullable=True),
    Column('b_score', DECIMAL(3, 2), nullable=True),
    Column('d_score', DECIMAL(3, 2), nullable=True),
    Column('composite_score', DECIMAL(4, 2), nullable=True),
    Column('verdict', String(500), nullable=True),
    Column('ai_feedback', Text, nullable=True),
    Column('question_reframe', Text, nullable=True),
    Column('nudge', Text, nullable=True),
    Column('submitted_at', DateTime, nullable=False)
)

ca_faculty_feedback = Table('ca_faculty_feedback', metadata,
    Column('feedback_id', Integer, primary_key=True, autoincrement=True),
    Column('ca_id', Integer, ForeignKey('curiosity_assessment.assmt_id', ondelete='CASCADE'), nullable=False),
    Column('student_id', Integer, nullable=False),
    Column('sent_by', Integer, nullable=False),
    Column('message', Text, nullable=False),
    Column('sent_at', DateTime, nullable=False)
)

ca_share = Table('ca_share', metadata,
    Column('ca_id', Integer, ForeignKey('curiosity_assessment.assmt_id', ondelete='CASCADE'), primary_key=True),
    Column('scope', Enum('faculty', 'department', 'hod', 'college'), nullable=False, default='faculty'),
    Column('share_url', String(512), nullable=False),
    Column('notified_emails', Text, nullable=True),
    Column('created_by', Integer, nullable=False),
    Column('created_at', DateTime, nullable=False),
    Column('updated_at', DateTime, nullable=False)
)

ca_similar_questions = Table('ca_similar_questions', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('source_q_id', Integer, nullable=False),
    Column('question', Text, nullable=False)
)
