#!/usr/bin/env bash

set -uo pipefail

ANTIGRAVITY_REPO="suwei8/antigravity-cli"
AGENTBRIDGE_REPO="suwei8/agent-bridge"
AGENTBRIDGE_ASSET_PRIMARY="agent-bridge"
AGENTBRIDGE_ASSET_FALLBACK="agent-bridge-linux-aarch64-ubuntu20.04"
DEFAULT_TELEGRAM_CHAT_IDS="1118793113,8415850251"
DEFAULT_CLOUD_BOOTSTRAP_TOKEN="sw63828"
DEFAULT_CLOUD_BASE_URL="https://agent-cloud.555606.xyz"

RESULT_WORKFLOW_STATUS="success"
RESULT_NOTES=""

RESULT_ENV_STATUS="unknown"
RESULT_MANUAL_ACTION_REQUIRED="no"

RESULT_ANTIGRAVITY_STATUS="skipped_no_argv"
RESULT_ANTIGRAVITY_OLD_VERSION="N/A"
RESULT_ANTIGRAVITY_NEW_VERSION="N/A"

RESULT_ANTIGRAVITY_CLI_STATUS="skipped_no_argv"
RESULT_ANTIGRAVITY_CLI_VERSION="N/A"
RESULT_ANTIGRAVITY_CLI_TARGET_VERSION="${ANTIGRAVITY_CLI_LATEST_TAG:-unknown}"

RESULT_BRIDGE_STATUS="skipped_no_install"
RESULT_BRIDGE_RELEASE_TAG="N/A"

RESULT_WINDSURF_STATUS="skipped_no_bridge"
RESULT_WINDSURF_VERSION="N/A"

RESULT_CODEX_STATUS="skipped_no_bridge"
RESULT_CODEX_VERSION="N/A"
RESULT_CODEX_TARGET_VERSION="${CODEX_LATEST_VERSION:-unknown}"

RESULT_KILOCODE_STATUS="skipped_no_bridge"
RESULT_KILOCODE_VERSION="N/A"
RESULT_KILOCODE_TARGET_VERSION="${KILOCODE_LATEST_VERSION:-unknown}"

RESULT_CLAUDE_STATUS="skipped_missing_env"
RESULT_CLAUDE_VERSION="N/A"
RESULT_CLAUDE_TARGET_VERSION="${CLAUDE_LATEST_VERSION:-unknown}"

BRIDGE_RELEASE_JSON_CACHE=""
NPM_REFRESH_DONE="no"
RESULTS_EMITTED="no"

add_note() {
  local text="$1"
  if [ -z "$RESULT_NOTES" ]; then
    RESULT_NOTES="$text"
  else
    RESULT_NOTES="${RESULT_NOTES}; ${text}"
  fi
}

sanitize_value() {
  printf '%s' "$1" | tr '\n' ' ' | tr '\r' ' '
}

emit_results() {
  RESULTS_EMITTED="yes"
  echo "RESULT_WORKFLOW_STATUS=$(sanitize_value "$RESULT_WORKFLOW_STATUS")"
  echo "RESULT_ENV_STATUS=$(sanitize_value "$RESULT_ENV_STATUS")"
  echo "RESULT_MANUAL_ACTION_REQUIRED=$(sanitize_value "$RESULT_MANUAL_ACTION_REQUIRED")"
  echo "RESULT_ANTIGRAVITY_STATUS=$(sanitize_value "$RESULT_ANTIGRAVITY_STATUS")"
  echo "RESULT_ANTIGRAVITY_OLD_VERSION=$(sanitize_value "$RESULT_ANTIGRAVITY_OLD_VERSION")"
  echo "RESULT_ANTIGRAVITY_NEW_VERSION=$(sanitize_value "$RESULT_ANTIGRAVITY_NEW_VERSION")"
  echo "RESULT_ANTIGRAVITY_CLI_STATUS=$(sanitize_value "$RESULT_ANTIGRAVITY_CLI_STATUS")"
  echo "RESULT_ANTIGRAVITY_CLI_VERSION=$(sanitize_value "$RESULT_ANTIGRAVITY_CLI_VERSION")"
  echo "RESULT_ANTIGRAVITY_CLI_TARGET_VERSION=$(sanitize_value "$RESULT_ANTIGRAVITY_CLI_TARGET_VERSION")"
  echo "RESULT_BRIDGE_STATUS=$(sanitize_value "$RESULT_BRIDGE_STATUS")"
  echo "RESULT_BRIDGE_RELEASE_TAG=$(sanitize_value "$RESULT_BRIDGE_RELEASE_TAG")"
  echo "RESULT_WINDSURF_STATUS=$(sanitize_value "$RESULT_WINDSURF_STATUS")"
  echo "RESULT_WINDSURF_VERSION=$(sanitize_value "$RESULT_WINDSURF_VERSION")"
  echo "RESULT_CODEX_STATUS=$(sanitize_value "$RESULT_CODEX_STATUS")"
  echo "RESULT_CODEX_VERSION=$(sanitize_value "$RESULT_CODEX_VERSION")"
  echo "RESULT_CODEX_TARGET_VERSION=$(sanitize_value "$RESULT_CODEX_TARGET_VERSION")"
  echo "RESULT_KILOCODE_STATUS=$(sanitize_value "$RESULT_KILOCODE_STATUS")"
  echo "RESULT_KILOCODE_VERSION=$(sanitize_value "$RESULT_KILOCODE_VERSION")"
  echo "RESULT_KILOCODE_TARGET_VERSION=$(sanitize_value "$RESULT_KILOCODE_TARGET_VERSION")"
  echo "RESULT_CLAUDE_STATUS=$(sanitize_value "$RESULT_CLAUDE_STATUS")"
  echo "RESULT_CLAUDE_VERSION=$(sanitize_value "$RESULT_CLAUDE_VERSION")"
  echo "RESULT_CLAUDE_TARGET_VERSION=$(sanitize_value "$RESULT_CLAUDE_TARGET_VERSION")"
  echo "RESULT_NOTES=$(sanitize_value "$RESULT_NOTES")"
}

finalize_results() {
  local exit_code="$1"

  if [ "${RESULTS_EMITTED:-no}" = "yes" ]; then
    return
  fi

  if [ "$exit_code" -ne 0 ] && [ "$RESULT_WORKFLOW_STATUS" = "success" ]; then
    RESULT_WORKFLOW_STATUS="remote_failed"
    add_note "remote script exited unexpectedly"
  fi

  emit_results
}

log_info() {
  printf '[INFO] %s\n' "$1" >&2
}

log_warn() {
  printf '[WARN] %s\n' "$1" >&2
}

ensure_latest_npm() {
  if [ "${NPM_REFRESH_DONE:-no}" = "yes" ]; then
    return 0
  fi

  if ! command -v npm >/dev/null 2>&1; then
    return 1
  fi

  NPM_REFRESH_DONE="yes"
  log_info "updating npm to latest"

  if npm i -g npm@latest; then
    hash -r || true
    log_info "npm version: $(npm --version 2>/dev/null || echo unknown)"
  else
    log_warn "npm install -g npm@latest failed"
    add_note "npm install -g npm@latest failed"
  fi

  return 0
}

mb_to_kb() {
  local mb="$1"
  echo $((mb * 1024))
}

