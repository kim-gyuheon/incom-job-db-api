from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

import numpy as np

from career_config import (
    AXIS_KEYS,
    AXIS_MAX,
    AXIS_MIN,
    DbConfig,
    JOB_SOURCE,
    N_AXES,
    get_db_config,
)


@dataclass(frozen=True)
class JobCatalog:
    job_ids: tuple[str, ...]
    job_names: tuple[str, ...]
    categories: tuple[str, ...]
    vectors: np.ndarray
    excludes: tuple[frozenset, ...]
    axis_keys: tuple[str, ...] = AXIS_KEYS
    statuses: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.job_ids)

    def subset(self, indices: Sequence[int]) -> "JobCatalog":
        idx = list(indices)
        return JobCatalog(
            job_ids=tuple(self.job_ids[i] for i in idx),
            job_names=tuple(self.job_names[i] for i in idx),
            categories=tuple(self.categories[i] for i in idx),
            vectors=self.vectors[idx],
            excludes=tuple(self.excludes[i] for i in idx),
            axis_keys=self.axis_keys,
            statuses=tuple(self.statuses[i] for i in idx) if self.statuses else (),
        )

    def index_of(self, job_id: str) -> int:
        return self.job_ids.index(job_id)


class CatalogSource(Protocol):
    def load_catalog(self) -> JobCatalog: ...
    def load_barrier_master(self) -> dict[str, str]: ...
    def describe(self) -> str: ...


class DbCatalogSource:
    def __init__(self, cfg: DbConfig | None = None, connect: Callable[[], object] | None = None):
        self.cfg = cfg or get_db_config()
        self._connect = connect or (lambda: sqlite3.connect(self.cfg.locate()))

    def describe(self) -> str:
        return f"DB({self.cfg.locate()}, {self.cfg.dialect})"

    def _job_query(self) -> str:
        c = self.cfg
        axis_cols = ",\n                   ".join(AXIS_KEYS)
        return f"""
            SELECT {c.col_job_id},
                   {c.col_job_name},
                   {c.col_category},
                   {axis_cols},
                   status
              FROM {c.table_jobs}
             WHERE {c.col_recommendable} = 1
             ORDER BY {c.col_job_id}
        """

    def _barrier_query(self) -> str:
        c = self.cfg
        return f"""
            SELECT {c.col_job_id}, {c.col_barrier_id}
              FROM {c.table_job_barriers}
             WHERE {c.col_excluded} = 1
        """

    def load_catalog(self) -> JobCatalog:
        conn = self._connect()
        try:
            verify_axis_order(conn, self.cfg)

            cur = conn.cursor()
            cur.execute(self._job_query())
            rows = cur.fetchall()

            cur.execute(self._barrier_query())
            ex_map: dict[str, set] = {}
            for job_id, barrier_id in cur.fetchall():
                ex_map.setdefault(job_id, set()).add(barrier_id)
            cur.close()
        finally:
            conn.close()

        if not rows:
            raise RuntimeError(
                f"직무 조회 결과가 비어 있습니다: {self.describe()}\n"
                f"  build_db.py 를 먼저 실행했는지, 테이블명 설정이 맞는지 확인하세요."
            )

        return _rows_to_catalog(rows, ex_map)

    def load_barrier_master(self) -> dict[str, str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT {self.cfg.col_barrier_id}, label FROM {self.cfg.table_barriers} "
                f"ORDER BY {self.cfg.col_barrier_id}"
            ).fetchall()
        finally:
            conn.close()
        return dict(rows)


def verify_axis_order(conn, cfg: DbConfig) -> None:
    try:
        rows = conn.execute(
            f"SELECT axis_key FROM {cfg.table_axes} ORDER BY position"
        ).fetchall()
    except Exception:
        print(f"[주의] {cfg.table_axes} 테이블이 없어 축 순서를 대조하지 못했습니다.")
        return

    db_axes = [r[0] for r in rows]
    if db_axes != list(AXIS_KEYS):
        raise ValueError(
            "축 순서 불일치 — 계산은 되지만 결과가 무의미해집니다.\n"
            f"  DB({cfg.locate()}) : {db_axes}\n"
            f"  career_config      : {list(AXIS_KEYS)}\n"
            "  DB 를 다시 구축하거나(build_db.py), 이 DB 에 맞는 축 정의를 쓰세요."
        )


