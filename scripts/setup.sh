#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

echo "🪿 Anseropolis setup check"
echo "   Root: $ROOT"
echo ""

# .env
if [ ! -f "$ROOT/.env" ]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    echo "✅ Created .env from .env.example — edit it with your paths."
else
    echo "✅ .env exists"
fi

# Source .env for checks
set -a; source "$ROOT/.env" 2>/dev/null || true; set +a

# llama-server
if command -v llama-server &>/dev/null; then
    echo "✅ llama-server found: $(command -v llama-server)"
else
    echo "⚠️  llama-server not found in PATH"
fi

# LLM endpoint
URL="${ANSEROPOLIS_LLM_URL:-http://localhost:8080/v1/chat/completions}"
echo "   LLM URL: $URL"

# CKIP
CKIP="${ANSEROPOLIS_CKIP_DIR:-}"
if [ -n "$CKIP" ] && [ -d "$CKIP" ]; then
    echo "✅ CKIP models: $CKIP"
elif [ -n "$CKIP" ]; then
    echo "❌ CKIP dir not found: $CKIP"
else
    echo "⏭️  CKIP not configured (optional)"
fi

# Embedding
EMBED="${ANSEROPOLIS_EMBED_DIR:-}"
if [ -n "$EMBED" ] && [ -d "$EMBED" ]; then
    echo "✅ Embedding model: $EMBED"
elif [ -n "$EMBED" ]; then
    echo "❌ Embedding dir not found: $EMBED"
else
    echo "⏭️  Embedding not configured (optional)"
fi

# Data files
if [ -f "$ROOT/data/public_index.json" ]; then
    echo "✅ public_index.json found"
else
    echo "❌ data/public_index.json missing"
fi

echo ""
echo "Done. Run: python3 -m src.run --help"