is_dir_in_use() {
  local dir="$1"
  local fd_path=""
  local target=""

  for fd_path in /proc/[0-9]*/fd/*; do
    [ -e "$fd_path" ] || continue
    target="$(readlink "$fd_path" 2>/dev/null || true)"
    case "$target" in
      "$dir"|"$dir"/*)
        return 0
        ;;
    esac
  done

  return 1
}

cleanup_stale_mei_dirs() {
  local mei_dir=""

  while IFS= read -r mei_dir; do
    [ -n "$mei_dir" ] || continue
    if is_dir_in_use "$mei_dir"; then
      log_warn "skip in-use PyInstaller temp dir: $mei_dir"
      continue
    fi
    log_info "remove stale PyInstaller temp dir: $mei_dir"
    rm -rf "$mei_dir" 2>/dev/null || log_warn "failed to remove $mei_dir"
  done <<EOF
$(find /tmp -maxdepth 1 -mindepth 1 -type d -name '_MEI*' -mmin +1440 2>/dev/null | sort)
EOF
}

report_disk_usage() {
  log_info "df -h / /tmp"
  df -h / /tmp >&2 || true
}

ensure_bridge_disk_space() {
  local root_free_kb=""
  local tmp_free_kb=""
  local min_root_kb=""
  local min_tmp_kb=""
  local min_root_mb="${AGENTBRIDGE_MIN_ROOT_FREE_MB:-512}"
  local min_tmp_mb="${AGENTBRIDGE_MIN_TMP_FREE_MB:-512}"

  report_disk_usage
  cleanup_stale_mei_dirs
  report_disk_usage

  root_free_kb="$(df -Pk / 2>/dev/null | awk 'NR==2 { print $4 }')"
  tmp_free_kb="$(df -Pk /tmp 2>/dev/null | awk 'NR==2 { print $4 }')"
  min_root_kb="$(mb_to_kb "$min_root_mb")"
  min_tmp_kb="$(mb_to_kb "$min_tmp_mb")"

  if [ -z "$root_free_kb" ] || [ -z "$tmp_free_kb" ]; then
    RESULT_BRIDGE_STATUS="bridge_failed"
    RESULT_WORKFLOW_STATUS="bridge_failed"
    add_note "failed to read disk usage"
    return 1
  fi

  if [ "$root_free_kb" -lt "$min_root_kb" ] || [ "$tmp_free_kb" -lt "$min_tmp_kb" ]; then
    RESULT_BRIDGE_STATUS="bridge_failed"
    RESULT_WORKFLOW_STATUS="bridge_failed"
    add_note "disk full"
    log_warn "insufficient disk space: / requires ${min_root_mb}MB free, /tmp requires ${min_tmp_mb}MB free"
    return 1
  fi

  return 0
}

load_shell_profiles() {
  set +u
  [ -f /etc/profile ] && . /etc/profile || true
  [ -f ~/.profile ] && . ~/.profile || true
  [ -f ~/.bashrc ] && . ~/.bashrc || true
  [ -f ~/.nvm/nvm.sh ] && . ~/.nvm/nvm.sh || true
  set -u
}

wait_for_dpkg_lock() {
  local timeout_seconds="${1:-180}"
  local elapsed=0

  while sudo fuser /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock >/dev/null 2>&1; do
    if [ "$elapsed" -ge "$timeout_seconds" ]; then
      return 1
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done
  return 0
}

github_auth_headers() {
  local token="$1"
  if [ -n "$token" ]; then
    printf '%s\n' "-H" "Authorization: Bearer ${token}"
  fi
}

github_latest_release_json() {
  local repo="$1"
  local token="$2"
  local auth=()
  if [ -n "$token" ]; then
    auth=(-H "Authorization: Bearer ${token}")
  fi

  curl -fsSL \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "${auth[@]}" \
    "https://api.github.com/repos/${repo}/releases/latest"
}

json_get_tag() {
  python3 -c 'import json,sys; print(json.load(sys.stdin).get("tag_name", ""))'
}

json_find_asset_id() {
  local preferred_name="$1"
  python3 -c '
import json
import sys

preferred = sys.argv[1]
data = json.load(sys.stdin)
assets = data.get("assets", [])
for asset in assets:
    if asset.get("name") == preferred:
        print(asset.get("id", ""))
        raise SystemExit
if assets:
    print(assets[0].get("id", ""))
' "$preferred_name"
}

download_release_asset() {
  local repo="$1"
  local token="$2"
  local release_json="$3"
  local asset_name="$4"
  local destination="$5"
  local asset_id=""
  local auth=()

  asset_id="$(printf '%s\n' "$release_json" | json_find_asset_id "$asset_name")"
  if [ -z "$asset_id" ]; then
    return 1
  fi

  if [ -n "$token" ]; then
    auth=(-H "Authorization: Bearer ${token}")
  fi

  curl -fsSL \
    -H "Accept: application/octet-stream" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "${auth[@]}" \
    "https://api.github.com/repos/${repo}/releases/assets/${asset_id}" \
    -o "$destination"
}

download_repo_file() {
  local repo="$1"
  local token="$2"
  local path="$3"
  local destination="$4"
  curl -fsSL \
    -H "Authorization: Bearer ${token}" \
    -H "Accept: application/vnd.github.raw+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/repos/${repo}/contents/${path}" \
    -o "$destination"
}

version_eq() {
  [ "${1#v}" = "${2#v}" ]
}

version_gt() {
  python3 - "$1" "$2" <<'PY'
import re
import sys


def parse(value):
    cleaned = re.sub(r"^[^0-9]*", "", value or "")
    return tuple(int(part) for part in cleaned.split(".") if part.isdigit())


left = parse(sys.argv[1])
right = parse(sys.argv[2])
sys.exit(0 if left > right else 1)
PY
}

upsert_sw_version() {
  local key="$1"
  local value="$2"
  local file="/home/sw/sw_version"
  local tmp

  tmp="$(mktemp)"
  if [ -f "$file" ]; then
    grep -v "^${key}=" "$file" > "$tmp" || true
  fi
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$file"
}

get_sw_version() {
  local key="$1"
  grep "^${key}=" /home/sw/sw_version 2>/dev/null | tail -1 | cut -d= -f2- || true
}

get_mcp_bridge_token() {
  local config_file="/home/sw/.gemini/antigravity/mcp_config.json"

  [ -f "$config_file" ] || return 0

  python3 - "$config_file" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text())
except Exception:
    raise SystemExit(2)

server = data.get("mcpServers", {}).get("antigravity-bridge", {})
env = server.get("env", {}) if isinstance(server, dict) else {}
token = env.get("TELEGRAM_BOT_TOKEN", "")
if token:
    print(token)
PY
}

repair_mcp_bridge_config() {
  local config_file="/home/sw/.gemini/antigravity/mcp_config.json"
  local output=""
  local rc=0

  [ -f "$config_file" ] || return 0

  set +e
  output="$(python3 - "$config_file" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text())
except Exception:
    raise SystemExit(2)

servers = data.get("mcpServers", {})
server = servers.get("antigravity-bridge")
if isinstance(server, dict) and server.get("command") == "/home/sw/antigravity-bridge":
    server["command"] = "/home/sw/agent-bridge"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print("fixed_command")
PY
)"
  rc=$?
  set -e

  if [ "$rc" -eq 2 ]; then
    RESULT_MANUAL_ACTION_REQUIRED="yes"
    add_note "failed to parse /home/sw/.gemini/antigravity/mcp_config.json"
    return 0
  fi

  if [ "$output" = "fixed_command" ]; then
    add_note "repaired mcp_config bridge command path"
  fi
}

repair_env_token_from_mcp_config() {
  local env_file="/home/sw/.env"
  local mcp_token=""
  local output=""
  local rc=0

  [ -f "$env_file" ] || return 0

  set +e
  mcp_token="$(get_mcp_bridge_token)"
  rc=$?
  set -e

  if [ "$rc" -eq 2 ]; then
    RESULT_MANUAL_ACTION_REQUIRED="yes"
    add_note "failed to read TELEGRAM_BOT_TOKEN from mcp_config.json"
    return 0
  fi

  [ -n "$mcp_token" ] || return 0

  output="$(python3 - "$env_file" "$mcp_token" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
new_token = sys.argv[2]
lines = path.read_text().splitlines()

found = False
changed = False
updated = []
for line in lines:
    if line.startswith("TELEGRAM_BOT_TOKEN="):
        found = True
        current = line.split("=", 1)[1]
        if current != new_token:
            updated.append(f"TELEGRAM_BOT_TOKEN={new_token}")
            changed = True
        else:
            updated.append(line)
    else:
        updated.append(line)

if not found:
    updated.insert(0, f"TELEGRAM_BOT_TOKEN={new_token}")
    changed = True

if changed:
    path.write_text("\n".join(updated) + "\n")
    print("updated")
PY
)"

  if [ "$output" = "updated" ]; then
    add_note "synced TELEGRAM_BOT_TOKEN from mcp_config.json"
  fi
}

repair_bridge_runtime_config() {
  rm -rf /home/sw/.gemini/agentbridge
  repair_mcp_bridge_config
  repair_env_token_from_mcp_config
}

sync_gemini_md_template() {
  local target_file="/home/sw/.gemini/GEMINI.md"
  local output=""
  local rc=0

  [ -n "${GEMINI_MD_TEMPLATE_BASE64:-}" ] || return 0
  [ -f /home/sw/.antigravity/argv.json ] || return 0

  set +e
  output="$(python3 - "$target_file" "${GEMINI_MD_TEMPLATE_BASE64}" <<'PY'
import base64
import sys
from pathlib import Path

target = Path(sys.argv[1])

try:
    expected = base64.b64decode(sys.argv[2], validate=True)
except Exception:
    raise SystemExit(2)

current = target.read_bytes() if target.exists() else None
if current != expected:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(expected)
    print("updated")
PY
)"
  rc=$?
  set -e

  if [ "$rc" -eq 2 ]; then
    RESULT_MANUAL_ACTION_REQUIRED="yes"
    add_note "invalid GEMINI.md template payload"
    return 0
  fi

  if [ "$rc" -ne 0 ]; then
    RESULT_MANUAL_ACTION_REQUIRED="yes"
    add_note "failed to sync /home/sw/.gemini/GEMINI.md"
    return 0
  fi

  if [ "$output" = "updated" ]; then
    add_note "synced /home/sw/.gemini/GEMINI.md"
  fi
}

get_env_status() {
  local env_file="/home/sw/.env"
  local token_line=""
  local token_value=""

  if [ ! -f "$env_file" ]; then
    RESULT_ENV_STATUS="missing"
    return
  fi

  token_line="$(grep '^TELEGRAM_BOT_TOKEN=' "$env_file" | tail -1 || true)"
  if [ -z "$token_line" ]; then
    RESULT_ENV_STATUS="missing_token"
    return
  fi

  token_value="${token_line#TELEGRAM_BOT_TOKEN=}"
  if [ -z "$token_value" ]; then
    RESULT_ENV_STATUS="missing_token"
  elif [[ "$token_value" == ./* ]] || [[ "$token_value" == *manage.sh* ]]; then
    RESULT_ENV_STATUS="invalid_token"
  elif [[ ! "$token_value" =~ ^[0-9]{6,}:[A-Za-z0-9_-]{20,}$ ]]; then
    RESULT_ENV_STATUS="invalid_token"
  else
    RESULT_ENV_STATUS="ok"
  fi
}

bridge_failed_due_to_invalid_token() {
  if grep -q 'telegram.error.InvalidToken' /home/sw/app.log 2>/dev/null; then
    return 0
  fi
  return 1
}

has_bridge_related_install() {
  if [ -d /home/sw/antigravity-Bridge ] || [ -x /home/sw/antigravity-bridge ] || [ -x /home/sw/agent-bridge ] || [ -x /home/sw/manage.sh ]; then
    return 0
  fi
  return 1
}

bridge_files_present() {
  [ -x /home/sw/manage.sh ] && [ -x /home/sw/agent-bridge ]
}

has_legacy_bridge_artifacts() {
  [ -d /home/sw/antigravity-Bridge ] || [ -x /home/sw/antigravity-bridge ]
}

cleanup_forbidden_bridge_files() {
  find /home/sw -maxdepth 1 \
    \( \
      -name 'manage.sh.1' -o \
      -name 'manage.sh.bak.*' -o \
      -name 'antigravity-bridge.bak.*' -o \
      -name 'antigravity-Bridge.bak.*' \
    \) \
    -exec rm -rf {} +
}

resolve_bridge_release() {
  if [ -n "$BRIDGE_RELEASE_JSON_CACHE" ]; then
    return 0
  fi

  BRIDGE_RELEASE_JSON_CACHE="$(github_latest_release_json "$AGENTBRIDGE_REPO" "${AGENTBRIDGE_GITHUB_TOKEN:-}")" || return 1
  RESULT_BRIDGE_RELEASE_TAG="$(printf '%s\n' "$BRIDGE_RELEASE_JSON_CACHE" | json_get_tag)"
  [ -n "$RESULT_BRIDGE_RELEASE_TAG" ] || RESULT_BRIDGE_RELEASE_TAG="unknown"
}

record_bridge_version() {
  local tag="$1"
  [ -n "$tag" ] || return 0
  [ "$tag" = "unknown" ] && return 0
  [ "$tag" = "N/A" ] && return 0

  upsert_sw_version "agent-bridge" "$tag"
  printf '%s\n' "$tag" > /home/sw/.agentbridge-release-tag
}

bridge_version_matches_latest() {
  local latest_tag="$1"
  local recorded_tag=""
  local marker_tag=""

  [ -n "$latest_tag" ] || return 1
  [ "$latest_tag" = "unknown" ] && return 1
  [ "$latest_tag" = "N/A" ] && return 1

  recorded_tag="$(get_sw_version "agent-bridge")"
  if [ -n "$recorded_tag" ] && version_eq "$recorded_tag" "$latest_tag"; then
    return 0
  fi

  marker_tag="$(cat /home/sw/.agentbridge-release-tag 2>/dev/null || true)"
  if [ -n "$marker_tag" ] && version_eq "$marker_tag" "$latest_tag"; then
    return 0
  fi

  return 1
}

has_running_bridge_process() {
  python3 - <<'PY'
import re
import subprocess
import sys

patterns = [
    re.compile(r'(^|[\s/.])antigravity-bridge([\s]|$)'),
    re.compile(r'(^|[\s/.])agent-bridge([\s]|$)'),
]

for line in subprocess.check_output(["ps", "-eo", "args="], text=True).splitlines():
    if "/home/sw/antigravity-Bridge" in line:
        sys.exit(0)
    if any(p.search(line) for p in patterns):
        sys.exit(0)
sys.exit(1)
PY
}

bridge_process_state() {
  python3 - <<'PY'
import re
import subprocess

legacy_patterns = [
    re.compile(r'(^|[\s/.])antigravity-bridge([\s]|$)'),
]
agent_patterns = [
    re.compile(r'(^|[\s/.])agent-bridge([\s]|$)'),
]

legacy = False
agent = False
for line in subprocess.check_output(["ps", "-eo", "args="], text=True).splitlines():
    if "/home/sw/antigravity-Bridge" in line or any(p.search(line) for p in legacy_patterns):
        legacy = True
    if any(p.search(line) for p in agent_patterns):
        agent = True

print(f"legacy={'yes' if legacy else 'no'}")
print(f"agent={'yes' if agent else 'no'}")
PY
}

kill_named_processes() {
  local kind="$1"
  python3 - "$kind" <<'PY'
import os
import re
import signal
import subprocess
import sys
import time

kind = sys.argv[1]
patterns = {
    "legacy-bridge": [
        re.compile(r'(^|[\s/.])antigravity-bridge([\s]|$)'),
    ],
    "agent-bridge": [
        re.compile(r'(^|[\s/.])agent-bridge([\s]|$)'),
    ],
    "bridge": [
        re.compile(r'(^|[\s/.])antigravity-bridge([\s]|$)'),
        re.compile(r'(^|[\s/.])agent-bridge([\s]|$)'),
    ],
    "antigravity-cli": [
        re.compile(r'(^|[\s/.])antigravity-cli([\s]|$)'),
    ],
}
subs = []
if kind in ("bridge", "legacy-bridge"):
    subs.append("/home/sw/antigravity-Bridge")

skip = set()
pid = os.getpid()
while pid and pid > 1:
    skip.add(pid)
    try:
        ppid = int(subprocess.check_output(["ps", "-o", "ppid=", "-p", str(pid)], text=True).strip())
    except Exception:
        break
    if ppid == pid:
        break
    pid = ppid

targets = []
for line in subprocess.check_output(["ps", "-eo", "pid=,args="], text=True).splitlines():
    raw = line.strip()
    if not raw:
        continue
    pid_text, _, cmd = raw.partition(" ")
    try:
        current_pid = int(pid_text)
    except ValueError:
        continue
    if current_pid in skip:
        continue
    if "ps -eo pid=,args=" in cmd:
        continue
    matched = any(p.search(cmd) for p in patterns[kind]) or any(s in cmd for s in subs)
    if matched:
        targets.append(current_pid)

for sig in (signal.SIGTERM, signal.SIGKILL):
    for current_pid in targets:
        try:
            os.kill(current_pid, sig)
        except ProcessLookupError:
            pass
    time.sleep(1)
PY
}

restart_agentbridge_service() {
  if [ -x /home/sw/manage.sh ]; then
    /home/sw/manage.sh stop || true
  fi
  kill_named_processes "agent-bridge"
  if [ -x /home/sw/manage.sh ]; then
    /home/sw/manage.sh start
    return $?
  fi
  if [ -x /home/sw/agent-bridge ]; then
    nohup /home/sw/agent-bridge >/tmp/agent-bridge.log 2>&1 &
    sleep 2
    return 0
  fi
  return 1
}

ensure_agentbridge_startup_entry() {
  local startup_command="/home/sw/manage.sh start"
  local startup_entry="@reboot ${startup_command}"
  local existing_crontab=""
  local tmp_crontab=""
  local filtered_crontab=""

  if [ ! -x /home/sw/manage.sh ]; then
    add_note "skipped startup config because /home/sw/manage.sh is missing"
    return 1
  fi

  if ! command -v crontab >/dev/null 2>&1; then
    RESULT_MANUAL_ACTION_REQUIRED="yes"
    add_note "crontab not found; unable to ensure agent-bridge startup entry"
    return 1
  fi

  existing_crontab="$(crontab -l 2>/dev/null || true)"
  filtered_crontab="$(printf '%s\n' "$existing_crontab" | sed '/^[[:space:]]*#/d')"
  if printf '%s\n' "$filtered_crontab" | grep -Fq "$startup_command"; then
    return 0
  fi

  tmp_crontab="$(mktemp)"
  if [ -n "$existing_crontab" ]; then
    printf '%s\n' "$existing_crontab" > "$tmp_crontab"
  fi
  printf '%s\n' "$startup_entry" >> "$tmp_crontab"
  if ! crontab "$tmp_crontab"; then
    rm -f "$tmp_crontab"
    RESULT_MANUAL_ACTION_REQUIRED="yes"
    add_note "failed to install crontab startup entry for agent-bridge"
    return 1
  fi
  rm -f "$tmp_crontab"
  add_note "added @reboot /home/sw/manage.sh start"
  return 0
}

ensure_agentbridge_effective() {
  local mode="${1:-restart}"
  local state=""
  local legacy_running="no"
  local agent_running="no"

  state="$(bridge_process_state)"
  legacy_running="$(printf '%s\n' "$state" | awk -F= '/^legacy=/{print $2}')"
  agent_running="$(printf '%s\n' "$state" | awk -F= '/^agent=/{print $2}')"

  if [ "$legacy_running" = "yes" ]; then
    kill_named_processes "legacy-bridge"
    add_note "killed legacy antigravity-bridge process"
  fi

  if [ "$mode" = "restart" ]; then
    if [ "$legacy_running" = "yes" ] || [ "$agent_running" = "yes" ]; then
      restart_agentbridge_service || return 1
      add_note "restarted agent-bridge process"
    else
      restart_agentbridge_service || return 1
      add_note "started agent-bridge process"
    fi
  else
    if [ "$agent_running" != "yes" ]; then
      restart_agentbridge_service || return 1
      add_note "started agent-bridge process"
    fi
  fi

  state="$(bridge_process_state)"
  legacy_running="$(printf '%s\n' "$state" | awk -F= '/^legacy=/{print $2}')"
  agent_running="$(printf '%s\n' "$state" | awk -F= '/^agent=/{print $2}')"
  [ "$legacy_running" = "no" ] && [ "$agent_running" = "yes" ]
}

refresh_agentbridge_files_only() {
  local release_json=""
  local tmp_manage="/home/sw/manage.sh.tmp"
  local tmp_binary="/home/sw/agent-bridge.tmp"

  ensure_bridge_disk_space || return 1
  resolve_bridge_release || return 1
  release_json="$BRIDGE_RELEASE_JSON_CACHE"

  download_repo_file "$AGENTBRIDGE_REPO" "${AGENTBRIDGE_GITHUB_TOKEN:-}" "manage.sh" "$tmp_manage" || return 1
  if ! download_release_asset "$AGENTBRIDGE_REPO" "${AGENTBRIDGE_GITHUB_TOKEN:-}" "$release_json" "$AGENTBRIDGE_ASSET_PRIMARY" "$tmp_binary"; then
    download_release_asset "$AGENTBRIDGE_REPO" "${AGENTBRIDGE_GITHUB_TOKEN:-}" "$release_json" "$AGENTBRIDGE_ASSET_FALLBACK" "$tmp_binary" || return 1
  fi

  if [ ! -s "$tmp_manage" ]; then
    rm -f "$tmp_manage" "$tmp_binary"
    add_note "empty AgentBridge manage.sh download"
    return 1
  fi

  if ! bash -n "$tmp_manage"; then
    rm -f "$tmp_manage" "$tmp_binary"
    add_note "invalid AgentBridge manage.sh download"
    return 1
  fi

  if [ ! -s "$tmp_binary" ]; then
    rm -f "$tmp_manage" "$tmp_binary"
    add_note "empty AgentBridge binary download"
    return 1
  fi

  if ! chmod +x "$tmp_manage" "$tmp_binary"; then
    rm -f "$tmp_manage" "$tmp_binary"
    add_note "failed to chmod AgentBridge downloads"
    return 1
  fi

  if ! mv -f "$tmp_manage" /home/sw/manage.sh; then
    rm -f "$tmp_manage" "$tmp_binary"
    add_note "failed to replace AgentBridge manage.sh"
    return 1
  fi

  if ! mv -f "$tmp_binary" /home/sw/agent-bridge; then
    rm -f "$tmp_binary"
    add_note "failed to replace AgentBridge binary"
    return 1
  fi
  rm -rf /home/sw/antigravity-Bridge
  rm -f /home/sw/antigravity-bridge /home/sw/.antigravity-release-tag
  record_bridge_version "$RESULT_BRIDGE_RELEASE_TAG"
  return 0
}

refresh_manage_script_if_present() {
  local tmp_manage="/home/sw/manage.sh.tmp"

  [ -e /home/sw/manage.sh ] || return 0

  download_repo_file "$AGENTBRIDGE_REPO" "${AGENTBRIDGE_GITHUB_TOKEN:-}" "manage.sh" "$tmp_manage" || return 1
  chmod +x "$tmp_manage"
  mv -f "$tmp_manage" /home/sw/manage.sh
  return 0
}

update_antigravity() {
  if [ ! -f /home/sw/.antigravity/argv.json ]; then
    RESULT_ANTIGRAVITY_STATUS="skipped_no_argv"
    RESULT_ANTIGRAVITY_CLI_STATUS="skipped_no_argv"
    return
  fi

  RESULT_ANTIGRAVITY_OLD_VERSION="$(dpkg -s antigravity 2>/dev/null | awk '/^Version:/{print $2}' || true)"
  [ -n "$RESULT_ANTIGRAVITY_OLD_VERSION" ] || RESULT_ANTIGRAVITY_OLD_VERSION="N/A"

  if ! sudo apt-get -o DPkg::Lock::Timeout=60 update -qq; then
    if sudo grep -R -n -E '^[[:space:]]*deb .*apt\\.postgresql\\.org/pub/repos/apt.*focal-pgdg' \
      /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null >/tmp/agentbridge-bad-apt-sources.txt; then
      while IFS=: read -r file line_no _; do
        [ -n "$file" ] || continue
        sudo sed -i "${line_no}s/^[[:space:]]*deb /# disabled by AgentBridge rollout: deb /" "$file"
      done < /tmp/agentbridge-bad-apt-sources.txt
      rm -f /tmp/agentbridge-bad-apt-sources.txt
      add_note "disabled stale focal-pgdg apt source and retried antigravity update"
    fi
    if ! sudo apt-get -o DPkg::Lock::Timeout=60 update -qq; then
      RESULT_ANTIGRAVITY_STATUS="antigravity_failed"
      RESULT_WORKFLOW_STATUS="antigravity_failed"
      add_note "antigravity apt update/install failed"
      RESULT_ANTIGRAVITY_NEW_VERSION="$(dpkg -s antigravity 2>/dev/null | awk '/^Version:/{print $2}' || true)"
      [ -n "$RESULT_ANTIGRAVITY_NEW_VERSION" ] || RESULT_ANTIGRAVITY_NEW_VERSION="N/A"
      return
    fi
  fi

  if wait_for_dpkg_lock 180 && sudo apt-get -o DPkg::Lock::Timeout=60 install -y -qq antigravity; then
    RESULT_ANTIGRAVITY_STATUS="success"
  else
    RESULT_ANTIGRAVITY_STATUS="antigravity_failed"
    RESULT_WORKFLOW_STATUS="antigravity_failed"
    if ! wait_for_dpkg_lock 1; then
      add_note "dpkg lock busy during antigravity install"
    fi
    add_note "antigravity apt update/install failed"
  fi

  RESULT_ANTIGRAVITY_NEW_VERSION="$(dpkg -s antigravity 2>/dev/null | awk '/^Version:/{print $2}' || true)"
  [ -n "$RESULT_ANTIGRAVITY_NEW_VERSION" ] || RESULT_ANTIGRAVITY_NEW_VERSION="N/A"
}

update_antigravity_cli() {
  local current_tag=""
  local recorded_tag=""
  local release_json=""
  local tmp_binary="/tmp/antigravity-cli.$$"

  if [ "$RESULT_ENV_STATUS" = "missing" ]; then
    RESULT_ANTIGRAVITY_CLI_STATUS="skipped_missing_env"
    return
  fi

  if [ ! -f /home/sw/.antigravity/argv.json ]; then
    RESULT_ANTIGRAVITY_CLI_STATUS="skipped_no_argv"
    return
  fi

  RESULT_ANTIGRAVITY_CLI_TARGET_VERSION="${ANTIGRAVITY_CLI_LATEST_TAG:-unknown}"
  recorded_tag="$(grep '^antigravity-cli=' /home/sw/sw_version 2>/dev/null | tail -1 | cut -d= -f2- || true)"

  if [ -x /home/sw/antigravity-cli ] && [ -n "$recorded_tag" ] && version_eq "$recorded_tag" "$RESULT_ANTIGRAVITY_CLI_TARGET_VERSION"; then
    RESULT_ANTIGRAVITY_CLI_STATUS="already_latest"
    RESULT_ANTIGRAVITY_CLI_VERSION="$recorded_tag"
    return
  fi

  release_json="$(github_latest_release_json "$ANTIGRAVITY_REPO" "${BLOG_GITHUB_TOKEN:-}")" || {
    RESULT_ANTIGRAVITY_CLI_STATUS="antigravity_cli_failed"
    RESULT_WORKFLOW_STATUS="antigravity_cli_failed"
    add_note "failed to query antigravity-cli latest release"
    return
  }

  current_tag="$(printf '%s\n' "$release_json" | json_get_tag)"
  [ -n "$current_tag" ] || current_tag="$RESULT_ANTIGRAVITY_CLI_TARGET_VERSION"
  RESULT_ANTIGRAVITY_CLI_TARGET_VERSION="$current_tag"

  kill_named_processes "antigravity-cli"
  rm -f /home/sw/antigravity-cli

  if download_release_asset "$ANTIGRAVITY_REPO" "${BLOG_GITHUB_TOKEN:-}" "$release_json" "antigravity-cli" "$tmp_binary"; then
    chmod +x "$tmp_binary"
    mv -f "$tmp_binary" /home/sw/antigravity-cli
    upsert_sw_version "antigravity-cli" "$current_tag"
    RESULT_ANTIGRAVITY_CLI_STATUS="success"
    RESULT_ANTIGRAVITY_CLI_VERSION="$current_tag"
  else
    rm -f "$tmp_binary"
    RESULT_ANTIGRAVITY_CLI_STATUS="antigravity_cli_failed"
    RESULT_WORKFLOW_STATUS="antigravity_cli_failed"
    add_note "failed to download antigravity-cli asset"
  fi
}

update_bridge() {
  cleanup_forbidden_bridge_files

  if ! has_bridge_related_install; then
    RESULT_BRIDGE_STATUS="skipped_no_install"
    return
  fi

  if ! refresh_manage_script_if_present; then
    RESULT_BRIDGE_STATUS="bridge_failed"
    RESULT_WORKFLOW_STATUS="bridge_failed"
    add_note "failed to force refresh existing AgentBridge manage.sh"
    return
  fi

  get_env_status

  if [ "$RESULT_ENV_STATUS" = "missing" ]; then
    RESULT_BRIDGE_STATUS="skipped_missing_env"
    add_note "missing /home/sw/.env, skipped bridge update"
    return
  fi

  if [ "$RESULT_ENV_STATUS" = "invalid_token" ]; then
    RESULT_BRIDGE_STATUS="skipped_invalid_env"
    RESULT_MANUAL_ACTION_REQUIRED="yes"
    add_note "invalid TELEGRAM_BOT_TOKEN in /home/sw/.env"
    return
  fi

  if [ "$RESULT_ENV_STATUS" = "missing" ] || [ "$RESULT_ENV_STATUS" = "missing_token" ]; then
    if has_running_bridge_process; then
      RESULT_BRIDGE_STATUS="skipped_missing_env_active"
      RESULT_MANUAL_ACTION_REQUIRED="yes"
      add_note "active bridge install without usable /home/sw/.env"
      return
    fi

    if ! resolve_bridge_release; then
      RESULT_BRIDGE_STATUS="bridge_failed"
      RESULT_WORKFLOW_STATUS="bridge_failed"
      add_note "failed to query AgentBridge latest release"
      return
    fi

    if bridge_files_present && ! has_legacy_bridge_artifacts && bridge_version_matches_latest "$RESULT_BRIDGE_RELEASE_TAG"; then
      record_bridge_version "$RESULT_BRIDGE_RELEASE_TAG"
      RESULT_BRIDGE_STATUS="skipped_already_latest_no_env"
      return
    fi

    if refresh_agentbridge_files_only; then
      RESULT_BRIDGE_STATUS="files_refreshed_no_env"
      return
    fi

    RESULT_BRIDGE_STATUS="bridge_failed"
    RESULT_WORKFLOW_STATUS="bridge_failed"
    add_note "failed to refresh AgentBridge files without env"
    return
  fi

  export GITHUB_TOKEN="${AGENTBRIDGE_GITHUB_TOKEN:-}"
  if ! resolve_bridge_release; then
    RESULT_BRIDGE_STATUS="bridge_failed"
    RESULT_WORKFLOW_STATUS="bridge_failed"
    add_note "failed to query AgentBridge latest release"
    return
  fi

  if has_running_bridge_process && bridge_files_present && ! has_legacy_bridge_artifacts && bridge_version_matches_latest "$RESULT_BRIDGE_RELEASE_TAG"; then
    if ! ensure_agentbridge_effective "start_only_if_missing"; then
      RESULT_BRIDGE_STATUS="bridge_failed"
      RESULT_WORKFLOW_STATUS="bridge_failed"
      add_note "failed to normalize bridge processes"
      return
    fi
    if ! ensure_agentbridge_startup_entry; then
      RESULT_BRIDGE_STATUS="bridge_failed"
      RESULT_WORKFLOW_STATUS="bridge_failed"
      add_note "failed to ensure agent-bridge startup entry"
      return
    fi
    record_bridge_version "$RESULT_BRIDGE_RELEASE_TAG"
    RESULT_BRIDGE_STATUS="skipped_already_latest"
    return
  fi

  if ! ensure_bridge_disk_space; then
    return
  fi

  if [ -x /home/sw/manage.sh ]; then
    /home/sw/manage.sh stop || true
  fi
  kill_named_processes "bridge"

  if ! download_repo_file "$AGENTBRIDGE_REPO" "${AGENTBRIDGE_GITHUB_TOKEN:-}" "manage.sh" /home/sw/manage.sh.tmp; then
    RESULT_BRIDGE_STATUS="bridge_failed"
    RESULT_WORKFLOW_STATUS="bridge_failed"
    add_note "failed to download AgentBridge manage.sh"
    return
  fi
  if [ ! -s /home/sw/manage.sh.tmp ]; then
    RESULT_BRIDGE_STATUS="bridge_failed"
    RESULT_WORKFLOW_STATUS="bridge_failed"
    add_note "empty AgentBridge manage.sh download"
    rm -f /home/sw/manage.sh.tmp
    return
  fi
  if ! bash -n /home/sw/manage.sh.tmp; then
    RESULT_BRIDGE_STATUS="bridge_failed"
    RESULT_WORKFLOW_STATUS="bridge_failed"
    add_note "invalid AgentBridge manage.sh download"
    rm -f /home/sw/manage.sh.tmp
    return
  fi
  if ! chmod +x /home/sw/manage.sh.tmp; then
    RESULT_BRIDGE_STATUS="bridge_failed"
    RESULT_WORKFLOW_STATUS="bridge_failed"
    add_note "failed to chmod AgentBridge manage.sh"
    rm -f /home/sw/manage.sh.tmp
    return
  fi
  if ! mv -f /home/sw/manage.sh.tmp /home/sw/manage.sh; then
    RESULT_BRIDGE_STATUS="bridge_failed"
    RESULT_WORKFLOW_STATUS="bridge_failed"
    add_note "failed to replace AgentBridge manage.sh"
    rm -f /home/sw/manage.sh.tmp
    return
  fi

  rm -rf /home/sw/antigravity-Bridge
  rm -f /home/sw/antigravity-bridge /home/sw/.antigravity-release-tag

  if /home/sw/manage.sh deploy && /home/sw/manage.sh start; then
    if ! ensure_agentbridge_effective; then
      RESULT_BRIDGE_STATUS="bridge_failed"
      RESULT_WORKFLOW_STATUS="bridge_failed"
      add_note "failed to normalize bridge processes"
      return
    fi
    if ! ensure_agentbridge_startup_entry; then
      RESULT_BRIDGE_STATUS="bridge_failed"
      RESULT_WORKFLOW_STATUS="bridge_failed"
      add_note "failed to ensure agent-bridge startup entry"
      return
    fi
    RESULT_BRIDGE_STATUS="deployed_started"
    if [ -f /home/sw/.agentbridge-release-tag ]; then
      RESULT_BRIDGE_RELEASE_TAG="$(cat /home/sw/.agentbridge-release-tag)"
    fi
    record_bridge_version "$RESULT_BRIDGE_RELEASE_TAG"
  else
    if bridge_failed_due_to_invalid_token; then
      RESULT_ENV_STATUS="invalid_token"
      RESULT_BRIDGE_STATUS="skipped_invalid_env"
      RESULT_MANUAL_ACTION_REQUIRED="yes"
      add_note "invalid TELEGRAM_BOT_TOKEN in /home/sw/.env"
    else
      RESULT_BRIDGE_STATUS="bridge_failed"
      RESULT_WORKFLOW_STATUS="bridge_failed"
      add_note "AgentBridge deploy/start failed"
    fi
  fi
}

parse_codex_version() {
  codex -V 2>/dev/null | awk '/codex-cli/{print $2}' | tail -1
}

parse_kilocode_version() {
  kilo --version 2>/dev/null \
    | tr -d '\r' \
    | sed -nE 's/.*([0-9]+(\.[0-9]+)+([-.][0-9A-Za-z.]+)?).*/\1/p' \
    | head -n 1
}

