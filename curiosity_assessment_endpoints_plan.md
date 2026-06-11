# Curiosity Assessment — Endpoints Redesign Plan

---

## ⚠ STRUCTURAL REQUIREMENTS (from `sampleCodeForEndpoints.py`) — MUST FOLLOW EXACTLY

These rules apply to **every handler function** in the new file without exception.

### 1. Imports

```python
from flask import Blueprint, jsonify, request, current_app
import os
import sendgrid                          # for exception email alerts
import curiosity_assessment_data
from auth import authorize
from database import get_db, metadata
```

### 2. Handler skeleton

```python
@curiosity_assessment.route('/path', methods=['GET'])
@authorize
def handlerName(user):
    user_id = user.get('user_id')

    # --- Extract ALL params here, outside the try block ---
    param1 = request.args.get('param1')
    param2 = request.args.get('param2')

    # --- Validate required params here, outside the try block ---
    if not param1: return jsonify({"status": 422, "message": "param1 is missing"})
    if not param2: return jsonify({"status": 422, "message": "param2 is missing"})

    # --- try block contains ONLY the data call and its return ---
    try:
        db   = get_db()
        data = curiosity_assessment_data.someFunction(user_id, db, metadata, param1, param2)
        if data:
            return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
        else:
            return jsonify({"status": 400, "message": "No Data Found!!"})

    except Exception as e:
        subject = "server:- {}, Error in /path".format(os.environ.get('FLASK_ENV'))
        content = sendgrid.Content("text/plain", "{}".format(e))
        sendgrid.sendmail(subject, content)
        current_app.logger.error('/path - EXCEPTION: {}'.format(e))
        return jsonify({"status": 500, "message": "Failure"})
```

### 3. Rules — do not deviate

| Rule | Detail |
|---|---|
| Param extraction | Always outside try block, immediately after `user_id` line |
| Validation | Always outside try block, after extraction, before try; one `if not x: return` per required param |
| try block scope | Contains ONLY `db = get_db()`, the data function call, and the `if data / else` return |
| Exception handler | MUST call `sendgrid.sendmail()` first, then `current_app.logger.error()`, then return 500 |
| Exception subject | `"server:- {}, Error in /route-path".format(os.environ.get('FLASK_ENV'))` |
| 200 vs 400 | `if data` → 200; `else` → 400 with `"No Data Found!!"` |
| List endpoints | Empty list `[]` is valid — return 200, not 400 (check `if data is not None` not `if data`) |
| `user_id` | Always `user_id = user.get('user_id')` as the first line of every handler |

---

## Metadata Source — Verified Decision

### Verdict: keep `from database import get_db, metadata` — do NOT import from `metadata.py`

After reading `metadata.py`, `database.py`, and all 1896 lines of `curiosity_assessment_data.py`, here is what the verification found.

### CA-specific tables — 100% consistent ✅

Every column accessed by the data layer on the 8 CA tables exists in `metadata.py` with the correct name and type:

| Table | Columns accessed by data.py | Present in metadata.py |
|---|---|---|
| `ca_documents` | `doc_id`, `uploaded_by`, `name`, `size_bytes`, `pages`, `storage_url`, `uploaded_at` | ✅ all present |
| `curiosity_assessment` | `assmt_id`, `created_by`, `topic_source`, `assmt_title`, `assmt_brief`, `question_count`, `duration_minutes`, `subject_code`, `document_id`, `rubric_*`, `status`, `start_time`, `end_time`, `is_deleted`, `created_at`, `updated_at` | ✅ all present |
| `ca_has_topics` | `ca_id`, `topic_id` | ✅ all present |
| `ca_has_sections` | `ca_id`, `section_id` | ✅ all present |
| `ca_has_students` | `ca_id`, `student_id`, `status`, `submitted_at`, `time_elapsed_seconds`, `added_at` | ✅ all present |
| `ca_question_submissions` | `q_id`, `ca_id`, `student_id`, `question_number`, `question`, `r_score`, `b_score`, `d_score`, `composite_score`, `ai_feedback`, `submitted_at` | ✅ all present |
| `ca_faculty_feedback` | `feedback_id`, `ca_id`, `student_id`, `sent_by`, `message`, `sent_at` | ✅ all present |
| `ca_share` | `ca_id`, `scope`, `share_url`, `notified_emails`, `created_by`, `created_at`, `updated_at` | ✅ all present |

### Why `metadata.py` cannot be the runtime metadata source

