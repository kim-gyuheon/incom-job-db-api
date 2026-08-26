"""자격증 카탈로그(486종) 적재와 조회.

출처는 Q-net 종목 정보를 정리한 486종이고, data/cert-catalog.json으로 저장소에 들어
있다(cert_matching.py가 STT 텍스트에서 자격증 이름을 찾을 때 쓰는 것과 같은 파일 —
데이터를 두 벌로 두지 않으려고 그대로 쓴다). Render 무료 플랜은 파일시스템이 비영속이라
배포마다 job.db가 초기화되므로, 다른 기준 데이터처럼 부팅 때 다시 채운다.

자격증 <-> 직무 연결
--------------------
카탈로그의 job_codes는 KECO(한국고용직업분류) 4자리 세분류 코드다. job.db의 jobs는
그보다 잘게 나뉜 워크넷 직업명이라 코드로 직접 이어지지 않고, KECO 세분류가 대응하는
곳은 job_categories의 level 3(소분류)이다. 그래서 두 단계로 잇는다.

    certification_catalog.job_codes (KECO 4자리)
      -> data/keco-code-map.csv 로 KECO 공식 직업명
      -> job_categories(level=3) 이름 정규화 매칭
      -> 그 소분류에 속한 jobs

이름 매칭이라 전부 이어지지는 않는다(2026-08-26 기준 486종 중 248종). 연결에 실패한
자격증도 카탈로그에는 그대로 남고, 실패 사실은 certification_job_links에 행이 없는
것으로 드러난다. 카탈로그의 job_codes는 AI가 매핑한 뒤 일부만 대조 검증한 값이라
verified=0이 기본이며, 사람 검수 전에는 추천 점수에 반영하지 않는다.
"""

import csv
import io
import json
import os
import re
from typing import Dict, List, Optional

from db import get_db

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CATALOG_JSON = os.path.join(DATA_DIR, "cert-catalog.json")
KECO_MAP_CSV = os.path.join(DATA_DIR, "keco-code-map.csv")

_CATALOG_DDL = """
CREATE TABLE IF NOT EXISTS certification_catalog (
    cert_code       TEXT PRIMARY KEY,
    cert_name       TEXT NOT NULL,
    grade           TEXT NOT NULL,
    field_official  TEXT,
    field_group     TEXT,
    kind            TEXT NOT NULL,
    common_rank     INTEGER,
    job_codes       TEXT NOT NULL DEFAULT '[]',
    verified        INTEGER NOT NULL DEFAULT 0
)
"""

# 자격증이 어떤 소분류(job_categories level 3)로 이어지는지. 부팅마다 다시 만든다.
_LINKS_DDL = """
CREATE TABLE IF NOT EXISTS certification_job_links (
    cert_code   TEXT    NOT NULL,
    keco_code   TEXT    NOT NULL,
    category_id INTEGER NOT NULL REFERENCES job_categories(id),
    PRIMARY KEY (cert_code, category_id)
)
"""


def _norm(name: str) -> str:
    """KECO 공식명과 job_categories 이름의 표기 차이를 흡수한다.

    같은 분류인데 '마케팅 및 광고ㆍ홍보 관리자' / '마케팅·광고·홍보 관리자'처럼
    가운뎃점과 띄어쓰기만 다른 경우가 많아서 그 문자들을 지우고 비교한다.
    """
    return re.sub(r"[\s·․.,()\[\]/‧・ㆍ]", "", name or "")


def ensure_certification_catalog(db) -> None:
    """카탈로그와 직무 연결을 채운다. 여러 번 호출해도 안전하다(전부 지우고 다시 씀)."""
    db.execute(_CATALOG_DDL)
    db.execute(_LINKS_DDL)
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_cert_links_category "
        "ON certification_job_links(category_id)"
    )

    if not os.path.exists(CATALOG_JSON):
        # 데이터 파일이 없으면 조용히 건너뛴다 — 다른 엔드포인트까지 막지 않는다.
        return

    with io.open(CATALOG_JSON, encoding="utf-8") as f:
        catalog = json.load(f)

    db.execute("DELETE FROM certification_catalog")
    db.executemany(
        "INSERT INTO certification_catalog (cert_code, cert_name, grade, field_official, "
        "field_group, kind, common_rank, job_codes, verified) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (
                r["code"],
                r["name"],
                r["grade"],
                r.get("field_official") or None,
                r.get("field_group") or None,
                r["kind"],
                int(r["rank"]) if str(r.get("rank") or "").strip().isdigit() else None,
                r.get("job_codes") or "[]",
                # cert-catalog.json에는 verified 필드가 없다. job_codes는 AI 매핑에
                # 일부만 대조 검증된 값이라 검수 전 상태(0)로 둔다.
                int(r.get("verified") or 0),
            )
            for r in catalog
        ],
    )

    _rebuild_links(db, catalog)


