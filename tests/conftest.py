"""api/ 모듈들을 bare import(예: `import voice`)로 그대로 쓸 수 있게 경로를 잡아준다.

job.db는 커밋된 파일을 직접 건드리면 안 되므로(로컬/CI에서 실행할 때마다 오염됨),
매 테스트마다 임시 사본으로 복사해서 db.DB_PATH를 그쪽으로 돌려놓는다.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))


@pytest.fixture()
def temp_job_db(tmp_path, monkeypatch):
    """커밋된 job.db를 임시 경로로 복사하고, db.DB_PATH가 그쪽을 보게 한다.

    실제 부팅 때(main.py의 lifespan)와 마찬가지로 ensure_voice_schema()를 먼저 돌려서
    sessions.ended_at 같은 마이그레이션 컬럼과 voice_questions 시드가 준비된 상태로
    테스트를 시작한다 — 그래야 세션 관련 테스트가 실제 운영과 같은 스키마를 본다.
    """
    import db as db_module

    src = REPO_ROOT / "job.db"
    dst = tmp_path / "job.db"
    shutil.copy(src, dst)
    monkeypatch.setattr(db_module, "DB_PATH", dst)

    import voice_db

    voice_db.ensure_voice_schema()
    return dst
