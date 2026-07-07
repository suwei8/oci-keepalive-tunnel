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
SECURITY_SYSTEMD_SERVICE_ALLOWLIST="${SECURITY_SYSTEMD_SERVICE_ALLOWLIST:-}"
SECURITY_SYSTEMD_EXEC_ALLOWLIST="${SECURITY_SYSTEMD_EXEC_ALLOWLIST:-}"

workflow_status="success"
repo_status="unknown"
keepalive_status="unknown"
prediction_status="unknown"
notes=()
RUN_LOG_FILE=""

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

cleanup() {
  if [ -n "${RUN_LOG_FILE}" ] && [ -f "${RUN_LOG_FILE}" ]; then
    rm -f "${RUN_LOG_FILE}"
  fi
}

trap cleanup EXIT

if [ -z "${KEEPALIVE_REPO_URL}" ]; then
  workflow_status="repo_sync_failed"
  repo_status="missing_repo_url"
  add_note "KEEPALIVE_REPO_URL is empty"
  print_results
  exit 1
fi

rm -f /tmp/prediction_result.json

# git 网络配置: 防止低速连接无限挂起 (30s 内速度低于 1000B/s 则中止)
GIT_NET_OPTS="-c http.lowSpeedLimit=1000 -c http.lowSpeedTime=30 -c http.postBuffer=524288"
# 从带 token 的 URL 中提取无 token 的回退 URL (public 仓库不需要认证)
KEEPALIVE_REPO_URL_PUBLIC="$(printf '%s' "${KEEPALIVE_REPO_URL}" | sed -E 's#https://[^@]+@#https://#')"
# git 操作错误日志临时文件
GIT_ERR_FILE="$(mktemp)"
trap 'rm -f "${GIT_ERR_FILE}"' EXIT

# git_sync_retry: 带重试的 git 同步，最多尝试 2 次 (不同 URL)
# 用法: git_sync_retry <description> <command...>
git_sync_retry() {
  local desc="$1"; shift
  local attempt=0
  local urls=("${KEEPALIVE_REPO_URL}" "${KEEPALIVE_REPO_URL_PUBLIC}")
  for url in "${urls[@]}"; do
    attempt=$((attempt + 1))
    echo ">>> ${desc} (attempt ${attempt}/${#urls[@]})..." >&2
    if "$@" "${url}" 2>"${GIT_ERR_FILE}"; then
      rm -f "${GIT_ERR_FILE}"
      return 0
    fi
    local err_tail
    err_tail="$(tail -3 "${GIT_ERR_FILE}" 2>/dev/null | tr '\n' ' ' | head -c 200)"
    echo ">>> ${desc} attempt ${attempt} failed: ${err_tail}" >&2
    sleep 3
  done
  # 保留最后一次错误信息供调用方读取
  return 1
}

git_err_note() {
  local err_tail
  err_tail="$(tail -3 "${GIT_ERR_FILE}" 2>/dev/null | tr '\n' ' ' | head -c 200)"
  if [ -n "$err_tail" ]; then
    printf '%s' "$err_tail"
  else
    printf 'no error output'
  fi
}

if [ -d "${KEEPALIVE_REPO_DIR}/.git" ]; then
  # 已有仓库: 尝试 fetch + reset，失败则删除后重新 clone
  do_fetch_update() {
    local _url="$1"
    # 更新 origin remote URL 以支持 token/public URL 切换重试
    git -C "${KEEPALIVE_REPO_DIR}" remote set-url origin "${_url}" 2>&1 \
      && git ${GIT_NET_OPTS} -C "${KEEPALIVE_REPO_DIR}" fetch --depth 1 origin "${KEEPALIVE_GIT_BRANCH}" 2>&1 \
      && git -C "${KEEPALIVE_REPO_DIR}" checkout -q "${KEEPALIVE_GIT_BRANCH}" 2>&1 \
      && git -C "${KEEPALIVE_REPO_DIR}" reset --hard "origin/${KEEPALIVE_GIT_BRANCH}" 2>&1
  }

  if git_sync_retry "git fetch+reset" do_fetch_update; then
    repo_status="updated"
  else
    # fetch 失败: 尝试删除目录后重新 clone (可能 .git 损坏)
    echo ">>> fetch failed, attempting fresh clone..." >&2
    rm -rf "${KEEPALIVE_REPO_DIR}"
    do_fresh_clone() {
      local _url="$1"
      git ${GIT_NET_OPTS} clone --depth 1 --branch "${KEEPALIVE_GIT_BRANCH}" "${_url}" "${KEEPALIVE_REPO_DIR}" 2>&1
    }
    if git_sync_retry "git clone (after fetch fail)" do_fresh_clone; then
      repo_status="cloned_after_fetch_fail"
    else
      workflow_status="repo_sync_failed"
      repo_status="update_failed"
      add_note "failed to update keepalive repo: $(git_err_note)"
      rm -f "${GIT_ERR_FILE}"
      print_results
      exit 1
    fi
  fi
elif [ ! -e "${KEEPALIVE_REPO_DIR}" ]; then
  do_fresh_clone() {
    local _url="$1"
    git ${GIT_NET_OPTS} clone --depth 1 --branch "${KEEPALIVE_GIT_BRANCH}" "${_url}" "${KEEPALIVE_REPO_DIR}" 2>&1
  }
  if git_sync_retry "git clone" do_fresh_clone; then
    repo_status="cloned"
  else
    workflow_status="repo_sync_failed"
    repo_status="clone_failed"
    add_note "failed to clone keepalive repo: $(git_err_note)"
    rm -f "${GIT_ERR_FILE}"
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
rm -f "${GIT_ERR_FILE}"

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

RUN_LOG_FILE="$(mktemp)"

set +e
env \
  TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN}" \
  TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID}" \
  SECURITY_KEYWORDS="${SECURITY_KEYWORDS}" \
  SECURITY_SYSTEMD_SERVICE_ALLOWLIST="${SECURITY_SYSTEMD_SERVICE_ALLOWLIST}" \
  SECURITY_SYSTEMD_EXEC_ALLOWLIST="${SECURITY_SYSTEMD_EXEC_ALLOWLIST}" \
  timeout "${KEEPALIVE_TIMEOUT_SECONDS}" \
  python3 scripts/remote_keepalive.py --hostname "${HOST_NAME}" \
  >"${RUN_LOG_FILE}" 2>&1
KEEPALIVE_RC=$?
set -e

cat "${RUN_LOG_FILE}"

if grep -Eq '⛔ .*安全问题.*中止保活任务|发现 [0-9]+ 个安全问题，中止保活任务' "${RUN_LOG_FILE}"; then
  workflow_status="security_blocked"
  keepalive_status="security_blocked"
  add_note "security check blocked keepalive run"
elif [ "${KEEPALIVE_RC}" -eq 0 ]; then
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
    if [ "${workflow_status}" = "success" ]; then
      workflow_status="prediction_invalid"
    fi
  fi
else
  prediction_status="missing"
  add_note "prediction_result.json missing"
  if [ "${workflow_status}" = "success" ]; then
    workflow_status="prediction_missing"
  fi
fi

print_results

if [ "${workflow_status}" != "success" ]; then
  exit 1
fi
