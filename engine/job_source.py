from __future__ import annotations

import glob
import os
import re

import pandas as pd

from career_config import (
    AXES,
    AXIS_KEYS,
    AXIS_MAX,
    AXIS_MIN,
    CATEGORY_BY_GROUP,
    COL_DRAFT,
    COL_REVIEW1,
    COL_REVIEW2,
    JOB_SOURCE,
    STATUS_ENRICH,
    SEARCH_DIRS,
    VERDICT_AGREE,
    VERDICT_EXCLUDE,
    VERDICT_KEEP_EDGE,
    JobSourceConfig,
    _norm,
    locate_barrier_matrix,
)

UNKNOWN_STATUS = "unknown"


def find_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    lookup = {_norm(c): c for c in df.columns}
    for cand in candidates:
        hit = lookup.get(_norm(cand))
        if hit is not None:
            return hit
    return None


def require_column(df: pd.DataFrame, candidates: tuple[str, ...], what: str) -> str:
    hit = find_column(df, candidates)
    if hit is None:
        raise KeyError(
            f"[{what}] 컬럼을 찾지 못했습니다.\n"
            f"  찾은 이름: {list(candidates)}\n"
            f"  파일 컬럼: {list(df.columns)}\n"
            f"  컬럼명이 바뀌었다면 career_config 의 별칭에 추가하세요."
        )
    return hit


def group_of(job_id: str) -> str:
    m = re.match(r"[A-Za-z]*(\d{2})", str(job_id))
    if not m:
        raise ValueError(f"직무ID 에서 그룹 번호를 찾을 수 없습니다: {job_id!r}")
    return m.group(1)


def _read_raw(cfg: JobSourceConfig) -> pd.DataFrame:
    path = cfg.locate()

    if os.path.isdir(path):
        files = sorted(glob.glob(os.path.join(path, cfg.csv_glob)))
        if not files:
            raise FileNotFoundError(f"{path} 에서 {cfg.csv_glob} 을 찾을 수 없습니다.")
        frames = []
        for f in files:
            d = pd.read_csv(f, encoding="utf-8-sig")
            d["__source_file"] = os.path.basename(f)
            frames.append(d)
        print(f"[원본] CSV {len(files)}개에서 {sum(len(f) for f in frames)}행 로드")
        return pd.concat(frames, ignore_index=True)

    if path.lower().endswith((".xlsx", ".xls")):
        try:
            d = pd.read_excel(path, sheet_name=cfg.sheet)
        except ImportError as e:
            raise ImportError(
                f"엑셀을 읽으려면 openpyxl 이 필요합니다: {e}\n"
                f"  설치: python -m pip install openpyxl\n"
                f"  또는 엑셀을 'CSV UTF-8' 로 저장한 뒤 그 파일을 쓰세요."
            ) from e
    else:
        d = pd.read_csv(path, encoding="utf-8-sig")
    d["__source_file"] = os.path.basename(path)
    print(f"[원본] {os.path.basename(path)} 에서 {len(d)}행 로드")
    return d


def load_job_table(cfg: JobSourceConfig = JOB_SOURCE) -> pd.DataFrame:
    raw = _read_raw(cfg)

    col_id = require_column(raw, cfg.id_columns, "직무ID")
    col_name = require_column(raw, cfg.name_columns, "직업명")
    col_second = find_column(raw, cfg.second_category_columns)
    col_third = find_column(raw, cfg.third_category_columns)

    out = pd.DataFrame()
    out["source_id"] = raw[col_id].astype(str).str.strip()
    out["job_name"] = raw[col_name].astype(str).str.strip()
    out["second_category"] = raw[col_second] if col_second else None
    out["third_category"] = raw[col_third] if col_third else None
    out["source_file"] = raw["__source_file"]

    if out["source_id"].str.fullmatch(r"\d+").all():
        file_no = raw["__source_file"].str.extract(r"(\d{2})", expand=False)
        if file_no.isna().any():
            raise ValueError("ID 가 파일 내 일련번호인데 파일명에 번호가 없어 job_id 를 만들 수 없습니다.")
        out["job_id"] = "J" + file_no + out["source_id"].str.zfill(3)
    else:
        out["job_id"] = out["source_id"]

    groups = out["job_id"].map(group_of)
    unknown = sorted(set(groups) - set(CATEGORY_BY_GROUP))
    if unknown:
        raise KeyError(f"1차분류 매핑에 없는 그룹 번호: {unknown}")
    out["category"] = groups.map(CATEGORY_BY_GROUP)

    for axis in AXES:
        col = require_column(raw, axis.candidates, f"축:{axis.label_ko}")
        out[axis.key] = pd.to_numeric(raw[col], errors="coerce")

    col_status = find_column(raw, cfg.status_columns)
    col_prec = find_column(raw, cfg.precision_columns)
    out["status"] = raw[col_status] if col_status else UNKNOWN_STATUS
    out["precision_type"] = raw[col_prec] if col_prec else UNKNOWN_STATUS

    if col_status is None and STATUS_ENRICH:
        out = _enrich_status(out, cfg)

    out = out[[
        "job_id", "job_name", "category", "second_category", "third_category",
        *AXIS_KEYS,
        "status", "precision_type", "source_file", "source_id",
    ]]

    validate_job_table(out)
    return out


