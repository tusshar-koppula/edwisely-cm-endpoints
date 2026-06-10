-- ============================================================
-- SUPPORTING TABLES (minimal stubs for testing)
-- Only the columns actually referenced in curiosity_assessment_data.py
-- ============================================================

USE edwisely_cm_db;

CREATE TABLE IF NOT EXISTS college_account_new (
    id                                      INT          NOT NULL AUTO_INCREMENT,
    name                                    VARCHAR(255) NOT NULL,
    roll_number                             VARCHAR(50)  DEFAULT NULL,
    college_university_degree_department_id INT          DEFAULT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS department_new (
    id        INT          NOT NULL AUTO_INCREMENT,
    name      VARCHAR(100) NOT NULL,
    full_name VARCHAR(255) DEFAULT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS university_degree_department_new (
    id            INT NOT NULL AUTO_INCREMENT,
    department_id INT NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS college_university_degree_department_new (
    id                              INT NOT NULL AUTO_INCREMENT,
    college_id                      INT NOT NULL,
    university_degree_department_id INT NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS college_department_section_new (
    id            INT          NOT NULL AUTO_INCREMENT,
    section_name  VARCHAR(100) NOT NULL,
    active        TINYINT(1)   NOT NULL DEFAULT 1,
    test          TINYINT(1)   NOT NULL DEFAULT 0,
    department_id INT          DEFAULT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS student_section_mapping (
    id         INT NOT NULL AUTO_INCREMENT,
    student_id INT NOT NULL,
    section_id INT NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS subject_master (
    id   INT          NOT NULL AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS subject_semester_new (
    id               INT NOT NULL AUTO_INCREMENT,
    subject_master_id INT NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS college_subject_mapping (
    id                                      INT         NOT NULL AUTO_INCREMENT,
    subject_code                            VARCHAR(20) NOT NULL,
    subject_semester_id                     INT         NOT NULL,
    college_university_degree_department_id INT         NOT NULL,
    semester_id                             INT         NOT NULL DEFAULT 1,
    regulation_batch_mapping_id             INT         NOT NULL DEFAULT 1,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS college_account_subject_college_department_section_new (
    id                           INT        NOT NULL AUTO_INCREMENT,
    college_account_id           INT        NOT NULL,
    college_subject_mapping_id   INT        NOT NULL,
    college_department_section_id INT       NOT NULL,
    inactive                     TINYINT(1) NOT NULL DEFAULT 0,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS topics (
    id                  INT          NOT NULL AUTO_INCREMENT,
    name                VARCHAR(255) NOT NULL,
    subject_semester_id INT          NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS regulation_batch_mapping (
    id INT NOT NULL AUTO_INCREMENT,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS academic_years (
    id   INT          NOT NULL AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS college_academic_years (
    id                          INT NOT NULL AUTO_INCREMENT,
    regulation_batch_mapping_id INT NOT NULL,
    start_semester              INT NOT NULL,
    end_semester                INT NOT NULL,
    academic_year_id            INT NOT NULL,
    PRIMARY KEY (id)
);
