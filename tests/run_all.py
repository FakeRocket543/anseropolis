"""Run all fixtures and record results."""
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

fixtures = json.load(open(Path(__file__).parent / "fixtures.json"))

results = []
for fix in fixtures:
    fid = fix["id"]
    text = fix["text"]
    print(f"\n{'='*60}")
    print(f"[{fid}] {text[:50]}...")
    print(f"{'='*60}")
    t0 = time.time()
    try:
        from src.run import run
        pkg = run(text)
        elapsed = round(time.time() - t0, 1)
        n_claims = len(pkg.get("claims", []))
        n_matches = len(pkg.get("matches", []))
        top_sim = pkg["matches"][0]["similarity"] if pkg.get("matches") else 0
        top_type = pkg["matches"][0]["match_type"] if pkg.get("matches") else "none"
        verdicts = [c.get("assessment", {}).get("verdict", "?") for c in pkg.get("claims", [])]
        results.append({
            "id": fid, "status": "PASS", "elapsed": elapsed,
            "claims": n_claims, "matches": n_matches,
            "top_sim": top_sim, "top_type": top_type,
            "expected_match": fix.get("expected_match", "?"),
            "verdicts": verdicts, "error": None,
        })
        print(f"  ✅ PASS ({elapsed}s) — {n_claims} claims, top_sim={top_sim:.4f} [{top_type}]")
    except Exception as e:
        elapsed = round(time.time() - t0, 1)
        results.append({
            "id": fid, "status": "FAIL", "elapsed": elapsed,
            "claims": 0, "matches": 0, "top_sim": 0, "top_type": "none",
            "expected_match": fix.get("expected_match", "?"),
            "verdicts": [], "error": str(e),
        })
        print(f"  ❌ FAIL ({elapsed}s) — {e}")
        traceback.print_exc()

# Summary
print(f"\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")
passed = sum(1 for r in results if r["status"] == "PASS")
print(f"Passed: {passed}/{len(results)}")
for r in results:
    status = "✅" if r["status"] == "PASS" else "❌"
    print(f"  {status} {r['id']}: {r['status']} ({r['elapsed']}s) "
          f"claims={r['claims']} top_sim={r['top_sim']:.4f} [{r['top_type']}] "
          f"expected=[{r['expected_match']}] verdicts={r['verdicts']}")

# Save results JSON
out = Path(__file__).parent / "e2e_results.json"
out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
print(f"\nResults saved to {out}")