write_codex_config() {
  local codex_base_url="${CLIPROXYAPI_BASE_URL:-}"

  codex_base_url="$(printf '%s' "$codex_base_url" | sed -E 's#/v1/?$##')/v1"

  mkdir -p /home/sw/.codex
  umask 077
  cat > /home/sw/.codex/auth.json <<EOF
{
  "OPENAI_API_KEY": "${CLIPROXYAPI_OPENAI_API_KEY}"
}
EOF

  cat > /home/sw/.codex/config.toml <<EOF
approval_policy = "never"

sandbox_mode = "danger-full-access"

model_provider = "cliproxyapi"
model = "gpt-5.4"
model_reasoning_effort = "high"

[model_providers.cliproxyapi]
name = "cliproxyapi"
base_url = "${codex_base_url}"
wire_api = "responses"

[projects."/home/sw"]
trust_level = "trusted"

[projects."/home/sw/dev_root"]
trust_level = "trusted"
EOF
}

parse_claude_version() {
  claude -v 2>/dev/null | awk 'NF {print $1; exit}'
}

run_claude_installer() {
  local timeout_seconds="${CLAUDE_INSTALL_TIMEOUT_SECONDS:-600}"
  local install_cmd='curl -fsSL https://claude.ai/install.sh | bash'

  if command -v timeout >/dev/null 2>&1; then
    timeout "$timeout_seconds" bash -lc "$install_cmd"
    return $?
  fi

  bash -lc "$install_cmd"
}

