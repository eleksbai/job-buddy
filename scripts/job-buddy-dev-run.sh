#!/usr/bin/env bash
set -euo pipefail

uv run uvicorn job_buddy.main:app \
  --reload \
  --reload-dir src \
  --reload-dir tests \
  --reload-exclude 'logs/*' \
  --reload-exclude 'data/*' \
  --reload-exclude '.venv/*' \
  --host 0.0.0.0 \
  --port 8000
