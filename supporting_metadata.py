# =============================================================
# CURIOSITY ASSESSMENT — SUPPORTING TABLES REFERENCE
#
# This file is for integration reference ONLY.
# It is not imported or used anywhere in the CA codebase.
#
# Each table definition reflects only the columns that the
# CA feature reads from that table.  Full table schemas may
# have additional columns not listed here.
#
# Two tables (college_subject_mapping, subject_topic_mappings)
# also appear in metadata.py with different column sets —
# the definitions here match the live DB columns used by CA.
# =============================================================


from sqlalchemy import Table, Column, Integer, String, SmallInteger, Enum, MetaData

supporting_metadata = MetaData()

academic_years = Table('academic_years', supporting_metadata,
    Column('id',   Integer, primary_key=True),
    Column('name', String(20), nullable=False)
)

college_academic_years = Table('college_academic_years', supporting_metadata,
    Column('id',                          Integer, primary_key=True),
    Column('regulation_batch_mapping_id', Integer, nullable=False),
    Column('academic_year_id',            Integer, nullable=False),
    Column('start_semester',              Integer, nullable=False),
    Column('end_semester',                Integer, nullable=False)
)

college_account_new = Table('college_account_new', supporting_metadata,
    Column('id',                                     Integer, primary_key=True),
    Column('name',                                   String(100), nullable=False),
    Column('roll_number',                            String(30),  nullable=True),
    Column('role',                                   Enum('faculty', 'hod', 'principal', 'student'), nullable=False),
    Column('college_university_degree_department_id', Integer, nullable=True)
)

college_account_subject_college_department_section_new = Table(
    'college_account_subject_college_department_section_new', supporting_metadata,
    Column('id',                           Integer,      primary_key=True),
    Column('college_account_id',           Integer,      nullable=False),
    Column('college_subject_mapping_id',   Integer,      nullable=False),
    Column('college_department_section_id', Integer,     nullable=False),
    Column('inactive',                     SmallInteger, nullable=False, default=0)
)

college_department_section_new = Table('college_department_section_new', supporting_metadata,
    Column('id',           Integer,      primary_key=True),
    Column('section_name', String(50),   nullable=False),
    Column('department_id', Integer,     nullable=False),
    Column('active',       SmallInteger, nullable=False, default=1),
    Column('test',         SmallInteger, nullable=False, default=0)
)

college_subject_mapping = Table('college_subject_mapping', supporting_metadata,
    Column('id',                                      Integer,    primary_key=True),
    Column('subject_code',                            String(20), nullable=False),
    Column('subject_semester_id',                     Integer,    nullable=False),
    Column('college_university_degree_department_id', Integer,    nullable=False),
    Column('semester_id',                             Integer,    nullable=False, default=1),
    Column('regulation_batch_mapping_id',             Integer,    nullable=True)
)

college_university_degree_department_new = Table('college_university_degree_department_new', supporting_metadata,
    Column('id',                               Integer, primary_key=True),
    Column('college_id',                       Integer, nullable=False),
    Column('university_degree_department_id',  Integer, nullable=False)
)

department_new = Table('department_new', supporting_metadata,
    Column('id',        Integer,      primary_key=True),
    Column('name',      String(20),   nullable=False),
    Column('full_name', String(100),  nullable=False)
)

regulation_batch_mapping = Table('regulation_batch_mapping', supporting_metadata,
    Column('id', Integer, primary_key=True)
)

student_section_mapping = Table('student_section_mapping', supporting_metadata,
    Column('id',         Integer, primary_key=True),
    Column('student_id', Integer, nullable=False),
    Column('section_id', Integer, nullable=False)
)

subject_master = Table('subject_master', supporting_metadata,
    Column('id',   Integer,      primary_key=True),
    Column('name', String(100),  nullable=False)
)

subject_semester_new = Table('subject_semester_new', supporting_metadata,
    Column('id',                Integer, primary_key=True),
    Column('subject_master_id', Integer, nullable=False)
)

subject_topic_mappings = Table('subject_topic_mappings', supporting_metadata,
    Column('id',                         Integer,      primary_key=True),
    Column('college_subject_mapping_id', Integer,      nullable=False),
    Column('unit_id',                    Integer,      nullable=False),
    Column('unit_name',                  String(100),  nullable=False),
    Column('topic_id',                   Integer,      nullable=False),
    Column('topic_name',                 String(200),  nullable=False),
    Column('topic_code',                 String(30),   nullable=False),
    Column('topic_type',                 String(30),   nullable=False, default='concept')
)

university_degree_department_new = Table('university_degree_department_new', supporting_metadata,
    Column('id',            Integer, primary_key=True),
    Column('department_id', Integer, nullable=False)
)