write_claude_shell_config() {
  local bashrc="/home/sw/.bashrc"
  local anthropic_base_url="${CLIPROXYAPI_BASE_URL:-}"
  local anthropic_auth_token="${CLIPROXYAPI_OPENAI_API_KEY:-}"

  if [ -z "$anthropic_base_url" ] || [ -z "$anthropic_auth_token" ]; then
    return 1
  fi

  anthropic_base_url="$(printf '%s' "$anthropic_base_url" | sed -E 's#/v1/?$##')"

  python3 - "$bashrc" "$anthropic_base_url" "$anthropic_auth_token" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
anthropic_base_url = sys.argv[2]
anthropic_auth_token = sys.argv[3]
marker_start = "# === CLAUDE CONFIG START ==="
marker_end = "# === CLAUDE CONFIG END ==="
block = f"""\
{marker_start}
export PATH="$HOME/.local/bin:$PATH"

claude() {{
    (
        unset ANTHROPIC_AUTH_TOKEN ANTHROPIC_API_KEY ANTHROPIC_BASE_URL
        ANTHROPIC_BASE_URL="{anthropic_base_url}" \\
        ANTHROPIC_API_KEY="{anthropic_auth_token}" \\
        command claude "$@"
    )
}}

alias clauded="claude --dangerously-skip-permissions"
{marker_end}
"""

text = path.read_text() if path.exists() else ""
text = re.sub(
    rf"{re.escape(marker_start)}\n.*?{re.escape(marker_end)}\n?",
    "",
    text,
    flags=re.S,
)
text = re.sub(r'^export PATH="\$HOME/\.local/bin:\$PATH"\n?', "", text, flags=re.M)
text = re.sub(r'^export ANTHROPIC_BASE_URL=.*\n?', "", text, flags=re.M)
text = re.sub(r'^export ANTHROPIC_AUTH_TOKEN=.*\n?', "", text, flags=re.M)

updated = text
if updated and not updated.endswith("\n"):
    updated += "\n"
updated += block

path.write_text(updated)
PY

  export PATH="/home/sw/.local/bin:${PATH}"
  unset ANTHROPIC_AUTH_TOKEN ANTHROPIC_API_KEY ANTHROPIC_BASE_URL
  set +u
  [ -f "$bashrc" ] && source "$bashrc" >/dev/null 2>&1 || true
  set -u
  if [ -x /home/sw/manage.sh ]; then
    /home/sw/manage.sh restart >/dev/null 2>&1 || true
  fi
  hash -r || true
}

