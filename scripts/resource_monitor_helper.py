#!/usr/bin/env python3

import csv
import html
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


def cmd_update_result(argv):
    path, workflow_status, notes = argv
    data = read_json(path)
    data["workflow_status"] = workflow_status
    data["notes"] = notes
    write_json(path, data)


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
            "cpu_min": min(cpu_values),
            "cpu_max": max(cpu_values),
            "mem_avg": round(sum(mem_values) / len(mem_values)),
            "mem_min": min(mem_values),
            "mem_max": max(mem_values),
            "load1_avg": round(sum(load_values) / len(load_values), 2),
            "load1_max": round(max(load_values), 2),
        }
    )
    write_json(result_file, data)


def load_results(all_results_dir):
    base = Path(all_results_dir)
    results = []
    if not base.exists():
        return results
    for path in sorted(base.glob("result-*/host_*.json")):
        results.append(json.loads(path.read_text()))
    return results


def rank_key(item):
    cpu_avg = item.get("cpu_avg")
    mem_avg = item.get("mem_avg")

    try:
        cpu_avg = int(cpu_avg)
    except (TypeError, ValueError):
        cpu_avg = 999

    try:
        mem_avg = int(mem_avg)
    except (TypeError, ValueError):
        mem_avg = 999

    return (cpu_avg, mem_avg, item.get("host", ""))


def cmd_build_csv(argv):
    all_results_dir, output_csv, run_timestamp = argv
    rows = []
    for item in load_results(all_results_dir):
        if item.get("workflow_status") != "success":
            continue
        rows.append(item)

    rows.sort(key=rank_key)

    snapshot_path = Path(output_csv)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with snapshot_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "name",
                "index",
                "cpu_avg_pct",
                "mem_avg_pct",
                "timestamp",
            ]
        )
        for item in rows:
            writer.writerow(
                [
                    item.get("host", ""),
                    item.get("index", ""),
                    item.get("cpu_avg", ""),
                    item.get("mem_avg", ""),
                    run_timestamp,
                ]
            )


def cmd_build_summary(argv):
    all_results_dir, host_count, output_file = argv
    results = load_results(all_results_dir)

    success = [item for item in results if item.get("workflow_status") == "success"]
    failed = [item for item in results if item.get("workflow_status") != "success"]
    ranked = sorted(success, key=rank_key)
    low_activity = [
        item
        for item in ranked
        if int(item.get("cpu_avg", 999)) < 20 and int(item.get("mem_avg", 999)) < 20
    ]

    timestamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "<b>ARM64 资源监控摘要</b>",
        f"🕐 {timestamp} (北京时间)",
        f"🖥️ 目标主机: {host_count}",
        f"✅ 成功: {len(success)}",
        f"❌ 失败: {len(failed)}",
        f"📉 低活跃(5分钟平均 CPU<20% 且内存<20%): {len(low_activity)}",
        "━━━━━━━━━━━━━━━━━━",
    ]

    if ranked:
        lines.append("<b>5分钟平均低活跃排名</b>")
        for idx, item in enumerate(ranked, start=1):
            host = html.escape(str(item.get("host", "unknown")))
            lines.append(
                (
                    f"{idx}. <b>{host}</b>#{item.get('index', '?')} | "
                    f"CPU {item.get('cpu_avg', 'N/A')}% | "
                    f"MEM {item.get('mem_avg', 'N/A')}%"
                )
            )
    else:
        lines.append("本次没有成功采集到任何主机数据")

    if failed:
        lines.append("")
        lines.append("<b>失败主机</b>")
        for item in failed[:10]:
            host = html.escape(str(item.get("host", "unknown")))
            notes = html.escape(item.get("notes", "").strip())
            detail = f"❌ <b>{host}</b>#{item.get('index', '?')} | {item.get('workflow_status', 'unknown')}"
            if notes:
                detail += f" | {notes}"
            lines.append(detail)

    content = "\n".join(lines).replace("<20%", "&lt;20%")
    Path(output_file).write_text(content + "\n")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: resource_monitor_helper.py <command> ...")

    command = sys.argv[1]
    argv = sys.argv[2:]

    if command == "write-result":
        cmd_write_result(argv)
    elif command == "update-result":
        cmd_update_result(argv)
    elif command == "merge-sample-metrics":
        cmd_merge_sample_metrics(argv)
    elif command == "build-csv":
        cmd_build_csv(argv)
    elif command == "build-summary":
        cmd_build_summary(argv)
    else:
        raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    main()