def _enrich_status(df: pd.DataFrame, cfg: JobSourceConfig) -> pd.DataFrame:
    files: list[str] = []
    for base in dict.fromkeys(SEARCH_DIRS):
        files = sorted(glob.glob(os.path.join(base, cfg.csv_glob)))
        if files:
            break
    if not files:
        return df

    old = pd.concat([pd.read_csv(f, encoding="utf-8-sig") for f in files], ignore_index=True)
    name_col = find_column(old, cfg.name_columns)
    s_col = find_column(old, cfg.status_columns)
    p_col = find_column(old, cfg.precision_columns)
    if not (name_col and s_col):
        return df

    key = old[name_col].astype(str).str.strip()
    df["status"] = df["job_name"].map(dict(zip(key, old[s_col]))).fillna(UNKNOWN_STATUS)
    if p_col:
        df["precision_type"] = df["job_name"].map(dict(zip(key, old[p_col]))).fillna(UNKNOWN_STATUS)

    matched = int((df["status"] != UNKNOWN_STATUS).sum())
    print(f"[status] 과거 CSV 에서 {matched}/{len(df)}건 보강 (v2 점수 기준 판정임에 주의)")
    return df


def validate_job_table(df: pd.DataFrame) -> None:
    if df.empty:
        raise ValueError("직무 데이터가 0건입니다.")

    dup_id = df.loc[df["job_id"].duplicated(), "job_id"].tolist()
    if dup_id:
        raise ValueError(f"job_id 중복: {dup_id[:10]}")

    dup_name = df.loc[df["job_name"].duplicated(), "job_name"].tolist()
    if dup_name:
        raise ValueError(f"job_name 중복 (barrier 이름 조인이 깨집니다): {dup_name[:10]}")

    axis_vals = df[list(AXIS_KEYS)]

    if axis_vals.isna().any().any():
        bad = df.loc[axis_vals.isna().any(axis=1), ["job_id", "job_name"]]
        raise ValueError(f"축 값 결측 {len(bad)}건: {bad.head(5).to_dict('records')}")

    lo, hi = float(axis_vals.to_numpy().min()), float(axis_vals.to_numpy().max())
    if lo < AXIS_MIN or hi > AXIS_MAX:
        raise ValueError(f"축 값 범위 이탈: min={lo}, max={hi} (허용 {AXIS_MIN}~{AXIS_MAX})")

    zero = df.loc[axis_vals.sum(axis=1) == 0, "job_name"].tolist()
    if zero:
        raise ValueError(f"영벡터 직무: {zero}")


def resolve_verdict(row) -> tuple[str, str]:
    v2, v1, v0 = row.get(COL_REVIEW2), row.get(COL_REVIEW1), row.get(COL_DRAFT)
    if pd.notna(v2) and v2 != VERDICT_AGREE:
        return v2, "review2"
    if pd.notna(v1):
        return v1, "review1"
    return v0, "draft"


def load_barrier_matrix(
    job_df: pd.DataFrame, path: str | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    empty = (
        pd.DataFrame(columns=["barrier_id", "label", "category"]),
        pd.DataFrame(columns=[
            "job_id", "barrier_id", "verdict", "is_excluded",
            "is_borderline", "verdict_source", "reviewer", "reviewed_at",
        ]),
    )
    found = locate_barrier_matrix(path)
    if found is None:
        print("[barrier] 매트릭스 파일을 찾지 못해 barrier 없이 진행합니다.")
        return empty

    d2 = pd.read_csv(found, encoding="utf-8-sig")

    barriers = d2[["barrier_id", "label", "category"]].drop_duplicates().reset_index(drop=True)

    resolved = d2.apply(resolve_verdict, axis=1, result_type="expand")
    d2["verdict"] = resolved[0]
    d2["verdict_source"] = resolved[1]
    d2["is_excluded"] = (d2["verdict"] == VERDICT_EXCLUDE).astype(int)
    d2["is_borderline"] = (
        (d2[COL_DRAFT] == VERDICT_KEEP_EDGE) | (d2[COL_REVIEW1] == VERDICT_KEEP_EDGE)
    ).astype(int)

    d2 = d2.rename(columns={"job_id": "source_job_id"})
    d2["mapped_job_id"] = d2["job_name"].map(dict(zip(job_df["job_name"], job_df["job_id"])))

    unmatched = sorted(d2.loc[d2["mapped_job_id"].isna(), "job_name"].unique())
    if unmatched:
        print(f"  [주의] 직무 목록에 없는 이름 {len(unmatched)}건 제외됨: {unmatched}")

    jb = d2[d2["mapped_job_id"].notna()].rename(columns={"mapped_job_id": "job_id"})
    for c in ("reviewer", "reviewed_at"):
        if c not in jb.columns:
            jb[c] = None
    jb = jb[[
        "job_id", "barrier_id", "verdict", "is_excluded",
        "is_borderline", "verdict_source", "reviewer", "reviewed_at",
    ]]

    print(f"[barrier] 마스터 {len(barriers)}종 / 판정 {len(jb)}건 "
          f"(제외 {int(jb['is_excluded'].sum())}건, 경계 {int(jb['is_borderline'].sum())}건)")
    return barriers, jb


if __name__ == "__main__":
    df = load_job_table()
    print(f"\n표준화 완료: {len(df)}건 × 축 {len(AXIS_KEYS)}개")
    print(df.head(3).to_string())