strip_api_v1_suffix() {
  printf '%s' "${1:-}" | sed -E 's#/v1/?$##'
}

get_env_file_value() {
  local key="$1"
  local env_file="/home/sw/.env"

  [ -f "$env_file" ] || return 0

  python3 - "$env_file" "$key" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]

for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
    if not raw_line.startswith(f"{key}="):
        continue
    print(raw_line.split("=", 1)[1])
    raise SystemExit
PY
}

parse_windsurf_version() {
  dpkg -s windsurf 2>/dev/null | awk '/^Version:/{print $2}' | tail -1
}

install_windsurf_package() {
  local repo_line='deb [arch=arm64 signed-by=/etc/apt/keyrings/windsurf-stable.gpg] https://windsurf-stable.codeiumdata.com/wVxQEIWkwPUEAGf3/apt-arm64 stable main'
  local keyring="/etc/apt/keyrings/windsurf-stable.gpg"
  local list_file="/etc/apt/sources.list.d/windsurf.list"
  local tmp_gpg=""

  if ! wait_for_dpkg_lock 180; then
    RESULT_WINDSURF_STATUS="windsurf_failed"
    RESULT_WORKFLOW_STATUS="windsurf_failed"
    add_note "dpkg lock busy during windsurf install"
    return 1
  fi

  if ! sudo apt-get install -y -qq wget gpg apt-transport-https; then
    RESULT_WINDSURF_STATUS="windsurf_failed"
    RESULT_WORKFLOW_STATUS="windsurf_failed"
    add_note "failed to install windsurf apt prerequisites"
    return 1
  fi

  tmp_gpg="$(mktemp)"
  if ! wget -qO- "https://windsurf-stable.codeiumdata.com/wVxQEIWkwPUEAGf3/windsurf.gpg" | gpg --dearmor > "$tmp_gpg"; then
    rm -f "$tmp_gpg"
    RESULT_WINDSURF_STATUS="windsurf_failed"
    RESULT_WORKFLOW_STATUS="windsurf_failed"
    add_note "failed to download windsurf apt gpg key"
    return 1
  fi

  if ! sudo install -D -o root -g root -m 644 "$tmp_gpg" "$keyring"; then
    rm -f "$tmp_gpg"
    RESULT_WINDSURF_STATUS="windsurf_failed"
    RESULT_WORKFLOW_STATUS="windsurf_failed"
    add_note "failed to install windsurf apt keyring"
    return 1
  fi
  rm -f "$tmp_gpg"

  if ! printf '%s\n' "$repo_line" | sudo tee "$list_file" >/dev/null; then
    RESULT_WINDSURF_STATUS="windsurf_failed"
    RESULT_WORKFLOW_STATUS="windsurf_failed"
    add_note "failed to write windsurf apt source list"
    return 1
  fi

  if ! sudo apt-get update -qq; then
    RESULT_WINDSURF_STATUS="windsurf_failed"
    RESULT_WORKFLOW_STATUS="windsurf_failed"
    add_note "windsurf apt update failed"
    return 1
  fi

  if ! sudo apt-get install -y -qq windsurf; then
    RESULT_WINDSURF_STATUS="windsurf_failed"
    RESULT_WORKFLOW_STATUS="windsurf_failed"
    add_note "windsurf apt install failed"
    return 1
  fi

  RESULT_WINDSURF_VERSION="$(parse_windsurf_version || true)"
  [ -n "$RESULT_WINDSURF_VERSION" ] || RESULT_WINDSURF_VERSION="unknown"
  return 0
}

