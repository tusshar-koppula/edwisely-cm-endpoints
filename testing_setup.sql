-- ============================================================
-- FRESH SETUP — curiosity assessment testing
-- Run after: DROP DATABASE cm_edwisely_db; CREATE DATABASE cm_edwisely_db;
-- ============================================================

USE cm_edwisely_db;

-- -------------------------------------------------------
-- PART A: Supporting tables (pre-existing platform schema)
-- -------------------------------------------------------

CREATE TABLE department_new (
    id        INT          NOT NULL AUTO_INCREMENT,
    name      VARCHAR(20)  NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE university_degree_department_new (
    id            INT NOT NULL AUTO_INCREMENT,
    department_id INT NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE college_university_degree_department_new (
    id                              INT NOT NULL AUTO_INCREMENT,
    college_id                      INT NOT NULL,
    university_degree_department_id INT NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE college_account_new (
    id                                      INT          NOT NULL AUTO_INCREMENT,
    name                                    VARCHAR(100) NOT NULL,
    roll_number                             VARCHAR(30)  DEFAULT NULL,
    role                                    ENUM('faculty','hod','principal','student') NOT NULL,
    college_university_degree_department_id INT          DEFAULT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE college_department_section_new (
    id            INT         NOT NULL AUTO_INCREMENT,
    section_name  VARCHAR(50) NOT NULL,
    department_id INT         NOT NULL,
    active        TINYINT(1)  NOT NULL DEFAULT 1,
    test          TINYINT(1)  NOT NULL DEFAULT 0,
    PRIMARY KEY (id)
);

CREATE TABLE regulation_batch_mapping (
    id INT NOT NULL AUTO_INCREMENT,
    PRIMARY KEY (id)
);

CREATE TABLE academic_years (
    id   INT         NOT NULL AUTO_INCREMENT,
    name VARCHAR(20) NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE college_academic_years (
    id                          INT NOT NULL AUTO_INCREMENT,
    regulation_batch_mapping_id INT NOT NULL,
    academic_year_id            INT NOT NULL,
    start_semester              INT NOT NULL,
    end_semester                INT NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE subject_master (
    id   INT          NOT NULL AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE subject_semester_new (
    id                INT NOT NULL AUTO_INCREMENT,
    subject_master_id INT NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE college_subject_mapping (
    id                                      INT         NOT NULL AUTO_INCREMENT,
    subject_code                            VARCHAR(20) NOT NULL,
    subject_semester_id                     INT         NOT NULL,
    college_university_degree_department_id INT         NOT NULL,
    semester_id                             INT         NOT NULL DEFAULT 1,
    regulation_batch_mapping_id             INT         DEFAULT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE college_account_subject_college_department_section_new (
    id                           INT        NOT NULL AUTO_INCREMENT,
    college_account_id           INT        NOT NULL,
    college_subject_mapping_id   INT        NOT NULL,
    college_department_section_id INT       NOT NULL,
    inactive                     TINYINT(1) NOT NULL DEFAULT 0,
    PRIMARY KEY (id)
);

CREATE TABLE subject_topic_mappings (
    id                         INT          NOT NULL AUTO_INCREMENT,
    college_subject_mapping_id INT          NOT NULL,
    unit_id                    INT          NOT NULL,
    unit_name                  VARCHAR(100) NOT NULL,
    topic_id                   INT          NOT NULL,
    topic_name                 VARCHAR(200) NOT NULL,
    topic_code                 VARCHAR(30)  NOT NULL,
    topic_type                 VARCHAR(30)  NOT NULL DEFAULT 'concept',
    PRIMARY KEY (id)
);

CREATE TABLE student_section_mapping (
    id         INT NOT NULL AUTO_INCREMENT,
    student_id INT NOT NULL,
    section_id INT NOT NULL,
    PRIMARY KEY (id)
);

-- -------------------------------------------------------
-- PART B: Curiosity Assessment tables
-- -------------------------------------------------------

CREATE TABLE curiosity_assessment (
    assmt_id               INT          NOT NULL AUTO_INCREMENT,
    created_by             INT          NOT NULL,
    topic_source           ENUM('document','topic') NOT NULL,
    assmt_title            VARCHAR(255) NOT NULL,
    assmt_brief            TEXT         DEFAULT NULL,
    question_count         TINYINT      NOT NULL DEFAULT 3,
    duration_minutes       SMALLINT     NOT NULL DEFAULT 15,
    subject_code           VARCHAR(20)  DEFAULT NULL,
    doc_name               VARCHAR(255) DEFAULT NULL,
    doc_s3_key             VARCHAR(512) DEFAULT NULL,
    doc_storage_url        TEXT         DEFAULT NULL,
    doc_pages              SMALLINT     DEFAULT NULL,
    doc_size_bytes         INT          DEFAULT NULL,
    rubric_relevance_limit TINYINT      NOT NULL DEFAULT 4,
    rubric_blooms_limit    TINYINT      NOT NULL DEFAULT 3,
    rubric_depth_limit     TINYINT      NOT NULL DEFAULT 3,
    status                 ENUM('draft','scheduled','live','ended') NOT NULL DEFAULT 'draft',
    start_time             DATETIME     DEFAULT NULL,
    end_time               DATETIME     DEFAULT NULL,
    is_deleted             TINYINT(1)   NOT NULL DEFAULT 0,
    avg_composite_score    DECIMAL(4,2) DEFAULT NULL,
    avg_r_score            DECIMAL(4,2) DEFAULT NULL,
    avg_b_score            DECIMAL(4,2) DEFAULT NULL,
    avg_d_score            DECIMAL(4,2) DEFAULT NULL,
    median_time_seconds    INT          DEFAULT NULL,
    score_distribution     JSON         DEFAULT NULL,
    created_at             DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (assmt_id)
);

CREATE TABLE ca_has_sections (
    ca_id      INT NOT NULL,
    section_id INT NOT NULL,
    PRIMARY KEY (ca_id, section_id),
    CONSTRAINT fk_sections_assmt FOREIGN KEY (ca_id)
        REFERENCES curiosity_assessment(assmt_id) ON DELETE CASCADE
);

CREATE TABLE ca_has_students (
    ca_id               INT          NOT NULL,
    student_id          INT          NOT NULL,
    status              ENUM('not_started','writing','submitted') NOT NULL DEFAULT 'not_started',
    submitted_at        DATETIME     DEFAULT NULL,
    time_elapsed_seconds INT         DEFAULT NULL,
    started_at           DATETIME    DEFAULT NULL,
    avg_composite_score DECIMAL(4,2) DEFAULT NULL,
    avg_r_score         DECIMAL(4,2) DEFAULT NULL,
    avg_b_score         DECIMAL(4,2) DEFAULT NULL,
    avg_d_score         DECIMAL(4,2) DEFAULT NULL,
    added_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ca_id, student_id),
    CONSTRAINT fk_students_assmt FOREIGN KEY (ca_id)
        REFERENCES curiosity_assessment(assmt_id) ON DELETE CASCADE
);

CREATE TABLE ca_question_submissions (
    q_id            INT          NOT NULL AUTO_INCREMENT,
    ca_id           INT          NOT NULL,
    student_id      INT          NOT NULL,
    question_number TINYINT      NOT NULL DEFAULT 1,
    question        TEXT         NOT NULL,
    r_score         DECIMAL(4,2) DEFAULT NULL,
    b_score         DECIMAL(4,2) DEFAULT NULL,
    d_score         DECIMAL(4,2) DEFAULT NULL,
    composite_score DECIMAL(4,2) DEFAULT NULL,
    ai_feedback     TEXT         DEFAULT NULL,
    submitted_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (q_id),
    CONSTRAINT fk_questions_assmt FOREIGN KEY (ca_id)
        REFERENCES curiosity_assessment(assmt_id) ON DELETE CASCADE
);

-- Index required for the single-query JOIN and scalar subquery performance
CREATE INDEX idx_ca_has_students_ca_id         ON ca_has_students(ca_id);
CREATE INDEX idx_ca_question_submissions_ca_id  ON ca_question_submissions(ca_id);

CREATE TABLE ca_has_topics (
    ca_id    INT NOT NULL,
    topic_id INT NOT NULL,
    PRIMARY KEY (ca_id, topic_id),
    CONSTRAINT fk_has_topics_assmt FOREIGN KEY (ca_id)
        REFERENCES curiosity_assessment(assmt_id) ON DELETE CASCADE
);

CREATE TABLE ca_faculty_feedback (
    feedback_id INT      NOT NULL AUTO_INCREMENT,
    ca_id       INT      NOT NULL,
    student_id  INT      NOT NULL,
    sent_by     INT      NOT NULL,
    message     TEXT     NOT NULL,
    sent_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (feedback_id),
    CONSTRAINT fk_feedback_assmt FOREIGN KEY (ca_id)
        REFERENCES curiosity_assessment(assmt_id) ON DELETE CASCADE
);

CREATE TABLE ca_share (
    ca_id           INT          NOT NULL,
    scope           ENUM('faculty','department','hod','college') NOT NULL DEFAULT 'faculty',
    share_url       VARCHAR(512) NOT NULL,
    notified_emails TEXT         DEFAULT NULL,
    created_by      INT          NOT NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (ca_id),
    CONSTRAINT fk_share_assmt FOREIGN KEY (ca_id)
        REFERENCES curiosity_assessment(assmt_id) ON DELETE CASCADE
);

CREATE TABLE ca_similar_questions (
    id          INT  NOT NULL AUTO_INCREMENT,
    source_q_id INT  NOT NULL,
    question    TEXT NOT NULL,
    PRIMARY KEY (id),
    INDEX idx_similar_source_q (source_q_id)
);

-- -------------------------------------------------------
-- PART C: Seed data
-- -------------------------------------------------------

-- Org structure
INSERT INTO department_new (id, name, full_name) VALUES
(1, 'CSE', 'Computer Science and Engineering');

INSERT INTO university_degree_department_new (id, department_id) VALUES (1, 1);

INSERT INTO college_university_degree_department_new (id, college_id, university_degree_department_id) VALUES
(1, 1, 1);

-- Users: 101=faculty, 102=hod, 103=principal, 201-204=students
INSERT INTO college_account_new (id, name, roll_number, role, college_university_degree_department_id) VALUES
(101, 'Dr. Ramesh Kumar', NULL,      'faculty',   1),
(102, 'Prof. Meena Nair', NULL,      'hod',       1),
(103, 'Dr. S. Venkat',    NULL,      'principal', 1),
(201, 'Alice Thomas',     '21CS001', 'student',   1),
(202, 'Bob Menon',        '21CS002', 'student',   1),
(203, 'Carol Patel',      '21CS003', 'student',   1),
(204, 'David Singh',      '21CS004', 'student',   1);

-- Sections
INSERT INTO college_department_section_new (id, section_name, department_id, active, test) VALUES
(1, 'CSE-A 2021', 1, 1, 0),
(2, 'CSE-B 2021', 1, 1, 0);

-- Regulation & academic years
INSERT INTO regulation_batch_mapping (id) VALUES (1);
INSERT INTO academic_years (id, name) VALUES (1, '2023-24'), (2, '2024-25');
INSERT INTO college_academic_years (id, regulation_batch_mapping_id, academic_year_id, start_semester, end_semester) VALUES
(1, 1, 1, 3, 4),
(2, 1, 2, 5, 6);

-- Subjects
INSERT INTO subject_master (id, name) VALUES
(1, 'Data Structures and Algorithms'),
(2, 'Operating Systems');

INSERT INTO subject_semester_new (id, subject_master_id) VALUES (1, 1), (2, 2);

INSERT INTO college_subject_mapping (id, subject_code, subject_semester_id, college_university_degree_department_id, semester_id, regulation_batch_mapping_id) VALUES
(1, 'CS201', 1, 1, 3, 1),
(2, 'CS301', 2, 1, 5, 1);

-- Faculty-subject-section assignments
INSERT INTO college_account_subject_college_department_section_new
    (id, college_account_id, college_subject_mapping_id, college_department_section_id, inactive) VALUES
(1, 101, 1, 1, 0),
(2, 101, 1, 2, 0),
(3, 102, 2, 1, 0);

-- Topics for CS201
INSERT INTO subject_topic_mappings (id, college_subject_mapping_id, unit_id, unit_name, topic_id, topic_name, topic_code, topic_type) VALUES
(1, 1, 1, 'Unit 1: Arrays and Linked Lists', 1, 'Arrays',          'CS201-1-1', 'concept'),
(2, 1, 1, 'Unit 1: Arrays and Linked Lists', 2, 'Linked Lists',    'CS201-1-2', 'concept'),
(3, 1, 2, 'Unit 2: Trees and Graphs',        3, 'Binary Trees',    'CS201-2-1', 'concept'),
(4, 1, 2, 'Unit 2: Trees and Graphs',        4, 'Graph Traversal', 'CS201-2-2', 'concept');

-- Student-section mapping
INSERT INTO student_section_mapping (id, student_id, section_id) VALUES
(1, 201, 1), (2, 202, 1),
(3, 203, 2), (4, 204, 2);

-- ── Assessment 1: DRAFT ───────────────────────────────────────
INSERT INTO curiosity_assessment
    (assmt_id, created_by, topic_source, assmt_title, assmt_brief, question_count, duration_minutes,
     subject_code, rubric_relevance_limit, rubric_blooms_limit, rubric_depth_limit,
     status, start_time, end_time, is_deleted, created_at, updated_at)
VALUES
(1, 101, 'topic', 'DSA Quiz - Unit 1 Basics', 'Arrays and linked lists curiosity check.',
 3, 15, 'CS201', 4, 3, 3, 'draft', NULL, NULL, 0,
 '2026-06-10 09:00:00', '2026-06-10 09:00:00');

INSERT INTO ca_has_sections (ca_id, section_id) VALUES (1, 1), (1, 2);
INSERT INTO ca_has_topics   (ca_id, topic_id)   VALUES (1, 1), (1, 2);

-- ── Assessment 2: LIVE ────────────────────────────────────────
-- avg scores reflect Alice's 3 submitted questions (Bob is still writing)
INSERT INTO curiosity_assessment
    (assmt_id, created_by, topic_source, assmt_title, assmt_brief, question_count, duration_minutes,
     subject_code, rubric_relevance_limit, rubric_blooms_limit, rubric_depth_limit,
     status, start_time, end_time, is_deleted,
     avg_composite_score, avg_r_score, avg_b_score, avg_d_score,
     created_at, updated_at)
VALUES
(2, 101, 'topic', 'DSA Quiz - Trees and Graphs', 'Binary trees and graph traversal.',
 3, 20, 'CS201', 4, 3, 3, 'live',
 '2026-06-12 08:00:00', '2026-06-12 23:59:00', 0,
 7.83, 8.33, 7.83, 7.33,
 '2026-06-11 18:00:00', '2026-06-12 08:00:00');

INSERT INTO ca_has_sections (ca_id, section_id) VALUES (2, 1);
INSERT INTO ca_has_topics   (ca_id, topic_id)   VALUES (2, 3), (2, 4);

-- avg scores for Alice: avg of her 3 question composite/dim scores
INSERT INTO ca_has_students
    (ca_id, student_id, status, submitted_at, time_elapsed_seconds, started_at,
     avg_composite_score, avg_r_score, avg_b_score, avg_d_score) VALUES
(2, 201, 'submitted', '2026-06-12 09:30:00', 820,  '2026-06-12 09:16:20', 7.83, 8.33, 7.83, 7.33),
(2, 202, 'writing',   NULL,                  NULL, '2026-06-12 09:20:00', NULL, NULL, NULL, NULL);

INSERT INTO ca_question_submissions (q_id, ca_id, student_id, question_number, question, r_score, b_score, d_score, composite_score, ai_feedback, submitted_at) VALUES
(1, 2, 201, 1, 'How does in-order traversal work in a binary tree?',  8.5, 7.0, 7.5, 7.67, 'Good understanding. Mention edge cases.',           '2026-06-12 09:15:00'),
(2, 2, 201, 2, 'What is the time complexity of BFS on a graph?',      9.0, 8.5, 8.0, 8.50, 'Excellent. Also discuss space complexity.',         '2026-06-12 09:22:00'),
(3, 2, 201, 3, 'Explain DFS with an example.',                         7.5, 8.0, 6.5, 7.33, 'Correct example. Deeper use-case analysis needed.', '2026-06-12 09:30:00');

-- ── Assessment 3: ENDED ───────────────────────────────────────
-- median of submitted elapsed times [2700, 4200, 5400] = 4200s
-- class avg across 3 submitted students (David is absent)
INSERT INTO curiosity_assessment
    (assmt_id, created_by, topic_source, assmt_title, assmt_brief, question_count, duration_minutes,
     doc_name, doc_s3_key, doc_storage_url, doc_pages, doc_size_bytes,
     rubric_relevance_limit, rubric_blooms_limit, rubric_depth_limit,
     status, start_time, end_time, is_deleted,
     avg_composite_score, avg_r_score, avg_b_score, avg_d_score, median_time_seconds, score_distribution,
     created_at, updated_at)
VALUES
(3, 101, 'document', 'DSA Notes Assessment', 'Based on the uploaded DSA notes PDF.',
 3, 15,
 'DSA_Notes_Unit1.pdf', 'ca_documents/101/seed__DSA_Notes_Unit1.pdf',
 'https://edwisely-ca.s3.ap-south-1.amazonaws.com/ca_documents/101/seed__DSA_Notes_Unit1.pdf',
 12, 204800,
 4, 3, 3, 'ended',
 '2026-06-05 09:00:00', '2026-06-05 11:00:00', 0,
 8.00, 8.28, 8.11, 7.61, 4200,
 '[{"band":"5-6","count":0},{"band":"6-7","count":0},{"band":"7-8","count":1},{"band":"8-9","count":2},{"band":"9-10","count":0}]',
 '2026-06-04 12:00:00', '2026-06-05 11:05:00');

INSERT INTO ca_has_sections (ca_id, section_id) VALUES (3, 1), (3, 2);

INSERT INTO ca_has_students
    (ca_id, student_id, status, submitted_at, time_elapsed_seconds, started_at,
     avg_composite_score, avg_r_score, avg_b_score, avg_d_score) VALUES
(3, 201, 'submitted', '2026-06-05 09:45:00', 2700, '2026-06-05 09:00:00', 8.22, 8.50, 8.33, 7.83),
(3, 202, 'submitted', '2026-06-05 10:10:00', 4200, '2026-06-05 09:00:00', 7.11, 7.33, 7.33, 6.67),
(3, 203, 'submitted', '2026-06-05 10:30:00', 5400, '2026-06-05 09:00:00', 8.67, 9.00, 8.67, 8.33),
(3, 204, 'not_started', NULL,                NULL, NULL,                  NULL, NULL, NULL, NULL);

INSERT INTO ca_question_submissions (q_id, ca_id, student_id, question_number, question, r_score, b_score, d_score, composite_score, ai_feedback, submitted_at) VALUES
-- Alice (avg composite=8.22, r=8.50, b=8.33, d=7.83)
(4,  3, 201, 1, 'What is the difference between a stack and a queue?',      8.0, 8.5, 7.0, 7.83, 'Clear explanation. Add real-world examples.',  '2026-06-05 09:20:00'),
(5,  3, 201, 2, 'How does dynamic memory allocation work in linked lists?', 9.0, 7.5, 8.5, 8.33, 'Strong. Mention memory leaks.',                '2026-06-05 09:35:00'),
(6,  3, 201, 3, 'Explain the concept of a hash table.',                     8.5, 9.0, 8.0, 8.50, 'Excellent. Cover collision handling.',         '2026-06-05 09:45:00'),
-- Bob (avg composite=7.11, r=7.33, b=7.33, d=6.67)
(7,  3, 202, 1, 'What is a stack and how is it used in recursion?',         7.5, 8.0, 6.5, 7.33, 'Good basics. Elaborate on call stack.',        '2026-06-05 09:50:00'),
(8,  3, 202, 2, 'Compare arrays and linked lists for memory usage.',        8.0, 7.0, 7.5, 7.50, 'Correct. Mention cache performance.',          '2026-06-05 10:00:00'),
(9,  3, 202, 3, 'What is a priority queue?',                                6.5, 7.0, 6.0, 6.50, 'Basic. Discuss heap implementations.',         '2026-06-05 10:10:00'),
-- Carol (avg composite=8.67, r=9.00, b=8.67, d=8.33)
(10, 3, 203, 1, 'Describe a real-world use of a queue.',                    9.0, 8.0, 8.5, 8.50, 'Very good real-world example.',                '2026-06-05 10:10:00'),
(11, 3, 203, 2, 'How is a BST different from a sorted array?',              8.5, 9.0, 7.5, 8.33, 'Good comparison. Add complexity analysis.',    '2026-06-05 10:20:00'),
(12, 3, 203, 3, 'What is memoization and when is it useful?',               9.5, 9.0, 9.0, 9.17, 'Outstanding!',                                 '2026-06-05 10:30:00');

INSERT INTO ca_faculty_feedback (feedback_id, ca_id, student_id, sent_by, message, sent_at) VALUES
(1, 3, 201, 101, 'Great attempt Alice! Focus more on time complexity.',         '2026-06-05 12:00:00'),
(2, 3, 204, 101, 'David, you missed this — please see me in office hours.',     '2026-06-05 12:05:00');

INSERT INTO ca_share (ca_id, scope, share_url, notified_emails, created_by, created_at, updated_at) VALUES
(3, 'department', 'https://sastra.ai/assessments/3/results?token=abc123def456ghi789jkl012',
 'hod@example.com,principal@example.com', 101, '2026-06-05 13:00:00', '2026-06-05 13:00:00');

-- ── Assessment 4: SCHEDULED ───────────────────────────────────
INSERT INTO curiosity_assessment
    (assmt_id, created_by, topic_source, assmt_title, assmt_brief, question_count, duration_minutes,
     subject_code, rubric_relevance_limit, rubric_blooms_limit, rubric_depth_limit,
     status, start_time, end_time, is_deleted, created_at, updated_at)
VALUES
(4, 101, 'topic', 'Weekly Check - Graph Theory', 'Short check on graphs.',
 2, 10, 'CS201', 4, 3, 3, 'scheduled',
 '2026-06-15 09:00:00', '2026-06-15 11:00:00', 0,
 '2026-06-12 10:00:00', '2026-06-12 10:00:00');

INSERT INTO ca_has_sections (ca_id, section_id) VALUES (4, 1);
INSERT INTO ca_has_topics   (ca_id, topic_id)   VALUES (4, 4);
INSERT INTO ca_has_students (ca_id, student_id, status) VALUES
(4, 201, 'not_started'),
(4, 202, 'not_started');

-- ── Similar questions (hardcoded for top q_ids from assessment 3) ───────────
-- q_id 12: "What is memoization and when is it useful?" (composite 9.17 — highest)
-- q_id  6: "Explain the concept of a hash table."       (composite 8.50)
-- q_id 10: "Describe a real-world use of a queue."      (composite 8.50)
INSERT INTO ca_similar_questions (source_q_id, question) VALUES
(12, 'When would you prefer memoization over tabulation in dynamic programming?'),
(12, 'How does Fibonacci sequence implementation differ with and without memoization?'),
(12, 'What is the space-time trade-off when applying memoization?'),
(6,  'How does a hash table handle collisions using chaining?'),
(6,  'What is the difference between a hash map and a hash set?'),
(6,  'Why is the load factor important when designing a hash table?'),
(10, 'How is a circular queue different from a linear queue?'),
(10, 'Where is a queue used in operating system scheduling?'),
(10, 'What is the time complexity of enqueue and dequeue operations?');

-- ── Assessment 5: SOFT-DELETED ────────────────────────────────
INSERT INTO curiosity_assessment
    (assmt_id, created_by, topic_source, assmt_title, assmt_brief, question_count, duration_minutes,
     subject_code, rubric_relevance_limit, rubric_blooms_limit, rubric_depth_limit,
     status, start_time, end_time, is_deleted, created_at, updated_at)
VALUES
(5, 101, 'topic', 'Old Draft (Deleted)', 'Should not appear.',
 3, 15, 'CS201', 4, 3, 3, 'draft', NULL, NULL, 1,
 '2026-06-01 10:00:00', '2026-06-01 10:00:00');


-- -------------------------------------------------------
-- PART D: Patches for getAssessmentStats() testing
-- -------------------------------------------------------

-- Fix end_time on the LIVE assessment so closes_in is meaningful
UPDATE curiosity_assessment
SET end_time = '2026-12-31 23:59:00'
WHERE assmt_id = 2;

-- Add started_at for LIVE assessment students (assmt_id = 2)
-- Alice: submitted 09:30, elapsed 820s → started_at = 09:30 - 820s = 09:16:20
-- Bob:   still writing, started at 09:20:00
UPDATE ca_has_students SET started_at = '2026-06-12 09:16:20' WHERE ca_id = 2 AND student_id = 201;
UPDATE ca_has_students SET started_at = '2026-06-12 09:20:00' WHERE ca_id = 2 AND student_id = 202;

-- Add started_at for ENDED assessment students (assmt_id = 3)
-- Alice: submitted 09:45, elapsed 2700s (45m) → started_at = 09:00:00
-- Bob:   submitted 10:10, elapsed 4200s (70m) → started_at = 09:00:00
-- Carol: submitted 10:30, elapsed 5400s (90m) → started_at = 09:00:00
-- David: not_started → stays NULL
UPDATE ca_has_students SET started_at = '2026-06-05 09:00:00' WHERE ca_id = 3 AND student_id = 201;
UPDATE ca_has_students SET started_at = '2026-06-05 09:00:00' WHERE ca_id = 3 AND student_id = 202;
UPDATE ca_has_students SET started_at = '2026-06-05 09:00:00' WHERE ca_id = 3 AND student_id = 203;