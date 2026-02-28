#!/usr/bin/env bash

# -------------------------------------------------------------------
# start-ui.sh
#
# Starts the 5G 3-Slice Framework Web UI:
#   - Backend (FastAPI) on port 8000
#   - Frontend (static HTTP server) on port 5173
#
# Assumptions:
#   - This script is located inside: repo/ui/
#   - It is executed from the repository root using:
#         ./ui/start-ui.sh
#   - Backend virtual environment (.venv) already exists
#
# To stop both services, press Ctrl+C.
# -------------------------------------------------------------------

# -----------------------------
# Start Backend (API Layer)
# -----------------------------
# - Activates Python virtual environment
# - Sets required environment variables
# - Launches FastAPI via uvicorn
# - Runs in background

(
  cd backend || exit 1

  # Create venv + install requirements ONLY if missing (one-time setup)
  if [[ ! -d ".venv" ]]; then
    echo "[backend] .venv not found -> creating venv and installing requirements..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
  else
    source .venv/bin/activate
  fi

  # Run backend API server
  REPO_ROOT="$(pwd)/../.." \
  SCRIPTS_DIR="$(pwd)/../../scripts" \
  COMPOSE_FILE="compose-files/network-slicing/docker-compose.yaml" \
  ENV_FILE="build-files/open5gs.env" \
  DBCTL="./open5gs-dbctl" \
  uvicorn main:app --host 0.0.0.0 --port 8000
) &


# -----------------------------
# Start Frontend (Web UI)
# -----------------------------
# - Serves static HTML/CSS/JS files
# - Accessible via browser on port 5173
# - Runs in background

(
  cd frontend || exit 1
  python3 -m http.server 5173
) &


# -----------------------------
# Keep script running
# -----------------------------
# Wait until one of the background processes exits.
# Press Ctrl+C to terminate both services.

wait
