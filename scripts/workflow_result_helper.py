#!/usr/bin/env python3

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def write_json(path_str, payload):
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_write_result(argv):
    path, host, index, workflow_status, notes = argv
    write_json(
        path,
        {
            "host": host,
            "index": int(index),
            "workflow_status": workflow_status,
            "notes": notes,
        },
    )


def cmd_merge_remote_log(argv):
    remote_log, result_file, host, index, remote_rc = argv
    data = {
        "host": host,
        "index": int(index),
        "workflow_status": "success" if remote_rc == "0" else "remote_failed",
        "notes": "",
    }
    for line in Path(remote_log).read_text().splitlines():
        if not line.startswith("RESULT_") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key[7:].lower()] = value
    if remote_rc != "0" and data.get("workflow_status") == "success":
        data["workflow_status"] = "remote_failed"
    write_json(result_file, data)


def cmd_enforce_fatal(argv):
    (result_file,) = argv
    result = json.loads(Path(result_file).read_text())
    fatal_statuses = {
        "remote_failed",
        "tunnel_failed",
        "whitelist_failed",
        "bridge_failed",
        "antigravity_failed",
        "antigravity_cli_failed",
        "codex_failed",
        "claude_failed",
    }
    if result.get("workflow_status", "unknown") in fatal_statuses:
        raise SystemExit(1)


def cmd_build_summary(argv):
    all_results_dir, host_count, output_file = argv
    base = Path(all_results_dir)
    results = []
    if base.exists():
        for path in sorted(base.glob("result-*/host_*.json")):
            results.append(json.loads(path.read_text()))

    def host_label(item):
        index = item.get("index", "?")
        host = item.get("host", "unknown")
        return f"{host}#{index}"

    def host_lines(lines, limit=10):
        labels = list(lines)
        if not labels:
            return "无"
        if len(labels) <= limit:
            return "\n".join(labels)
        return "\n".join(labels[:limit]) + f"\n等{len(labels)}台"

    def is_updated(item):
        return any(
            (
                item.get("antigravity_status") == "success",
                item.get("antigravity_cli_status") == "success",
                item.get("bridge_status") in {"deployed_started", "files_refreshed_no_env"},
                item.get("codex_status") == "success",
                item.get("claude_status") == "success",
            )
        )

    def skip_reason(item):
        env_status = item.get("env_status", "unknown")
        bridge_status = item.get("bridge_status", "unknown")
        codex_status = item.get("codex_status", "unknown")
        antigravity_cli_status = item.get("antigravity_cli_status", "unknown")

        if env_status in {"missing", "missing_token"}:
            return ".env缺失/缺token"
        if env_status == "invalid_token":
            return "TELEGRAM_BOT_TOKEN异常"
        if bridge_status == "skipped_no_install" and codex_status == "skipped_no_bridge":
            return "未安装Bridge"
        if bridge_status in {"skipped_already_latest", "skipped_already_latest_no_env"}:
            return "Bridge已是最新"
        if codex_status == "already_latest":
            return "Codex已是最新"
        if item.get("claude_status") == "already_latest":
            return "Claude已是最新"
        if antigravity_cli_status == "already_latest":
            return "CLI已是最新"
        if bridge_status.startswith("skipped_"):
            return bridge_status
        if codex_status.startswith("skipped_"):
            return codex_status
        if str(item.get("claude_status", "")).startswith("skipped_"):
            return item.get("claude_status")
        return "无变更"

    def failure_reason(item):
        workflow_status = item.get("workflow_status", "unknown")
        notes = item.get("notes", "").strip()
        labels = {
            "remote_failed": "远程执行失败",
            "tunnel_failed": "隧道失败",
            "whitelist_failed": "白名单失败",
            "bridge_failed": "Bridge失败",
            "antigravity_failed": "Antigravity失败",
            "antigravity_cli_failed": "CLI失败",
            "codex_failed": "Codex失败",
            "claude_failed": "Claude失败",
        }
        reason = labels.get(workflow_status, workflow_status)
        if notes:
            return f"{reason} | {notes}"
        return reason

    updated_hosts = []
    skipped_lines = []
    failed_lines = []

    for item in results:
        workflow_status = item.get("workflow_status", "unknown")

        if workflow_status == "success":
            if is_updated(item):
                updated_hosts.append(item)
            else:
                skipped_lines.append(f"{host_label(item)} | {skip_reason(item)}")
        else:
            failed_lines.append(f"{host_label(item)} | {failure_reason(item)}")

    timestamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    header = (
        "<b>Agent Stack 更新报告</b>\n"
        f"🕐 {timestamp} (北京时间)\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    summary_lines = [
        f"总数：{host_count}     更新：{len(updated_hosts)}",
        "",
        f"跳过：{len(skipped_lines)}",
    ]
    if skipped_lines:
        summary_lines.append(host_lines(skipped_lines))
    summary_lines.extend(["", f"失败：{len(failed_lines)}"])
    if failed_lines:
        summary_lines.append(host_lines(failed_lines))

    Path(output_file).write_text(header + "\n" + "\n".join(summary_lines))


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: workflow_result_helper.py <command> ...")

    command = sys.argv[1]
    argv = sys.argv[2:]

    if command == "write-result":
        cmd_write_result(argv)
    elif command == "merge-remote-log":
        cmd_merge_remote_log(argv)
    elif command == "enforce-fatal":
        cmd_enforce_fatal(argv)
    elif command == "build-summary":
        cmd_build_summary(argv)
    else:
        raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    main()
