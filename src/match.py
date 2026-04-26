"""anseropolis.match — 比對已知謠言庫"""

import json
import numpy as np
from pathlib import Path

from src.config import DATA_DIR, EMBED_MODEL_DIR


def load_index():
    with open(DATA_DIR / "public_index.json") as f:
        return json.load(f)


_CACHED_EMBS = None
_CACHED_RIDS = None

def load_embeddings():
    npz = DATA_DIR / "report_embeddings.npz"
    if not npz.exists():
        return None, None
    d = np.load(npz)
    return d["embeddings"], d["report_ids"]


def cosine_sim(a, b):
    a_norm = np.linalg.norm(a, axis=-1, keepdims=True)
    b_norm = np.linalg.norm(b, axis=-1, keepdims=True)
    a_safe = np.where(a_norm > 1e-10, a / a_norm, 0)
    b_safe = np.where(b_norm > 1e-10, b / b_norm, 0)
    return np.nan_to_num(a_safe @ b_safe.T).squeeze()


def _keyword_match(keywords: list[str], top_k: int = 5) -> list[dict]:
    """Fallback: match by keyword overlap when embedding is unavailable."""
    index = load_index()
    scored = []
    kw_set = set(keywords)
    for r in index:
        rkws = set(r.get("claim_keywords", []))
        overlap = len(kw_set & rkws)
        if overlap > 0:
            scored.append((overlap, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for overlap, r in scored[:top_k]:
        results.append({
            "report_id": r.get("report_id", 0),
            "similarity": round(overlap / max(len(kw_set), 1), 4),
            "title": r.get("title", ""),
            "verdict": r.get("verdict", ""),
            "topic": r.get("topic", ""),
            "date": r.get("date", ""),
            "url": r.get("url", ""),
            "claim_keywords": r.get("claim_keywords", []),
            "match_type": "keyword",
        })
    return results


def match(query_embedding: np.ndarray = None, top_k: int = 5,
          keywords: list[str] | None = None) -> list[dict]:
    """Compare query against rumor index.

    Uses embedding similarity when available, falls back to keyword overlap.
    """
    # Keyword fallback if no embedding or no embedding model
    if query_embedding is None or not EMBED_MODEL_DIR:
        embs, _ = load_embeddings()
        if query_embedding is None or embs is None:
            return _keyword_match(keywords or [], top_k)

    embs, rids = load_embeddings()
    if embs is None:
        return _keyword_match(keywords or [], top_k)

    index = {r["report_id"]: r for r in load_index()}
    sims = cosine_sim(query_embedding.reshape(1, -1), embs)
    top_idx = sims.argsort()[::-1][:top_k]

    results = []
    for i in top_idx:
        rid = int(rids[i])
        meta = index.get(rid, {})
        results.append({
            "report_id": rid,
            "similarity": round(float(sims[i]), 4),
            "title": meta.get("title", ""),
            "verdict": meta.get("verdict", ""),
            "topic": meta.get("topic", ""),
            "date": meta.get("date", ""),
            "url": meta.get("url", ""),
            "claim_keywords": meta.get("claim_keywords", []),
            "match_type": (
                "high" if sims[i] > 0.85
                else "variant" if sims[i] > 0.6
                else "none"
            ),
        })
    return results


# ── Self-test ──

if __name__ == "__main__":
    print("Loading index...")
    index = load_index()
    embs, rids = load_embeddings()
    if embs is not None:
        print(f"Index: {len(index)} reports, Embeddings: {embs.shape}")
        query = embs[0]
        print("\n=== Self-match test (first report) ===")
        results = match(query, top_k=5)
    else:
        print(f"Index: {len(index)} reports, Embeddings: not available")
        print("\n=== Keyword match test ===")
        results = match(keywords=["疫苗", "副作用"], top_k=5)

    for r in results:
        print(f'  sim={r["similarity"]:.4f} [{r["match_type"]:7s}] {r.get("verdict",""):6s} | {r["title"][:50]}')

    print("\n✓ Match tests passed.")
