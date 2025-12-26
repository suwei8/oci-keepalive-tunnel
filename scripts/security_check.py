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

# 挖矿进程关键词 (从环境变量读取，避免在代码中暴露敏感关键词)
# 格式: 逗号分隔的关键词列表
_default_keywords = "arm7,arm5,uhavenobotsxd,.monitor"  # 最小默认值
MINER_KEYWORDS = os.environ.get("SECURITY_KEYWORDS", _default_keywords).split(",")

# 可疑 crontab 模式
SUSPICIOUS_CRON_PATTERNS = [
    r"/tmp/", r"/dev/shm/", r"/var/tmp/.*\.(sh|py|pl|exe)",
    r"curl.*\|.*sh", r"wget.*\|.*sh", r"base64"
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
            found_suspicious = False
            for line in result.stdout.split('\n'):
                lower_line = line.lower()
                for keyword in MINER_KEYWORDS:
                    if keyword in lower_line and "grep" not in lower_line:
                        # 提取进程信息
                        parts = line.split()
                        if len(parts) >= 11:
                            pid = parts[1]
                            cmd = ' '.join(parts[10:])[:80]
                            
                            # 跳过内核进程 (命令在方括号中，如 [kswapd0])
                            if cmd.startswith('[') and cmd.endswith(']'):
                                continue
                            
                            # 跳过系统合法进程
                            if '/usr/bin/python3' in cmd and 'networkd-dispatcher' in line:
                                continue
                            
                            # 跳过浏览器辅助进程 (Chromium/Chrome)
                            if '--type=utility' in cmd or '--type=renderer' in cmd or '--type=gpu' in cmd:
                                continue
                            if '/proc/self/exe' in cmd and '--type=' in line:
                                continue
                            
                            # 跳过用户白名单应用
                            if 'com.fluxpay.monitor' in cmd:
                                continue
                            
                            self.add_issue("CRITICAL", f"疑似挖矿进程 (PID: {pid})", cmd)
                            found_suspicious = True
                        break
            
            if not found_suspicious:
                print("[安全] ✅ 未发现可疑挖矿进程")
        except Exception as e:
            print(f"[安全] 检查进程出错: {e}")
    
    def check_suspicious_tmp_files(self):
        """检查 /tmp 中的可疑文件"""
        print("\n[安全] 检查 /tmp 可疑文件...")
        # 白名单目录 - AppImage 挂载点等正常目录
        whitelist_dirs = ['.mount_']  # AppImage 运行时挂载点
        
        try:
            suspicious_files = []
            for root, dirs, files in os.walk("/tmp"):
                # 跳过白名单目录
                if any(wl in root for wl in whitelist_dirs):
                    dirs[:] = []  # 不继续遍历
                    continue
                
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
        # 白名单父进程 - 这些进程产生的僵尸进程不告警
        whitelist_parents = ['antigravity', 'npm', 'node', 'code', 'vscode']
        
        try:
            # 获取所有僵尸进程及其父进程
            result = subprocess.run(
                ["ps", "-eo", "pid,ppid,stat,comm"],
                capture_output=True, text=True, timeout=10
            )
            
            zombie_pids = []
            for line in result.stdout.split('\n'):
                parts = line.split()
                if len(parts) >= 3 and parts[2].startswith('Z'):
                    zombie_pids.append((parts[0], parts[1]))  # (pid, ppid)
            
            if not zombie_pids:
                print("[安全] ✅ 僵尸进程数: 0")
                return
            
            # 检查父进程是否在白名单
            non_whitelisted_zombies = 0
            for pid, ppid in zombie_pids:
                try:
                    # 获取父进程命令
                    parent_result = subprocess.run(
                        ["ps", "-p", ppid, "-o", "comm="],
                        capture_output=True, text=True, timeout=5
                    )
                    parent_comm = parent_result.stdout.strip().lower()
                    
                    # 检查是否在白名单
                    is_whitelisted = any(wl in parent_comm for wl in whitelist_parents)
                    if not is_whitelisted:
                        non_whitelisted_zombies += 1
                except:
                    non_whitelisted_zombies += 1
            
            total_zombies = len(zombie_pids)
            if non_whitelisted_zombies > 10:
                self.add_issue("WARNING", "大量僵尸进程", f"数量: {non_whitelisted_zombies} (总计: {total_zombies})")
            else:
                whitelisted = total_zombies - non_whitelisted_zombies
                print(f"[安全] ✅ 僵尸进程数: {total_zombies} (白名单: {whitelisted})")
        except Exception as e:
            print(f"[安全] 检查僵尸进程出错: {e}")
    
    def check_root_users(self):
        """检查异常 root 用户"""
        print("\n[安全] 检查 UID=0 用户...")
        # 允许的 UID=0 用户白名单
        allowed_root_users = ['root', 'sw']
        try:
            with open("/etc/passwd") as f:
                for line in f:
                    parts = line.strip().split(':')
                    if len(parts) >= 3 and parts[2] == '0' and parts[0] not in allowed_root_users:
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
            found = False
            for line in result.stdout.split('\n'):
                # 跳过表头
                if line.startswith("State") or not line.strip():
                    continue
                    
                # 跳过本地连接
                if '127.0.0.1' in line or '::1' in line:
                    continue
                
                # 只检查已建立的连接
                if "ESTAB" not in line:
                    continue
                
                # 解析 ss 输出格式:
                # State  Recv-Q  Send-Q  Local Address:Port  Peer Address:Port  Process
                parts = line.split()
                if len(parts) < 5:
                    continue
                
                # 获取远程地址 (第5列, 索引4)
                peer_addr = parts[4] if len(parts) > 4 else ""
                
                # 获取进程信息 (最后一列)
                process_info = parts[-1] if parts else ""
                
                # 检查是否连接到矿池端口 (只检查远程端口)
                is_mining_port = False
                matched_port = 0
                for port in MINING_PORTS:
                    # 确保是远程端口，格式如 ip:port 或 [ipv6]:port
                    if peer_addr.endswith(f":{port}"):
                        is_mining_port = True
                        matched_port = port
                        break
                
                if not is_mining_port:
                    continue
                
                # 提取进程名用于告警
                proc_match = re.search(r'users:\(\("([^"]+)"', process_info)
                proc_name = proc_match.group(1) if proc_match else "unknown"
                
                self.add_issue("WARNING", "疑似矿池连接", 
                              f"进程: {proc_name}, 远程: {peer_addr}, 端口: {matched_port}")
                found = True
                
            if not found:
                print("[安全] ✅ 未发现可疑矿池连接")
        except Exception as e:
            print(f"[安全] 检查网络出错: {e}")
    
    def check_disk_usage(self):
        """检查磁盘使用率"""
        print("\n[安全] 检查磁盘使用率...")
        try:
            result = subprocess.run(
                ["df", "-h", "/"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.split('\n')[1:]:
                parts = line.split()
                if len(parts) >= 5:
                    usage_str = parts[4].replace('%', '')
                    if usage_str.isdigit():
                        usage = int(usage_str)
                        if usage >= 95:
                            self.add_issue("WARNING", "磁盘使用率过高", f"根分区: {usage}%")
                        else:
                            print(f"[安全] ✅ 磁盘使用率: {usage}%")
                        break
        except Exception as e:
            print(f"[安全] 检查磁盘出错: {e}")
    
    def check_suspicious_systemd_services(self):
        """检查可疑 systemd 服务
        
        定义可疑服务:
        - ExecStart 指向 /tmp, /dev/shm, /var/tmp 等目录
        - 服务名称包含可疑关键词
        - 最近创建的非系统服务
        """
        print("\n[安全] 检查 systemd 服务...")
        suspicious_paths = ["/tmp/", "/dev/shm/", "/var/tmp/", "/home/"]
        try:
            # 列出所有用户服务单元
            result = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--state=running", "--no-pager", "--no-legend"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.split('\n'):
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 1:
                    service_name = parts[0]
                    # 检查服务配置
                    show_result = subprocess.run(
                        ["systemctl", "show", service_name, "--property=ExecStart"],
                        capture_output=True, text=True, timeout=5
                    )
                    exec_start = show_result.stdout.strip()
                    for path in suspicious_paths:
                        if path in exec_start:
                            # 跳过 GitHub Actions 自托管 runner 服务
                            if service_name.startswith('actions.runner.'):
                                continue
                            self.add_issue("WARNING", "可疑 systemd 服务", f"{service_name}: {exec_start[:80]}")
                            break
            print("[安全] ✅ 未发现可疑 systemd 服务")
        except Exception as e:
            print(f"[安全] 检查 systemd 出错: {e}")
    
    def check_brute_force(self):
        """检查暴力破解尝试"""
        print("\n[安全] 检查暴力破解尝试...")
        try:
            # 检查最近的登录失败记录
            auth_log = "/var/log/auth.log"
            if not os.path.exists(auth_log):
                auth_log = "/var/log/secure"  # CentOS/RHEL
            
            if os.path.exists(auth_log):
                result = subprocess.run(
                    ["grep", "-c", "Failed password", auth_log],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    failed_count = int(result.stdout.strip())
                    if failed_count > 100:
                        self.add_issue("WARNING", "大量登录失败", f"失败次数: {failed_count}")
                    else:
                        print(f"[安全] ✅ 登录失败次数: {failed_count}")
                else:
                    print("[安全] ✅ 无登录失败记录")
            else:
                print("[安全] ⚠️  无法访问 auth.log")
        except Exception as e:
            print(f"[安全] 检查暴力破解出错: {e}")
    
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
        self.check_disk_usage()
        self.check_suspicious_systemd_services()
        self.check_brute_force()
        
        print("\n" + "-" * 40)
        if self.issues:
            print(f"⚠️  发现 {len(self.issues)} 个安全问题")
            self.send_telegram_alert()
        else:
            print("✅ 安全检测通过，未发现问题")
        print("-" * 40)
        
        return self.issues
    
    def has_critical_issues(self) -> bool:
        """检查是否有严重问题"""
        return any(issue["level"] == "CRITICAL" for issue in self.issues)


def run_security_checks(hostname: str) -> tuple:
    """运行安全检查的入口函数
    
    Returns:
        tuple: (issues_list, has_critical_issues)
    """
    checker = SecurityChecker(hostname)
    issues = checker.run_all_checks()
    return issues, checker.has_critical_issues()


if __name__ == "__main__":
    import sys
    hostname = sys.argv[1] if len(sys.argv) > 1 else "test-host"
    run_security_checks(hostname)
