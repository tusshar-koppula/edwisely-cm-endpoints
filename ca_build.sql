-- ============================================================
-- CURIOSITY ASSESSMENT — FULL BUILD SCRIPT (MySQL 8.0+)
--
-- Creates all CA-owned tables from scratch.
-- Safe to run on a fresh schema; aborts cleanly if tables
-- already exist (IF NOT EXISTS).
--
-- HOW TO RUN:
--   mysql -u <user> -p <database> < ca_build.sql
--
-- DEPENDENCY ORDER (FK chain):
--   1. curiosity_assessment
--   2. ca_has_topics, ca_has_sections, ca_has_students,
--      ca_question_submissions, ca_share
--   3. ca_similar_questions  (no FK to parent — standalone)
-- ============================================================


-- -------------------------------------------------------
-- 1. curiosity_assessment
--    One row per assessment.  All doc/topic columns use
--    nullable-by-design so a faculty can save a draft
--    without filling every field.
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS curiosity_assessment (
    assmt_id               INT             NOT NULL AUTO_INCREMENT,
    created_by             INT             NOT NULL,               -- FK to college_account_new.id (faculty)
    source_kind            ENUM('document','topic') NOT NULL,
    assmt_title            VARCHAR(255)    NOT NULL,
    assmt_brief            TEXT            DEFAULT NULL,
    question_count         TINYINT         NOT NULL DEFAULT 3,
    duration_minutes       SMALLINT        NOT NULL DEFAULT 15,

    -- Topic-mode fields
    subject_code           VARCHAR(20)     DEFAULT NULL,

    -- Document-mode fields
    doc_name               VARCHAR(255)    DEFAULT NULL,
    doc_s3_key             VARCHAR(512)    DEFAULT NULL,
    doc_storage_url        TEXT            DEFAULT NULL,
    vector_store_id        VARCHAR(100)    DEFAULT NULL,
    vs_status              ENUM('pending','ready','failed') DEFAULT NULL,
    doc_pages              SMALLINT        DEFAULT NULL,
    doc_size_bytes         INT             DEFAULT NULL,

    -- Rubric limits (must sum to 10)
    rubric_relevance_limit TINYINT         NOT NULL DEFAULT 4,
    rubric_blooms_limit    TINYINT         NOT NULL DEFAULT 3,
    rubric_depth_limit     TINYINT         NOT NULL DEFAULT 3,

    status                 ENUM('draft','scheduled','live','ended') NOT NULL DEFAULT 'draft',
    start_time             DATETIME        DEFAULT NULL,
    end_time               DATETIME        DEFAULT NULL,
    is_deleted             TINYINT(1)      NOT NULL DEFAULT 0,

    -- Assessment-level aggregate scores (populated when ended)
    avg_composite_score    DECIMAL(4,2)    DEFAULT NULL,
    avg_r_score            DECIMAL(4,2)    DEFAULT NULL,
    avg_b_score            DECIMAL(3,2)    DEFAULT NULL,
    avg_d_score            DECIMAL(3,2)    DEFAULT NULL,

    -- Populated at end-time: median completion and band distribution
    median_time_seconds    INT             DEFAULT NULL,
    score_distribution     JSON            DEFAULT NULL,

    created_at             DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- S3 key for the compressed embedding matrix (.npz)
    embedding_s3_key       VARCHAR(512)    DEFAULT NULL,

    -- ── Keys ──────────────────────────────────────────────
    PRIMARY KEY (assmt_id),

    -- Most common filter: faculty's own non-deleted assessments
    INDEX idx_ca_created_by_deleted  (created_by, is_deleted)

) ENGINE=InnoDB;


-- -------------------------------------------------------
-- 2. ca_has_topics
--    Topics selected for topic-mode assessments.
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS ca_has_topics (
    ca_id       INT NOT NULL,
    topic_id    INT NOT NULL,       -- FK to subject_topic_mappings.topic_id

    -- ── Keys ──────────────────────────────────────────────
    PRIMARY KEY (ca_id, topic_id),

    CONSTRAINT fk_caht_ca
        FOREIGN KEY (ca_id) REFERENCES curiosity_assessment (assmt_id)
        ON DELETE CASCADE

) ENGINE=InnoDB;


-- -------------------------------------------------------
-- 3. ca_has_sections
--    Sections assigned to an assessment (direct + expanded
--    from department/semester selections).
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS ca_has_sections (
    ca_id       INT NOT NULL,
    section_id  INT NOT NULL,       -- FK to college_department_section_new.id

    -- ── Keys ──────────────────────────────────────────────
    PRIMARY KEY (ca_id, section_id),

    CONSTRAINT fk_cahs_ca
        FOREIGN KEY (ca_id) REFERENCES curiosity_assessment (assmt_id)
        ON DELETE CASCADE

) ENGINE=InnoDB;


