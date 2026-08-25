"""KNOW 82축 엔진 이식(voice_engine.py) 검증.

job.db의 jobs.name <-> KNOW 82축 CSV 직업명 크로스워크, barrier 하드필터,
82축 코사인 유사도 채점이 기대대로 동작하는지 확인한다.
"""

from __future__ import annotations

import db as db_module
import voice_engine


def test_crosswalk_matches_all_538_jobs(temp_job_db):
    """job.db의 jobs.name과 KNOW 82축 CSV 직업명이 538개 전부 매칭돼야 한다.

    is_voice_recommendable은 자격증/시험/학위로 막힌 직군이 빠져서 538보다 적지만,
    벡터 자체는 크로스워크된 538개 전부에 저장돼 있어야 한다(추천 후보 선정과
    "벡터가 있는지"는 별개 — voice_job_axis_vectors 참고).
    """
    with db_module.get_db() as db:
        voice_engine.ensure_voice_engine_data(db)
        recommendable = db.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE is_voice_recommendable = 1"
        ).fetchone()["n"]
        vectors = db.execute("SELECT COUNT(*) AS n FROM voice_job_axis_vectors").fetchone()["n"]

    assert vectors == 538
    assert 0 < recommendable < 538


def test_credential_gated_categories_are_excluded(temp_job_db):
    """의사/판사/연구원 등 자격증·시험·학위로 막힌 직군은 추천 후보에서 빠져야 한다.

    실측으로 확인된 문제(돌봄 답변 -> 안과의사 등 전문의가 top5에 나옴)의 재발 방지.
    """
    with db_module.get_db() as db:
        voice_engine.ensure_voice_engine_data(db)
        rows = {
            r["name"]: r["is_voice_recommendable"]
            for r in db.execute("SELECT name, is_voice_recommendable FROM jobs")
        }

    for name in ("판사", "외과의사", "내과의사", "대학교수", "물리학연구원", "기업고위임원", "경찰관"):
        assert rows.get(name) == 0, f"{name}은(는) 자격 게이트가 있는 직업이라 빠져야 한다"

    # 원래 27개 파일럿에 있던 요양보호사(제일 대표적인 접근 가능 직업)는 그대로 살아있어야 한다.
    assert rows.get("요양보호사 및 간병인") == 1


def test_allowed_exceptions_survive_category_exclusion(temp_job_db):
    """법률사무원/간호조무사는 cat1/cat2 통째 제외 대상이지만 ALLOWED_EXCEPTIONS라
    살아있어야 한다 — 부팅마다 다시 도는 ensure_voice_engine_data()가 매번 이걸
    지우고 다시 계산하므로, 여기서 깨지면 DB를 직접 고쳐도 다음 배포에서 원상복구된다."""
    with db_module.get_db() as db:
        voice_engine.ensure_voice_engine_data(db)
        rows = {
            r["name"]: r["is_voice_recommendable"]
            for r in db.execute("SELECT name, is_voice_recommendable FROM jobs")
        }

    assert rows.get("법률사무원") == 1
    assert rows.get("간호조무사") == 1


def test_existing_recommendable_flag_and_jobs_endpoint_untouched(temp_job_db):
    """기존 is_recommendable(27개 파일럿)은 절대 건드리면 안 된다 — /api/jobs 회귀 방지."""
    with db_module.get_db() as db:
        before = db.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE is_recommendable = 1"
        ).fetchone()["n"]
        voice_engine.ensure_voice_engine_data(db)
        after = db.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE is_recommendable = 1"
        ).fetchone()["n"]

    assert before == 27
    assert after == before


def test_ensure_voice_engine_data_is_idempotent(temp_job_db):
    """부팅마다 다시 불려도(Render는 배포마다 job.db가 초기화됨) 안전해야 하고,
    결과(추천 후보 수)도 두 번 다 똑같아야 한다."""
    with db_module.get_db() as db:
        voice_engine.ensure_voice_engine_data(db)
        first = db.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE is_voice_recommendable = 1"
        ).fetchone()["n"]

        voice_engine.ensure_voice_engine_data(db)
        second = db.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE is_voice_recommendable = 1"
        ).fetchone()["n"]
        vectors = db.execute("SELECT COUNT(*) AS n FROM voice_job_axis_vectors").fetchone()["n"]

    assert first == second
    assert vectors == 538


def test_barrier_exclusion_removes_matching_jobs(temp_job_db):
    """night_shift barrier 태그를 걸면 그 태그로 제외 판정된 직무가 후보에서 빠져야 한다."""
    with db_module.get_db() as db:
        voice_engine.ensure_voice_engine_data(db)
        excluded_by_night_shift = {
            r["job_id"]
            for r in db.execute(
                "SELECT job_id FROM voice_job_barrier_excludes WHERE barrier_id = 'night_shift'"
            )
        }
        assert excluded_by_night_shift, "night_shift로 제외되는 직무가 하나도 없으면 barrier CSV 적재가 잘못된 것"

        positive = [
            voice_engine.TagMatch(
                tag_id="office_admin", category="experience", label="사무·문서 정리 경험", keywords=("사무",)
            )
        ]
        items, is_fallback = voice_engine.score_and_rank(
            db, positive, {"night_shift"}, set(), top_k=538
        )

    returned_ids = {item["job_id"] for item in items}
    assert not (returned_ids & excluded_by_night_shift)


def test_score_and_rank_falls_back_when_no_positive_signal(temp_job_db):
    """긍정 신호 태그가 하나도 없으면(영벡터) 코사인 유사도를 계산할 수 없어 폴백이어야 한다."""
    with db_module.get_db() as db:
        voice_engine.ensure_voice_engine_data(db)
        items, is_fallback = voice_engine.score_and_rank(db, [], set(), set(), top_k=5)

    assert is_fallback is True
    assert items == []


def test_extract_positive_and_barrier_splits_by_category():
    # 실제 앱에서는 질문(C/D/E/F)마다 sttText가 따로 들어오므로 각각 별도 문장으로 테스트한다
    # (한 문장에 긍정+어려움을 같이 넣으면 tagging.py의 부정어 근접 억제 로직이 끼어들 수 있음).
    positive, _ = voice_engine.extract_positive_and_barrier("사무실에서 서류 정리하는 일을 했어요")
    _, barrier = voice_engine.extract_positive_and_barrier("오래 서 있는 건 힘들어요")

    positive_ids = {m.tag_id for m in positive}
    barrier_ids = {m.tag_id for m in barrier}

    assert "office_admin" in positive_ids
    assert "stand_long" in barrier_ids
