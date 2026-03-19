#!/usr/bin/env bash

set -uo pipefail

ANTIGRAVITY_REPO="suwei8/antigravity-cli"
AGENTBRIDGE_REPO="suwei8/agent-bridge"
AGENTBRIDGE_ASSET_PRIMARY="agent-bridge"
AGENTBRIDGE_ASSET_FALLBACK="agent-bridge-linux-aarch64-ubuntu20.04"

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

RESULT_CODEX_STATUS="skipped_no_bridge"
RESULT_CODEX_VERSION="N/A"
RESULT_CODEX_TARGET_VERSION="${CODEX_LATEST_VERSION:-unknown}"

BRIDGE_RELEASE_JSON_CACHE=""

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
  echo "RESULT_CODEX_STATUS=$(sanitize_value "$RESULT_CODEX_STATUS")"
  echo "RESULT_CODEX_VERSION=$(sanitize_value "$RESULT_CODEX_VERSION")"
  echo "RESULT_CODEX_TARGET_VERSION=$(sanitize_value "$RESULT_CODEX_TARGET_VERSION")"
  echo "RESULT_NOTES=$(sanitize_value "$RESULT_NOTES")"
}

load_shell_profiles() {
  set +u
  [ -f /etc/profile ] && . /etc/profile || true
  [ -f ~/.profile ] && . ~/.profile || true
  [ -f ~/.bashrc ] && . ~/.bashrc || true
  [ -f ~/.nvm/nvm.sh ] && . ~/.nvm/nvm.sh || true
  set -u
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
  rm -f \
    /home/sw/manage.sh.1 \
    /home/sw/manage.sh.bak.20260317-165803 \
    /home/sw/antigravity-bridge.bak.20260317-165806
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

  resolve_bridge_release || return 1
  release_json="$BRIDGE_RELEASE_JSON_CACHE"

  download_repo_file "$AGENTBRIDGE_REPO" "${AGENTBRIDGE_GITHUB_TOKEN:-}" "manage.sh" "$tmp_manage" || return 1
  if ! download_release_asset "$AGENTBRIDGE_REPO" "${AGENTBRIDGE_GITHUB_TOKEN:-}" "$release_json" "$AGENTBRIDGE_ASSET_PRIMARY" "$tmp_binary"; then
    download_release_asset "$AGENTBRIDGE_REPO" "${AGENTBRIDGE_GITHUB_TOKEN:-}" "$release_json" "$AGENTBRIDGE_ASSET_FALLBACK" "$tmp_binary" || return 1
  fi

  chmod +x "$tmp_manage" "$tmp_binary"
  mv -f "$tmp_manage" /home/sw/manage.sh
  mv -f "$tmp_binary" /home/sw/agent-bridge
  rm -rf /home/sw/antigravity-Bridge
  rm -f /home/sw/antigravity-bridge /home/sw/.antigravity-release-tag
  record_bridge_version "$RESULT_BRIDGE_RELEASE_TAG"
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

  if sudo apt-get -o DPkg::Lock::Timeout=60 update -qq && \
     sudo apt-get -o DPkg::Lock::Timeout=60 install -y -qq antigravity; then
    RESULT_ANTIGRAVITY_STATUS="success"
  else
    RESULT_ANTIGRAVITY_STATUS="antigravity_failed"
    RESULT_WORKFLOW_STATUS="antigravity_failed"
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
    record_bridge_version "$RESULT_BRIDGE_RELEASE_TAG"
    RESULT_BRIDGE_STATUS="skipped_already_latest"
    return
  fi

  if [ -x /home/sw/manage.sh ]; then
    /home/sw/manage.sh stop || true
  fi
  kill_named_processes "bridge"

  rm -f /home/sw/manage.sh
  if ! download_repo_file "$AGENTBRIDGE_REPO" "${AGENTBRIDGE_GITHUB_TOKEN:-}" "manage.sh" /home/sw/manage.sh; then
    RESULT_BRIDGE_STATUS="bridge_failed"
    RESULT_WORKFLOW_STATUS="bridge_failed"
    add_note "failed to download AgentBridge manage.sh"
    return
  fi
  chmod +x /home/sw/manage.sh

  rm -rf /home/sw/antigravity-Bridge
  rm -f /home/sw/antigravity-bridge /home/sw/.antigravity-release-tag

  if /home/sw/manage.sh deploy && /home/sw/manage.sh start; then
    if ! ensure_agentbridge_effective; then
      RESULT_BRIDGE_STATUS="bridge_failed"
      RESULT_WORKFLOW_STATUS="bridge_failed"
      add_note "failed to normalize bridge processes"
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

write_codex_config() {
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
base_url = "${CLIPROXYAPI_BASE_URL}"
wire_api = "responses"

[projects."/home/sw"]
trust_level = "trusted"

[projects."/home/sw/dev_root"]
trust_level = "trusted"
EOF
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
      return
    fi
  fi

  write_codex_config
  RESULT_CODEX_VERSION="$(parse_codex_version || true)"
  [ -n "$RESULT_CODEX_VERSION" ] || RESULT_CODEX_VERSION="unknown"
}

main() {
  load_shell_profiles
  repair_bridge_runtime_config
  get_env_status
  update_antigravity
  update_antigravity_cli
  update_bridge
  update_codex
  emit_results
}

main "$@"