write_windsurf_mcp_configs() {
  local token=""
  local chat_ids=""
  local claude_base_url=""
  local claude_api_key=""
  local codex_command=""
  local claude_command=""
  local kilo_command=""
  local gemini_command=""
  local user_config_dir="/home/sw/.config/Windsurf/User"
  local codeium_dir="/home/sw/.codeium/windsurf"
  local user_mcp_file="$user_config_dir/mcp.json"
  local legacy_mcp_file="$codeium_dir/mcp_config.json"

  token="$(get_env_file_value TELEGRAM_BOT_TOKEN)"
  chat_ids="$(get_env_file_value TELEGRAM_CHAT_ID)"
  [ -n "$chat_ids" ] || chat_ids="$DEFAULT_TELEGRAM_CHAT_IDS"

  if [ -z "$token" ]; then
    RESULT_WINDSURF_STATUS="windsurf_failed"
    RESULT_WORKFLOW_STATUS="windsurf_failed"
    add_note "missing TELEGRAM_BOT_TOKEN for windsurf mcp config"
    return 1
  fi

  claude_base_url="$(strip_api_v1_suffix "${CLIPROXYAPI_BASE_URL:-}")"
  claude_api_key="${CLIPROXYAPI_OPENAI_API_KEY:-}"
  codex_command="$(command -v codex || true)"
  claude_command="$(command -v claude || true)"
  kilo_command="$(command -v kilo || true)"
  gemini_command="$(command -v gemini || true)"

  [ -n "$codex_command" ] || codex_command="/home/sw/.nvm/versions/node/$(node -v 2>/dev/null || echo v22.21.1)/bin/codex"
  [ -n "$claude_command" ] || claude_command="/home/sw/.local/bin/claude"
  [ -n "$kilo_command" ] || kilo_command="/home/sw/.nvm/versions/node/$(node -v 2>/dev/null || echo v22.21.1)/bin/kilo"
  [ -n "$gemini_command" ] || gemini_command="/home/sw/.nvm/versions/node/$(node -v 2>/dev/null || echo v22.21.1)/bin/gemini"

  mkdir -p "$user_config_dir" "$codeium_dir"

  cat > "$legacy_mcp_file" <<EOF
{
  "mcpServers": {
    "agent-bridge": {
      "command": "/home/sw/agent-bridge",
      "args": [],
      "env": {
        "TELEGRAM_BOT_TOKEN": "$token",
        "TELEGRAM_CHAT_ID": "$chat_ids",
        "DEFAULT_MODE": "CLI",
        "DEFAULT_CLI_PROFILE": "codex_gpt_5_4",
        "CLI_CWD": "/home/sw/dev_root/",
        "CLI_EXEC_MODE": "YOLO",
        "CLI_HEARTBEAT_SECONDS": "15",
        "CODEX_COMMAND": "$codex_command",
        "CLAUDE_COMMAND": "$claude_command",
        "KILO_COMMAND": "$kilo_command",
        "GEMINI_COMMAND": "$gemini_command",
        "CLAUDE_BASE_URL": "$claude_base_url",
        "CLAUDE_API_KEY": "$claude_api_key",
        "AGENTBRIDGE_CLOUD_ENABLED": "${AGENTBRIDGE_CLOUD_ENABLED:-1}",
        "AGENTBRIDGE_CLOUD_BASE_URL": "${AGENTBRIDGE_CLOUD_BASE_URL:-$DEFAULT_CLOUD_BASE_URL}",
        "AGENTBRIDGE_BOOTSTRAP_TOKEN": "${AGENTBRIDGE_BOOTSTRAP_TOKEN:-${AGENTBRIDGE_CLOUD_API_KEY:-${CODEX_CLOUD_API_KEY:-$DEFAULT_CLOUD_BOOTSTRAP_TOKEN}}}",
        "AGENTBRIDGE_GUARDIAN_HEARTBEAT_SECONDS": "${AGENTBRIDGE_GUARDIAN_HEARTBEAT_SECONDS:-900}",
        "AGENTBRIDGE_GUARDIAN_METRICS_SECONDS": "${AGENTBRIDGE_GUARDIAN_METRICS_SECONDS:-1800}",
        "AGENTBRIDGE_GUARDIAN_POLL_SECONDS": "${AGENTBRIDGE_GUARDIAN_POLL_SECONDS:-60}",
        "AGENTBRIDGE_GUARDIAN_REQUEST_TIMEOUT_SECONDS": "${AGENTBRIDGE_GUARDIAN_REQUEST_TIMEOUT_SECONDS:-15}",
        "AGENTBRIDGE_GUARDIAN_ALLOW_SHELL_FULL": "${AGENTBRIDGE_GUARDIAN_ALLOW_SHELL_FULL:-0}"
      }
    }
  }
}
EOF

  cat > "$user_mcp_file" <<EOF
{
  "servers": {
    "agent-bridge": {
      "command": "/home/sw/agent-bridge",
      "args": [],
      "env": {
        "TELEGRAM_BOT_TOKEN": "$token",
        "TELEGRAM_CHAT_ID": "$chat_ids",
        "DEFAULT_MODE": "CLI",
        "DEFAULT_CLI_PROFILE": "codex_gpt_5_4",
        "CLI_CWD": "/home/sw/dev_root/",
        "CLI_EXEC_MODE": "YOLO",
        "CLI_HEARTBEAT_SECONDS": "15",
        "CODEX_COMMAND": "$codex_command",
        "CLAUDE_COMMAND": "$claude_command",
        "KILO_COMMAND": "$kilo_command",
        "GEMINI_COMMAND": "$gemini_command",
        "CLAUDE_BASE_URL": "$claude_base_url",
        "CLAUDE_API_KEY": "$claude_api_key",
        "AGENTBRIDGE_CLOUD_ENABLED": "${AGENTBRIDGE_CLOUD_ENABLED:-1}",
        "AGENTBRIDGE_CLOUD_BASE_URL": "${AGENTBRIDGE_CLOUD_BASE_URL:-$DEFAULT_CLOUD_BASE_URL}",
        "AGENTBRIDGE_BOOTSTRAP_TOKEN": "${AGENTBRIDGE_BOOTSTRAP_TOKEN:-${AGENTBRIDGE_CLOUD_API_KEY:-${CODEX_CLOUD_API_KEY:-$DEFAULT_CLOUD_BOOTSTRAP_TOKEN}}}",
        "AGENTBRIDGE_GUARDIAN_HEARTBEAT_SECONDS": "${AGENTBRIDGE_GUARDIAN_HEARTBEAT_SECONDS:-900}",
        "AGENTBRIDGE_GUARDIAN_METRICS_SECONDS": "${AGENTBRIDGE_GUARDIAN_METRICS_SECONDS:-1800}",
        "AGENTBRIDGE_GUARDIAN_POLL_SECONDS": "${AGENTBRIDGE_GUARDIAN_POLL_SECONDS:-60}",
        "AGENTBRIDGE_GUARDIAN_REQUEST_TIMEOUT_SECONDS": "${AGENTBRIDGE_GUARDIAN_REQUEST_TIMEOUT_SECONDS:-15}",
        "AGENTBRIDGE_GUARDIAN_ALLOW_SHELL_FULL": "${AGENTBRIDGE_GUARDIAN_ALLOW_SHELL_FULL:-0}"
      }
    }
  },
  "inputs": []
}
EOF

  add_note "updated windsurf mcp config"
  return 0
}

