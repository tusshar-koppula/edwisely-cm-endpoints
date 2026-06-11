-- ============================================================
-- CURIOSITY ASSESSMENT — COMPLETE SCHEMA
-- ============================================================

-- -------------------------------------------------------
-- STATUS TRANSITION RULES (enforced in data layer)
-- -------------------------------------------------------
-- draft      → draft       (re-save without publishing)
-- draft      → scheduled   (set start/end time, publish later)
-- draft      → live        (send to class immediately)
-- scheduled  → draft       (cancel back, clears start/end time)
-- scheduled  → scheduled   (reschedule with new start/end time)
-- scheduled  → live        (go live now before planned time)
-- live       → ended       (faculty ends early, or auto-end at end_time)
-- ended      → (terminal — no further transitions allowed)
-- -------------------------------------------------------


CREATE TABLE curiosity_assessment (
    assmt_id         INT             NOT NULL AUTO_INCREMENT,
    created_by       INT             NOT NULL,               -- FK → college_account_new.id (faculty owner)
    topic_source     ENUM('document', 'topic') NOT NULL,    -- 'document' = PDF upload, 'topic' = subject topics from DB
    assmt_title      VARCHAR(255)    NOT NULL,
    assmt_brief      TEXT            DEFAULT NULL,
    question_count   TINYINT         NOT NULL DEFAULT 3,     -- allowed: 3 | 4 | 5 | 7 | 10
    duration_minutes SMALLINT        NOT NULL DEFAULT 15,    -- allowed: 15 | 20 | 25 | 30 | 45
    subject_code     VARCHAR(20)     DEFAULT NULL,           -- populated when topic_source = 'topic'
    document_id      INT             DEFAULT NULL,           -- FK → ca_documents.doc_id, populated when topic_source = 'document'
    rubric_relevance TINYINT         NOT NULL DEFAULT 4,     -- weight, must sum to 10 with blooms + depth
    rubric_blooms    TINYINT         NOT NULL DEFAULT 3,
    rubric_depth     TINYINT         NOT NULL DEFAULT 3,
    status           ENUM('draft', 'scheduled', 'live', 'ended') NOT NULL DEFAULT 'draft',
    start_time       DATETIME        DEFAULT NULL,
    end_time         DATETIME        DEFAULT NULL,
    is_deleted       TINYINT(1)      NOT NULL DEFAULT 0,     -- soft delete; 1 = in trash
    created_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (assmt_id),
    CONSTRAINT chk_rubric_sum CHECK (rubric_relevance + rubric_blooms + rubric_depth = 10)
);


-- Uploaded PDF documents (document-mode source)
CREATE TABLE ca_documents (
    doc_id       INT             NOT NULL AUTO_INCREMENT,
    uploaded_by  INT             NOT NULL,               -- FK → college_account_new.id
    name         VARCHAR(255)    NOT NULL,               -- original filename
    size_bytes   INT             NOT NULL,
    pages        SMALLINT        NOT NULL,
    storage_url  TEXT            NOT NULL,               -- S3 / storage path
    uploaded_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (doc_id)
);


-- Topics selected for topic-mode assessments (one row per topic)
CREATE TABLE ca_has_topics (
    ca_id       INT  NOT NULL,
    topic_id    INT  NOT NULL,
    PRIMARY KEY (ca_id, topic_id),
    CONSTRAINT fk_has_topics_assmt FOREIGN KEY (ca_id)
        REFERENCES curiosity_assessment(assmt_id) ON DELETE CASCADE
);


-- Sections added as audience recipients
CREATE TABLE ca_has_sections (
    ca_id       INT  NOT NULL,
    section_id  INT  NOT NULL,
    PRIMARY KEY (ca_id, section_id),
    CONSTRAINT fk_has_sections_assmt FOREIGN KEY (ca_id)
        REFERENCES curiosity_assessment(assmt_id) ON DELETE CASCADE
);


-- Individual students enrolled in an assessment
-- (populated from section expansion at launch time)
CREATE TABLE ca_has_students (
    ca_id                INT                                             NOT NULL,
    student_id           INT                                             NOT NULL,
    status               ENUM('not_started', 'writing', 'submitted')    NOT NULL DEFAULT 'not_started',
    submitted_at         DATETIME                                        DEFAULT NULL,   -- set when status → submitted
    time_elapsed_seconds INT                                             DEFAULT NULL,   -- seconds from start_time to submitted_at
    added_at             DATETIME                                        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ca_id, student_id),
    CONSTRAINT fk_has_students_assmt FOREIGN KEY (ca_id)
        REFERENCES curiosity_assessment(assmt_id) ON DELETE CASCADE
);


-- Student question submissions with AI rubric scores
CREATE TABLE ca_question_submissions (
    q_id             INT             NOT NULL AUTO_INCREMENT,
    ca_id            INT             NOT NULL,
    student_id       INT             NOT NULL,
    question_number  TINYINT         NOT NULL,               -- ordering: 1..question_count
    question         TEXT            NOT NULL,
    r_score          DECIMAL(5,2)    DEFAULT NULL,           -- relevance: 0–100
    b_score          DECIMAL(3,2)    DEFAULT NULL,           -- bloom's:   1–6
    d_score          DECIMAL(3,2)    DEFAULT NULL,           -- depth:     1–4
    composite_score  DECIMAL(5,2)    DEFAULT NULL,
    ai_feedback      TEXT            DEFAULT NULL,           -- AI-generated per-question narrative
    submitted_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (q_id),
    CONSTRAINT chk_r_score CHECK (r_score BETWEEN 0 AND 100),
    CONSTRAINT chk_b_score CHECK (b_score BETWEEN 1 AND 6),
    CONSTRAINT chk_d_score CHECK (d_score BETWEEN 1 AND 4),
    CONSTRAINT fk_questions_assmt FOREIGN KEY (ca_id)
        REFERENCES curiosity_assessment(assmt_id) ON DELETE CASCADE
);


-- Faculty feedback sent to individual students
CREATE TABLE ca_faculty_feedback (
    feedback_id  INT     NOT NULL AUTO_INCREMENT,
    ca_id        INT     NOT NULL,
    student_id   INT     NOT NULL,
    sent_by      INT     NOT NULL,               -- FK → college_account_new.id (faculty)
    message      TEXT    NOT NULL,
    sent_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (feedback_id),
    CONSTRAINT fk_feedback_assmt FOREIGN KEY (ca_id)
        REFERENCES curiosity_assessment(assmt_id) ON DELETE CASCADE
);


-- Share settings per assessment (one active record per assessment)
CREATE TABLE ca_share (
    ca_id            INT             NOT NULL,
    scope            ENUM('faculty', 'department', 'hod', 'college') NOT NULL DEFAULT 'faculty',
    share_url        VARCHAR(512)    NOT NULL,               -- generated token URL
    notified_emails  TEXT            DEFAULT NULL,           -- comma-separated emails that were notified
    created_by       INT             NOT NULL,               -- FK → college_account_new.id
    created_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (ca_id),
    CONSTRAINT fk_share_assmt FOREIGN KEY (ca_id)
        REFERENCES curiosity_assessment(assmt_id) ON DELETE CASCADE
);