**Reason 1 — 12 institutional tables are missing entirely.** The data layer accesses these tables via `metadata.tables[...]` — they are not defined in `metadata.py` at all. Calling `metadata.tables['college_account_new']` on `metadata.py`'s object would raise `KeyError` at runtime:

- `college_account_new`
- `college_account_subject_college_department_section_new`
- `college_department_section_new`
- `college_university_degree_department_new`
- `department_new`
- `university_degree_department_new`
- `subject_semester_new`
- `subject_master`
- `college_academic_years`
- `academic_years`
- `regulation_batch_mapping`
- `student_section_mapping`

**Reason 2 — Pre-existing table definitions in `metadata.py` are incomplete.** The `college_subject_mapping` entry defines only 7 columns, but the data layer also accesses `subject_code`, `college_university_degree_department_id`, and `regulation_batch_mapping_id` — all missing from the definition. Using `metadata.py`'s object would cause `AttributeError` on those columns.

**Reason 3 — `topics` has naming errors.** `metadata.py` names two columns `created_id` and `modified_id` (DateTime) — these should be `created_at` / `modified_at`. Data.py doesn't access them, so no runtime error, but the definition is inaccurate.

### What `metadata.py` is used for

`metadata.py` is the **migration reference and schema documentation** for CA-specific tables. It defines the correct schema for `CREATE TABLE` statements. It is NOT imported at runtime.

### Correct import — unchanged

```python
from database import get_db, metadata
```

`database.py` runs `metadata.reflect(bind=engine)` which reads all tables from the live DB, including all institutional tables and the 8 CA tables (once the migration has been run). This is the only metadata object that gives the data layer access to everything it needs.

---

## HTML Coverage Verification

All views and sub-screens in `Comprehensive faculty design_Curiosity Assessment Included.html`
under **Assess › Curiosity Assessment** have been verified against the 5-route structure below.

| View / Screen | Data Needed | Route |
|---|---|---|
| Library list (CELibrary) | GET /assessments | Route 1 GET |
| Library delete row action | DELETE /assessments/\<assessment_id\> | Route 2 DELETE |
| Library duplicate row action | Client-side clone → Compose → POST /assessments/create | Route 1 POST |
| Compose · 01 Source · topic mode subjects | GET /compose-data?type=subjects | Route 4 |
| Compose · 03 Audience · "By section" tab | GET /compose-data?type=filters&filter_type=sections | Route 4 |
| Compose · 03 Audience · "By semester" tab | GET /compose-data?type=filters&filter_type=semesters | Route 4 |
| Compose · 03 Audience · "By department" tab | GET /compose-data?type=filters&filter_type=departments | Route 4 |
| Compose · 03 Audience · "Specific students" tab | GET /compose-data?type=filters&filter_type=students&q= | Route 4 |
| Compose · 01 Source · document upload | POST /documents | Route 5 |
| Compose · Save draft button | POST /assessments/create (status=draft) | Route 1 POST |
| Compose · Schedule button | POST /assessments/create (status=scheduled) | Route 1 POST |
| Compose · Launch now button | POST /assessments/create (status=live) | Route 1 POST |
| Compose · editing existing draft/scheduled | PATCH /assessments/\<assessment_id\> | Route 2 PATCH |
| Compose · Cancel / Discard new draft | DELETE /assessments/\<assessment_id\> | Route 2 DELETE |
| Monitor · KPI strip (polled ~5s) | GET /assessments/\<id\>?view=stats | Route 2 GET |
| Monitor · roster (left panel) | GET /assessments/\<id\>?view=participants&context=monitor | Route 2 GET |
| Monitor · per-student detail + transcript drawer | GET /assessments/\<id\>/students/\<student_id\> | Route 3 GET |
| Monitor · source drawer (doc or topics) | GET /assessments/\<id\>?view=source | Route 2 GET |
| Monitor · send feedback (inline composer) | POST /assessments/\<id\>/students/\<student_id\> | Route 3 POST |
| Monitor · "End early" button | PATCH /assessments/\<id\> {action: 'end'} | Route 2 PATCH |
| Ended · Overview tab (score dist + by-dimension) | GET /assessments/\<id\>?view=overview | Route 2 GET |
| Ended · Top Questions tab | GET /assessments/\<id\>?view=top_questions | Route 2 GET |
| Ended · Students tab (roster + filters) | GET /assessments/\<id\>?view=participants&context=ended | Route 2 GET |
| Ended · "See N similar" → CeSimilarQuestionsDrawer | GET /assessments/\<id\>?view=similar&question_id=\<id\> | Route 2 GET |
| Ended · CEStudentReviewDrawer (row click) | GET /assessments/\<id\>/students/\<student_id\> | Route 3 GET |
| Ended · post-hoc feedback in review drawer | POST /assessments/\<id\>/students/\<student_id\> | Route 3 POST |
| Ended · "Export grades" → CEExportModal | GET /assessments/\<id\>?view=export&format=csv\|xlsx\|pdf&columns[]=… | Route 2 GET |
| Ended · "Share" → CEShareModal | PATCH /assessments/\<id\> {action: 'share', scope: …, emails: […]} | Route 2 PATCH |
| Ended · "Duplicate & re-run" button | Client-side clone → Compose → POST /assessments/create | Route 1 POST |

