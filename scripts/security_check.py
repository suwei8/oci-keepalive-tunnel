#!/usr/bin/env python3
"""
OCI 实例安全检测模块
- 检测挖矿木马、恶意 crontab、异常进程
- 发送 Telegram 告警通知
"""

import os
import subprocess
import re
import urllib.request
import urllib.parse
import json
from datetime import datetime
from typing import List, Tuple, Dict

# Telegram 配置 (从环境变量读取)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# 已知的挖矿进程关键词
MINER_KEYWORDS = [
    "xmrig", "xmr-stak", "kswapd0", "kdevtmpfsi", "kinsing",
    "arm7", "arm5", "ld-linux", "bioset", "crypto",
    "ddgs", "watchdogs", "uhavenobotsxd", ".monitor",
    "minerd", "cpuminer", "cgminer", "bfgminer", "ethminer",
    "t9miner", "httpsd", "kthreaddi", "sysupdate", "networkservice"
]

# 可疑 crontab 模式
SUSPICIOUS_CRON_PATTERNS = [
    r"/tmp/", r"/dev/shm/", r"/var/tmp/.*\.(sh|py|pl|exe)",
    r"curl.*\|.*sh", r"wget.*\|.*sh", r"base64", r"\.monitor",
    r"arm[0-9]", r"uhave", r"kswapd", r"kdevtmpfsi"
]

# 挖矿矿池常用端口
MINING_PORTS = [3333, 4444, 5555, 7777, 8888, 9999, 14444, 45700]


