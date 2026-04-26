"""anseropolis.serve — HTTP API server (FastAPI)"""

import argparse
import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import OUTPUT_DIR

app = FastAPI(title="Anseropolis API")


MAX_INPUT_LEN = 5000

class TextInput(BaseModel):
    text: str

    def __init__(self, **data):
        super().__init__(**data)
        if len(self.text) > MAX_INPUT_LEN:
            raise ValueError(f"Input too long ({len(self.text)} > {MAX_INPUT_LEN})")
        if not self.text.strip():
            raise ValueError("Input is empty")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/check")
def api_check(body: TextInput):
    from src.run import run
    try:
        pkg = run(body.text, str(OUTPUT_DIR))
        return pkg
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/agent")
def api_agent(body: TextInput):
    from src.agent import run_agent
    try:
        result = run_agent(body.text, verbose=False)
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/packages")
def list_packages(limit: int = 20):
    files = sorted(OUTPUT_DIR.glob("*.json"), key=os.path.getmtime, reverse=True)
    out = []
    for f in files[:limit]:
        try:
            data = json.loads(f.read_text())
            out.append({
                "id": f.stem,
                "slug": data.get("slug", ""),
                "summary": data.get("summary", ""),
                "timestamp": data.get("timestamp", ""),
            })
        except Exception:
            continue
    return out


@app.get("/api/packages/{pkg_id}")
def get_package(pkg_id: str):
    # Try exact filename first, then glob
    candidates = list(OUTPUT_DIR.glob(f"{pkg_id}*.json"))
    if not candidates:
        raise HTTPException(status_code=404, detail="package not found")
    data = json.loads(candidates[0].read_text())
    return data


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    uvicorn.run("src.serve:app", host=args.host, port=args.port, reload=False)
