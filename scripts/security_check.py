#!/usr/bin/env python3
"""
OCI 实例安全检测模块
- 检测挖矿木马、恶意 crontab、异常进程
- 发送 Telegram 告警通知
"""

import ipaddress
import os
import subprocess
import re
import time
import urllib.request
import urllib.parse
import json
import fnmatch
from datetime import datetime
from typing import List, Tuple, Dict, Sequence

# Telegram 配置 (从环境变量读取)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def load_csv_env(name: str, default: str, lowercase: bool = False) -> List[str]:
    """读取逗号分隔环境变量；空字符串视为未设置，回退到默认值。"""
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        raw_value = default

    items = [item.strip() for item in raw_value.split(",") if item.strip()]
    if lowercase:
        items = [item.lower() for item in items]
    return items

# 挖矿进程关键词 (从环境变量读取，避免在代码中暴露敏感关键词)
# 格式: 逗号分隔的关键词列表
_default_keywords = "arm7,arm5,uhavenobotsxd,.monitor"  # 最小默认值
MINER_KEYWORDS = load_csv_env("SECURITY_KEYWORDS", _default_keywords, lowercase=True)

# /tmp 文件名检测使用更收敛的关键词，避免误把正常依赖缓存命中为异常文件
_default_tmp_file_keywords = "arm7,arm5,uhavenobotsxd,.monitor,xmrig,kinsing,kdevtmpfsi,watchdogs,sysupdate"
TMP_FILE_KEYWORDS = load_csv_env(
    "SECURITY_TMP_FILE_KEYWORDS",
    _default_tmp_file_keywords,
    lowercase=True,
)

SAFE_TMP_FILE_SUFFIXES = (
    ".js",
    ".json",
    ".map",
    ".txt",
    ".md",
    ".rst",
    ".log",
    ".lock",
    ".deb",
    ".rpm",
    ".apk",
    ".dylib",
    ".dll",
    ".so",
    ".so.0",
    ".so.1",
    ".a",
    ".o",
    ".gz",
    ".xz",
    ".zip",
    ".tar",
    ".tgz",
    ".xml",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
)

SYSTEMD_SERVICE_ALLOWLIST = load_csv_env(
    "SECURITY_SYSTEMD_SERVICE_ALLOWLIST",
    "actions.runner.*",
)
SYSTEMD_SERVICE_ALLOWLIST_LOWER = [item.lower() for item in SYSTEMD_SERVICE_ALLOWLIST]

SYSTEMD_EXEC_ALLOWLIST = load_csv_env(
    "SECURITY_SYSTEMD_EXEC_ALLOWLIST",
    "/home/*/.nvm/*,/home/*/.local/bin/*,/home/*/.cargo/bin/*,"
    "/home/*/.pyenv/*,/home/*/.rbenv/*,/home/*/.asdf/*,/home/*/bin/*",
    lowercase=True,
)

# SSH 防火墙允许的外部来源 IP/CIDR（逗号分隔）
# 留空则仅验证 SSH 未对全网开放
SSH_ALLOWED_SOURCES = load_csv_env("SECURITY_SSH_ALLOWED_SOURCES", "")

