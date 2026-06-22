import os
import logging
from flask import Flask, g
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)

app = Flask(__name__)
app.config['FLASK_ENV'] = os.environ.get('FLASK_ENV', 'development')

# ── Database teardown ─────────────────────────────────────────────────────────
# Runs at the end of every request to cleanly close the DB session.
from database import Session

@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop('db', None)
    if db is not None:
        if exception:
            db.rollback()
        Session.remove()


# ── Register blueprint ────────────────────────────────────────────────────────
from curiosity_assessment_endpoints import curiosity_assessment
app.register_blueprint(curiosity_assessment)

from curiosity_assessment_student_API_endpoints import curiosity_student
app.register_blueprint(curiosity_student)


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(debug=True, port=5000)
