-- ============================================================
-- CURIOSITY ASSESSMENT — PRODUCTION MIGRATION (MySQL 8.0+)
-- Migrates the existing 4-table schema to the full new schema.
--
-- HOW TO RUN:
--   mysql -u <user> -p <database> < production_migration.sql
--
-- BEFORE RUNNING:
--   1. Back up the database.
--   2. Run on staging first.
--   3. If old schema already had some new columns added manually,
--      comment out the corresponding ADD COLUMN lines to avoid errors.
-- ============================================================

-- -------------------------------------------------------
-- SECTION 1: curiosity_assessment
-- -------------------------------------------------------

-- 1a. Remove old columns (not in new schema)
--     Safe: DROP COLUMN IF EXISTS is valid MySQL 8.0+
ALTER TABLE curiosity_assessment
    DROP COLUMN IF EXISTS unit_id,
    DROP COLUMN IF EXISTS topic_id;

-- 1b. Fix topic_source ENUM: 'db' → 'topic'
ALTER TABLE curiosity_assessment
    MODIFY COLUMN topic_source ENUM('document', 'topic') NOT NULL;

-- 1c. Add new columns
--     NOTE: created_by uses DEFAULT 0 so ALTER succeeds on existing rows.
--     After migration, UPDATE existing rows with real faculty IDs, then
--     remove the default with:
--       ALTER TABLE curiosity_assessment ALTER COLUMN created_by DROP DEFAULT;
ALTER TABLE curiosity_assessment
    ADD COLUMN created_by       INT         NOT NULL DEFAULT 0  AFTER assmt_id,
    ADD COLUMN question_count   TINYINT     NOT NULL DEFAULT 3  AFTER assmt_brief,
    ADD COLUMN duration_minutes SMALLINT    NOT NULL DEFAULT 15 AFTER question_count,
    ADD COLUMN subject_code     VARCHAR(20) DEFAULT NULL        AFTER duration_minutes,
    ADD COLUMN document_id      INT         DEFAULT NULL        AFTER subject_code,
    ADD COLUMN rubric_relevance TINYINT     NOT NULL DEFAULT 4  AFTER document_id,
    ADD COLUMN rubric_blooms    TINYINT     NOT NULL DEFAULT 3  AFTER rubric_relevance,
    ADD COLUMN rubric_depth     TINYINT     NOT NULL DEFAULT 3  AFTER rubric_blooms,
    ADD COLUMN is_deleted       TINYINT(1)  NOT NULL DEFAULT 0  AFTER end_time;

-- 1d. Add rubric sum CHECK constraint
--     The defaults (4+3+3=10) already satisfy this for new rows.
--     For existing rows: they have the new columns with those defaults,
--     so this should pass. If you get an error, run:
--       SELECT * FROM curiosity_assessment WHERE rubric_relevance + rubric_blooms + rubric_depth != 10;
--     and fix those rows before re-running this statement.
ALTER TABLE curiosity_assessment
    ADD CONSTRAINT chk_rubric_sum
        CHECK (rubric_relevance + rubric_blooms + rubric_depth = 10);


-- -------------------------------------------------------
-- SECTION 2: ca_has_students
-- -------------------------------------------------------

ALTER TABLE ca_has_students
    ADD COLUMN status               ENUM('not_started','writing','submitted')
                                    NOT NULL DEFAULT 'not_started' AFTER student_id,
    ADD COLUMN submitted_at         DATETIME DEFAULT NULL                    AFTER status,
    ADD COLUMN time_elapsed_seconds INT      DEFAULT NULL                    AFTER submitted_at;


-- -------------------------------------------------------
-- SECTION 3: ca_question_submissions
-- -------------------------------------------------------

--     NOTE: If the pre-existing table already had a `question` column,
--     comment out the ADD COLUMN question line below to avoid errors.
ALTER TABLE ca_question_submissions
    ADD COLUMN question_number TINYINT NOT NULL DEFAULT 1    AFTER student_id,
    ADD COLUMN question        TEXT    NOT NULL DEFAULT ''   AFTER question_number,
    ADD COLUMN ai_feedback     TEXT    DEFAULT NULL          AFTER composite_score;

-- After migration, backfill question values where needed, then drop the default:
--   ALTER TABLE ca_question_submissions ALTER COLUMN question DROP DEFAULT;

-- Add FK to parent assessment (skip if already present)
ALTER TABLE ca_question_submissions
    ADD CONSTRAINT fk_questions_assmt
        FOREIGN KEY (ca_id) REFERENCES curiosity_assessment(assmt_id) ON DELETE CASCADE;


-- -------------------------------------------------------
-- SECTION 4: ca_has_sections — no changes needed
-- -------------------------------------------------------


-- -------------------------------------------------------
-- SECTION 5: New tables
-- -------------------------------------------------------

-- Uploaded PDF documents (document-mode source)
CREATE TABLE IF NOT EXISTS ca_documents (
    doc_id      INT          NOT NULL AUTO_INCREMENT,
    uploaded_by INT          NOT NULL,
    name        VARCHAR(255) NOT NULL,
    size_bytes  INT          NOT NULL,
    pages       SMALLINT     NOT NULL,
    storage_url TEXT         NOT NULL,
    uploaded_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (doc_id)
);

-- Topics selected for topic-mode assessments
CREATE TABLE IF NOT EXISTS ca_has_topics (
    ca_id    INT NOT NULL,
    topic_id INT NOT NULL,
    PRIMARY KEY (ca_id, topic_id),
    CONSTRAINT fk_has_topics_assmt FOREIGN KEY (ca_id)
        REFERENCES curiosity_assessment(assmt_id) ON DELETE CASCADE
);

-- Faculty feedback sent to individual students
CREATE TABLE IF NOT EXISTS ca_faculty_feedback (
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

-- Share settings (one record per assessment)
CREATE TABLE IF NOT EXISTS ca_share (
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


-- -------------------------------------------------------
-- VERIFICATION — uncomment and run after migration
-- -------------------------------------------------------
-- SHOW TABLES LIKE 'ca_%';
-- SHOW TABLES LIKE 'curiosity%';
-- DESCRIBE curiosity_assessment;
-- DESCRIBE ca_has_students;
-- DESCRIBE ca_question_submissions;