class SecurityChecker:
    def __init__(self, hostname: str):
        self.hostname = hostname
        self.issues: List[Dict] = []
        self.timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    def add_issue(self, level: str, title: str, detail: str):
        """添加安全问题"""
        self.issues.append({
            "level": level,  # CRITICAL, WARNING, INFO
            "title": title,
            "detail": detail
        })
        level_emoji = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "🟢"}.get(level, "⚪")
        print(f"[安全] {level_emoji} [{level}] {title}")
        if detail:
            print(f"        {detail[:100]}...")
    
    def check_malicious_crontab(self):
        """检查恶意 crontab 条目"""
        print("\n[安全] 检查 crontab...")
        try:
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                crontab_content = result.stdout
                for pattern in SUSPICIOUS_CRON_PATTERNS:
                    matches = re.findall(f".*{pattern}.*", crontab_content, re.IGNORECASE)
                    for match in matches:
                        self.add_issue("CRITICAL", "恶意 Crontab 条目", match.strip())
            else:
                print("[安全] ✅ 用户 crontab 为空或无法读取")
        except Exception as e:
            print(f"[安全] 检查 crontab 出错: {e}")
    
    def check_mining_processes(self):
        """检查挖矿进程"""
        print("\n[安全] 检查挖矿进程...")
        try:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.split('\n'):
                lower_line = line.lower()
                for keyword in MINER_KEYWORDS:
                    if keyword in lower_line and "grep" not in lower_line:
                        # 提取进程信息
                        parts = line.split()
                        if len(parts) >= 11:
                            pid = parts[1]
                            cmd = ' '.join(parts[10:])[:80]
                            self.add_issue("CRITICAL", f"疑似挖矿进程 (PID: {pid})", cmd)
                        break
        except Exception as e:
            print(f"[安全] 检查进程出错: {e}")
    
    def check_suspicious_tmp_files(self):
        """检查 /tmp 中的可疑文件"""
        print("\n[安全] 检查 /tmp 可疑文件...")
        try:
            suspicious_files = []
            for root, dirs, files in os.walk("/tmp"):
                for f in files:
                    filepath = os.path.join(root, f)
                    # 检查隐藏的可执行文件或可疑名称
                    if (f.startswith('.') and os.access(filepath, os.X_OK)) or \
                       any(keyword in f.lower() for keyword in MINER_KEYWORDS):
                        suspicious_files.append(filepath)
                # 不深入遍历系统目录
                dirs[:] = [d for d in dirs if not d.startswith('systemd-')]
            
            for filepath in suspicious_files[:5]:  # 最多报告5个
                self.add_issue("WARNING", "可疑 /tmp 文件", filepath)
            
            if not suspicious_files:
                print("[安全] ✅ /tmp 目录正常")
        except Exception as e:
            print(f"[安全] 检查 /tmp 出错: {e}")
    
    def check_ssh_localhost_only(self):
        """检查 SSH 是否仅监听本地"""
        print("\n[安全] 检查 SSH 监听配置...")
        try:
            result = subprocess.run(
                ["ss", "-tlnp"],
                capture_output=True, text=True, timeout=10
            )
            ssh_lines = [l for l in result.stdout.split('\n') if ':22 ' in l or ':22\t' in l]
            
            for line in ssh_lines:
                if '0.0.0.0:22' in line or '*:22' in line or ':::22' in line:
                    self.add_issue("INFO", "SSH 监听所有接口", "建议配置为仅监听 127.0.0.1")
                    return
            
            if ssh_lines:
                print("[安全] ✅ SSH 仅监听本地接口")
            else:
                print("[安全] ⚠️  未检测到 SSH 服务")
        except Exception as e:
            print(f"[安全] 检查 SSH 出错: {e}")
    
    def check_cpu_anomaly(self):
        """检查 CPU 使用异常"""
        print("\n[安全] 检查 CPU 使用率...")
        try:
            # 读取 /proc/stat 计算 CPU 使用率
            with open("/proc/stat") as f:
                line = f.readline()
                parts = line.split()
                user, nice, system, idle, iowait = map(int, parts[1:6])
                total = user + nice + system + idle + iowait
                usage = 100 * (total - idle - iowait) / total if total > 0 else 0
                
                # 注意：保活任务本身会产生高 CPU，这里检查是否超过 95%
                if usage > 95:
                    self.add_issue("WARNING", "CPU 使用率异常", f"当前: {usage:.1f}%")
                else:
                    print(f"[安全] ✅ CPU 使用率: {usage:.1f}%")
        except Exception as e:
            print(f"[安全] 检查 CPU 出错: {e}")
    
    def check_zombie_processes(self):
        """检查僵尸进程"""
        print("\n[安全] 检查僵尸进程...")
        try:
            result = subprocess.run(
                ["ps", "-A", "-ostat"],
                capture_output=True, text=True, timeout=10
            )
            zombie_count = sum(1 for line in result.stdout.split('\n') if line.startswith('Z'))
            
            if zombie_count > 10:
                self.add_issue("WARNING", "大量僵尸进程", f"数量: {zombie_count}")
            else:
                print(f"[安全] ✅ 僵尸进程数: {zombie_count}")
        except Exception as e:
            print(f"[安全] 检查僵尸进程出错: {e}")
    
    def check_root_users(self):
        """检查异常 root 用户"""
        print("\n[安全] 检查 UID=0 用户...")
        try:
            with open("/etc/passwd") as f:
                for line in f:
                    parts = line.strip().split(':')
                    if len(parts) >= 3 and parts[2] == '0' and parts[0] != 'root':
                        self.add_issue("CRITICAL", "异常 UID=0 用户", parts[0])
            print("[安全] ✅ 未发现异常 root 用户")
        except Exception as e:
            print(f"[安全] 检查用户出错: {e}")
    
    def check_mining_connections(self):
        """检查到矿池的网络连接"""
        print("\n[安全] 检查可疑网络连接...")
        try:
            result = subprocess.run(
                ["ss", "-tnp"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.split('\n'):
                for port in MINING_PORTS:
                    if f":{port}" in line and "ESTAB" in line:
                        self.add_issue("WARNING", "疑似矿池连接", line.strip()[:100])
        except Exception as e:
            print(f"[安全] 检查网络出错: {e}")
    
    def send_telegram_alert(self):
        """发送 Telegram 告警"""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            print("[安全] ⚠️  Telegram 未配置，跳过通知")
            return
        
        if not self.issues:
            print("[安全] ✅ 未发现安全问题，无需发送告警")
            return
        
        # 构建消息
        critical_count = sum(1 for i in self.issues if i["level"] == "CRITICAL")
        warning_count = sum(1 for i in self.issues if i["level"] == "WARNING")
        
        message = f"🚨 *安全告警 - {self.hostname}*\n\n"
        message += f"发现 {len(self.issues)} 个问题 "
        message += f"(🔴 {critical_count} 严重, 🟡 {warning_count} 警告)\n\n"
        
        for issue in self.issues[:10]:  # 最多显示10个
            emoji = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "🟢"}.get(issue["level"], "⚪")
            message += f"{emoji} *[{issue['level']}]* {issue['title']}\n"
            if issue["detail"]:
                # 转义 Markdown 特殊字符
                detail = issue["detail"].replace("_", "\\_").replace("*", "\\*")
                message += f"   `{detail[:60]}`\n"
            message += "\n"
        
        message += f"⏰ {self.timestamp}"
        
        # 发送请求
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = urllib.parse.urlencode({
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown"
            }).encode()
            
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    print("[安全] ✅ Telegram 告警已发送")
                else:
                    print(f"[安全] ❌ Telegram 发送失败: {response.status}")
        except Exception as e:
            print(f"[安全] ❌ Telegram 发送出错: {e}")
    
    def run_all_checks(self):
        """运行所有安全检查"""
        print("\n" + "=" * 60)
        print("🛡️  安全检测")
        print("=" * 60)
        
        self.check_malicious_crontab()
        self.check_mining_processes()
        self.check_suspicious_tmp_files()
        self.check_ssh_localhost_only()
        self.check_cpu_anomaly()
        self.check_zombie_processes()
        self.check_root_users()
        self.check_mining_connections()
        
        print("\n" + "-" * 40)
        if self.issues:
            print(f"⚠️  发现 {len(self.issues)} 个安全问题")
            self.send_telegram_alert()
        else:
            print("✅ 安全检测通过，未发现问题")
        print("-" * 40)
        
        return self.issues


def run_security_checks(hostname: str) -> List[Dict]:
    """运行安全检查的入口函数"""
    checker = SecurityChecker(hostname)
    return checker.run_all_checks()


if __name__ == "__main__":
    import sys
    hostname = sys.argv[1] if len(sys.argv) > 1 else "test-host"
    run_security_checks(hostname)
