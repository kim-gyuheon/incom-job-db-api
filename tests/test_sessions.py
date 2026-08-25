"""세션 즉시 종료(end_session) + 만료 데이터 정리(sweep) 검증.

프런트 보안 리뷰(2026-08-26) 대응: "시작 화면으로 돌아가도 이전 세션이 재사용 가능한
채로 남는다"는 문제의 백엔드 측 대응 — 명시적 세션 종료와, 오래 지난 세션·전사문을
무기한 보관하지 않는 정리 루틴.
"""

from __future__ import annotations

from datetime import timedelta

import db as db_module
import voice_db as store


def test_end_session_makes_it_immediately_expired(temp_job_db):
    created = store.create_session()
    session = store.get_session(created["id"])
    assert store.is_expired(session) is False  # 방금 만들었으니 아직 유효

    store.end_session(created["id"])
    session = store.get_session(created["id"])
    assert store.is_expired(session) is True


def test_end_session_is_idempotent_and_safe_on_unknown_id(temp_job_db):
    created = store.create_session()
    store.end_session(created["id"])
    store.end_session(created["id"])  # 두 번째 호출도 에러 없이 통과해야 한다
    store.end_session("no-such-session-id")  # 존재하지 않아도 에러 없이 통과해야 한다


def test_sweep_deletes_only_sessions_past_the_retention_grace_period(temp_job_db):
    fresh = store.create_session()
    about_to_expire = store.create_session()
    long_expired = store.create_session()

    with db_module.get_db() as db:
        now = store.utcnow()
        # 방금 만료됐지만 유예 기간(1시간) 안 -> 아직 지우면 안 됨(SESSION_EXPIRED 응답을
        # 정상적으로 받을 수 있어야 하므로).
        db.execute(
            "UPDATE sessions SET expires_at = ? WHERE id = ?",
            (store.to_sql(now - timedelta(minutes=5)), about_to_expire["id"]),
        )
        # 유예 기간을 훨씬 넘김 -> 정리 대상.
        db.execute(
            "UPDATE sessions SET expires_at = ? WHERE id = ?",
            (store.to_sql(now - timedelta(hours=2)), long_expired["id"]),
        )

    with db_module.get_db() as db:
        swept = store._sweep_expired_sessions(db)

    assert swept == 1
    assert store.get_session(fresh["id"]) is not None
    assert store.get_session(about_to_expire["id"]) is not None
    assert store.get_session(long_expired["id"]) is None


def test_create_session_triggers_sweep_of_old_sessions(temp_job_db):
    """create_session()이 호출될 때마다 스윕이 도는지 — 별도 스케줄러가 없으므로."""
    old = store.create_session()
    with db_module.get_db() as db:
        db.execute(
            "UPDATE sessions SET expires_at = ? WHERE id = ?",
            (store.to_sql(store.utcnow() - timedelta(hours=2)), old["id"]),
        )

    store.create_session()  # 이 호출이 sweep을 트리거해야 한다

    assert store.get_session(old["id"]) is None
