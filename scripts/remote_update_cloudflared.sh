#!/usr/bin/env bash
# cloudflared 远程升级辅助脚本 —— 在目标主机上执行。
#
# 模式:
#   check   检查当前版本; 已最新/未安装则直接输出 RESULT_* 退出;
#           落后则通过 systemd-run 分离单元启动 `apply`。
#           注意: SSH 走 cloudflared 隧道, 升级重启服务必然断开本会话,
#           所以升级绝不能在前台 SSH 会话内执行。
#   apply   实际执行升级 (systemd-run 单元内以 root 运行)。
#           dpkg 安装的走 apt --only-upgrade (缺 repo 自动补齐);
#           手工二进制安装的走 GitHub releases 下载替换。
#           完成后 try-restart cloudflared 服务并写 /tmp/cfup_result.env。
#   verify  升级后核验版本与服务状态, 输出 RESULT_*。
#
# 环境变量: TARGET_VERSION (目标版本, 如 2025.11.1); SSH_PASSWORD 仅作 sudo -S 兜底。

set -uo pipefail

MODE="${1:-check}"
RESULT_FILE="/tmp/cfup_result.env"

run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif sudo -n true 2>/dev/null; then
    sudo "$@"
  else
    printf '%s\n' "${SSH_PASSWORD:-}" | sudo -S -k "$@"
  fi
}

current_version() {
  cloudflared --version 2>/dev/null | awk '{print $3}'
}

is_dpkg() {
  dpkg-query -W -f='${Status}' cloudflared 2>/dev/null | grep -q 'install ok installed'
}

ver_ge() {
  # $1 >= $2 (sort -V 版本比较); $1 为空视为不满足
  [ -n "$1" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n1)" = "$2" ]
}

emit() {
  local v
  v="$(printf '%s' "$2" | tr -d '\r\n\t' | tr ' ' '_')"
  echo "RESULT_$1=${v:-unknown}"
}

ensure_apt_repo() {
  [ -f /etc/apt/sources.list.d/cloudflared.list ] && return 0
  if ! command -v curl >/dev/null 2>&1; then
    run_root apt-get update -qq || true
    run_root apt-get install -y -qq curl ca-certificates || true
  fi
  local tmp_key tmp_list
  tmp_key="$(mktemp)"; tmp_list="$(mktemp)"
  curl -fsSL https://pkg.cloudflare.com/cloudflare-public-v2.gpg -o "$tmp_key" || { rm -f "$tmp_key" "$tmp_list"; return 1; }
  run_root install -D -m 644 "$tmp_key" /usr/share/keyrings/cloudflare-public-v2.gpg || { rm -f "$tmp_key" "$tmp_list"; return 1; }
  printf '%s\n' 'deb [signed-by=/usr/share/keyrings/cloudflare-public-v2.gpg] https://pkg.cloudflare.com/cloudflared any main' > "$tmp_list"
  run_root install -D -m 644 "$tmp_list" /etc/apt/sources.list.d/cloudflared.list || { rm -f "$tmp_key" "$tmp_list"; return 1; }
  rm -f "$tmp_key" "$tmp_list"
}

# 列出运行中的 cloudflared 进程: 每行 "pid|ver|age_s|owner_unit"
# /proc/<pid>/exe 对旧(已替换)二进制仍可执行拿到旧版本号;
# 需 root 才能读他人进程 exe -> run_root。owner 由 cgroup 末段解析。
list_cloudflared_procs() {
  local p pv p_age cgrp unit
  for p in $(pgrep -x cloudflared 2>/dev/null); do
    pv="$(run_root /proc/"$p"/exe --version 2>/dev/null | awk '{print $3}')"
    p_age="$(ps -o etimes= -p "$p" 2>/dev/null | tr -d ' ')"
    cgrp="$(awk -F: '{print $NF}' "/proc/$p/cgroup" 2>/dev/null)"
    unit="${cgrp##*/}"
    echo "${p}|${pv:-?}|${p_age:-0}|${unit:-?}"
  done
}

restart_service() {
  local svc="none" extra="" stray="" p pv p_age unit
  if run_root systemctl cat cloudflared.service >/dev/null 2>&1; then
    run_root systemctl try-restart cloudflared.service || true
    sleep 3
    svc="$(run_root systemctl is-active cloudflared.service 2>/dev/null || echo unknown)"
  fi
  # 隧道可能跑在别的单元(cloudflared@x.service 等): 按进程 cgroup 反查
  # 所属单元逐个重启; docker/裸进程无法重启 -> 记录 stray。
  while IFS='|' read -r p pv p_age unit; do
    case "$unit" in
      cloudflared.service) : ;;  # 上面已处理
      *.service)
        run_root systemctl try-restart "$unit" || true
        extra="$extra $unit" ;;
      *) stray="$stray ${p}(${unit})" ;;
    esac
  done < <(list_cloudflared_procs)
  [ -n "$extra" ] && svc="${svc} restarted_extra:$(echo "$extra" | xargs | tr ' ' ',')"
  [ -n "$stray" ] && svc="${svc} stray_pids:$(echo "$stray" | xargs | tr ' ' ',')"
  echo "$svc"
}

