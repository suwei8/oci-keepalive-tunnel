#!/usr/bin/env bash
set -Eeuo pipefail

HOST_NAME="${HOST_NAME:-unknown}"
KEEPALIVE_REPO_URL="${KEEPALIVE_REPO_URL:-}"
KEEPALIVE_REPO_DIR="${KEEPALIVE_REPO_DIR:-/home/sw/oci-keepalive}"
KEEPALIVE_GIT_BRANCH="${KEEPALIVE_GIT_BRANCH:-main}"
KEEPALIVE_TIMEOUT_SECONDS="${KEEPALIVE_TIMEOUT_SECONDS:-1800}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"
SECURITY_KEYWORDS="${SECURITY_KEYWORDS:-}"

workflow_status="success"
repo_status="unknown"
keepalive_status="unknown"
prediction_status="unknown"
notes=()

add_note() {
  notes+=("$1")
}

print_results() {
  local joined_notes=""
  if [ "${#notes[@]}" -gt 0 ]; then
    joined_notes="$(printf '%s; ' "${notes[@]}")"
    joined_notes="${joined_notes%; }"
  fi

  echo "RESULT_WORKFLOW_STATUS=${workflow_status}"
  echo "RESULT_REPO_STATUS=${repo_status}"
  echo "RESULT_KEEPALIVE_STATUS=${keepalive_status}"
  echo "RESULT_PREDICTION_STATUS=${prediction_status}"
  echo "RESULT_NOTES=${joined_notes}"
}

if [ -z "${KEEPALIVE_REPO_URL}" ]; then
  workflow_status="repo_sync_failed"
  repo_status="missing_repo_url"
  add_note "KEEPALIVE_REPO_URL is empty"
  print_results
  exit 1
fi

rm -f /tmp/prediction_result.json

if [ -d "${KEEPALIVE_REPO_DIR}/.git" ]; then
  if git -C "${KEEPALIVE_REPO_DIR}" fetch --depth 1 origin "${KEEPALIVE_GIT_BRANCH}" >/dev/null 2>&1 \
    && git -C "${KEEPALIVE_REPO_DIR}" checkout -q "${KEEPALIVE_GIT_BRANCH}" >/dev/null 2>&1 \
    && git -C "${KEEPALIVE_REPO_DIR}" reset --hard "origin/${KEEPALIVE_GIT_BRANCH}" >/dev/null 2>&1; then
    repo_status="updated"
  else
    workflow_status="repo_sync_failed"
    repo_status="update_failed"
    add_note "failed to update keepalive repo"
    print_results
    exit 1
  fi
elif [ ! -e "${KEEPALIVE_REPO_DIR}" ]; then
  if git clone --depth 1 --branch "${KEEPALIVE_GIT_BRANCH}" "${KEEPALIVE_REPO_URL}" "${KEEPALIVE_REPO_DIR}" >/dev/null 2>&1; then
    repo_status="cloned"
  else
    workflow_status="repo_sync_failed"
    repo_status="clone_failed"
    add_note "failed to clone keepalive repo"
    print_results
    exit 1
  fi
else
  workflow_status="repo_sync_failed"
  repo_status="invalid_repo_dir"
  add_note "keepalive repo dir exists without .git"
  print_results
  exit 1
fi

if [ ! -f "${KEEPALIVE_REPO_DIR}/scripts/remote_keepalive.py" ]; then
  workflow_status="repo_sync_failed"
  repo_status="missing_script"
  add_note "scripts/remote_keepalive.py missing in repo dir"
  print_results
  exit 1
fi

if [ ! -f "${KEEPALIVE_REPO_DIR}/data/fc3d_history.csv" ]; then
  workflow_status="repo_sync_failed"
  repo_status="missing_data"
  add_note "data/fc3d_history.csv missing in repo dir"
  print_results
  exit 1
fi

cd "${KEEPALIVE_REPO_DIR}"

set +e
env \
  TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN}" \
  TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID}" \
  SECURITY_KEYWORDS="${SECURITY_KEYWORDS}" \
  timeout "${KEEPALIVE_TIMEOUT_SECONDS}" \
  python3 scripts/remote_keepalive.py --hostname "${HOST_NAME}"
KEEPALIVE_RC=$?
set -e

if [ "${KEEPALIVE_RC}" -eq 0 ]; then
  keepalive_status="success"
else
  workflow_status="keepalive_failed"
  keepalive_status="failed"
  if [ "${KEEPALIVE_RC}" -eq 124 ]; then
    add_note "keepalive timeout after ${KEEPALIVE_TIMEOUT_SECONDS}s"
  else
    add_note "remote_keepalive.py exited with ${KEEPALIVE_RC}"
  fi
fi

if [ -f /tmp/prediction_result.json ]; then
  if python3 - <<'PY' >/dev/null 2>&1
import json
from pathlib import Path

data = json.loads(Path("/tmp/prediction_result.json").read_text())
required = {"timestamp", "hostname", "issue", "d1", "d2", "d3", "model_type"}
missing = required.difference(data.keys())
if missing:
    raise SystemExit(1)
PY
  then
    prediction_status="present"
  else
    prediction_status="invalid"
    add_note "prediction_result.json is invalid"
  fi
else
  prediction_status="missing"
  add_note "prediction_result.json missing"
fi

print_results

if [ "${workflow_status}" != "success" ]; then
  exit 1
fi
