#!/usr/bin/env bash
set -euo pipefail
export ENABLE_LOG=${ENABLE_LOG:-1}
uvicorn api_app:app --host 0.0.0.0 --port 8000