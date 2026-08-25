import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).resolve().parent.parent / "job.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# job_categories는 3단계 계층(level 1 대분류 -> 2 중분류 -> 3 소분류)이고
# jobs.category_id는 항상 level 3을 가리킨다. 따라서 대분류까지 두 번 거슬러 올라간다.
# /api/jobs와 음성 추천이 같은 필드 구성을 내보내야 하므로 여기서 공유한다.
JOBS_SQL = """
    SELECT
        j.id                AS id,
        j.name              AS name,
        j.easy_name         AS easyName,
        j.one_line_desc     AS description,
        c1.id               AS categoryId,
        c1.name             AS categoryName,
        c2.name             AS subCategoryName,
        c3.name             AS detailCategoryName,
        j.requires_cert     AS requiresCert,
        j.cert_note         AS certNote,
        j.is_recommendable  AS isRecommendable
    FROM jobs j
    JOIN job_categories c3 ON c3.id = j.category_id
    JOIN job_categories c2 ON c2.id = c3.parent_id
    JOIN job_categories c1 ON c1.id = c2.parent_id
"""