# 可疑 crontab 模式
# 只标记"临时目录中的可执行内容被执行"和"下载/解码后管道执行"，
# 避免把 /tmp 下的锁文件(flock)、日志重定向等正常引用误判为恶意。
_CRON_TMP_ROOT = r"(?:/tmp|/dev/shm|/var/tmp|/run/user/\d+)"
_CRON_TMP_DIR = _CRON_TMP_ROOT + r"/"
_CRON_TMP_PATH = _CRON_TMP_DIR + r"\S+"
# 允许带引号的临时路径，如 sh -c "/tmp/x"
_CRON_TMP_TOKEN = r"[\"']?" + _CRON_TMP_PATH
_CRON_TMP_EXEC = _CRON_TMP_DIR + r"\S*\.(?:sh|py|pl|exe|bin|elf)\b"
# crontab 调度字段：@macro 或 5 段时间字段，其后是命令位
_CRON_SCHEDULE = r"(?:@[a-z]+|(?:\S+\s+){5})"
# 可选的 sudo 前缀（只允许 -flag / K=V 形态参数，不吞普通参数，
# 避免越过 flock 等命令误匹配）
_CRON_SUDO = r"(?:sudo(?:\s+(?:-\S+|\w+=\S+)){0,3}\s+)?"
# 能执行其他程序的命令：shell/解释器/启动器/find -exec/xargs 等；
# 名字必须占据整个 token（可带路径前缀），避免误中 run.sh、snap.py 等文件名
_CRON_RUNNER = (
    r"(?:[^\s|&;'\"]*/)?"
    r"(?:bash|sh|dash|zsh|ksh|csh|tcsh|fish|python\d*(?:\.\d+)?|perl|php|ruby|node|"
    r"exec|source|xargs|nohup|setsid|env|-exec(?:dir)?|\.)"
    r"(?=\s|$)"
)
# 选项或 KEY=VALUE 形式的中间参数
_CRON_OPT = r"(?:-\S+|\w+=\S+)"
# 命令分隔符（含管道、子 shell、命令替换）
_CRON_SEP = r"(?:&&|\|\||[;&|(`])"
# 仅 shell 类解释器（用于任意管道执行检测，python 等留给下载器规则）
_CRON_SHELL = (
    r"(?:[^\s|&;'\"]*/)?"
    r"(?:bash|sh|dash|zsh|ksh|csh|tcsh|fish)"
    r"(?=\s|$)"
)

SUSPICIOUS_CRON_PATTERNS = [
    # 调度字段后直接执行临时目录路径: "*/5 * * * * /tmp/x"、"@reboot /tmp/x"
    r"^\s*" + _CRON_SCHEDULE + r"\s*(?:" + _CRON_OPT + r"\s+){0,3}\s*" + _CRON_SUDO + _CRON_TMP_TOKEN,
    # 解释器/启动器执行临时目录路径: "bash /tmp/x.sh"、"python3 -u /dev/shm/a.py"
    r"(?:^|[\s;|&(\"'`])" + _CRON_RUNNER + r"(?:\s+" + _CRON_OPT + r"){0,3}\s+" + _CRON_TMP_TOKEN,
    # 命令分隔符后接临时目录路径: "...; /tmp/x"、"x | /tmp/p"、"x && /tmp/x"、"$(/tmp/x)"
    _CRON_SEP + r"\s*" + _CRON_SUDO + _CRON_TMP_TOKEN,
    # cd 到临时目录后执行相对路径: "cd /tmp; ...; ./x"
    r"\bcd\s+" + _CRON_TMP_ROOT + r"\b[^\n]*" + _CRON_SEP + r"[^\n]*\./\S+",
    # flock 的"锁文件之后"才是被执行的命令: flock [opts] lockfile <cmd>
    # 选项只允许 -flag / -w 数字 形态，锁文件不允许以 - 开头，
    # 使 lockfile 恰好在 /tmp 时不误报（flock -n /tmp/x.lock /home/run.sh）
    r"\bflock\b(?:\s+-\S+(?:\s+\d+)?)*\s+(?!-)\S+\s+" + _CRON_SUDO + _CRON_TMP_TOKEN,
    # 引用临时目录中的脚本/可执行文件（兜底: /tmp/x.sh、/var/tmp/a.elf 等）
    r"(?<![\w/.=-])" + _CRON_TMP_EXEC,
    # 任意命令管道给 shell 解释器: "... | sh"、"echo xxx | bash"、"x | xargs sh"
    r"\|\s*" + _CRON_SUDO + r"(?:xargs\s+|env(?:\s+\w+=\S+)*\s+)?" + _CRON_SHELL,
    # 下载器输出管道给任意解释器: "curl ... | python3"、"wget -qO- ... | perl"
    r"\b(?:curl|wget|fetch)\b[^\n]*\|\s*" + _CRON_SUDO + _CRON_RUNNER,
    # base64 解码执行或解码落盘
    r"\bbase64\b[^\n]*\|\s*" + _CRON_SUDO + _CRON_RUNNER,
    r"\bbase64\s+(?:-d\b|-D\b|--decode)",
]

# 挖矿矿池常用端口
MINING_PORTS = [3333, 4444, 5555, 7777, 8888, 9999, 14444, 45700]

