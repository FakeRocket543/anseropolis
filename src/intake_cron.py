"""anseropolis.intake_cron — Cron-compatible intake: read watchlist, run pipeline, save results."""

import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DATA_DIR, OUTPUT_DIR

WATCHLIST = DATA_DIR / "watchlist.json"


def log(msg: str):
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def run_watchlist(watchlist_path: str = None, output_dir: str = None):
    wl = Path(watchlist_path) if watchlist_path else WATCHLIST
    out = Path(output_dir) if output_dir else OUTPUT_DIR
    out.mkdir(exist_ok=True)

    if not wl.exists():
        log(f"ERROR: watchlist not found: {wl}")
        return

    items = json.loads(wl.read_text())
    log(f"Loaded {len(items)} watchlist items from {wl}")

    from src.run import run

    for i, item in enumerate(items):
        text = item.get("text", "")
        label = item.get("label", f"item-{i}")
        if not text:
            log(f"  SKIP [{label}]: empty text")
            continue
        log(f"  [{label}] processing...")
        try:
            pkg = run(text, str(out))
            log(f"  [{label}] done → slug={pkg.get('slug', '?')}")
        except Exception as e:
            log(f"  [{label}] FAILED: {e}")
            traceback.print_exc()

    log("Watchlist run complete.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Anseropolis cron intake")
    parser.add_argument("--watchlist", default=None, help="Path to watchlist JSON")
    parser.add_argument("--output", default=None, help="Output directory")
    args = parser.parse_args()
    run_watchlist(args.watchlist, args.output)
