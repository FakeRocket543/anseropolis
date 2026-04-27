"""anseropolis.ingest — 入料：文字 → CKIP 斷詞 → embedding"""

import importlib.util
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

from src.config import CKIP_MODEL_DIR, CKIP_BATCH_PY, EMBED_MODEL_DIR

_ckip_pipeline = None
_ckip_backend = None  # "mlx" | "transformers" | "jieba" | None
_embed_model = None

CKIP_AVAILABLE = bool(CKIP_MODEL_DIR)
EMBED_AVAILABLE = bool(EMBED_MODEL_DIR)


def _load_ckip():
    """Three-tier fallback: MLX CKIP → transformers CKIP → jieba"""
    global _ckip_pipeline, _ckip_backend
    if _ckip_backend is not None:
        return

    # Tier 1: MLX CKIP (fastest, Apple Silicon native)
    if CKIP_AVAILABLE and CKIP_BATCH_PY:
        try:
            ckip_path = Path(CKIP_BATCH_PY)
            if ckip_path.exists():
                spec = importlib.util.spec_from_file_location("ckip_batch", ckip_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _ckip_pipeline = mod.CKIPBatchProcessor(CKIP_MODEL_DIR)
                _ckip_backend = "mlx"
                return
        except Exception as e:
            print(f"⚠️  MLX CKIP failed: {e}")

    # Tier 2: ckip-transformers (pip install ckip-transformers)
    try:
        from ckip_transformers.nlp import CkipWordSegmenter, CkipPosTagger
        _ckip_pipeline = {
            "ws": CkipWordSegmenter(model="bert-base"),
            "pos": CkipPosTagger(model="bert-base"),
        }
        _ckip_backend = "transformers"
        return
    except ImportError:
        pass
    except Exception as e:
        print(f"⚠️  ckip-transformers failed: {e}")

    # Tier 3: jieba (pip install jieba)
    try:
        import jieba
        import jieba.posseg
        # Add common terms jieba misses
        # Load custom dictionary
        dict_file = Path(__file__).parent.parent / "data" / "custom_dict.txt"
        if dict_file.exists():
            for line in dict_file.read_text().splitlines():
                w = line.strip()
                if w:
                    jieba.add_word(w)
        _ckip_pipeline = jieba
        _ckip_backend = "jieba"
        return
    except ImportError:
        pass

    _ckip_backend = "none"


def _segment_mlx(text: str) -> dict:
    result = _ckip_pipeline.process(text)
    return {"ws": result.get("ws", []), "pos": result.get("pos", [])}


def _segment_transformers(text: str) -> dict:
    ws_result = _ckip_pipeline["ws"]([text])
    pos_result = _ckip_pipeline["pos"]([text])
    return {"ws": ws_result[0], "pos": pos_result[0]}


def _segment_jieba(text: str) -> dict:
    import jieba
    import jieba.posseg
    # posseg for POS tags (exact mode)
    pairs = list(jieba.posseg.cut(text))
    # cut_for_search for better keyword recall (adds sub-words)
    search_words = list(jieba.cut_for_search(text))
    return {
        "ws": [w.word for w in pairs],
        "pos": [w.flag for w in pairs],
        "ws_search": search_words,  # extra: for keyword extraction
    }


def ckip_segment(text: str) -> dict:
    """Run word segmentation + POS. Fallback: MLX → transformers → jieba → empty."""
    _load_ckip()
    if _ckip_backend == "mlx":
        return _segment_mlx(text)
    elif _ckip_backend == "transformers":
        return _segment_transformers(text)
    elif _ckip_backend == "jieba":
        return _segment_jieba(text)
    return {"ws": [], "pos": []}


def embed_text(text: str) -> np.ndarray | None:
    """Embed text. Returns None if embedding model unavailable."""
    global _embed_model
    if not EMBED_AVAILABLE:
        return None
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer(EMBED_MODEL_DIR, device="mps")
    clean = re.sub(r'https?://\S+', '[連結]', text)
    emb = _embed_model.encode([clean], batch_size=1)
    return emb[0].astype(np.float32)


def fingerprint(text: str) -> dict:
    """Scan for rumor linguistic fingerprints."""
    return {
        "網傳": bool(re.search(r'網傳', text)),
        "問號": bool(re.search(r'？[」』]?$', text)),
        "引述": bool(re.search(r'「[^」]{3,}」', text)),
        "情緒詞": bool(re.search(r'震驚|千萬|注意|小心|緊急|竟然|居然|快轉|恐怖|可怕', text)),
        "來源模糊": bool(re.search(r'有人說|聽說|據說|瘋傳', text)),
    }


def extract_keywords(ws: list, pos: list, ws_search: list = None, top_n: int = 15) -> list:
    """Extract noun/verb keywords. Uses ws_search (jieba search mode) if available."""
    keep_pos = {'Na', 'Nb', 'Nc', 'Ncd', 'Nd', 'VC', 'VD', 'VH', 'VJ',
                'n', 'nr', 'ns', 'nt', 'nz', 'v', 'vn'}  # jieba POS tags too
    seen = set()
    kws = []
    # Primary: POS-filtered from ws+pos
    for w, p in zip(ws, pos):
        if p in keep_pos and len(w) >= 2 and w not in seen:
            seen.add(w)
            kws.append(w)
    # Supplement: sub-words from search mode (jieba only)
    if ws_search:
        for w in ws_search:
            if len(w) >= 2 and w not in seen:
                seen.add(w)
                kws.append(w)
    return kws[:top_n]


def ingest(text: str, compute_embedding: bool = True) -> dict:
    """Full ingest: text → ckip + fingerprint + keywords [+ embedding].

    Works without CKIP/embedding models — just returns text + fingerprint.
    """
    t0 = time.time()
    ckip = ckip_segment(text)
    fp = fingerprint(text)
    kws = extract_keywords(ckip["ws"], ckip["pos"], ckip.get("ws_search"))

    result = {
        "text": text,
        "ws": ckip["ws"],
        "pos": ckip["pos"],
        "fingerprint": fp,
        "keywords": kws,
        "elapsed": round(time.time() - t0, 2),
    }

    # 重點實體提示器（CEUR-WS 2025 Claim Rewriting 方法）
    from src.highlight import extract_entities, entity_queries
    result["entities"] = extract_entities(ckip["ws"], ckip["pos"])
    result["entity_queries"] = entity_queries(result["entities"])

    if compute_embedding:
        emb = embed_text(text)
        if emb is not None:
            result["embedding"] = emb

    return result


# ── Self-test ──

if __name__ == "__main__":
    fixtures = json.load(open(Path(__file__).parent.parent / "tests" / "fixtures.json"))

    print(f"CKIP backend: {_ckip_backend or 'not loaded yet'}")
    print(f"Embedding available: {EMBED_AVAILABLE}\n")

    print("=== Ingest test ===\n")
    for fix in fixtures[:3]:
        print(f'[{fix["id"]}] {fix["text"][:50]}...')
        r = ingest(fix["text"], compute_embedding=False)
        print(f'  ws: {r["ws"][:8]}...')
        print(f'  fingerprint: {r["fingerprint"]}')
        print(f'  keywords: {r["keywords"]}')
        print(f'  elapsed: {r["elapsed"]}s\n')

    if EMBED_AVAILABLE:
        print("=== Ingest + embedding ===\n")
        r = ingest(fixtures[0]["text"], compute_embedding=True)
        emb = r.get("embedding")
        if emb is not None:
            print(f'  embedding: {emb.shape}, norm={np.linalg.norm(emb):.4f}')
        print(f'  elapsed: {r["elapsed"]}s')

    print("\n✓ Ingest tests passed.")
