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

    counts = {
        "success": 0,
        "manual": 0,
        "fatal": 0,
        "env_missing": 0,
        "env_invalid": 0,
        "bridge_deployed": 0,
        "bridge_files_only": 0,
        "bridge_skipped": 0,
        "codex_success": 0,
        "codex_skipped": 0,
        "codex_failed": 0,
    }
    manual_lines = []
    fatal_lines = []

    for item in results:
        workflow_status = item.get("workflow_status", "unknown")
        env_status = item.get("env_status", "unknown")
        bridge_status = item.get("bridge_status", "unknown")
        codex_status = item.get("codex_status", "unknown")
        host = item.get("host", "unknown")
        notes = item.get("notes", "").strip()

        if workflow_status == "success":
            counts["success"] += 1
        else:
            counts["fatal"] += 1
            fatal_lines.append(f"❌ <b>{host}</b> | {workflow_status}")

        if item.get("manual_action_required", "no") == "yes":
            counts["manual"] += 1
            extra = []
            if env_status not in ("ok", "unknown"):
                extra.append(f"env={env_status}")
            if bridge_status not in ("unknown", "skipped_no_install"):
                extra.append(f"bridge={bridge_status}")
            if notes:
                extra.append(notes)
            manual_lines.append(f"⚠️ <b>{host}</b> | " + " | ".join(extra or ["manual check"]))

        if env_status in ("missing", "missing_token"):
            counts["env_missing"] += 1
        if env_status == "invalid_token":
            counts["env_invalid"] += 1

        if bridge_status == "deployed_started":
            counts["bridge_deployed"] += 1
        elif bridge_status == "files_refreshed_no_env":
            counts["bridge_files_only"] += 1
        elif bridge_status.startswith("skipped_"):
            counts["bridge_skipped"] += 1

        if codex_status in ("success", "already_latest"):
            counts["codex_success"] += 1
        elif codex_status.startswith("skipped_"):
            counts["codex_skipped"] += 1
        elif codex_status.endswith("failed") or codex_status.startswith("failed"):
            counts["codex_failed"] += 1

    timestamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    header = (
        "<b>Agent Stack 更新报告</b>\n"
        f"🕐 {timestamp} (北京时间)\n"
        f"🖥️ 目标主机: {host_count}\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    summary = (
        f"\n✅ 成功: {counts['success']}"
        f"\n⚠️ 需人工处理: {counts['manual']}"
        f"\n❌ 致命失败: {counts['fatal']}"
        f"\n🌉 AgentBridge已部署启动: {counts['bridge_deployed']}"
        f"\n📦 仅替换文件: {counts['bridge_files_only']}"
        f"\n⏭️ Bridge跳过: {counts['bridge_skipped']}"
        f"\n🤖 Codex成功/已最新: {counts['codex_success']}"
        f"\n⏭️ Codex跳过: {counts['codex_skipped']}"
        f"\n❌ Codex失败: {counts['codex_failed']}"
        f"\n📭 .env缺失/缺token: {counts['env_missing']}"
        f"\n🚨 TELEGRAM_BOT_TOKEN异常: {counts['env_invalid']}"
    )
    details = []
    if fatal_lines:
        details.append("异常主机:\n" + "\n".join(fatal_lines[:20]))
    if manual_lines:
        details.append("人工处理主机:\n" + "\n".join(manual_lines[:20]))
    if not details:
        details.append("本次无异常主机")

    Path(output_file).write_text(header + "\n" + "\n\n".join(details) + "\n" + summary)


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