check_mode() {
  if [ "$(uname -s 2>/dev/null)" != "Linux" ]; then
    emit WORKFLOW_STATUS unsupported_os
    emit BEFORE_VERSION none
    emit TARGET_VERSION "${TARGET_VERSION:-unknown}"
    return 0
  fi

  if ! command -v cloudflared >/dev/null 2>&1; then
    emit WORKFLOW_STATUS not_installed
    emit BEFORE_VERSION none
    emit TARGET_VERSION "${TARGET_VERSION:-unknown}"
    emit INSTALL_TYPE none
    return 0
  fi

  local before install_type
  before="$(current_version)"
  if is_dpkg; then install_type="dpkg"; else install_type="binary"; fi

  emit BEFORE_VERSION "${before:-unknown}"
  emit TARGET_VERSION "${TARGET_VERSION:-unknown}"
  emit INSTALL_TYPE "$install_type"

  if [ -n "${TARGET_VERSION:-}" ] && ver_ge "${before:-}" "$TARGET_VERSION"; then
    # 二进制已最新,但"正在运行的进程"可能还是旧版: 隧道不归
    # cloudflared.service 管时,apt postinst/try-restart 碰不到它,
    # CF 面板仍显示旧版本。扫描运行进程, 归 systemd 单元的直接重启
    # (新二进制即生效) -> restart_launched,走工作流的 verify 通道;
    # docker/裸进程 -> stale_process 交人工。
    local stale=0 units="" strays="" rvers=""
    while IFS='|' read -r p pv p_age unit; do
      rvers="$rvers ${p}:${pv}(${p_age}s@${unit})"
      if ! ver_ge "${pv:-}" "$TARGET_VERSION" && [ "${p_age:-9999}" -gt 90 ] 2>/dev/null; then
        stale=$((stale+1))
        case "$unit" in
          *.service) units="$units $unit" ;;
          *) strays="$strays ${p}(${unit})" ;;
        esac
      fi
    done < <(list_cloudflared_procs)
    rvers="$(echo "$rvers" | xargs)"; strays="$(echo "$strays" | xargs)"
    emit RUNNING_PROCS "${rvers:-none}"
    emit STALE_PROCS "$stale"
    if [ "$stale" -eq 0 ]; then
      emit WORKFLOW_STATUS already_latest
      return 0
    fi
    units="$(echo "$units" | xargs)"
    emit STRAY_PIDS "${strays:-none}"
    if [ -n "$units" ]; then
      # 先 emit 再重启: 若该单元正承载本 SSH 会话, restart 会立即断连,
      # 结果行必须在此之前已送达。断连属预期, 工作流按 restart_launched 走 verify。
      emit WORKFLOW_STATUS restart_launched
      for u in $units; do
        run_root systemctl try-restart "$u" || true
      done
    else
      emit WORKFLOW_STATUS stale_process
    fi
    return 0
  fi

  # 分离执行升级: 升级重启 cloudflared 会断开本 SSH 会话(走隧道),
  # 必须放进独立 systemd 单元里跑。
  if run_root systemd-run --unit="cfup-$(date +%s)" --description="cloudflared upgrade" bash "$0" apply; then
    emit WORKFLOW_STATUS upgrade_launched
  else
    emit WORKFLOW_STATUS launch_failed
  fi
}

