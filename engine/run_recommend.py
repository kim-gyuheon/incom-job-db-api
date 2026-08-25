from __future__ import annotations

import argparse

import numpy as np

from career_config import AXIS_KEYS, AXIS_LABELS_KO, N_AXES
from job_repository import (
    FileCatalogSource,
    JobCatalog,
    get_job_catalog,
    load_barrier_master,
)
from matching_engine import recommend

USER_SCORES: dict[str, float] = {
    "hand_skill": 4.0,
    "aesthetic": 1.0,
    "communication": 2.0,
    "documentation": 1.0,
    "operations": 1.0,
    "judgment": 2.0,
    "expertise": 3.0,
    "logic": 2.0,
    "digital": 1.0,
    "physical": 5.0,
}

USER_BARRIER_TAGS: frozenset[str] = frozenset()

TOP_K = 3


def build_user_vector(scores: dict[str, float]) -> np.ndarray:
    missing = [k for k in AXIS_KEYS if k not in scores]
    unknown = [k for k in scores if k not in AXIS_KEYS]
    if missing or unknown:
        raise ValueError(
            f"사용자 벡터 축 불일치 — 누락: {missing} / 미정의: {unknown}\n"
            f"  현재 축 정의: {list(AXIS_KEYS)}"
        )
    return np.array([float(scores[k]) for k in AXIS_KEYS], dtype=float)


def apply_hard_filter(
    catalog: JobCatalog,
    barrier_tags: frozenset,
    *,
    barrier_labels: dict[str, str] | None = None,
    verbose: bool = True,
) -> JobCatalog:
    if not barrier_tags:
        if verbose:
            print("[D-0] barrier 정보 없음 → 필터 미적용")
            print(f"      {len(catalog)}건 전체를 후보로 사용")
        return catalog

    labels = barrier_labels if barrier_labels else load_barrier_master()
    unknown = sorted(barrier_tags - labels.keys())
    if unknown:
        raise ValueError(
            f"barriers 목록에 없는 barrier_id: {unknown}\n  사용 가능: {sorted(labels)}"
        )

    keep = [i for i, ex in enumerate(catalog.excludes) if not (barrier_tags & ex)]
    filtered = catalog.subset(keep)

    if verbose:
        chosen = ", ".join(labels[b] for b in sorted(barrier_tags))
        removed = len(catalog) - len(filtered)
        print(f"[D-0] 받은 barrier: {chosen}")
        print(f"      {len(catalog)}건 → {len(filtered)}건 (제외 {removed}건)")
        if removed:
            keep_set = set(keep)
            names = [catalog.job_names[i] for i in range(len(catalog)) if i not in keep_set]
            print(f"      제외된 직무: {', '.join(names)}")

    if len(filtered) < TOP_K:
        print(f"      [경고] 후보가 {len(filtered)}건뿐입니다. 완화 정책 필요")

    return filtered


def main(argv: list[str] | None = None):
    p = argparse.ArgumentParser(description="직무 추천 실행")
    p.add_argument("-b", "--barriers", nargs="*", default=None)
    p.add_argument("--db", help="조회할 DB 경로")
    p.add_argument("--from-file", action="store_true", help="DB 대신 원본 파일에서 읽기")
    p.add_argument("-k", "--top-k", type=int, default=TOP_K)
    args = p.parse_args(argv)

    barrier_tags = frozenset(args.barriers) if args.barriers else USER_BARRIER_TAGS

    source = FileCatalogSource() if args.from_file else None
    catalog = get_job_catalog(source=source, db_path=args.db)
    labels = load_barrier_master(source=source, db_path=args.db) if barrier_tags else {}

    print(f"[로드] 직무 {len(catalog)}건, 축 {N_AXES}개\n")

    user_vector = build_user_vector(USER_SCORES)
    print("[사용자 벡터]")
    print("  " + "  ".join(
        f"{ko}:{v:.0f}" for ko, v in zip(AXIS_LABELS_KO, user_vector)
    ))
    print()

    candidates = apply_hard_filter(catalog, barrier_tags, barrier_labels=labels)
    print()

    result = recommend(
        user_vector,
        list(candidates.job_ids),
        candidates.vectors,
        top_k=args.top_k,
    )

    name_of = dict(zip(candidates.job_ids, candidates.job_names))
    cat_of = dict(zip(candidates.job_ids, candidates.categories))
    status_of = dict(zip(candidates.job_ids, candidates.statuses or [""] * len(candidates)))

    print("=" * 72)
    print(f"추천 결과 (상위 {args.top_k}개)")
    print("=" * 72)
    for item in result["top_k"]:
        jid = item["job_id"]
        print(f"{item['rank']}위  {name_of[jid]:<22} [{cat_of[jid]}]")
        print(f"     유사도 {item['similarity']:.4f}   softmax {item['probability']:.2%}"
              f"   신뢰도 {status_of.get(jid, '-')}")

    print("\n" + "-" * 72)
    print(f"{args.top_k + 1}~10위 (D-4 '다시 보기' 노출 대상)")
    print("-" * 72)
    for item in result["rankings"][args.top_k:10]:
        jid = item["job_id"]
        print(f"{item['rank']:>2}위  {name_of[jid]:<22} 유사도 {item['similarity']:.4f}")

    print("\n" + "-" * 72)
    print("유사도 분포 진단")
    print("-" * 72)
    s = result["similarity_stats"]
    print(f"  후보 수         : {s['n_candidates']}")
    print(f"  최소 / 최대     : {s['min']:.4f} / {s['max']:.4f}")
    print(f"  평균 / 표준편차 : {s['mean']:.4f} / {s['std']:.4f}")
    print(f"  1위-3위 간격    : {s['top1_top3_gap']:.4f}")


if __name__ == "__main__":
    main()