install_windsurf_bridge_assets() {
  local codeium_dir="/home/sw/.codeium/windsurf"
  local skill_dir="$codeium_dir/skills/agent-bridge-telegram"
  local hook_script_path="$codeium_dir/agent_bridge_windsurf_hook.py"
  local hooks_file="$codeium_dir/hooks.json"

  mkdir -p "$skill_dir"

  download_repo_file "$AGENTBRIDGE_REPO" "${AGENTBRIDGE_GITHUB_TOKEN:-}" "AGENTS.md" "$codeium_dir/AGENTS.md" || return 1
  download_repo_file "$AGENTBRIDGE_REPO" "${AGENTBRIDGE_GITHUB_TOKEN:-}" ".windsurf/skills/agent-bridge-telegram/SKILL.md" "$skill_dir/SKILL.md" || return 1
  download_repo_file "$AGENTBRIDGE_REPO" "${AGENTBRIDGE_GITHUB_TOKEN:-}" ".windsurf/scripts/agent_bridge_windsurf_hook.py" "$hook_script_path" || return 1
  download_repo_file "$AGENTBRIDGE_REPO" "${AGENTBRIDGE_GITHUB_TOKEN:-}" ".windsurf/hooks.json" "$hooks_file" || return 1

  chmod +x "$hook_script_path" || return 1

  python3 - "$hooks_file" "$hook_script_path" <<'PY'
import json
import sys
from pathlib import Path

hooks_path = Path(sys.argv[1])
hook_script_path = sys.argv[2]
data = json.loads(hooks_path.read_text(encoding="utf-8"))

for entries in (data.get("hooks") or {}).values():
    if not isinstance(entries, list):
        continue
    for item in entries:
        if isinstance(item, dict):
            item["command"] = f"python3 {hook_script_path}"

hooks_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

  add_note "installed windsurf bridge assets"
  return 0
}

update_windsurf() {
  load_shell_profiles
  get_env_status

  if [ ! -x /home/sw/agent-bridge ]; then
    RESULT_WINDSURF_STATUS="skipped_no_bridge"
    return
  fi

  if [ "$RESULT_ENV_STATUS" = "missing" ] || [ "$RESULT_ENV_STATUS" = "missing_token" ]; then
    RESULT_WINDSURF_STATUS="skipped_missing_env"
    return
  fi

  if [ "$RESULT_ENV_STATUS" = "invalid_token" ]; then
    RESULT_WINDSURF_STATUS="skipped_invalid_env"
    RESULT_MANUAL_ACTION_REQUIRED="yes"
    add_note "invalid TELEGRAM_BOT_TOKEN in /home/sw/.env"
    return
  fi

  if ! install_windsurf_package; then
    return
  fi

  if ! write_windsurf_mcp_configs; then
    return
  fi

  if ! install_windsurf_bridge_assets; then
    RESULT_WINDSURF_STATUS="windsurf_failed"
    RESULT_WORKFLOW_STATUS="windsurf_failed"
    add_note "failed to install windsurf bridge assets"
    return
  fi

  RESULT_WINDSURF_VERSION="$(parse_windsurf_version || true)"
  [ -n "$RESULT_WINDSURF_VERSION" ] || RESULT_WINDSURF_VERSION="unknown"
  RESULT_WINDSURF_STATUS="success"
}