apply_mode() {
  {
    echo "STATUS=running"
    echo "STARTED=$(date -u +%FT%TZ)"
  } | run_root tee "$RESULT_FILE" >/dev/null

  local status="failed" method="none" svc="none" after="unknown"

  if is_dpkg; then
    method="apt"
    ensure_apt_repo || true
    # 只刷新 cloudflared 源索引: 有的主机源列表本身带病(如 ports 镜像上
    # 挂了 binary-amd64 外来架构条目), 全量 apt-get update 会 404 返回非零,
    # 但 cloudflared 源其实是好的, 不应被其它源拖死。
    run_root apt-get update \
      -o Dir::Etc::sourcelist="sources.list.d/cloudflared.list" \
      -o Dir::Etc::sourceparts="-" \
      -o APT::Get::List-Cleanup="0" -qq \
      || run_root apt-get update -qq || true
    if run_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --only-upgrade cloudflared; then
      status="done"
    else
      status="apt_failed"
    fi
  else
    local bin arch
    bin="$(command -v cloudflared || true)"
    case "$(uname -m)" in
      x86_64|amd64) arch="amd64" ;;
      aarch64|arm64) arch="arm64" ;;
      *) arch="" ;;
    esac
    if [ -n "$bin" ] && [ -n "$arch" ]; then
      method="binary"
      if curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${arch}" -o /tmp/cfup.new \
         && /tmp/cfup.new --version >/dev/null 2>&1; then
        if run_root install -m 0755 /tmp/cfup.new "$bin"; then
          status="done"
        else
          status="install_failed"
        fi
      else
        status="download_failed"
      fi
      rm -f /tmp/cfup.new
    else
      status="not_installed"
    fi
  fi

  if [ "$status" = "done" ]; then
    svc="$(restart_service)"
  fi
  after="$(current_version)"

  {
    echo "STATUS=${status}"
    echo "AFTER_VERSION=${after:-unknown}"
    echo "METHOD=${method}"
    echo "SERVICE=${svc:-none}"
    echo "FINISHED=$(date -u +%FT%TZ)"
  } | run_root tee "$RESULT_FILE" >/dev/null
}

verify_mode() {
  local now svc st aft meth
  now="$(current_version)"
  if run_root systemctl cat cloudflared.service >/dev/null 2>&1; then
    svc="$(run_root systemctl is-active cloudflared.service 2>/dev/null || echo unknown)"
  else
    svc="none"
  fi

  st="missing"; aft=""; meth="unknown"
  if [ -f "$RESULT_FILE" ]; then
    st="$(grep -E '^STATUS=' "$RESULT_FILE" | tail -1 | cut -d= -f2-)"
    aft="$(grep -E '^AFTER_VERSION=' "$RESULT_FILE" | tail -1 | cut -d= -f2-)"
    meth="$(grep -E '^METHOD=' "$RESULT_FILE" | tail -1 | cut -d= -f2-)"
    st="${st:-running}"
  fi

  # apply 失败时把最近一次 cfup-* 单元的 journal 打出来(错误细节都在里面)
  if [ "$st" != "done" ] && [ "$st" != "running" ]; then
    unit="$(run_root journalctl -F _SYSTEMD_UNIT 2>/dev/null | grep '^cfup-' | sort | tail -1)"
    if [ -n "$unit" ]; then
      echo "----- journal $unit (tail 50) -----"
      run_root journalctl -u "$unit" --no-pager -n 50 2>/dev/null | tail -50
      echo "----- end journal -----"
    fi
  fi

  # 检查"正在运行的进程"版本: 二进制升级了但旧进程没重启,
  # CF 面板仍显示旧版本(隧道由其它单元/裸进程/docker 提供)。
  # etimes>90s 才算 stale, 避开服务重启瞬间旧 pid 未退出的误判。
  local stale=0 running_vers=""
  while IFS='|' read -r p pv p_age unit; do
    running_vers="$running_vers ${p}:${pv}(${p_age}s@${unit})"
    if [ -n "${TARGET_VERSION:-}" ] && ! ver_ge "${pv:-}" "$TARGET_VERSION" \
       && [ "${p_age:-9999}" -gt 90 ] 2>/dev/null; then
      stale=$((stale+1))
    fi
  done < <(list_cloudflared_procs)
  running_vers="$(echo "$running_vers" | xargs)"

  emit AFTER_VERSION "${now:-${aft:-unknown}}"
  emit APPLY_STATUS "${st:-missing}"
  emit APPLY_METHOD "${meth:-unknown}"
  emit SERVICE_ACTIVE "${svc:-none}"
  emit RUNNING_PROCS "${running_vers:-none}"
  emit STALE_PROCS "$stale"

  if [ "$stale" -gt 0 ]; then
    emit WORKFLOW_STATUS stale_process
  elif [ -n "${TARGET_VERSION:-}" ] && ver_ge "${now:-}" "$TARGET_VERSION"; then
    emit WORKFLOW_STATUS success
  elif [ "$st" = "running" ]; then
    emit WORKFLOW_STATUS verify_pending
  else
    emit WORKFLOW_STATUS verify_failed
  fi
}

case "$MODE" in
  check)  check_mode ;;
  apply)  apply_mode ;;
  verify) verify_mode ;;
  *) echo "unknown mode: $MODE" >&2; exit 2 ;;
esac
