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

    def host_label(item):
        index = item.get("index", "?")
        host = item.get("host", "unknown")
        return f"{host}#{index}"

    def host_lines(items, limit=10):
        labels = [host_label(item) for item in items]
        if not labels:
            return "无"
        if len(labels) <= limit:
            return "\n".join(labels)
        return "\n".join(labels[:limit]) + f"\n等{len(labels)}台"

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
    success_hosts = []
    manual_hosts = []
    fatal_hosts = []
    bridge_file_only_hosts = []
    bridge_skipped_hosts = []
    env_missing_hosts = []
    env_invalid_hosts = []
    codex_failed_hosts = []
    manual_lines = []
    fatal_lines = []
    bridge_skip_reasons = {}
    codex_skip_reasons = {}

    for item in results:
        workflow_status = item.get("workflow_status", "unknown")
        env_status = item.get("env_status", "unknown")
        bridge_status = item.get("bridge_status", "unknown")
        codex_status = item.get("codex_status", "unknown")
        host = item.get("host", "unknown")
        notes = item.get("notes", "").strip()

        if workflow_status == "success":
            counts["success"] += 1
            success_hosts.append(item)
        else:
            counts["fatal"] += 1
            fatal_hosts.append(item)
            fatal_lines.append(f"❌ <b>{host}</b> | {workflow_status}")

        if item.get("manual_action_required", "no") == "yes":
            counts["manual"] += 1
            manual_hosts.append(item)
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
            env_missing_hosts.append(item)
        if env_status == "invalid_token":
            counts["env_invalid"] += 1
            env_invalid_hosts.append(item)

        if bridge_status == "deployed_started":
            counts["bridge_deployed"] += 1
        elif bridge_status == "files_refreshed_no_env":
            counts["bridge_files_only"] += 1
            bridge_file_only_hosts.append(item)
        elif bridge_status.startswith("skipped_"):
            counts["bridge_skipped"] += 1
            bridge_skipped_hosts.append(item)
            bridge_skip_reasons[bridge_status] = bridge_skip_reasons.get(bridge_status, 0) + 1

        if codex_status in ("success", "already_latest"):
            counts["codex_success"] += 1
        elif codex_status.startswith("skipped_"):
            counts["codex_skipped"] += 1
            codex_skip_reasons[codex_status] = codex_skip_reasons.get(codex_status, 0) + 1
        elif codex_status.endswith("failed") or codex_status.startswith("failed"):
            counts["codex_failed"] += 1
            codex_failed_hosts.append(item)

    def summarize_reason_counts(reason_counts):
        if not reason_counts:
            return ""
        parts = []
        reason_labels = {
            "skipped_no_install": "未安装",
            "skipped_missing_env": ".env缺失",
            "skipped_missing_env_active": ".env缺失但服务存活",
            "skipped_invalid_env": "Token异常",
            "skipped_already_latest": "已是最新",
            "skipped_already_latest_no_env": "已是最新且无.env",
            "skipped_no_bridge": "未安装Bridge",
        }
        for reason, count in sorted(reason_counts.items()):
            parts.append(f"{reason_labels.get(reason, reason)} {count}")
        return "、".join(parts)

    timestamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    header = (
        "<b>Agent Stack 更新报告</b>\n"
        f"🕐 {timestamp} (北京时间)\n"
        f"🖥️ 目标主机: {host_count}\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    summary = (
        "<b>总览</b>\n"
        f"✅ 成功 {counts['success']} | ⚠️ 人工处理 {counts['manual']} | ❌ 致命失败 {counts['fatal']}\n"
        f"🌉 Bridge: 已部署 {counts['bridge_deployed']} | 仅替换文件 {counts['bridge_files_only']} | 跳过 {counts['bridge_skipped']}\n"
        f"🤖 Codex: 成功/已最新 {counts['codex_success']} | 跳过 {counts['codex_skipped']} | 失败 {counts['codex_failed']}\n"
        f"📭 环境: .env缺失/缺token {counts['env_missing']} | Token异常 {counts['env_invalid']}"
    )
    details = []
    if success_hosts:
        details.append(f"<b>执行结果</b>\n成功主机: {counts['success']}/{host_count} 台")
    if fatal_lines:
        details.append("<b>致命失败</b>\n" + "\n".join(fatal_lines[:20]))
    if manual_lines:
        details.append("<b>需人工处理</b>\n" + "\n".join(manual_lines[:20]))
    if bridge_file_only_hosts:
        details.append("<b>仅替换文件</b>\n" + host_lines(bridge_file_only_hosts))
    if bridge_skipped_hosts:
        bridge_skip_summary = summarize_reason_counts(bridge_skip_reasons)
        if counts["bridge_skipped"] == len(results):
            line = f"Bridge 本轮全部跳过: {counts['bridge_skipped']} 台"
            if bridge_skip_summary:
                line += f"\n原因: {bridge_skip_summary}"
            details.append("<b>Bridge 跳过</b>\n" + line)
        else:
            line = f"跳过主机: {counts['bridge_skipped']} 台"
            if bridge_skip_summary:
                line += f"\n原因: {bridge_skip_summary}"
            line += "\n" + host_lines(bridge_skipped_hosts)
            details.append("<b>Bridge 跳过</b>\n" + line)
    if env_missing_hosts:
        details.append("<b>.env缺失/缺token</b>\n" + host_lines(env_missing_hosts))
    if env_invalid_hosts:
        details.append("<b>TELEGRAM_BOT_TOKEN异常</b>\n" + host_lines(env_invalid_hosts))
    if codex_failed_hosts:
        details.append("<b>Codex失败</b>\n" + host_lines(codex_failed_hosts))
    elif counts["codex_skipped"] > 0:
        codex_skip_summary = summarize_reason_counts(codex_skip_reasons)
        line = f"Codex 跳过: {counts['codex_skipped']} 台"
        if codex_skip_summary:
            line += f"\n原因: {codex_skip_summary}"
        details.append("<b>Codex 跳过</b>\n" + line)
    if not details:
        details.append("本次无异常主机")

    Path(output_file).write_text(header + "\n" + summary + "\n\n" + "\n\n".join(details))


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