def _rebuild_links(db, catalog: List[Dict]) -> None:
    """KECO 코드 -> 공식 직업명 -> job_categories(level 3) 순으로 이어 붙인다."""
    db.execute("DELETE FROM certification_job_links")
    if not os.path.exists(KECO_MAP_CSV):
        return

    with io.open(KECO_MAP_CSV, encoding="utf-8") as f:
        keco = {r["keco_code"]: r["keco_name"] for r in csv.DictReader(f)}

    categories = {}
    for row in db.execute("SELECT id, name FROM job_categories WHERE level = 3"):
        categories.setdefault(_norm(row["name"]), row["id"])

    links = set()
    for cert in catalog:
        try:
            codes = json.loads(cert.get("job_codes") or "[]")
        except ValueError:
            continue
        for code in codes:
            category_id = categories.get(_norm(keco.get(code, "")))
            if category_id is not None:
                links.add((cert["code"], code, category_id))

    if links:
        db.executemany(
            "INSERT OR IGNORE INTO certification_job_links (cert_code, keco_code, category_id) "
            "VALUES (?,?,?)",
            sorted(links),
        )


# --- 조회 -----------------------------------------------------------------


def _row_to_item(row) -> Dict:
    item = dict(row)
    try:
        item["jobCodes"] = json.loads(item.pop("job_codes") or "[]")
    except ValueError:
        item["jobCodes"] = []
    return {
        "certCode": item["cert_code"],
        "certName": item["cert_name"],
        "grade": item["grade"],
        "fieldOfficial": item["field_official"],
        "fieldGroup": item["field_group"],
        "kind": item["kind"],
        "commonRank": item["common_rank"],
        "jobCodes": item["jobCodes"],
        "verified": bool(item["verified"]),
    }


def search_certifications(
    query: Optional[str] = None,
    field_group: Optional[str] = None,
    grade: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict:
    conditions = []
    params: List = []
    if query:
        conditions.append("cert_name LIKE ?")
        params.append("%" + query + "%")
    if field_group:
        conditions.append("field_group = ?")
        params.append(field_group)
    if grade:
        conditions.append("grade = ?")
        params.append(grade)
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_db() as db:
        total = db.execute(
            "SELECT COUNT(*) AS n FROM certification_catalog" + where, params
        ).fetchone()["n"]
        rows = db.execute(
            "SELECT * FROM certification_catalog" + where
            + " ORDER BY field_group, common_rank, cert_name LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
    return {"total": total, "items": [_row_to_item(r) for r in rows]}


def get_certification(cert_code: str) -> Optional[Dict]:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM certification_catalog WHERE cert_code = ?", (cert_code,)
        ).fetchone()
        if row is None:
            return None
        item = _row_to_item(row)
        item["linkedJobs"] = [
            {
                "id": j["id"],
                "name": j["name"],
                "easyName": j["easy_name"],
                "categoryName": j["category_name"],
                "isVoiceRecommendable": bool(j["is_voice_recommendable"]),
            }
            for j in db.execute(
                """
                SELECT j.id, j.name, j.easy_name, c.name AS category_name,
                       j.is_voice_recommendable
                FROM certification_job_links l
                JOIN job_categories c ON c.id = l.category_id
                JOIN jobs j ON j.category_id = l.category_id
                WHERE l.cert_code = ?
                ORDER BY j.id
                """,
                (cert_code,),
            )
        ]
    return item


def field_groups() -> List[Dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT field_group AS code, COUNT(*) AS n FROM certification_catalog "
            "WHERE field_group IS NOT NULL GROUP BY field_group ORDER BY field_group"
        ).fetchall()
    return [{"code": r["code"], "count": r["n"]} for r in rows]


def link_stats() -> Dict:
    """연결 현황. 데이터 검수 진행도를 보기 위한 값."""
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) AS n FROM certification_catalog").fetchone()["n"]
        linked = db.execute(
            "SELECT COUNT(DISTINCT cert_code) AS n FROM certification_job_links"
        ).fetchone()["n"]
        verified = db.execute(
            "SELECT COUNT(*) AS n FROM certification_catalog WHERE verified = 1"
        ).fetchone()["n"]
    return {"total": total, "linked": linked, "verified": verified}
