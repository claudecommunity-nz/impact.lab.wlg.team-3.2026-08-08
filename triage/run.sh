#!/usr/bin/env bash
# Start the triage prototype.
#   ./run.sh          start on :8000
#   ./run.sh --seed   wipe and reload the demo corpus first
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"

python3 - <<'PY'
import importlib, sys
missing = [m for m in ("fastapi", "uvicorn", "pydantic", "yaml", "httpx")
           if not importlib.util.find_spec(m)]
if missing:
    print("Missing packages:", ", ".join(missing))
    print("Install them with:  python3 -m pip install -r requirements.txt")
    sys.exit(1)
PY

if [[ "${1:-}" == "--seed" ]]; then
  echo "Loading the demo corpus…"
  python3 -c "from app.demo import seed_demo; print(seed_demo(reset=True)['loaded'], 'reportings loaded')"
fi

echo
echo "  EOC triage → http://localhost:${PORT}"
echo "  API docs   → http://localhost:${PORT}/docs"
echo "  Map feed   → http://localhost:${PORT}/api/v1/geojson"
echo
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --reload
