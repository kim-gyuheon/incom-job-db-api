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


def test_sweep_does_not_choke_on_more_rows_than_sqlite_param_limit(temp_job_db):
    """회귀 테스트: SELECT로 id를 모아 IN (?,?,?...)으로 지우던 예전 구현은 정리 대상이
    SQLite 바인드 파라미터 상한(보통 999개)을 넘으면 "too many SQL variables"로 죽었고,
    그게 create_session() 안에서 터져서 세션 생성 자체가 막혔다. 서브쿼리 기반으로 고친
    뒤에는 몇 개가 쌓였든 안전해야 한다."""
    STALE_COUNT = 1200  # 옛 구현이 쓰던 SQLite 파라미터 상한(999)보다 많게
    old_cutoff = store.to_sql(store.utcnow() - timedelta(hours=2))
    # create_session()이 자기 커넥션을 따로 여니까(중첩하면 "database is locked"),
    # 세션을 다 만든 다음에 한 번에 만료 처리한다. IN (id...) 대신 전체를 만료시켜서
    # 여기서도 같은 파라미터 상한 문제를 안 만든다.
    for _ in range(STALE_COUNT):
        store.create_session()
    with db_module.get_db() as db:
        db.execute("UPDATE sessions SET expires_at = ?", (old_cutoff,))

    with db_module.get_db() as db:
        swept = store._sweep_expired_sessions(db)  # 예전 구현이면 여기서 예외가 났다

    assert swept == STALE_COUNT
    with db_module.get_db() as db:
        remaining = db.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
    assert remaining == 0
