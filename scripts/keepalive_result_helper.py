#!/usr/bin/env python3

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def read_json(path_str):
    return json.loads(Path(path_str).read_text())


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


def cmd_update_runner_fields(argv):
    (
        result_file,
        duration_seconds,
        cpu_before,
        mem_before,
        cpu_after,
        mem_after,
        jitter_seconds,
    ) = argv
    data = read_json(result_file)
    data.update(
        {
            "duration_seconds": int(duration_seconds),
            "cpu_before": cpu_before,
            "mem_before": mem_before,
            "cpu_after": cpu_after,
            "mem_after": mem_after,
            "jitter_seconds": int(jitter_seconds),
        }
    )
    write_json(result_file, data)


def cmd_enforce_fatal(argv):
    (result_file,) = argv
    result = read_json(result_file)
    fatal_statuses = {
        "remote_failed",
        "tunnel_failed",
        "repo_sync_failed",
        "keepalive_failed",
        "security_blocked",
        "prediction_missing",
        "prediction_invalid",
    }
    if result.get("workflow_status", "unknown") in fatal_statuses:
        raise SystemExit(1)


def format_duration(seconds):
    if seconds <= 0:
        return "0秒"
    minutes, remain = divmod(seconds, 60)
    if minutes <= 0:
        return f"{remain}秒"
    return f"{minutes}分{remain}秒"


def cmd_build_summary(argv):
    all_results_dir, host_count, output_file = argv
    base = Path(all_results_dir)
    results = []
    if base.exists():
        for path in sorted(base.glob("result-*/host_*.json")):
            results.append(json.loads(path.read_text()))

    def host_label(item):
        return f"{item.get('host', 'unknown')}#{item.get('index', '?')}"

    def join_hosts(items):
        labels = [host_label(item) for item in items]
        if not labels:
            return "无"
        if len(labels) <= 8:
            return "、".join(labels)
        return "、".join(labels[:8]) + f" 等{len(labels)}台"

    success_hosts = []
    fatal_lines = []
    warning_lines = []

    for item in results:
        workflow_status = item.get("workflow_status", "unknown")
        prediction_status = item.get("prediction_status", "unknown")
        notes = item.get("notes", "").strip()
        if workflow_status == "success":
            success_hosts.append(item)
            if prediction_status != "present":
                warning_lines.append(
                    f"⚠️ <b>{item.get('host', 'unknown')}</b> | prediction={prediction_status}"
                    + (f" | {notes}" if notes else "")
                )
        else:
            detail = f"❌ <b>{item.get('host', 'unknown')}</b> | {workflow_status}"
            if notes:
                detail += f" | {notes}"
            fatal_lines.append(detail)

    timestamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    header = (
        "<b>ARM64 OCI 保活报告 V2</b>\n"
        f"🕐 {timestamp} (北京时间)\n"
        f"🖥️ 目标主机: {host_count}\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    summary = (
        f"\n✅ 成功: {len(success_hosts)}"
        f"\n⚠️ 警告: {len(warning_lines)}"
        f"\n❌ 失败: {len(fatal_lines)}"
    )

    details = []
    if success_hosts:
        success_lines = []
        for item in success_hosts[:20]:
            duration = format_duration(int(item.get("duration_seconds", 0)))
            cpu_after = item.get("cpu_after", "N/A")
            mem_after = item.get("mem_after", "N/A")
            success_lines.append(
                f"{host_label(item)} | {duration} | CPU {cpu_after}% | MEM {mem_after}%"
            )
        details.append("成功主机:\n" + "\n".join(success_lines))
    if fatal_lines:
        details.append("失败主机:\n" + "\n".join(fatal_lines[:20]))
    if warning_lines:
        details.append("警告主机:\n" + "\n".join(warning_lines[:20]))
    if not details:
        details.append("本次无执行数据")

    Path(output_file).write_text(header + "\n" + "\n\n".join(details) + "\n" + summary)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: keepalive_result_helper.py <command> ...")

    command = sys.argv[1]
    argv = sys.argv[2:]

    if command == "write-result":
        cmd_write_result(argv)
    elif command == "merge-remote-log":
        cmd_merge_remote_log(argv)
    elif command == "update-runner-fields":
        cmd_update_runner_fields(argv)
    elif command == "enforce-fatal":
        cmd_enforce_fatal(argv)
    elif command == "build-summary":
        cmd_build_summary(argv)
    else:
        raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    main()
