#!/usr/bin/env python3

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def read_json(path_str):
    return json.loads(Path(path_str).read_text())


def read_text_lossy(path_str):
    return Path(path_str).read_text(encoding="utf-8", errors="replace")


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
    for line in read_text_lossy(remote_log).splitlines():
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
        load_before,
        cpu_after,
        mem_after,
        load_after,
        jitter_seconds,
    ) = argv
    data = read_json(result_file)
    data.update(
        {
            "duration_seconds": int(duration_seconds),
            "cpu_before": cpu_before,
            "mem_before": mem_before,
            "load_before": load_before,
            "cpu_after": cpu_after,
            "mem_after": mem_after,
            "load_after": load_after,
            "jitter_seconds": int(jitter_seconds),
        }
    )
    write_json(result_file, data)


def cmd_merge_sample_metrics(argv):
    result_file, sample_file = argv
    data = read_json(result_file)
    sample_path = Path(sample_file)

    samples = []
    if sample_path.exists():
        for line in sample_path.read_text().splitlines():
            parts = line.strip().split("|")
            if len(parts) != 3:
                continue
            try:
                cpu = int(parts[0])
                mem = int(parts[1])
                load1 = float(parts[2])
            except ValueError:
                continue
            samples.append((cpu, mem, load1))

    if not samples:
        data["sample_count"] = 0
        write_json(result_file, data)
        return

    cpu_values = [item[0] for item in samples]
    mem_values = [item[1] for item in samples]
    load_values = [item[2] for item in samples]

    data.update(
        {
            "sample_count": len(samples),
            "cpu_avg": round(sum(cpu_values) / len(cpu_values)),
            "cpu_max": max(cpu_values),
            "mem_avg": round(sum(mem_values) / len(mem_values)),
            "mem_max": max(mem_values),
            "load1_avg": round(sum(load_values) / len(load_values), 2),
            "load1_max": round(max(load_values), 2),
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
    if len(argv) < 3:
        raise SystemExit(
            "usage: keepalive_result_helper.py build-summary <all_results_dir> <host_count> <output_file> [title]"
        )

    all_results_dir, host_count, output_file, *rest = argv
    title = rest[0] if rest else "ARM64 OCI 保活报告 V2"
    base = Path(all_results_dir)
    results = []
    if base.exists():
        for path in sorted(base.glob("result-*/host_*.json")):
            results.append(json.loads(path.read_text()))

    def host_label(item):
        return f"{item.get('host', 'unknown')}#{item.get('index', '?')}"

    def metric_int(item, preferred_key, fallback_key):
        value = item.get(preferred_key)
        if value in (None, "", "N/A"):
            value = item.get(fallback_key, "N/A")
        return str(value)

    def metric_float(item, preferred_key, fallback_key):
        value = item.get(preferred_key)
        if value in (None, "", "N/A"):
            value = item.get(fallback_key, "N/A")
        return str(value)

    def metric_sort_int(item, preferred_key, fallback_key, default=999):
        value = item.get(preferred_key)
        if value in (None, "", "N/A"):
            value = item.get(fallback_key)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def metric_sort_float(item, preferred_key, fallback_key, default=999.0):
        value = item.get(preferred_key)
        if value in (None, "", "N/A"):
            value = item.get(fallback_key)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def success_sort_key(item):
        return (
            metric_sort_float(item, "load1_avg", "load_after"),
            metric_sort_float(item, "load1_max", "load_after"),
            metric_sort_int(item, "cpu_avg", "cpu_after"),
            metric_sort_int(item, "mem_avg", "mem_after"),
            host_label(item),
        )

    def success_warning_reasons(item):
        reasons = []
        duration_seconds = int(item.get("duration_seconds", 0) or 0)
        sample_count = int(item.get("sample_count", 0) or 0)

        cpu_avg_raw = item.get("cpu_avg", item.get("cpu_after"))
        mem_avg_raw = item.get("mem_avg", item.get("mem_after"))

        try:
            cpu_avg = int(cpu_avg_raw)
        except (TypeError, ValueError):
            cpu_avg = None

        try:
            mem_avg = int(mem_avg_raw)
        except (TypeError, ValueError):
            mem_avg = None

        if duration_seconds > 600:
            reasons.append("duration>10m")
        if cpu_avg is not None and cpu_avg >= 80:
            reasons.append(f"cpu_avg={cpu_avg}%")
        if mem_avg is not None and mem_avg >= 60:
            reasons.append(f"mem_avg={mem_avg}%")
        if sample_count == 0:
            reasons.append("metrics=snapshot_only")
        return reasons

    success_hosts = []
    fatal_lines = []
    warning_lines = []

    for item in results:
        workflow_status = item.get("workflow_status", "unknown")
        prediction_status = item.get("prediction_status", "unknown")
        notes = item.get("notes", "").strip()
        if workflow_status == "success":
            success_hosts.append(item)
            reasons = success_warning_reasons(item)
            if prediction_status != "present":
                reasons.insert(0, f"prediction={prediction_status}")
            if reasons:
                detail = f"⚠️ <b>{item.get('host', 'unknown')}</b> | " + " | ".join(reasons)
                if notes:
                    detail += f" | {notes}"
                warning_lines.append(detail)
        else:
            detail = f"❌ <b>{item.get('host', 'unknown')}</b> | {workflow_status}"
            if notes:
                detail += f" | {notes}"
            fatal_lines.append(detail)

    timestamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    header = (
        f"<b>{title}</b>\n"
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
        success_hosts = sorted(success_hosts, key=success_sort_key)
        success_lines = []
        for item in success_hosts[:20]:
            cpu_avg = metric_int(item, "cpu_avg", "cpu_after")
            cpu_max = metric_int(item, "cpu_max", "cpu_after")
            mem_avg = metric_int(item, "mem_avg", "mem_after")
            mem_max = metric_int(item, "mem_max", "mem_after")
            load1_max = metric_float(item, "load1_max", "load_after")
            success_lines.append(
                f"{host_label(item)} | CPU {cpu_avg}/{cpu_max}% | MEM {mem_avg}/{mem_max}% | L1 {load1_max}"
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
    elif command == "merge-sample-metrics":
        cmd_merge_sample_metrics(argv)
    elif command == "enforce-fatal":
        cmd_enforce_fatal(argv)
    elif command == "build-summary":
        cmd_build_summary(argv)
    else:
        raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    main()