-- -------------------------------------------------------
-- 4. ca_has_students
--    Students enrolled in an assessment.  Stores per-student
--    aggregate scores and timing so the monitor view can be
--    served without hitting ca_question_submissions.
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS ca_has_students (
    ca_id                INT          NOT NULL,
    student_id           INT          NOT NULL,   -- FK to college_account_new.id
    status               ENUM('not_started','writing','submitted') NOT NULL DEFAULT 'not_started',
    submitted_at         DATETIME     DEFAULT NULL,
    time_elapsed_seconds INT          DEFAULT NULL,
    started_at           DATETIME     DEFAULT NULL,
    avg_composite_score  DECIMAL(4,2) DEFAULT NULL,
    avg_r_score          DECIMAL(4,2) DEFAULT NULL,
    avg_b_score          DECIMAL(3,2) DEFAULT NULL,
    avg_d_score          DECIMAL(3,2) DEFAULT NULL,
    added_at             DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    faculty_feedback     TEXT         DEFAULT NULL,
    feedback_sent_by     INT          DEFAULT NULL,
    feedback_sent_at     DATETIME     DEFAULT NULL,

    -- ── Keys ──────────────────────────────────────────────
    PRIMARY KEY (ca_id, student_id),

    CONSTRAINT fk_cahst_ca
        FOREIGN KEY (ca_id) REFERENCES curiosity_assessment (assmt_id)
        ON DELETE CASCADE

) ENGINE=InnoDB;


-- -------------------------------------------------------
-- 5. ca_question_submissions
--    One row per scored question per student.  The embedding
--    BLOB is populated asynchronously after evaluation and
--    used to build the .npz matrix when the assessment ends.
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS ca_question_submissions (
    q_id             INT          NOT NULL AUTO_INCREMENT,
    ca_id            INT          NOT NULL,
    student_id       INT          NOT NULL,   -- FK to college_account_new.id
    question_number  TINYINT      NOT NULL DEFAULT 1,
    question         TEXT         NOT NULL,
    r_score          DECIMAL(4,2) DEFAULT NULL,
    b_score          DECIMAL(3,2) DEFAULT NULL,
    d_score          DECIMAL(3,2) DEFAULT NULL,
    composite_score  DECIMAL(4,2) DEFAULT NULL,
    verdict          VARCHAR(500) DEFAULT NULL,
    ai_feedback      TEXT         DEFAULT NULL,
    question_reframe TEXT         DEFAULT NULL,
    nudge            TEXT         DEFAULT NULL,
    submitted_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    embedding        BLOB         DEFAULT NULL,  -- float32[1536] = 6144 bytes

    -- ── Keys ──────────────────────────────────────────────
    PRIMARY KEY (q_id),

    -- Most common filter: all questions for a student in an assessment
    INDEX idx_cqs_ca_student  (ca_id, student_id),

    -- Top-N questions by score (getTopQuestions)
    INDEX idx_cqs_ca_score    (ca_id, composite_score DESC),

    CONSTRAINT fk_cqs_ca
        FOREIGN KEY (ca_id) REFERENCES curiosity_assessment (assmt_id)
        ON DELETE CASCADE

) ENGINE=InnoDB;


-- -------------------------------------------------------
-- 6. ca_share
--    One share record per assessment (upserted on each
--    share action).
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS ca_share (
    ca_id           INT          NOT NULL,
    scope           ENUM('faculty','department','hod','college') NOT NULL DEFAULT 'faculty',
    share_url       VARCHAR(512) NOT NULL,
    notified_emails TEXT         DEFAULT NULL,   -- comma-separated list
    created_by      INT          NOT NULL,       -- FK to college_account_new.id
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- ── Keys ──────────────────────────────────────────────
    PRIMARY KEY (ca_id),

    CONSTRAINT fk_cas_ca
        FOREIGN KEY (ca_id) REFERENCES curiosity_assessment (assmt_id)
        ON DELETE CASCADE

) ENGINE=InnoDB;


-- -------------------------------------------------------
-- 7. ca_similar_questions
--    Memoized cosine-similarity pairs computed at result
--    time.  No FK to ca_question_submissions intentionally:
--    cascade deletes via the parent assessment are handled
--    by the application layer (submissions are cascade-
--    deleted → these rows become stale but harmless).
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS ca_similar_questions (
    id               INT          NOT NULL AUTO_INCREMENT,
    source_q_id      INT          NOT NULL,
    similar_q_id     INT          NOT NULL,
    similarity_score DECIMAL(5,4) NOT NULL,

    -- ── Keys ──────────────────────────────────────────────
    PRIMARY KEY (id),

    -- Fast memo lookup (hot read path)
    INDEX idx_similar_source_q (source_q_id),

    -- Prevent duplicate pairs from concurrent inserts
    UNIQUE KEY uq_casq_pair (source_q_id, similar_q_id)

) ENGINE=InnoDB;


-- -------------------------------------------------------
-- VERIFICATION — uncomment and run after build
-- -------------------------------------------------------
-- SHOW TABLES LIKE 'ca\_%';
-- SHOW TABLES LIKE 'curiosity%';
-- DESCRIBE curiosity_assessment;
-- DESCRIBE ca_has_students;
-- DESCRIBE ca_question_submissions;
-- SHOW INDEX FROM ca_question_submissions;
-- SHOW INDEX FROM ca_has_students;
