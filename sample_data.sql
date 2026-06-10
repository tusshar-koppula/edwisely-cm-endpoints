-- ============================================================
-- SAMPLE DATA for local Postman testing
-- ============================================================

USE edwisely_cm_db;

-- ── Supporting hierarchy ──────────────────────────────────────

INSERT INTO regulation_batch_mapping (id) VALUES (1);

INSERT INTO academic_years (id, name) VALUES (1, '2024-25');

INSERT INTO college_academic_years
    (id, regulation_batch_mapping_id, start_semester, end_semester, academic_year_id)
VALUES (1, 1, 1, 8, 1);

INSERT INTO department_new (id, name, full_name)
VALUES (1, 'CSE', 'Computer Science and Engineering');

INSERT INTO university_degree_department_new (id, department_id)
VALUES (1, 1);

-- college_id = 1 for all users
INSERT INTO college_university_degree_department_new
    (id, college_id, university_degree_department_id)
VALUES (1, 1, 1);

-- ── Faculty user (token = 1 in Postman) ──────────────────────

INSERT INTO college_account_new (id, name, roll_number, college_university_degree_department_id)
VALUES (1, 'Dr. Test Faculty', NULL, 1);

-- ── Sections ─────────────────────────────────────────────────

INSERT INTO college_department_section_new (id, section_name, active, test, department_id)
VALUES
    (1, 'CSE-A', 1, 0, 1),
    (2, 'CSE-B', 1, 0, 1);

-- ── Students ─────────────────────────────────────────────────

INSERT INTO college_account_new (id, name, roll_number, college_university_degree_department_id)
VALUES
    (10, 'Alice Johnson',  '21CS001', 1),
    (11, 'Bob Smith',      '21CS002', 1),
    (12, 'Carol Williams', '21CS003', 1),
    (13, 'David Brown',    '21CS004', 1),
    (14, 'Eva Martinez',   '21CS005', 1);

-- Map students → sections (10,11,12 in CSE-A; 13,14 in CSE-B)
INSERT INTO student_section_mapping (student_id, section_id)
VALUES
    (10, 1), (11, 1), (12, 1),
    (13, 2), (14, 2);

-- ── Subject + topics ─────────────────────────────────────────

INSERT INTO subject_master (id, name) VALUES (1, 'Data Structures');

INSERT INTO subject_semester_new (id, subject_master_id) VALUES (1, 1);

INSERT INTO college_subject_mapping
    (id, subject_code, subject_semester_id, college_university_degree_department_id, semester_id, regulation_batch_mapping_id)
VALUES (1, 'CS301', 1, 1, 3, 1);

INSERT INTO topics (id, name, subject_semester_id)
VALUES
    (1, 'Unit 1 - Arrays & Linked Lists', 1),
    (2, 'Unit 2 - Trees & Graphs',        1),
    (3, 'Unit 3 - Sorting & Searching',   1);

-- Assign faculty (id=1) to the subject + sections
INSERT INTO college_account_subject_college_department_section_new
    (college_account_id, college_subject_mapping_id, college_department_section_id, inactive)
VALUES
    (1, 1, 1, 0),   -- faculty → CS301 → CSE-A
    (1, 1, 2, 0);   -- faculty → CS301 → CSE-B