**All views and drawers covered. No gaps.**

---

## Notes from HTML Analysis

- **Transcript drawer (CETranscriptDrawer)** receives `questions` as a prop already fetched from the
  detail panel — no separate API call. Same data from Route 3 GET.
- **Duplicate** (library row + ended action bar) is purely client-side: clones the item into a draft
  shape and opens Compose. Backend sees a fresh POST /assessments/create.
- **LARosterPicker** used in Compose Audience (03) has 4 tabs: section / semester / department / student.
  These are scoped by role: faculty sees section + student; hod adds semester; principal adds department.
  All map to Route 4 with `filter_type` param.
- **Source drawer** (CEReadingDrawer for document mode, CETopicsDrawer for topic mode) is a single
  Route 2 `?view=source` call — the backend checks `source_kind` on the assessment row and returns
  the appropriate payload.
- **Stats polling**: `?view=stats` is called every ~5 seconds during Monitor. It must be the FIRST
  branch in the GET handler with an immediate return. No shared pre-computation before it.

---

## Final Route Structure (5 routes)

```
Route 1   GET, POST          /assessments
Route 2   GET, PATCH, DELETE /assessments/<int:assessment_id>
Route 3   GET, POST          /assessments/<int:assessment_id>/students/<int:student_id>
Route 4   GET                /compose-data
Route 5   POST               /documents
```

---

## File: `curiosity_assessment_endpoints.py`

### Imports & Blueprint

```python
from flask import Blueprint, jsonify, request, current_app
import curiosity_assessment_data
from auth import authorize
from database import get_db, metadata

curiosity_assessment = Blueprint('curiosity_assessment', __name__)
```

---

### Route 1 — `/assessments` (GET, POST)

**Handler name:** `handleAssessments(user)`

#### GET branch — Library list
- Params (all optional): `status`, `subject_code`, `section_id` (cast int if present)
- Calls: `curiosity_assessment_data.getAssessments(user_id, db, metadata, status, subject_code, section_id)`
- Returns 200 with list (empty list is valid — return 200 not 400)

#### POST branch — Create assessment
- Parse JSON body; return 422 if body missing
- Extract fields:
  - Required: `title`, `source_kind`
  - Conditional required: `document_id` if `source_kind == 'document'`
  - Conditional required: `topic_ids` (list) if `source_kind == 'topic'`
  - Required: `recipients` (list), `question_count`, `duration_minutes`, `rubric`
  - Optional: `description`, `subject_code`, `start_time`, `end_time`
  - Optional: `status` (default `'draft'`) — client sends `'draft'` | `'scheduled'` | `'live'`
- Validate in order, return 422 on first missing required field with descriptive message
- Calls: `curiosity_assessment_data.createAssessment(user_id, db, metadata, title, description, source_kind, document_id, topic_ids, subject_code, recipients, question_count, duration_minutes, start_time, end_time, rubric, status)`
- Returns 200 with created assessment data

---

### Route 2 — `/assessments/<int:assessment_id>` (GET, PATCH, DELETE)

**Handler name:** `handleAssessment(user, assessment_id)`

#### DELETE branch — Soft delete / discard
- No body, no params
- Calls: `curiosity_assessment_data.deleteAssessment(user_id, db, metadata, assessment_id)`
- Returns 200 on success, 400 if not found

