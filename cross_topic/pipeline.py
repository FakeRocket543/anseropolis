"""Cross-corpus topic modeling pipeline (v2).

Key improvements over v1:
- opencc s2t normalization BEFORE tokenization (fixes 簡繁 false differences)
- BERTopic with transform() for cross-apply (proper BTM methodology)
- Per-topic BM25 differences on normalized text

Usage:
    cd anseropolis
    python -m cross_topic.pipeline
"""

import json
import os
import re
import random
from collections import Counter, defaultdict
from pathlib import Path

import jieba
import numpy as np
import opencc
import yaml

jieba.setLogLevel(20)
random.seed(42)

ROOT = Path(__file__).parent.parent
CONFIG_PATH = Path(__file__).parent / "config.yaml"

# opencc: all text → Traditional Chinese before comparison
CC = opencc.OpenCC("s2t")


def load_config():
    return yaml.safe_load(open(CONFIG_PATH))


def normalize_text(text):
    """Normalize: simplified→traditional, strip noise."""
    text = CC.convert(text)
    text = re.sub(r'[a-zA-Z0-9\s]{20,}', ' ', text)  # strip long ASCII blocks
    text = re.sub(r'https?://\S+', '', text)  # strip URLs
    text = re.sub(r'[❗❤️😘🔥💯]+', '', text)  # strip emoji
    return text


def tokenize(text):
    return [w for w in jieba.cut(text) if len(w) >= 2 and re.fullmatch(r'[\u4e00-\u9fff]+', w)]


def load_corpus(path, max_docs=100, min_len=200):
    """Load, normalize, and sample documents."""
    full = open(ROOT / path).read()
    # Split into articles
    docs = [d.strip() for d in full.split("\n\n") if len(d.strip()) > min_len]
    if len(docs) < 20:
        docs = [d.strip() for d in full.split("\n") if len(d.strip()) > min_len]
    if len(docs) < 20:
        docs = [full[i:i+800] for i in range(0, len(full)-800, 600)]
    # Filter: must have >50% CJK characters
    def is_cjk_heavy(t):
        cjk = sum(1 for c in t if '\u4e00' <= c <= '\u9fff')
        return cjk / max(len(t), 1) > 0.4
    docs = [d for d in docs if is_cjk_heavy(d)]
    if len(docs) > max_docs:
        docs = random.sample(docs, max_docs)
    # Normalize ALL to traditional Chinese
    return [normalize_text(d[:1500]) for d in docs]


def compute_bm25_diff(docs_a, docs_b, top_n=10):
    """BM25-style distinctive terms: A vs B."""
    tf_a, tf_b = Counter(), Counter()
    for d in docs_a:
        tf_a.update(tokenize(d))
    for d in docs_b:
        tf_b.update(tokenize(d))
    total_a = sum(tf_a.values()) or 1
    total_b = sum(tf_b.values()) or 1

    diff_a, diff_b = [], []
    for w in set(tf_a) | set(tf_b):
        ra, rb = tf_a[w] / total_a, tf_b[w] / total_b
        if ra > 0.001 and (rb == 0 or ra / rb > 3):
            diff_a.append((w, ra, ra / (rb + 1e-8)))
        if rb > 0.001 and (ra == 0 or rb / ra > 3):
            diff_b.append((w, rb, rb / (ra + 1e-8)))
    diff_a.sort(key=lambda x: -x[2])
    diff_b.sort(key=lambda x: -x[2])
    return diff_a[:top_n], diff_b[:top_n]