KEEPALIVE_WRAPPER_MARKERS = (
    "export host_name=",
    "keepalive_repo_url=",
    "keepalive_repo_dir=",
    "keepalive_git_branch=",
    "keepalive_timeout_seconds=",
    "security_keywords=",
)

SUSPICIOUS_SYSTEMD_PATH_PREFIXES = (
    "/tmp/",
    "/dev/shm/",
    "/var/tmp/",
    "/run/user/",
)

SUSPICIOUS_SYSTEMD_NAME_PATTERNS = (
    "*xmrig*",
    "*kinsing*",
    "*kdevtmpfsi*",
    "*watchdogs*",
    "*sysupdate*",
)

SUSPICIOUS_SYSTEMD_EXEC_PATTERNS = (
    "*xmrig*",
    "*kinsing*",
    "*kdevtmpfsi*",
    "*/curl",
    "*/wget",
)


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

    @staticmethod
    def is_keepalive_wrapper_process(lower_cmd: str) -> bool:
        """忽略由 workflow 包装出来的远端保活启动命令，避免自命中。"""
        if "export host_name=" not in lower_cmd:
            return False
        if "bash -c" not in lower_cmd and "bash -lc" not in lower_cmd:
            return False
        return any(marker in lower_cmd for marker in KEEPALIVE_WRAPPER_MARKERS)

    @staticmethod
    def extract_systemd_exec_paths(exec_start: str) -> List[str]:
        """从 `systemctl show --property=ExecStart` 输出中提取可执行路径。"""
        paths = re.findall(r"path=([^ ;}]+)", exec_start)
        if paths:
            return paths

        fallback_paths = []
        for match in re.findall(r"(/[^ ;}]+)", exec_start):
            if match.startswith("/"):
                fallback_paths.append(match)
        return fallback_paths

    @staticmethod
    def matches_any_pattern(value: str, patterns: Sequence[str]) -> bool:
        return any(fnmatch.fnmatch(value, pattern) for pattern in patterns)

    def is_allowlisted_systemd_service(self, service_name: str, exec_paths: List[str]) -> bool:
        lower_name = service_name.lower()
        if self.matches_any_pattern(lower_name, SYSTEMD_SERVICE_ALLOWLIST_LOWER):
            return True

        for path in exec_paths:
            lower_path = path.lower()
            if self.matches_any_pattern(lower_path, SYSTEMD_EXEC_ALLOWLIST):
                return True
        return False

    def classify_systemd_service(self, service_name: str, exec_start: str) -> List[str]:
        lower_name = service_name.lower()
        lower_exec = exec_start.lower()
        exec_paths = [path.lower() for path in self.extract_systemd_exec_paths(exec_start)]

        if self.is_allowlisted_systemd_service(service_name, exec_paths):
            return []

        reasons = []

        if self.matches_any_pattern(lower_name, SUSPICIOUS_SYSTEMD_NAME_PATTERNS):
            reasons.append("服务名称包含高风险关键词")

        if self.matches_any_pattern(lower_exec, SUSPICIOUS_SYSTEMD_EXEC_PATTERNS):
            reasons.append("ExecStart 包含高风险关键词")

        for path in exec_paths:
            if any(path.startswith(prefix) for prefix in SUSPICIOUS_SYSTEMD_PATH_PREFIXES):
                reasons.append("ExecStart 指向高风险临时目录")
                break

        for path in exec_paths:
            if fnmatch.fnmatch(path, "/home/*/.*") and not self.matches_any_pattern(path, SYSTEMD_EXEC_ALLOWLIST):
                reasons.append("ExecStart 指向主目录隐藏路径")
                break

        return reasons
    
    def check_malicious_crontab(self):
        """检查恶意 crontab 条目"""
        print("\n[安全] 检查 crontab...")
        try:
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    if any(re.search(pattern, line, re.IGNORECASE)
                           for pattern in SUSPICIOUS_CRON_PATTERNS):
                        self.add_issue("CRITICAL", "恶意 Crontab 条目", stripped)
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
                                
                            # 跳过 Playwright 相关浏览器进程 (避免误报 SG2-新加坡西7)
                            if 'chromium_headless_shell' in cmd or 'ms-playwright' in line:
                                continue

                            # 跳过当前保活 workflow 的远端包装命令，避免被 SECURITY_KEYWORDS 自己命中
                            if self.is_keepalive_wrapper_process(lower_line):
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
        # 白名单目录 - 已确认会在 /tmp 下展开正常依赖或缓存的工具链目录
        whitelist_dirs = [
            '.mount_',
            '_MEI',
            'pyrefly',
            'Antigravity-Manager',
            '/tmp/ag/unpack/Antigravity',
            '/tmp/pw-run',
            '/tmp/adb-bullseye',
            '/tmp/codex-chrome-headless',
        ]  # AppImage 挂载点, PyInstaller 临时目录, Pyrefly 类型存根, 正常项目解包目录, Playwright/npm 临时目录, adb Debian 解包目录, Chromium 临时 profile
        
        try:
            suspicious_files = []
            for root, dirs, files in os.walk("/tmp"):
                # 跳过白名单目录
                if any(wl in root for wl in whitelist_dirs):
                    dirs[:] = []  # 不继续遍历
                    continue
                
                for f in files:
                    filepath = os.path.join(root, f)
                    lower_name = f.lower()
                    is_hidden_executable = lower_name.startswith('.') and os.access(filepath, os.X_OK)
                    has_suspicious_keyword = any(keyword in lower_name for keyword in TMP_FILE_KEYWORDS)
                    is_safe_dependency_artifact = lower_name.endswith(SAFE_TMP_FILE_SUFFIXES)

                    # 隐藏可执行文件始终告警；关键词命中则排除常见依赖/缓存制品
                    if is_hidden_executable or (has_suspicious_keyword and not is_safe_dependency_artifact):
                        suspicious_files.append(filepath)
                # 不深入遍历系统目录
                dirs[:] = [d for d in dirs if not d.startswith('systemd-')]
            
            for filepath in suspicious_files[:5]:  # 最多报告5个
                self.add_issue("WARNING", "可疑 /tmp 文件", filepath)
            
            if not suspicious_files:
                print("[安全] ✅ /tmp 目录正常")
        except Exception as e:
            print(f"[安全] 检查 /tmp 出错: {e}")
    
    def check_ssh_listen_config(self):
        """检查 SSH 监听配置

        预期配置：SSH 监听一个外部 IP + 本地回环（或等效的通配绑定），
        且防火墙仅放行可信来源 IP。以下情况才告警：
        - 绑定到非本机地址
        - 未覆盖回环（Tunnel 保活无法连接）
        - 外网访问未受防火墙限制，或放行来源不在白名单内
        """
        print("\n[安全] 检查 SSH 监听配置...")
        try:
            result = subprocess.run(
                ["ss", "-tln"],
                capture_output=True, text=True, timeout=10
            )
            listen_addrs = []
            for line in result.stdout.splitlines():
                cols = line.split()
                if len(cols) < 4:
                    continue
                local = cols[3]
                addr, _, port = local.rpartition(":")
                if port == "22":
                    listen_addrs.append(addr.strip("[]"))

            if not listen_addrs:
                print("[安全] ⚠️  未检测到 SSH 服务")
                return

            # 本机网卡 IP（回环与通配之外的合法绑定地址）
            host_ips = set()
            try:
                ips = subprocess.run(
                    ["hostname", "-I"],
                    capture_output=True, text=True, timeout=5
                )
                host_ips.update(ips.stdout.split())
            except Exception:
                pass

            loopback = {"127.0.0.1", "::1"}
            wildcard_v4 = {"0.0.0.0", "*"}
            wildcard_v6 = {"::", "0:0:0:0:0:0:0:0"}
            wildcard = wildcard_v4 | wildcard_v6

            unexpected = sorted(
                a for a in set(listen_addrs)
                if a not in loopback and a not in wildcard and a not in host_ips
            )
            if unexpected:
                self.add_issue(
                    "WARNING", "SSH 监听异常地址",
                    f"绑定了非本机地址: {', '.join(unexpected)}"
                )
                return

            if not any(a in loopback or a in wildcard for a in listen_addrs):
                self.add_issue(
                    "INFO", "SSH 未监听本地回环",
                    "仅绑定外部地址，Tunnel 保活可能无法连接"
                )

            external_v4 = any(
                a in wildcard_v4 or a in host_ips
                for a in listen_addrs if ":" not in a
            )
            external_v6 = any(
                a in wildcard_v6 or (":" in a and a not in loopback)
                for a in listen_addrs
            )
            if external_v4:
                self._check_ssh_firewall(ipv6=False)
            if external_v6:
                self._check_ssh_firewall(ipv6=True)
            if not external_v4 and not external_v6:
                print("[安全] ✅ SSH 仅监听本地回环")
        except Exception as e:
            print(f"[安全] 检查 SSH 出错: {e}")

    @staticmethod
    def _iptables_rules(ipv6=False):
        """读取 iptables filter 表全部链规则；无权限或不可用时返回 None"""
        tool = "ip6tables" if ipv6 else "iptables"
        for cmd in ([tool, "-S"], ["sudo", "-n", tool, "-S"]):
            try:
                r = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=10
                )
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout.splitlines()
            except Exception:
                continue
        return None

    @staticmethod
    def _is_external_source(src):
        """来源地址是否公网可路由。

        RFC1918 / CGNAT / 链路本地 / 回环 / IPv6 ULA 等非全局路由源段
        无法从公网到达，视为天然可信，不参与白名单比对。
        """
        try:
            return ipaddress.ip_network(src, strict=False).is_global
        except ValueError:
            # 无法解析的源按外部处理，保守告警
            return True

    @staticmethod
    def _port22_match(spec):
        """判断 --dport/--dports 规格是否覆盖端口 22（支持单端口与 lo:hi 范围）"""
        for item in spec.split(","):
            if ":" in item:
                lo, _, hi = item.partition(":")
                try:
                    if int(lo or 0) <= 22 <= int(hi or 65535):
                        return True
                except ValueError:
                    continue
            elif item == "22":
                return True
        return False

    @classmethod
    def _ssh_probe_verdict(cls, rules):
        """模拟外部任意来源 -> tcp/22 NEW 探测包逐条匹配 INPUT 规则。

        跟随 -j 跳转进入自定义链（如 SSH_RULES / DOCKER-USER / ufw-*），
        自定义链遍历到底相当于 RETURN 回到上级链继续匹配。

        返回 (verdict, allowed_sources)：
        - verdict: "open" 表示任意外部来源可连通，"restricted" 表示会被丢弃/拒绝
        - allowed_sources: 终止判定前遇到的、放行 tcp/22 的指定来源地址
        """
        chains = {}
        policies = {}
        for line in rules:
            parts = line.split()
            if len(parts) < 2:
                continue
            if parts[0] == "-P":
                policies[parts[1]] = parts[2] if len(parts) > 2 else "ACCEPT"
                chains.setdefault(parts[1], [])
            elif parts[0] == "-N":
                chains.setdefault(parts[1], [])
            elif parts[0] == "-A" and len(parts) > 2:
                chains.setdefault(parts[1], []).append(parts[2:])

        allowed = set()

        def probe(chain_name, stack):
            """返回 accept/drop/return；return 表示回到上级链继续匹配"""
            if chain_name in stack:
                return "return"
            stack = stack | {chain_name}
            for tokens in chains.get(chain_name, []):
                if "-j" not in tokens or "!" in tokens:
                    continue
                target = tokens[tokens.index("-j") + 1]

                def opt(name, _tokens=tokens):
                    return _tokens[_tokens.index(name) + 1] if name in _tokens else None

                proto = opt("-p")
                if proto and proto != "tcp":
                    continue
                if opt("-i") == "lo":
                    continue
                states = opt("--state") or opt("--ctstate")
                if states and "NEW" not in states.upper():
                    continue
                dport = opt("--dport") or opt("--dports")
                if dport and not cls._port22_match(dport):
                    continue

                src = (opt("-s") or "0.0.0.0/0").lstrip("!")
                if src in ("0.0.0.0/0", "0/0", "0.0.0.0", "::/0"):
                    # 探测包命中：首个匹配规则决定放行与否
                    if target == "ACCEPT":
                        return "accept"
                    if target in ("DROP", "REJECT"):
                        return "drop"
                    if target == "RETURN":
                        return "return"
                    if target in chains:
                        verdict = probe(target, stack)
                        if verdict != "return":
                            return verdict
                    # LOG 等非终止目标或未知链：继续匹配下一条
                    continue
                if target == "ACCEPT":
                    allowed.add(src)

            if chain_name in policies:
                return "accept" if policies[chain_name] == "ACCEPT" else "drop"
            # 自定义链遍历到底 = 隐式 RETURN，回到上级链
            return "return"

        return ("open" if probe("INPUT", frozenset()) == "accept" else "restricted"), allowed

    def _check_ssh_firewall(self, ipv6=False):
        """检查防火墙是否限制 SSH 仅允许可信来源访问"""
        label = "IPv6" if ipv6 else "IPv4"
        rules = self._iptables_rules(ipv6=ipv6)
        if rules is None:
            self.add_issue(
                "INFO", f"SSH {label} 防火墙状态未知",
                "无权限读取 iptables，无法确认外网访问限制"
            )
            return

        verdict, allowed = self._ssh_probe_verdict(rules)
        if verdict == "open":
            self.add_issue(
                "WARNING", f"SSH {label} 对外无限制开放",
                "防火墙未限制来源（若由安全组/NSG 限制可忽略）"
            )
            return

        # 归一化主机掩码（/32、/128）后再比对白名单
        def norm(src):
            for suffix in ("/32", "/128"):
                if src.endswith(suffix):
                    return src[: -len(suffix)]
            return src

        expected = {norm(s) for s in SSH_ALLOWED_SOURCES}
        external = {norm(s) for s in allowed if self._is_external_source(norm(s))}
        extra = external - expected if expected else set()
        if extra:
            self.add_issue(
                "WARNING", f"SSH {label} 放行来源异常",
                f"非预期来源: {', '.join(sorted(extra))}"
            )
            return

        print(f"[安全] ✅ SSH {label} 外部访问受限"
              f"（放行: {', '.join(sorted(allowed)) or '无'}）")
    
    def check_cpu_anomaly(self):
        """检查 CPU 使用异常"""
        print("\n[安全] 检查 CPU 使用率...")
        try:
            def get_cpu_times():
                with open("/proc/stat") as f:
                    parts = f.readline().split()[1:]
                    idle = float(parts[3]) + float(parts[4])
                    total = sum(float(x) for x in parts[:8])
                    return idle, total

            idle1, total1 = get_cpu_times()
            time.sleep(1.0)
            idle2, total2 = get_cpu_times()

            total_delta = total2 - total1
            idle_delta = idle2 - idle1
            usage = 0.0
            if total_delta > 0:
                usage = 100.0 * (1.0 - idle_delta / total_delta)

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
        
        # Docker 内部网络白名单 (172.16.0.0/12 - 172.31.255.255)
        # 包括常见的 Docker 网络: 172.17.x.x (bridge), 172.18.x.x, etc.
        docker_network_prefixes = [
            "172.16.", "172.17.", "172.18.", "172.19.",
            "172.20.", "172.21.", "172.22.", "172.23.",
            "172.24.", "172.25.", "172.26.", "172.27.",
            "172.28.", "172.29.", "172.30.", "172.31.",
            "10.0.", "10.1.", "10.2.", "10.3.",  # 其他常见内网
        ]
        
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
                
                # 跳过 Docker 内部网络连接 (避免误报)
                is_docker_network = any(peer_addr.startswith(prefix) for prefix in docker_network_prefixes)
                if is_docker_network:
                    # 记录跳过信息但不告警
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
        try:
            found_suspicious = False
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
                    reasons = self.classify_systemd_service(service_name, exec_start)
                    if reasons:
                        found_suspicious = True
                        detail = f"{service_name}: {'; '.join(reasons)}; {exec_start[:120]}"
                        self.add_issue("WARNING", "可疑 systemd 服务", detail)
            if not found_suspicious:
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
        # 支持多个 chat_id (逗号分隔)
        chat_ids = [cid.strip() for cid in TELEGRAM_CHAT_ID.split(',') if cid.strip()]
        
        for chat_id in chat_ids:
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                data = urllib.parse.urlencode({
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "Markdown"
                }).encode()
                
                req = urllib.request.Request(url, data=data)
                with urllib.request.urlopen(req, timeout=10) as response:
                    if response.status == 200:
                        print(f"[安全] ✅ Telegram 告警已发送 (to {chat_id})")
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
        self.check_ssh_listen_config()
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
