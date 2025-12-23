#!/usr/bin/env python3
"""
福彩3D 数据采集脚本
使用新浪彩票 API (稳定可靠)
在 GitHub Actions runner 上运行，采集后保存到仓库
"""

import csv
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path


DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = DATA_DIR / "fc3d_history.csv"


def fetch_from_sina(limit: int = 200) -> list:
    """从新浪彩票采集 (主要数据源)"""
    print(f"[采集] 使用新浪彩票 API...")
    
    # 新浪彩票 API (稳定可靠)
    base_url = "https://mix.lottery.sina.com.cn/gateway/index/entry"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://lottery.sina.com.cn/"
    }
    
    all_results = []
    page = 1
    max_pages = (limit // 20) + 1  # 每页20条
    
    while page <= max_pages and len(all_results) < limit:
        params = urllib.parse.urlencode({
            "format": "json",
            "__caller__": "wap",
            "__version__": "1.0.0",
            "__verno__": "10000",
            "cat1": "gameOpenList",
            "lottoType": "102",      # 福彩3D
            "paginationType": "1",
            "pageSize": "20",
            "page": str(page),
            "dpc": "1"
        })
        
        try:
            req = urllib.request.Request(f"{base_url}?{params}", headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            
            if data.get("result") and data["result"].get("data"):
                items = data["result"]["data"]
                for item in items:
                    issue_no = item.get("issueNo", "")
                    open_time = item.get("openTime", "")
                    open_results = item.get("openResults", [])
                    
                    if issue_no and len(open_results) >= 3:
                        all_results.append({
                            "issue": str(issue_no),
                            "d1": int(open_results[0]),
                            "d2": int(open_results[1]),
                            "d3": int(open_results[2]),
                            "date": open_time
                        })
                
                # 检查是否还有更多页
                pagination = data["result"].get("pagination", {})
                total_pages = int(pagination.get("totalPage", 1))
                
                print(f"[采集] 第 {page}/{total_pages} 页, 已获取 {len(all_results)} 期")
                
                if page >= total_pages:
                    break
                page += 1
            else:
                print(f"[采集] 第 {page} 页无数据")
                break
                
        except Exception as e:
            print(f"[采集] ❌ 第 {page} 页失败: {e}")
            break
    
    if all_results:
        print(f"[采集] ✅ 新浪彩票成功，共获取 {len(all_results)} 期")
    
    return all_results[:limit]


def fetch_from_cwl_backup(limit: int = 200) -> list:
    """从中彩网采集 (备用)"""
    print(f"[采集] 尝试备用: 中彩网 API...")
    
    url = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
    params = urllib.parse.urlencode({
        "name": "3d",
        "issueCount": str(limit),
    })
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.cwl.gov.cn/ygkj/wqkjgg/3d/"
    }
    
    try:
        req = urllib.request.Request(f"{url}?{params}", headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        
        if data.get("state") == 0 and data.get("result"):
            results = []
            for item in data["result"]:
                issue = item.get("code", "")
                red = item.get("red", "")
                date = item.get("date", "")
                
                if issue and red:
                    digits = [int(d) for d in red.split() if d.isdigit()]
                    if len(digits) == 3:
                        results.append({
                            "issue": str(issue),
                            "d1": digits[0],
                            "d2": digits[1],
                            "d3": digits[2],
                            "date": date
                        })
            
            if results:
                print(f"[采集] ✅ 中彩网成功，获取 {len(results)} 期")
                return results
    except Exception as e:
        print(f"[采集] ❌ 中彩网失败: {e}")
    
    return []


def load_existing_data() -> list:
    """加载现有数据"""
    if not OUTPUT_FILE.exists():
        return []
    
    try:
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            return [{"issue": r["issue"], "d1": int(r["d1"]), "d2": int(r["d2"]), 
                     "d3": int(r["d3"]), "date": r.get("date", "")} for r in reader]
    except Exception as e:
        print(f"[加载] ⚠️ 读取现有数据失败: {e}")
        return []


def save_data(data: list):
    """保存数据"""
    # 按期号排序（从旧到新）
    data.sort(key=lambda x: x["issue"])
    
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["issue", "d1", "d2", "d3", "date"])
        writer.writeheader()
        writer.writerows(data)
    
    print(f"[存储] ✅ 已保存 {len(data)} 期数据到 {OUTPUT_FILE}")


def main():
    print("=" * 60)
    print(f"福彩3D 数据采集 (使用新浪彩票 API)")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 主数据源: 新浪彩票
    new_data = fetch_from_sina(200)
    
    # 备用数据源: 中彩网
    if not new_data or len(new_data) < 50:
        print("[采集] 主数据源数据不足，尝试备用源...")
        new_data = fetch_from_cwl_backup(200)
    
    if not new_data:
        print("[错误] 所有数据源都失败了")
        sys.exit(1)
    
    # 合并现有数据
    existing = load_existing_data()
    existing_issues = {d["issue"] for d in existing}
    
    # 添加新数据
    added = 0
    for item in new_data:
        if item["issue"] not in existing_issues:
            existing.append(item)
            added += 1
    
    print(f"[合并] 新增 {added} 期数据")
    
    save_data(existing)
    
    # 显示最新几期
    print("\n最新 5 期开奖:")
    for item in existing[-5:]:
        print(f"  {item['issue']}: {item['d1']} {item['d2']} {item['d3']}")
    
    print("\n" + "=" * 60)
    print("采集完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