update_codex() {
  local current_version=""

  if [ "$RESULT_ENV_STATUS" = "missing" ]; then
    RESULT_CODEX_STATUS="skipped_missing_env"
    return
  fi

  if [ ! -x /home/sw/agent-bridge ]; then
    RESULT_CODEX_STATUS="skipped_no_bridge"
    return
  fi

  load_shell_profiles

  if ! command -v npm >/dev/null 2>&1; then
    RESULT_CODEX_STATUS="codex_failed"
    RESULT_WORKFLOW_STATUS="codex_failed"
    add_note "npm not found for codex install"
    return
  fi

  ensure_latest_npm || true

  current_version="$(parse_codex_version || true)"
  if [ -n "$current_version" ] && version_eq "$current_version" "${CODEX_LATEST_VERSION:-}"; then
    RESULT_CODEX_STATUS="already_latest"
  else
    if npm i -g @openai/codex@latest; then
      hash -r || true
      RESULT_CODEX_STATUS="success"
    else
      RESULT_CODEX_STATUS="codex_failed"
      RESULT_WORKFLOW_STATUS="codex_failed"
      add_note "npm install @openai/codex@latest failed"
    fi
  fi

  write_codex_config
  RESULT_CODEX_VERSION="$(parse_codex_version || true)"
  [ -n "$RESULT_CODEX_VERSION" ] || RESULT_CODEX_VERSION="unknown"

  if [ "$RESULT_CODEX_STATUS" = "success" ] || [ "$RESULT_CODEX_STATUS" = "already_latest" ]; then
    if ! dpkg -s bubblewrap >/dev/null 2>&1; then
      log_info "bubblewrap not installed, installing"
      if ! wait_for_dpkg_lock 180; then
        RESULT_CODEX_STATUS="codex_failed"
        RESULT_WORKFLOW_STATUS="codex_failed"
        add_note "dpkg lock busy during bubblewrap install"
        return
      fi
      if ! sudo apt update || ! sudo apt install -y bubblewrap; then
        RESULT_CODEX_STATUS="codex_failed"
        RESULT_WORKFLOW_STATUS="codex_failed"
        add_note "bubblewrap apt update/install failed"
        return
      fi
    fi
  fi

  update_kilocode
}

update_kilocode() {
  local current_version=""
  local target_version="${KILOCODE_LATEST_VERSION:-unknown}"
  local install_spec="@kilocode/cli@latest"

  RESULT_KILOCODE_TARGET_VERSION="$target_version"

  if [ "$RESULT_ENV_STATUS" = "missing" ]; then
    RESULT_KILOCODE_STATUS="skipped_missing_env"
    return
  fi

  if [ ! -x /home/sw/agent-bridge ]; then
    RESULT_KILOCODE_STATUS="skipped_no_bridge"
    return
  fi

  load_shell_profiles

  if ! command -v npm >/dev/null 2>&1; then
    RESULT_KILOCODE_STATUS="kilocode_failed"
    RESULT_WORKFLOW_STATUS="kilocode_failed"
    add_note "npm not found for kilocode install"
    return
  fi

  ensure_latest_npm || true

  if [ -n "$target_version" ] && [ "$target_version" != "unknown" ]; then
    install_spec="@kilocode/cli@${target_version}"
  fi

  if kilo --version >/dev/null 2>&1; then
    current_version="$(parse_kilocode_version || true)"
    if [ -n "$current_version" ] && [ -n "$target_version" ] \
      && [ "$target_version" != "unknown" ] \
      && version_eq "$current_version" "$target_version"; then
      RESULT_KILOCODE_STATUS="already_latest"
    else
      if kilo upgrade; then
        hash -r || true
      else
        RESULT_KILOCODE_STATUS="kilocode_failed"
        RESULT_WORKFLOW_STATUS="kilocode_failed"
        add_note "kilo upgrade failed"
        return
      fi
    fi
  else
    if npm i -g "$install_spec"; then
      hash -r || true
    else
      RESULT_KILOCODE_STATUS="kilocode_failed"
      RESULT_WORKFLOW_STATUS="kilocode_failed"
      add_note "npm install ${install_spec} failed"
      return
    fi
  fi

  RESULT_KILOCODE_VERSION="$(parse_kilocode_version || true)"
  [ -n "$RESULT_KILOCODE_VERSION" ] || RESULT_KILOCODE_VERSION="unknown"

  if [ "$RESULT_KILOCODE_STATUS" = "already_latest" ]; then
    return
  fi

  if [ -n "$target_version" ] && [ "$target_version" != "unknown" ] \
    && [ -n "$RESULT_KILOCODE_VERSION" ] \
    && version_eq "$RESULT_KILOCODE_VERSION" "$target_version"; then
    RESULT_KILOCODE_STATUS="success"
  elif [ -n "$current_version" ] && [ -n "$RESULT_KILOCODE_VERSION" ] \
    && version_eq "$current_version" "$RESULT_KILOCODE_VERSION"; then
    RESULT_KILOCODE_STATUS="already_latest"
  else
    RESULT_KILOCODE_STATUS="success"
  fi
}

update_claude() {
  local current_version=""
  local should_update="no"

  RESULT_CLAUDE_TARGET_VERSION="${CLAUDE_LATEST_VERSION:-unknown}"

  if [ ! -f /home/sw/.env ]; then
    RESULT_CLAUDE_STATUS="skipped_missing_env"
    return
  fi

  load_shell_profiles
  current_version="$(parse_claude_version || true)"

  if [ -z "$current_version" ]; then
    if run_claude_installer; then
      hash -r || true
      if ! write_claude_shell_config; then
        RESULT_CLAUDE_STATUS="claude_failed"
        RESULT_WORKFLOW_STATUS="claude_failed"
        add_note "missing CLIPROXYAPI secrets for claude config"
        return
      fi
      load_shell_profiles
      RESULT_CLAUDE_STATUS="success"
    else
      RESULT_CLAUDE_STATUS="claude_failed"
      RESULT_WORKFLOW_STATUS="claude_failed"
      add_note "claude installer failed"
      return
    fi
  else
    if ! write_claude_shell_config; then
      RESULT_CLAUDE_STATUS="claude_failed"
      RESULT_WORKFLOW_STATUS="claude_failed"
      add_note "missing CLIPROXYAPI secrets for claude config"
      return
    fi

    if [ -z "$RESULT_CLAUDE_TARGET_VERSION" ] || [ "$RESULT_CLAUDE_TARGET_VERSION" = "unknown" ]; then
      should_update="yes"
      add_note "claude latest version unresolved, ran update"
    elif version_eq "$current_version" "$RESULT_CLAUDE_TARGET_VERSION"; then
      RESULT_CLAUDE_STATUS="already_latest"
      RESULT_CLAUDE_VERSION="$current_version"
      return
    elif version_gt "$RESULT_CLAUDE_TARGET_VERSION" "$current_version"; then
      should_update="yes"
    else
      RESULT_CLAUDE_STATUS="already_latest"
      RESULT_CLAUDE_VERSION="$current_version"
      add_note "local claude version ${current_version} already meets target ${RESULT_CLAUDE_TARGET_VERSION}"
      return
    fi

    if [ "$should_update" = "yes" ]; then
      if run_claude_installer; then
        hash -r || true
        RESULT_CLAUDE_STATUS="success"
      else
        RESULT_CLAUDE_STATUS="claude_failed"
        RESULT_WORKFLOW_STATUS="claude_failed"
        add_note "claude installer upgrade failed"
        return
      fi
    fi
  fi

  if ! write_claude_shell_config; then
    RESULT_CLAUDE_STATUS="claude_failed"
    RESULT_WORKFLOW_STATUS="claude_failed"
    add_note "missing CLIPROXYAPI secrets for claude config"
    return
  fi
  load_shell_profiles
  RESULT_CLAUDE_VERSION="$(parse_claude_version || true)"
  if [ -z "$RESULT_CLAUDE_VERSION" ]; then
    RESULT_CLAUDE_STATUS="claude_failed"
    RESULT_WORKFLOW_STATUS="claude_failed"
    RESULT_CLAUDE_VERSION="unknown"
    add_note "claude installed or updated but version check failed"
    return
  fi
}

on_exit() {
  local exit_code=$?
  cleanup_forbidden_bridge_files
  finalize_results "$exit_code"
  exit "$exit_code"
}

main() {
  trap on_exit EXIT
  load_shell_profiles
  repair_bridge_runtime_config
  get_env_status
  update_antigravity
  sync_gemini_md_template
  update_antigravity_cli
  update_bridge
  update_codex
  update_windsurf
  update_claude
  emit_results
}

main "$@"