def run():
    config = load_config()
    output_dir = ROOT / config["output"]["dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    max_docs = config["modeling"]["max_docs_per_corpus"]
    n_topics = config["modeling"]["n_topics_per_corpus"]
    embed_model = config["modeling"]["embedding_model"]

    # === Stage 1: Load + normalize ===
    print("=" * 60)
    print("Stage 1: Load corpora (all normalized to 繁體)")
    print("=" * 60)

    corpus_data = {}
    for name, info in config["corpora"].items():
        path = info["path"]
        if not (ROOT / path).exists():
            continue
        docs = load_corpus(path, max_docs=max_docs)
        if len(docs) < 15:
            print(f"  {name}: skipped ({len(docs)} docs)")
            continue
        corpus_data[name] = {"docs": docs, "label": info["label"], "group": info["group"]}
        # Quick check: show first 20 chars of first doc
        sample = docs[0][:30].replace('\n', ' ')
        print(f"  {name}: {len(docs)} docs  [{sample}...]")

    # === Stage 2: Embed ===
    print(f"\n{'='*60}")
    print("Stage 2: Embedding")
    print("=" * 60)

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(embed_model)

    for name, data in corpus_data.items():
        print(f"  {name} ({len(data['docs'])} docs)...", flush=True)
        embs = model.encode(
            data["docs"], show_progress_bar=False, batch_size=16
        ).astype(np.float32)
        # Fix NaN/Inf from float16 overflow
        embs = np.nan_to_num(embs, nan=0.0, posinf=0.0, neginf=0.0)
        # Normalize
        norms = np.linalg.norm(embs, axis=1, keepdims=True)
        norms[norms == 0] = 1
        embs = embs / norms
        data["embeddings"] = embs

    # === Stage 3: BERTopic per corpus ===
    print(f"\n{'='*60}")
    print("Stage 3: BERTopic per corpus")
    print("=" * 60)

    from bertopic import BERTopic
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import CountVectorizer

    # Fix: BERTopic's _preprocess_text strips CJK on Python 3.14
    BERTopic._preprocess_text = lambda self, docs: list(docs)

    # Fix: skip UMAP (we already have good embeddings)
    class PassThrough:
        def fit(self, X, y=None): return self
        def transform(self, X): return X
        def fit_transform(self, X, y=None): return X

    def jieba_analyzer(text):
        return [w for w in jieba.cut(text) if len(w) >= 2 and re.fullmatch(r'[\u4e00-\u9fff]+', w)]

    failed = []
    for name, data in corpus_data.items():
        actual_n = min(n_topics, max(5, len(data["docs"]) // 8))
        cluster_model = KMeans(n_clusters=actual_n, random_state=42, n_init=5)
        vectorizer = CountVectorizer(analyzer=jieba_analyzer)

        topic_model = BERTopic(
            umap_model=PassThrough(),
            hdbscan_model=cluster_model,
            vectorizer_model=vectorizer,
            calculate_probabilities=False,
            verbose=False,
        )
        try:
            topics, _ = topic_model.fit_transform(data["docs"], embeddings=data["embeddings"])
        except ValueError as e:
            print(f"    ⚠️ {name} failed: {e}")
            failed.append(name)
            continue
        data["model"] = topic_model
        data["topics"] = np.array(topics)
        data["n_topics"] = actual_n

        # Print topic info
        topic_info = topic_model.get_topic_info()
        print(f"\n  {name} ({data['label']}, {actual_n} topics):")
        for _, row in topic_info.iterrows():
            if row["Topic"] == -1:
                continue
            words = topic_model.get_topic(row["Topic"])
            kw = ", ".join(w for w, _ in words[:5])
            print(f"    T{row['Topic']:02d} [{row['Count']:>3}篇] {kw}")

    # === Stage 4: Cross-apply (BTM transform) ===
    for f in failed:
        del corpus_data[f]
    print(f"\n{'='*60}")
    print("Stage 4: Cross-apply (BERTopic transform)")
    print("=" * 60)

    names = list(corpus_data.keys())
    cross_assignments = {}

    for src in names:
        src_model = corpus_data[src]["model"]
        for tgt in names:
            if src == tgt:
                continue
            tgt_docs = corpus_data[tgt]["docs"]
            tgt_embs = corpus_data[tgt]["embeddings"]
            cross_topics, _ = src_model.transform(tgt_docs, embeddings=tgt_embs)
            cross_assignments[(src, tgt)] = np.array(cross_topics)

    print(f"  {len(cross_assignments)} cross-apply pairs computed")

    # === Stage 5: Pairing strength + BM25 diff ===
    print(f"\n{'='*60}")
    print("Stage 5: Topic pairing + BM25 language differences")
    print("=" * 60)

    cn_groups = {"cn_official", "cn_media"}
    tw_groups = {"tw_blue_cn", "tw_blue", "tw_neutral", "tw_green", "anti_ccp"}

    results = []
    for src in names:
        src_group = corpus_data[src]["group"]
        for tgt in names:
            tgt_group = corpus_data[tgt]["group"]
            # Only cross-strait pairs
            if not ((src_group in cn_groups and tgt_group in tw_groups) or
                    (src_group in tw_groups and tgt_group in cn_groups)):
                continue

            cross_t = cross_assignments[(src, tgt)]
            native_t = corpus_data[tgt]["topics"]

            # For each native topic in tgt, find where it maps in src's space
            for nt in range(corpus_data[tgt]["n_topics"]):
                mask = [i for i in range(len(native_t)) if native_t[i] == nt]
                if len(mask) < 5:
                    continue
                cross_dist = Counter(int(cross_t[i]) for i in mask)
                top_ct, top_count = cross_dist.most_common(1)[0]
                strength = top_count / len(mask)
                if strength < 0.4:
                    continue

                # Get docs for BM25 comparison
                src_topic_docs = [corpus_data[src]["docs"][i]
                                  for i in range(len(corpus_data[src]["topics"]))
                                  if corpus_data[src]["topics"][i] == top_ct]
                tgt_topic_docs = [corpus_data[tgt]["docs"][i] for i in mask]

                if len(src_topic_docs) < 3 or len(tgt_topic_docs) < 3:
                    continue

                diff_src, diff_tgt = compute_bm25_diff(src_topic_docs, tgt_topic_docs)

                # Get topic keywords
                src_words = corpus_data[src]["model"].get_topic(top_ct)
                tgt_words = corpus_data[tgt]["model"].get_topic(nt)
                src_kw = [w for w, _ in (src_words or [])[:5]]
                tgt_kw = [w for w, _ in (tgt_words or [])[:5]]

                results.append({
                    "src": src, "src_label": corpus_data[src]["label"],
                    "src_topic": int(top_ct), "src_kw": src_kw,
                    "tgt": tgt, "tgt_label": corpus_data[tgt]["label"],
                    "tgt_topic": int(nt), "tgt_kw": tgt_kw,
                    "strength": round(strength, 3),
                    "n_docs": len(mask),
                    "src_distinctive": [(w, round(r, 2)) for w, _, r in diff_src[:8]],
                    "tgt_distinctive": [(w, round(r, 2)) for w, _, r in diff_tgt[:8]],
                })

    results.sort(key=lambda x: -x["strength"])

    # Print top results
    print(f"\n  Found {len(results)} cross-strait topic alignments\n")
    for r in results[:25]:
        src_kw = ", ".join(r["src_kw"][:4])
        tgt_kw = ", ".join(r["tgt_kw"][:4])
        print(f"  [{r['src_label']}] T{r['src_topic']}({src_kw})")
        print(f"  ↔ [{r['tgt_label']}] T{r['tgt_topic']}({tgt_kw})  str={r['strength']}")
        if r["src_distinctive"]:
            print(f"    {r['src_label']}獨有: {', '.join(w for w,_ in r['src_distinctive'][:6])}")
        if r["tgt_distinctive"]:
            print(f"    {r['tgt_label']}獨有: {', '.join(w for w,_ in r['tgt_distinctive'][:6])}")
        print()

    # === Save ===
    output = {
        "meta": {
            "n_corpora": len(corpus_data),
            "n_alignments": len(results),
            "normalization": "opencc s2t (all text converted to Traditional Chinese)",
            "method": "BERTopic transform() cross-apply",
        },
        "alignments": results,
        "corpus_topics": {
            name: {
                "label": d["label"],
                "group": d["group"],
                "n_docs": len(d["docs"]),
                "n_topics": d["n_topics"],
                "topics": {
                    int(t): [w for w, _ in (d["model"].get_topic(t) or [])[:8]]
                    for t in range(d["n_topics"])
                },
            }
            for name, d in corpus_data.items()
        },
    }
    json.dump(output, open(output_dir / "cross_topic_results.json", "w"),
              ensure_ascii=False, indent=2)
    print(f"\nSaved: {output_dir / 'cross_topic_results.json'}")


if __name__ == "__main__":
    run()
