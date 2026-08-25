from __future__ import annotations

from typing import Callable, Optional, Sequence

import numpy as np

SOFTMAX_TEMPERATURE = 1.0
TOP_K = 3


def validate_job_vectors(job_ids: Sequence, job_vectors: np.ndarray) -> np.ndarray:
    m = np.asarray(job_vectors, dtype=float)

    if m.ndim != 2:
        raise ValueError(f"직무 벡터는 2차원이어야 합니다. 현재: {m.ndim}차원")
    if m.shape[0] == 0:
        raise ValueError("후보 직무가 0건입니다. (D-0 필터가 전부 걸러냈을 수 있습니다)")
    if len(job_ids) != m.shape[0]:
        raise ValueError(
            f"job_ids 개수({len(job_ids)})와 벡터 행 수({m.shape[0]})가 다릅니다."
        )
    if not np.all(np.isfinite(m)):
        raise ValueError("직무 벡터에 NaN 또는 inf 가 있습니다.")

    zero_rows = np.where(np.linalg.norm(m, axis=1) == 0)[0]
    if len(zero_rows) > 0:
        raise ValueError(f"영벡터인 직무가 있습니다: {[job_ids[i] for i in zero_rows]}")

    return m


def validate_user_vector(user_vector: np.ndarray, n_axes: int) -> np.ndarray:
    v = np.asarray(user_vector, dtype=float)

    if v.ndim != 1:
        raise ValueError(f"사용자 벡터는 1차원이어야 합니다. 현재: {v.ndim}차원")
    if v.shape[0] != n_axes:
        raise ValueError(
            f"축 개수 불일치: 직무 벡터 {n_axes}축, 사용자 벡터 {v.shape[0]}축"
        )
    if not np.all(np.isfinite(v)):
        raise ValueError("사용자 벡터에 NaN 또는 inf 가 있습니다.")
    if np.linalg.norm(v) == 0:
        raise ValueError(
            "사용자 벡터가 영벡터입니다. 코사인 유사도를 계산할 수 없습니다."
        )
    return v


def cosine_similarity(user_vector: np.ndarray, job_vectors: np.ndarray) -> np.ndarray:
    dot_products = job_vectors @ user_vector
    user_norm = np.linalg.norm(user_vector)
    job_norms = np.linalg.norm(job_vectors, axis=1)
    return dot_products / (user_norm * job_norms)


def softmax(scores: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    if temperature <= 0:
        raise ValueError(f"temperature 는 양수여야 합니다. 입력: {temperature}")

    scaled = np.asarray(scores, dtype=float) / temperature
    exp_shifted = np.exp(scaled - np.max(scaled))
    return exp_shifted / np.sum(exp_shifted)


def recommend(
    user_vector: np.ndarray,
    job_ids: Sequence,
    job_vectors: np.ndarray,
    top_k: int = TOP_K,
    temperature: float = SOFTMAX_TEMPERATURE,
    adjust: Optional[Callable[[np.ndarray, Sequence], np.ndarray]] = None,
) -> dict:
    v = validate_job_vectors(job_ids, job_vectors)
    u = validate_user_vector(user_vector, n_axes=v.shape[1])

    similarities = cosine_similarity(u, v)
    raw_similarities = similarities.copy()

    if adjust is not None:
        similarities = np.asarray(adjust(similarities, job_ids), dtype=float)
        if similarities.shape != raw_similarities.shape:
            raise ValueError("adjust 는 입력과 같은 길이의 배열을 반환해야 합니다.")

    probabilities = softmax(similarities, temperature=temperature)
    order = np.argsort(-similarities, kind="stable")

    rankings = [
        {
            "rank": rank,
            "job_id": job_ids[idx],
            "similarity": float(similarities[idx]),
            "raw_similarity": float(raw_similarities[idx]),
            "probability": float(probabilities[idx]),
        }
        for rank, idx in enumerate(order, start=1)
    ]

    sorted_sims = similarities[order]
    stats = {
        "n_candidates": len(job_ids),
        "min": float(sorted_sims[-1]),
        "max": float(sorted_sims[0]),
        "mean": float(np.mean(sorted_sims)),
        "std": float(np.std(sorted_sims)),
        "top1_top3_gap": (
            float(sorted_sims[0] - sorted_sims[2]) if len(sorted_sims) >= 3 else None
        ),
    }

    return {"rankings": rankings, "top_k": rankings[:top_k], "similarity_stats": stats}


if __name__ == "__main__":
    rng = np.random.default_rng(42)
    demo_ids = [f"DEMO_{i:03d}" for i in range(1, 9)]
    demo_vectors = rng.uniform(0.5, 5.0, size=(8, 10))
    demo_user = rng.uniform(0.0, 5.0, size=10)

    result = recommend(demo_user, demo_ids, demo_vectors)

    print("=" * 58)
    print(f"엔진 점검 (상위 {TOP_K}개 / 더미 데이터)")
    print("=" * 58)
    for item in result["top_k"]:
        print(f"{item['rank']}위  {item['job_id']}   "
              f"유사도 {item['similarity']:.4f}   softmax {item['probability']:.1%}")

    s = result["similarity_stats"]
    print(f"\n후보 {s['n_candidates']}건  "
          f"min {s['min']:.4f} / max {s['max']:.4f} / 1위-3위 간격 {s['top1_top3_gap']:.4f}")