class FileCatalogSource:
    def __init__(self, source_cfg=JOB_SOURCE, barrier_path: str | None = None):
        self.source_cfg = source_cfg
        self.barrier_path = barrier_path

    def describe(self) -> str:
        return f"File({self.source_cfg.path})"

    def load_catalog(self) -> JobCatalog:
        from job_source import load_barrier_matrix, load_job_table

        df = load_job_table(self.source_cfg).sort_values("job_id")
        _, jb = load_barrier_matrix(df, self.barrier_path)

        ex_map: dict[str, set] = {}
        for r in jb[jb["is_excluded"] == 1].itertuples(index=False):
            ex_map.setdefault(r.job_id, set()).add(r.barrier_id)

        rows = [
            (r.job_id, r.job_name, r.category, *[getattr(r, k) for k in AXIS_KEYS], r.status)
            for r in df.itertuples(index=False)
        ]
        return _rows_to_catalog(rows, ex_map)

    def load_barrier_master(self) -> dict[str, str]:
        from job_source import load_barrier_matrix, load_job_table

        df = load_job_table(self.source_cfg)
        barriers, _ = load_barrier_matrix(df, self.barrier_path)
        return dict(zip(barriers["barrier_id"], barriers["label"]))


def _rows_to_catalog(rows, ex_map: dict[str, set]) -> JobCatalog:
    job_ids, job_names, categories, statuses = [], [], [], []
    vector_rows, excludes = [], []

    for row in rows:
        job_id, job_name, category = row[0], row[1], row[2]
        axis_values = row[3 : 3 + N_AXES]
        status = row[3 + N_AXES] if len(row) > 3 + N_AXES else "unknown"

        if any(v is None for v in axis_values):
            missing = [AXIS_KEYS[i] for i, v in enumerate(axis_values) if v is None]
            raise ValueError(f"[{job_id} {job_name}] 축 값 결측: {missing}")

        job_ids.append(job_id)
        job_names.append(job_name)
        categories.append(category)
        statuses.append(status if status is not None else "unknown")
        vector_rows.append([float(v) for v in axis_values])
        excludes.append(frozenset(ex_map.get(job_id, ())))

    vectors = np.array(vector_rows, dtype=float)
    _validate(job_ids, vectors)
    vectors.flags.writeable = False

    return JobCatalog(
        job_ids=tuple(job_ids),
        job_names=tuple(job_names),
        categories=tuple(categories),
        vectors=vectors,
        excludes=tuple(excludes),
        axis_keys=AXIS_KEYS,
        statuses=tuple(statuses),
    )


def _validate(job_ids: list[str], vectors: np.ndarray) -> None:
    if vectors.shape[1] != N_AXES:
        raise ValueError(f"축 개수 불일치: 기대 {N_AXES}, 조회 {vectors.shape[1]}")

    if len(job_ids) != len(set(job_ids)):
        seen, dup = set(), set()
        for j in job_ids:
            (dup if j in seen else seen).add(j)
        raise ValueError(f"job_id 중복: {sorted(dup)}")

    if not np.all(np.isfinite(vectors)):
        raise ValueError("직무 벡터에 NaN/inf 가 있습니다.")

    if vectors.min() < AXIS_MIN or vectors.max() > AXIS_MAX:
        raise ValueError(
            f"값 범위 이탈: min={vectors.min()}, max={vectors.max()} "
            f"(허용 {AXIS_MIN}~{AXIS_MAX})"
        )

    zero_rows = np.where(np.linalg.norm(vectors, axis=1) == 0)[0]
    if len(zero_rows) > 0:
        raise ValueError(f"영벡터 직무: {[job_ids[i] for i in zero_rows]}")


_CACHE: dict[str, JobCatalog] = {}


def get_job_catalog(
    source: CatalogSource | None = None,
    *,
    db_path: str | None = None,
    refresh: bool = False,
) -> JobCatalog:
    src = source or DbCatalogSource(get_db_config(db_path))
    key = src.describe()
    if refresh or key not in _CACHE:
        _CACHE[key] = src.load_catalog()
    return _CACHE[key]


def load_barrier_master(
    source: CatalogSource | None = None, *, db_path: str | None = None
) -> dict[str, str]:
    src = source or DbCatalogSource(get_db_config(db_path))
    return src.load_barrier_master()


if __name__ == "__main__":
    cat = get_job_catalog()
    print(f"로드 완료: {len(cat)}건, vectors.shape = {cat.vectors.shape}")
    print(f"축 순서: {cat.axis_keys}")

    with_ex = sum(1 for e in cat.excludes if e)
    print(f"excludes 보유 직무: {with_ex}/{len(cat)}")

    print("\n[샘플] excludes 가 있는 직무 5건")
    shown = 0
    for i, ex in enumerate(cat.excludes):
        if ex and shown < 5:
            print(f"  {cat.job_ids[i]} {cat.job_names[i]:<20} → {sorted(ex)}")
            shown += 1

    print("\n[barrier 마스터]")
    for bid, label in load_barrier_master().items():
        print(f"  {bid:<16} {label}")