#### PATCH branch — Update / end / share
- Parse JSON body; return 422 if body missing
- Read `action = body.get('action')` — determines which sub-operation runs:

  **`action == 'end'`** — End live assessment
  - No further validation needed
  - Calls: `curiosity_assessment_data.endAssessment(user_id, db, metadata, assessment_id)`
  - Returns 200 on success

  **`action == 'share'`** — Save share settings
  - Validate `scope` present; return 422 if missing
  - Extract `emails = body.get('emails', [])` (optional list)
  - Calls: `curiosity_assessment_data.shareAssessment(user_id, db, metadata, assessment_id, scope, emails)`
  - Returns 200 with share token / link

  **No action (field absent or None)** — Partial field update
  - All fields optional (partial update pattern)
  - Extract: `title`, `description`, `source_kind`, `document_id`, `topic_ids`, `subject_code`, `recipients`, `question_count`, `duration_minutes`, `start_time`, `end_time`, `rubric`, `status`
  - Status transitions enforced in data layer: `draft → draft|scheduled|live`, `scheduled → draft|scheduled|live`
  - Calls: `curiosity_assessment_data.updateAssessment(user_id, db, metadata, assessment_id, title, description, source_kind, document_id, topic_ids, subject_code, recipients, question_count, duration_minutes, start_time, end_time, rubric, status)`
  - Returns 200 with updated assessment data

#### GET branch — All assessment reads (view param gates which query runs)
- Read `view = request.args.get('view')`
- Return 422 with `"view param is required"` if missing or unrecognised
- **Branch order is critical — stats must be first (no code above it)**

  **`view == 'stats'`** ← FIRST — polled every ~5s, must return immediately
  - No extra params
  - Calls: `curiosity_assessment_data.getAssessmentStats(user_id, db, metadata, assessment_id)`
  - Returns 200 with KPI payload

  **`view == 'participants'`** — Roster (Monitor) or student list (Ended)
  - Extract `context` (required: `'monitor'` | `'ended'`); return 422 if missing
  - Extract optional: `status`, `sort`, `score_band` (ended only)
  - Calls: `curiosity_assessment_data.getAssessmentParticipants(user_id, db, metadata, assessment_id, context, status, sort, score_band)`
  - Returns 200 with student list

  **`view == 'source'`** — Source drawer (document or topic)
  - No extra params (backend reads source_kind from assessment row)
  - Calls: `curiosity_assessment_data.getAssessmentSource(user_id, db, metadata, assessment_id)`
  - Returns 200 with document metadata or topic list

  **`view == 'overview'`** — Ended analytics
  - No extra params
  - Calls: `curiosity_assessment_data.getAssessmentOverview(user_id, db, metadata, assessment_id)`
  - Returns 200 with score distribution, by_dimension, KPIs, median time

  **`view == 'top_questions'`** — Top 6 ranked questions
  - No extra params
  - Calls: `curiosity_assessment_data.getTopQuestions(user_id, db, metadata, assessment_id)`
  - Returns 200 with ranked question list

  **`view == 'similar'`** — Similar questions cohort (CeSimilarQuestionsDrawer)
  - Extract `question_id` (required); cast int, return 422 if missing
  - Calls: `curiosity_assessment_data.getSimilarQuestions(user_id, db, metadata, assessment_id, question_id)`
  - Returns 200 with canonical question + variant rows

  **`view == 'export'`** — Grade export data
  - Extract `format` (required: `csv` | `xlsx` | `pdf`); return 422 if missing
  - Extract `columns = request.args.getlist('columns[]')` (optional list)
  - Calls: `curiosity_assessment_data.exportAssessment(user_id, db, metadata, assessment_id, fmt, columns)`
  - Returns 200 with export payload

  **default** — Unknown view
  - Return 422 with `"unrecognised view param"`

---

### Route 3 — `/assessments/<int:assessment_id>/students/<int:student_id>` (GET, POST)

**Handler name:** `handleStudent(user, assessment_id, student_id)`

#### GET branch — Student questions + feedback
- Used by: Monitor detail panel, Monitor transcript drawer (same data, different UI render),
  Ended CEStudentReviewDrawer
- No params
- Calls: `curiosity_assessment_data.getStudentQuestions(user_id, db, metadata, assessment_id, student_id)`
- Returns 200 with questions + rubric scores + AI feedback + sent faculty feedback

#### POST branch — Send faculty feedback
- Used by: Monitor inline feedback composer, Ended review drawer post-hoc feedback
- Parse JSON body; return 422 if body missing
- Validate `message` present; return 422 if missing or empty
- Calls: `curiosity_assessment_data.sendStudentFeedback(user_id, db, metadata, assessment_id, student_id, message)`
- Returns 200 on success

---

### Route 4 — `/compose-data` (GET)

**Handler name:** `getComposeData(user)`

