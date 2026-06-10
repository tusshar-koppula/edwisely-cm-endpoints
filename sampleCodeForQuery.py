def getCoursesDataV2(user_id, db, metadata, academic_year_id = None, semester_type = None):
    college_id = getCollegeId(user_id, db, metadata)
    attendance_feature_enabled = attendanceFeatureCheck(college_id, db, metadata)
    response_data = OrderedDict()
    response_data['courses'] = []
    response_data['semesters'] = []
    semesters_data = []
    # Get required tables from metadata (same as in getDashboardData)
    college_account_new = metadata.tables['college_account_new']
    college_university_degree_department_new = metadata.tables['college_university_degree_department_new']
    college = metadata.tables['college']
    college_account_subject_college_department_section_new = metadata.tables['college_account_subject_college_department_section_new']
    college_subject_mapping = metadata.tables['college_subject_mapping']
    regulation_batch_mapping = metadata.tables['regulation_batch_mapping']
    academic_batches = metadata.tables['academic_batches']
    college_academic_years = metadata.tables['college_academic_years']
    academic_years = metadata.tables['academic_years']
    semester_migration = metadata.tables['semester_migration']
    subject_semester_new = metadata.tables['subject_semester_new']
    subject_master = metadata.tables['subject_master']
    university_degree_department_new = metadata.tables['university_degree_department_new']
    department_new = metadata.tables['department_new']
    topics = metadata.tables['topics']
    college_faculty_nav = metadata.tables['college_faculty_nav']
    faculty_navbar = metadata.tables['faculty_navbar']
    college_account_teater_unit_progress = metadata.tables['college_account_teater_unit_progress']
    college_department_section_new = metadata.tables['college_department_section_new']
    elective_subject_sections = metadata.tables['elective_subject_sections']
    cuddn2 = metadata.tables['college_university_degree_department_new'].alias('cuddn2')
    # Build the query using SQLAlchemy ORM
    if academic_year_id :
        faculty_courses_query = (
            select(
                college_account_subject_college_department_section_new.c.college_subject_mapping_id,
                college_account_subject_college_department_section_new.c.college_department_section_id,
                college_subject_mapping.c.subject_semester_id,
                subject_semester_new.c.subject_master_id,
                subject_master.c.name.label('subject_name'),
                case(
                    (college_subject_mapping.c.elective == 1, elective_subject_sections.c.section_name),
                    else_=college_department_section_new.c.section_name
                ).label('section_name'),
                college_subject_mapping.c.elective,
                academic_years.c.id.label('academic_year'),
                academic_years.c.name.label('academic_year_name'),
                college_subject_mapping.c.semester_id,
                cuddn2.c.id.label('subject_cudd_id'),
                department_new.c.id.label('subject_department_id'),
                department_new.c.name.label('subject_department_name'),
                department_new.c.full_name.label('subject_department_full_name'),
                topics.c.id.label('unit_id'),
                topics.c.name.label('unit_name'),
                college_faculty_nav.c.faculty_nav_id,
                college_account_teater_unit_progress.c.status,
                faculty_navbar.c.display_name.label('nav_bar_name'),
                college_account_subject_college_department_section_new.c.id.label('fsa_id'),
                college_subject_mapping.c.subject_code,
                college_subject_mapping.c.semester_id,
                academic_batches.c.batch_start,
                academic_batches.c.batch_end,
                func.coalesce(func.count(distinct(topics.c.id)), 0).label('total_units'),
                func.coalesce(func.sum(college_account_teater_unit_progress.c.status), 0).label('completed_units')
            )
            .select_from(
                college_account_new
                .join(college_university_degree_department_new, college_university_degree_department_new.c.id == college_account_new.c.college_university_degree_department_id)
                .join(college, college.c.id == college_university_degree_department_new.c.college_id)
                .join(college_account_subject_college_department_section_new, college_account_subject_college_department_section_new.c.college_account_id == college_account_new.c.id)
                .join(college_subject_mapping, college_subject_mapping.c.id == college_account_subject_college_department_section_new.c.college_subject_mapping_id)
                .join(regulation_batch_mapping, regulation_batch_mapping.c.id == college_subject_mapping.c.regulation_batch_mapping_id)
                .join(academic_batches, academic_batches.c.id == regulation_batch_mapping.c.batch_id)
                .join(college_academic_years, 
                    and_(
                        college_academic_years.c.regulation_batch_mapping_id == college_subject_mapping.c.regulation_batch_mapping_id,
                        or_(
                            college_academic_years.c.start_semester == college_subject_mapping.c.semester_id,
                            college_academic_years.c.end_semester == college_subject_mapping.c.semester_id
                        )
                    ))
                .join(academic_years, academic_years.c.id == college_academic_years.c.academic_year_id)
                .join(semester_migration, 
                    and_(
                        semester_migration.c.college_id == college.c.id,
                        semester_migration.c.batch_id == regulation_batch_mapping.c.batch_id,
                        college_subject_mapping.c.semester_id == semester_migration.c.semester_id
                    ))
                .join(subject_semester_new, subject_semester_new.c.id == college_subject_mapping.c.subject_semester_id)
                .join(subject_master, subject_master.c.id == subject_semester_new.c.subject_master_id)
                .join(cuddn2, 
                    cuddn2.c.id == college_subject_mapping.c.college_university_degree_department_id)
                .join(university_degree_department_new, 
                    university_degree_department_new.c.id == cuddn2.c.university_degree_department_id)
                .join(department_new, department_new.c.id == university_degree_department_new.c.department_id)
                .join(topics, topics.c.subject_semester_id == college_subject_mapping.c.subject_semester_id)
                .join(college_faculty_nav, 
                    and_(
                        college_faculty_nav.c.college_id == college_university_degree_department_new.c.college_id,
                        college_faculty_nav.c.active_status == 1
                    ))
                .join(faculty_navbar, 
                    and_(
                        faculty_navbar.c.id == college_faculty_nav.c.faculty_nav_id,
                        faculty_navbar.c.require_tracking == 1
                    ))
                .outerjoin(college_account_teater_unit_progress, 
                        and_(
                            college_account_teater_unit_progress.c.college_account_id == college_account_new.c.id,
                            college_account_teater_unit_progress.c.college_subject_mapping_id == college_subject_mapping.c.id,
                            topics.c.id == college_account_teater_unit_progress.c.unit_id,
                            college_faculty_nav.c.faculty_nav_id == college_account_teater_unit_progress.c.faculty_nav_id,
                            college_account_teater_unit_progress.c.section_id == college_account_subject_college_department_section_new.c.college_department_section_id
                        ))
                .outerjoin(college_department_section_new, 
                        and_(
                            college_department_section_new.c.id == college_account_subject_college_department_section_new.c.college_department_section_id,
                            college_subject_mapping.c.elective == 0 , college_department_section_new.c.test == 0, college_department_section_new.c.active == 1
                        ))
                .outerjoin(elective_subject_sections, 
                        and_(
                            elective_subject_sections.c.id == college_account_subject_college_department_section_new.c.college_department_section_id,
                            college_subject_mapping.c.elective == 1, elective_subject_sections.c.active_status == 1
                        ))
            )
            .where(
                and_(
                    college_account_new.c.id == user_id,
                    college_account_subject_college_department_section_new.c.college_subject_mapping_id != None,
                    college_account_subject_college_department_section_new.c.college_department_section_id != None,
                    college_account_subject_college_department_section_new.c.inactive == 0,
                    academic_years.c.id == academic_year_id,
                    college_subject_mapping.c.semester_id %2 == 0 if semester_type == 'even' else college_subject_mapping.c.semester_id %2 != 0 if semester_type == 'odd' else True,
                    # college_subject_mapping.c.semester_id == semester_id,                    
                )
            )
            .group_by(
                college_account_subject_college_department_section_new.c.id,
                faculty_navbar.c.id
            )
        )
    else:
        faculty_courses_query = (
            select(
                college_account_subject_college_department_section_new.c.college_subject_mapping_id,
                college_account_subject_college_department_section_new.c.college_department_section_id,
                college_subject_mapping.c.subject_semester_id,
                subject_semester_new.c.subject_master_id,
                subject_master.c.name.label('subject_name'),
                case(
                    (college_subject_mapping.c.elective == 1, elective_subject_sections.c.section_name),
                    else_=college_department_section_new.c.section_name
                ).label('section_name'),
                college_subject_mapping.c.elective,
                academic_years.c.id.label('academic_year'),
                academic_years.c.name.label('academic_year_name'),
                college_subject_mapping.c.semester_id,
                cuddn2.c.id.label('subject_cudd_id'),
                department_new.c.id.label('subject_department_id'),
                department_new.c.name.label('subject_department_name'),
                department_new.c.full_name.label('subject_department_full_name'),
                topics.c.id.label('unit_id'),
                topics.c.name.label('unit_name'),
                college_faculty_nav.c.faculty_nav_id,
                college_account_teater_unit_progress.c.status,
                faculty_navbar.c.display_name.label('nav_bar_name'),
                college_account_subject_college_department_section_new.c.id.label('fsa_id'),
                college_subject_mapping.c.subject_code,
                college_subject_mapping.c.semester_id,
                academic_batches.c.batch_start,
                academic_batches.c.batch_end,
                func.coalesce(func.count(distinct(topics.c.id)), 0).label('total_units'),
                func.coalesce(func.sum(college_account_teater_unit_progress.c.status), 0).label('completed_units')
            )
            .select_from(
                college_account_new
                .join(college_university_degree_department_new, college_university_degree_department_new.c.id == college_account_new.c.college_university_degree_department_id)
                .join(college, college.c.id == college_university_degree_department_new.c.college_id)
                .join(college_account_subject_college_department_section_new, college_account_subject_college_department_section_new.c.college_account_id == college_account_new.c.id)
                .join(college_subject_mapping, college_subject_mapping.c.id == college_account_subject_college_department_section_new.c.college_subject_mapping_id)
                .join(regulation_batch_mapping, regulation_batch_mapping.c.id == college_subject_mapping.c.regulation_batch_mapping_id)
                .join(academic_batches, academic_batches.c.id == regulation_batch_mapping.c.batch_id)
                .join(college_academic_years, 
                    and_(
                        college_academic_years.c.regulation_batch_mapping_id == college_subject_mapping.c.regulation_batch_mapping_id,
                        or_(
                            college_academic_years.c.start_semester == college_subject_mapping.c.semester_id,
                            college_academic_years.c.end_semester == college_subject_mapping.c.semester_id
                        )
                    ))
                .join(academic_years, academic_years.c.id == college_academic_years.c.academic_year_id)
                .join(semester_migration, 
                    and_(
                        semester_migration.c.college_id == college.c.id,
                        semester_migration.c.batch_id == regulation_batch_mapping.c.batch_id,
                        college_subject_mapping.c.semester_id == semester_migration.c.semester_id,
                        semester_migration.c.end_date == None
                    ))
                .join(subject_semester_new, subject_semester_new.c.id == college_subject_mapping.c.subject_semester_id)
                .join(subject_master, subject_master.c.id == subject_semester_new.c.subject_master_id)
                .join(cuddn2, 
                    cuddn2.c.id == college_subject_mapping.c.college_university_degree_department_id)
                .join(university_degree_department_new, 
                    university_degree_department_new.c.id == cuddn2.c.university_degree_department_id)
                .join(department_new, department_new.c.id == university_degree_department_new.c.department_id)
                .join(topics, topics.c.subject_semester_id == college_subject_mapping.c.subject_semester_id)
                .join(college_faculty_nav, 
                    and_(
                        college_faculty_nav.c.college_id == college_university_degree_department_new.c.college_id,
                        college_faculty_nav.c.active_status == 1
                    ))
                .join(faculty_navbar, 
                    and_(
                        faculty_navbar.c.id == college_faculty_nav.c.faculty_nav_id,
                        faculty_navbar.c.require_tracking == 1
                    ))
                .outerjoin(college_account_teater_unit_progress, 
                        and_(
                            college_account_teater_unit_progress.c.college_account_id == college_account_new.c.id,
                            college_account_teater_unit_progress.c.college_subject_mapping_id == college_subject_mapping.c.id,
                            topics.c.id == college_account_teater_unit_progress.c.unit_id,
                            college_faculty_nav.c.faculty_nav_id == college_account_teater_unit_progress.c.faculty_nav_id,
                            college_account_teater_unit_progress.c.section_id == college_account_subject_college_department_section_new.c.college_department_section_id
                        ))
                .outerjoin(college_department_section_new, 
                        and_(
                            college_department_section_new.c.id == college_account_subject_college_department_section_new.c.college_department_section_id,
                            college_subject_mapping.c.elective == 0 , college_department_section_new.c.test == 0, college_department_section_new.c.active == 1
                        ))
                .outerjoin(elective_subject_sections, 
                        and_(
                            elective_subject_sections.c.id == college_account_subject_college_department_section_new.c.college_department_section_id,
                            college_subject_mapping.c.elective == 1, elective_subject_sections.c.active_status == 1
                        ))
            )
            .where(
                and_(
                    college_account_new.c.id == user_id,
                    college_account_subject_college_department_section_new.c.college_subject_mapping_id != None,
                    college_account_subject_college_department_section_new.c.college_department_section_id != None,
                    college_account_subject_college_department_section_new.c.inactive == 0
                )
            )
            .group_by(
                college_account_subject_college_department_section_new.c.id,
                faculty_navbar.c.id
            )
        )
    faculty_courses = db.execute(faculty_courses_query).mappings().all()

    # Measure time for processing faculty courses data
    fsa_ids = set()
    semester_ids = set()
    faculty_subject_sections_dict = OrderedDict()
    if faculty_courses:
        section_ids = []
        csm_ids = []

        for course in faculty_courses:
            section_name = course['section_name']
            if not section_name:
                continue
            section_key = (user_id, course['college_subject_mapping_id'], course['college_department_section_id'])
            fsa_id = course['fsa_id']
            fsa_ids.add(fsa_id)
            
            if course['semester_id'] not in semester_ids:
                semesters_data.append({
                    'unique_id': course['semester_id'],
                    'display_name': course['semester_id'],
                    'semester_id': course['semester_id'],
                    'academic_year_id': course['academic_year'],
                    'academic_year_name': course['academic_year_name']
                })
            semester_ids.add(course['semester_id'])

            if section_key not in faculty_subject_sections_dict:
                faculty_subject_sections_dict[section_key] = {
                    'faculty_section_id': fsa_id,
                    'fsa_id':fsa_id,
                    'college_subject_mapping_id': course['college_subject_mapping_id'],
                    'subject_master_id': course['subject_master_id'],
                    'subject_semester_id': course['subject_semester_id'],
                    'subject_name': course['subject_name'],
                    'section_id': course['college_department_section_id'],
                    'section_name': course['section_name'],
                    'semester_id': course['semester_id'],
                    'subject_code': course['subject_code'],
                    'department_id': course['subject_department_id'],
                    'department_name': course['subject_department_full_name'],
                    'elective': course['elective'],
                    'batch_start': course['batch_start'],
                    'batch_end': course['batch_end'],
                    'course_completion_percentage':None,
                    'teater_progress': [],
                    'stats': {
                        'tests_conducted': 0,
                        'avg_participation': 0,
                        'avg_performance': 0
                    }
                }
                section_ids.append(course['college_department_section_id'])
                csm_ids.append(course['college_subject_mapping_id'])

            teater_progress_entry = next(
                (entry for entry in faculty_subject_sections_dict[section_key]['teater_progress'] if entry['faculty_nav_id'] == course['faculty_nav_id']),
                None
            )
            if not teater_progress_entry:
                teater_progress = course['completed_units'] / course['total_units'] * 100 if course['total_units'] > 0 else 0
                teater_progress_entry = {
                    'faculty_nav_id': course['faculty_nav_id'],
                    'faculty_nav_name': course['nav_bar_name'],
                    'display_name': course['nav_bar_name'][0].upper(),
                    # 'unit_status': [],
                    'total_units': course['total_units'],
                    'completed_units_count': course['completed_units'],
                    'teater_completion_percentage': teater_progress if teater_progress <= 100 else 0,
                }
                faculty_subject_sections_dict[section_key]['teater_progress'].append(teater_progress_entry)

        # Prepare unique pairs of section IDs and CSM IDs
        section_csm_pairs = list({(course['college_department_section_id'], course['college_subject_mapping_id']) for course in faculty_courses if course['college_department_section_id'] is not None and course['college_subject_mapping_id'] is not None})

        # Fetch stats for all combinations at once
        stats_data = getSubjectStats(section_csm_pairs, user_id, db, metadata)
        stats_dict = {}
        for row in stats_data:
            key = (row['section_id'], row['csm_id'])
            if key not in stats_dict:
                stats_dict[key] = []
            stats_dict[key].append(row)

        # Fetch participation and performance trends
        trends_data = getParticipationPerformanceTrends(section_csm_pairs, user_id, db, metadata)
        trends_dict = { (row['section_id'], row['csm_id']): row for row in trends_data }

        if attendance_feature_enabled and section_csm_pairs:
            course_completion_data_sql = text('''select fss.section_id,fss.college_subject_mapping_id,round(sum(fss.percentage_completed),2) as course_completion_percentage
                                            from faculty_subject_summary fss 
                                            where (fss.section_id,fss.college_subject_mapping_id ) in :section_csm_pairs
                                            group by fss.section_id,fss.college_subject_mapping_id''').bindparams(
                bindparam('section_csm_pairs', expanding=True)  
            )
            course_completion_data = db.execute(course_completion_data_sql,{'section_csm_pairs':section_csm_pairs}).mappings().all()
            course_completion_data = { (row['section_id'], row['college_subject_mapping_id']): row for row in course_completion_data }
        else:
            course_completion_data = None
        # Assign stats and trends to each section
        for section_key, section_data in faculty_subject_sections_dict.items():
            section_id = section_data['section_id']
            csm_id = section_data['college_subject_mapping_id']
            section_stats = stats_dict.get((section_id, csm_id), [])
            section_trends = trends_dict.get((section_id, csm_id), {})

            if course_completion_data:
                section_data['course_completion_percentage'] = course_completion_data.get((section_id, csm_id), {}).get('course_completion_percentage', 0)
            else:
                section_data['course_completion_percentage'] = None
                
            if section_stats:
                total_weight = sum(row['faculty_weight'] for row in section_stats)
                weighted_performance = 0

                for row in section_stats:
                    test_type_weight = row['faculty_weight']
                    participation = row['average_participation']
                    performance = row['average_performance']

                    weighted_performance += (performance * (participation / 100)) * (test_type_weight / total_weight)
                section_data['stats']['tests_conducted'] = sum(row['total_tests'] for row in section_stats)
                section_data['stats']['avg_participation'] = round(sum(row['average_participation'] for row in section_stats) / len(section_stats), 2)  
                section_data['stats']['avg_performance'] = round(weighted_performance, 2)

            if section_trends:
                participation_change = section_trends.get('avg_participation_last_7_days', 0) - section_trends.get('avg_participation_last_7_to_14_days', 0)
                performance_change = section_trends.get('avg_performance_last_7_days', 0) - section_trends.get('avg_performance_last_7_to_14_days', 0)

                participation_percentage_change = (
                    (participation_change / section_trends.get('avg_participation_last_7_to_14_days', 1)) * 100
                    if section_trends.get('avg_participation_last_7_to_14_days', 0) != 0 else 0
                )
                performance_percentage_change = (
                    (performance_change / section_trends.get('avg_performance_last_7_to_14_days', 1)) * 100
                    if section_trends.get('avg_performance_last_7_to_14_days', 0) != 0 else 0
                )

                section_data['stats']['avg_participation_last_7_days'] = round(section_trends.get('avg_participation_last_7_days', 0),2)
                section_data['stats']['avg_performance_last_7_days'] = round(section_trends.get('avg_performance_last_7_days', 0),2)     
                section_data['stats']['avg_participation_last_7_to_14_days'] = round(section_trends.get('avg_participation_last_7_to_14_days', 0),2)
                section_data['stats']['avg_performance_last_7_to_14_days'] = round(section_trends.get('avg_performance_last_7_to_14_days', 0),2)  
                section_data['stats']['participation_percentage_change'] = round(participation_percentage_change, 2)
                section_data['stats']['performance_percentage_change'] = round(performance_percentage_change, 2)
            else:
                section_data['stats']['avg_participation_last_7_days'] = None
                section_data['stats']['avg_performance_last_7_days'] = None  
                section_data['stats']['avg_participation_last_7_to_14_days'] = None
                section_data['stats']['avg_performance_last_7_to_14_days'] = None
                section_data['stats']['participation_percentage_change'] = 0
                section_data['stats']['performance_percentage_change'] = 0

    response_data['semesters'] = sorted(semesters_data, key=lambda x: x['semester_id'])
    
    courses_data = list(faculty_subject_sections_dict.values())
    response_data['courses'] = courses_data
    return 200, "Successfully retrieved the data", response_data
