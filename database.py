import os
from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import scoped_session, sessionmaker
from flask import g
from dotenv import load_dotenv

load_dotenv()

# ── Build connection URL ──────────────────────────────────────────────────────
DATABASE_URL = "mysql+pymysql://{user}:{password}@{host}:{port}/{db}".format(
    user     = os.environ.get('DB_USER'),
    password = os.environ.get('DB_PASSWORD'),
    host     = os.environ.get('DB_HOST', 'localhost'),
    port     = os.environ.get('DB_PORT', '3306'),
    db       = os.environ.get('DB_NAME')
)

# ── Engine + reflected metadata ───────────────────────────────────────────────
engine   = create_engine(DATABASE_URL, pool_pre_ping=True)
metadata = MetaData()
metadata.reflect(bind=engine)          # reads all table definitions from DB

# ── Scoped session factory ────────────────────────────────────────────────────
Session = scoped_session(sessionmaker(bind=engine))


def get_db():
    """
    Return the SQLAlchemy session for the current request.
    Creates a new session the first time it is called per request,
    then reuses it for subsequent calls within the same request.
    """
    if 'db' not in g:
        g.db = Session()
    return g.db