- Extract `type = request.args.get('type')`; return 422 if missing

  **`type == 'subjects'`**
  - No extra params
  - Calls: `curiosity_assessment_data.getSubjects(user_id, db, metadata)`
  - Returns 200 with subject → unit → topic tree

  **`type == 'filters'`**
  - Extract `role` (required: `'faculty'` | `'hod'` | `'principal'`); return 422 if missing
  - Extract `filter_type` (required: `'sections'` | `'semesters'` | `'departments'` | `'students'`); return 422 if missing
  - Dispatch by `filter_type`:
    - `'sections'`    → `curiosity_assessment_data.getSections(user_id, db, metadata, role)`
    - `'semesters'`   → extract optional `department_code` → `curiosity_assessment_data.getSemesters(user_id, db, metadata, role, department_code)`
    - `'departments'` → `curiosity_assessment_data.getDepartments(user_id, db, metadata)`
    - `'students'`    → extract optional `section_id` (cast int), `q` → `curiosity_assessment_data.getStudents(user_id, db, metadata, role, section_id, q)`
    - unknown `filter_type` → return 422

  **default** — Unknown type
  - Return 422 with `"unrecognised type param"`

---

### Route 5 — `/documents` (POST)

**Handler name:** `uploadDocument(user)`

- Extract `file = request.files.get('file')`; return 422 if missing
- Calls: `curiosity_assessment_data.uploadDocument(user_id, db, metadata, file)`
- Returns 200 with `document_id` and metadata on success, 400 if upload failed

---

## Error Handling Pattern (consistent across all routes)

```python
try:
    db   = get_db()
    data = curiosity_assessment_data.<function>(user_id, db, metadata, ...)
    if data:
        return jsonify({"status": 200, "message": "Successfully fetched Data", "data": data})
    else:
        return jsonify({"status": 400, "message": "No Data Found!!"})

except Exception as e:
    subject = "server:- {}, Error in /route-path".format(os.environ.get('FLASK_ENV'))
    content = sendgrid.Content("text/plain", "{}".format(e))
    sendgrid.sendmail(subject, content)
    current_app.logger.error('/route-path - EXCEPTION: {}'.format(e))
    return jsonify({"status": 500, "message": "Failure"})
```

**Special case — list endpoints** (`GET /assessments`): an empty list `[]` is a valid result.
Use `if data is not None` instead of `if data` so an empty list returns 200 not 400.

---

## Route Registration Order in File

```
# 1. /assessments            (GET=list, POST=create)
# 2. /assessments/<id>       (GET=views, PATCH=update|end|share, DELETE=delete)
# 3. /assessments/<id>/students/<student_id>  (GET=questions, POST=feedback)
# 4. /compose-data           (GET=subjects|filters)
# 5. /documents              (POST=upload)
```

Flask's `<int:assessment_id>` converter means Flask will never match a non-integer
segment to Route 2, so there is no routing conflict between Route 1 (`/assessments`)
and Route 2 (`/assessments/<int:assessment_id>`).

---

## Data Layer Functions Called (unchanged names from current codebase)

| Function | Called by |
|---|---|
| `getAssessments` | Route 1 GET |
| `createAssessment` | Route 1 POST |
| `deleteAssessment` | Route 2 DELETE |
| `updateAssessment` | Route 2 PATCH (no action) |
| `endAssessment` | Route 2 PATCH (action=end) |
| `shareAssessment` | Route 2 PATCH (action=share) |
| `getAssessmentStats` | Route 2 GET view=stats |
| `getAssessmentParticipants` | Route 2 GET view=participants *(renamed from getAssessmentRoster + getEndedAssessmentStudents)* |
| `getAssessmentSource` | Route 2 GET view=source *(renamed from getAssessmentDocument + getAssessmentTopics)* |
| `getAssessmentOverview` | Route 2 GET view=overview |
| `getTopQuestions` | Route 2 GET view=top_questions |
| `getSimilarQuestions` | Route 2 GET view=similar |
| `exportAssessment` | Route 2 GET view=export |
| `getStudentQuestions` | Route 3 GET |
| `sendStudentFeedback` | Route 3 POST |
| `getSubjects` | Route 4 GET type=subjects |
| `getSections` | Route 4 GET type=filters filter_type=sections |
| `getSemesters` | Route 4 GET type=filters filter_type=semesters |
| `getDepartments` | Route 4 GET type=filters filter_type=departments |
| `getStudents` | Route 4 GET type=filters filter_type=students |
| `uploadDocument` | Route 5 POST |

**Note:** `getAssessmentParticipants` and `getAssessmentSource` are new unified function names
in the data layer. The endpoint file calls these; the data layer file is responsible for merging
the old split functions into these unified ones.
