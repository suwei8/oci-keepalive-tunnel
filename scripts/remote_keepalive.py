#!/usr/bin/env python3
"""
福彩3D 深度 BPNN 预测保活脚本
- 从仓库 data/ 目录读取历史数据
- 运行深度 BP 神经网络训练 (2 隐藏层)
- 产生真实的 CPU/内存负载
- 纯 Python 实现，零依赖
"""

import csv
import os
import sys
import time
import random
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

# 使用纯 Python 实现，无需 numpy 依赖

# ============================================
# 系统资源监控
# ============================================

def get_system_stats():
    """获取并打印系统资源使用情况"""
    print("\n" + "=" * 50)
    print("📊 系统资源监控")
    print("=" * 50)
    
    # CPU 使用率 (从 /proc/stat 计算)
    try:
        with open("/proc/stat") as f:
            line = f.readline()
            parts = line.split()
            user, nice, system, idle = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
            total = user + nice + system + idle
            usage = 100 * (total - idle) / total if total > 0 else 0
            print(f"CPU 使用率: {usage:.1f}%")
    except Exception as e:
        print(f"CPU 使用率: 无法读取 ({e})")
    
    # 内存使用率 (从 /proc/meminfo)
    try:
        mem_info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    mem_info[parts[0].rstrip(":")] = int(parts[1])
        
        mem_total = mem_info.get("MemTotal", 0)
        mem_available = mem_info.get("MemAvailable", 0)
        mem_used = mem_total - mem_available
        mem_usage = 100 * mem_used / mem_total if mem_total > 0 else 0
        
        print(f"内存使用率: {mem_usage:.1f}% ({mem_used // 1024} MB / {mem_total // 1024} MB)")
    except Exception as e:
        print(f"内存使用率: 无法读取 ({e})")
    
    # 系统负载
    try:
        with open("/proc/loadavg") as f:
            loadavg = f.read().split()[:3]
            print(f"系统负载 (1/5/15分钟): {loadavg[0]} / {loadavg[1]} / {loadavg[2]}")
    except Exception as e:
        print(f"系统负载: 无法读取 ({e})")
    
    print("=" * 50 + "\n")

# 数据文件路径 (从仓库根目录读取)
# 脚本位于 scripts/remote_keepalive.py，数据在 data/fc3d_history.csv
SCRIPT_DIR = Path(__file__).parent.resolve()
REPO_ROOT = SCRIPT_DIR.parent
DATA_FILE = REPO_ROOT / "data" / "fc3d_history.csv"
PREDICTION_FILE = Path("/tmp/fc3d_predictions.log")

print("=" * 60)
print(f"福彩3D 深度 BPNN 预测保活任务")
print(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"主机名: {os.uname().nodename}")
print("=" * 60)


# ============================================
# 第一步：加载历史数据
# ============================================

def load_history() -> List[dict]:
    """从仓库 data/ 目录加载历史数据"""
    print(f"\n[数据] 加载数据文件: {DATA_FILE}")
    
    if not DATA_FILE.exists():
        print(f"[数据] ❌ 数据文件不存在")
        return []
    
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            data = [{"issue": r["issue"], "d1": int(r["d1"]), "d2": int(r["d2"]), 
                     "d3": int(r["d3"]), "date": r.get("date", "")} for r in reader]
        
        # 按期号排序
        data.sort(key=lambda x: x["issue"])
        print(f"[数据] ✅ 加载 {len(data)} 期数据")
        return data
    except Exception as e:
        print(f"[数据] ❌ 加载失败: {e}")
        return []


# ============================================
# 第二步：统计分析
# ============================================

def statistical_analysis(data: List[dict]):
    """统计分析 - 产生 CPU 负载 (纯 Python 实现)"""
    print("\n[统计] 执行统计分析...")
    
    # 频率统计
    freq = [[0] * 10 for _ in range(3)]
    for item in data:
        freq[0][item["d1"]] += 1
        freq[1][item["d2"]] += 1
        freq[2][item["d3"]] += 1
    
    print("[统计] 号码频率分布:")
    positions = ["百位", "十位", "个位"]
    for i, pos in enumerate(positions):
        top3 = sorted(range(10), key=lambda x: freq[i][x], reverse=True)[:3]
        cold3 = sorted(range(10), key=lambda x: freq[i][x])[:3]
        print(f"  {pos}: 热号 {top3[0]},{top3[1]},{top3[2]} | 冷号 {cold3[0]},{cold3[1]},{cold3[2]}")
    
    # 遗漏分析 (多次计算增加负载)
    print("[统计] 执行遗漏分析...")
    for round_num in range(20):  # 增加计算轮次
        missing = [[0] * 10 for _ in range(3)]
        for pos in range(3):
            for num in range(10):
                for i, item in enumerate(reversed(data)):
                    d = [item["d1"], item["d2"], item["d3"]][pos]
                    if d == num:
                        missing[pos][num] = i
                        break
        if (round_num + 1) % 5 == 0:
            print(f"[统计] 遗漏分析轮次 {round_num+1}/20")
    
    print("[统计] ✅ 统计分析完成")
    return freq





# ============================================
# 深度 BP 神经网络实现 (2 隐藏层, 无 numpy)
# ============================================

import math

class DeepBPNN:
    """
    深度 BP 神经网络 - 2 隐藏层架构
    结构: Input -> Hidden1 (128) -> Hidden2 (64) -> Output (10)
    特点: 更强的非线性拟合能力，更高的计算复杂度
    """
    def __init__(self, input_size, hidden1_size, hidden2_size, output_size, learning_rate=0.1):
        self.input_size = input_size
        self.hidden1_size = hidden1_size
        self.hidden2_size = hidden2_size
        self.output_size = output_size
        self.learning_rate = learning_rate
        self.initial_lr = learning_rate
        
        # Xavier 初始化 (更好的权重初始化)
        scale1 = math.sqrt(2.0 / (input_size + hidden1_size))
        scale2 = math.sqrt(2.0 / (hidden1_size + hidden2_size))
        scale3 = math.sqrt(2.0 / (hidden2_size + output_size))
        
        # 第一层权重: Input -> Hidden1
        self.W1 = [[random.uniform(-scale1, scale1) for _ in range(hidden1_size)] for _ in range(input_size)]
        self.B1 = [0.0 for _ in range(hidden1_size)]
        
        # 第二层权重: Hidden1 -> Hidden2
        self.W2 = [[random.uniform(-scale2, scale2) for _ in range(hidden2_size)] for _ in range(hidden1_size)]
        self.B2 = [0.0 for _ in range(hidden2_size)]
        
        # 第三层权重: Hidden2 -> Output
        self.W3 = [[random.uniform(-scale3, scale3) for _ in range(output_size)] for _ in range(hidden2_size)]
        self.B3 = [0.0 for _ in range(output_size)]
        
    def sigmoid(self, x):
        if x > 100: return 1.0
        if x < -100: return 0.0
        return 1.0 / (1.0 + math.exp(-x))
    
    def relu(self, x):
        return max(0.0, x)
    
    def relu_derivative(self, x):
        return 1.0 if x > 0 else 0.0
    
    def decay_learning_rate(self, epoch, decay_rate=0.995):
        """学习率衰减"""
        self.learning_rate = self.initial_lr * (decay_rate ** epoch)
        
    def forward(self, inputs):
        self.inputs = inputs
        
        # 第一隐藏层 (ReLU 激活)
        self.h1_raw = []
        self.h1_out = []
        for j in range(self.hidden1_size):
            activation = self.B1[j]
            for i in range(self.input_size):
                activation += inputs[i] * self.W1[i][j]
            self.h1_raw.append(activation)
            self.h1_out.append(self.relu(activation))
        
        # 第二隐藏层 (ReLU 激活)
        self.h2_raw = []
        self.h2_out = []
        for j in range(self.hidden2_size):
            activation = self.B2[j]
            for i in range(self.hidden1_size):
                activation += self.h1_out[i] * self.W2[i][j]
            self.h2_raw.append(activation)
            self.h2_out.append(self.relu(activation))
            
        # 输出层 (Sigmoid 激活 for probability)
        self.final_outputs = []
        for j in range(self.output_size):
            activation = self.B3[j]
            for i in range(self.hidden2_size):
                activation += self.h2_out[i] * self.W3[i][j]
            self.final_outputs.append(self.sigmoid(activation))
            
        return self.final_outputs
    
    def backward(self, expected):
        # 输出层误差 (Sigmoid derivative)
        output_errors = []
        for i in range(self.output_size):
            error = expected[i] - self.final_outputs[i]
            output_errors.append(error * self.final_outputs[i] * (1 - self.final_outputs[i]))
        
        # 第二隐藏层误差 (ReLU derivative)
        h2_errors = []
        for i in range(self.hidden2_size):
            error = 0.0
            for j in range(self.output_size):
                error += output_errors[j] * self.W3[i][j]
            h2_errors.append(error * self.relu_derivative(self.h2_raw[i]))
        
        # 第一隐藏层误差 (ReLU derivative)
        h1_errors = []
        for i in range(self.hidden1_size):
            error = 0.0
            for j in range(self.hidden2_size):
                error += h2_errors[j] * self.W2[i][j]
            h1_errors.append(error * self.relu_derivative(self.h1_raw[i]))
        
        # 更新 W3 和 B3
        for i in range(self.hidden2_size):
            for j in range(self.output_size):
                self.W3[i][j] += self.learning_rate * output_errors[j] * self.h2_out[i]
        for j in range(self.output_size):
            self.B3[j] += self.learning_rate * output_errors[j]
        
        # 更新 W2 和 B2
        for i in range(self.hidden1_size):
            for j in range(self.hidden2_size):
                self.W2[i][j] += self.learning_rate * h2_errors[j] * self.h1_out[i]
        for j in range(self.hidden2_size):
            self.B2[j] += self.learning_rate * h2_errors[j]
            
        # 更新 W1 和 B1
        for i in range(self.input_size):
            for j in range(self.hidden1_size):
                self.W1[i][j] += self.learning_rate * h1_errors[j] * self.inputs[i]
        for j in range(self.hidden1_size):
            self.B1[j] += self.learning_rate * h1_errors[j]

def one_hot_encode(digit):
    vec = [0.0] * 10
    vec[digit] = 1.0
    return vec

def train_pure_python(data: List[dict], seq_len: int, target_duration: int = 300) -> Tuple[int, int, int]:
    """
    深度 BP 神经网络预测 (2 隐藏层架构)
    - 更长的训练时间 (300秒) 以提高准确率
    - 更深的网络结构 (128 + 64 隐藏层)
    - 学习率衰减策略
    """
    print(f"[训练] 使用深度 BP 神经网络 (2 隐藏层)，目标运行时间: {target_duration}秒...")
    
    # 使用更长的序列来捕获更多历史模式
    effective_seq_len = min(seq_len, 50)  # 最多使用 50 期历史
    
    # 特征工程
    # 输入特征: seq_len 期的 d1, d2, d3 (共 seq_len * 3 个特征)
    input_size = effective_seq_len * 3
    hidden1_size = 128  # 第一隐藏层
    hidden2_size = 64   # 第二隐藏层
    output_size = 10    # 输出 0-9 的概率
    
    print(f"[训练] 网络结构: {input_size} -> {hidden1_size} -> {hidden2_size} -> {output_size}")
    
    # 为三个位置分别创建深度网络
    nn_d1 = DeepBPNN(input_size, hidden1_size, hidden2_size, output_size, learning_rate=0.05)
    nn_d2 = DeepBPNN(input_size, hidden1_size, hidden2_size, output_size, learning_rate=0.05)
    nn_d3 = DeepBPNN(input_size, hidden1_size, hidden2_size, output_size, learning_rate=0.05)
    
    start_time = time.time()
    epoch = 0
    samples_processed = 0
    total_loss = 0.0
    
    # 准备训练数据
    train_data = []
    for i in range(len(data) - effective_seq_len):
        inputs = []
        for j in range(effective_seq_len):
            item = data[i + j]
            # 归一化输入到 [0, 1]
            inputs.extend([item["d1"]/9.0, item["d2"]/9.0, item["d3"]/9.0])
        
        target = data[i + effective_seq_len]
        train_data.append({
            "inputs": inputs,
            "d1": target["d1"],
            "d2": target["d2"],
            "d3": target["d3"]
        })
    
    print(f"[训练] 训练集样本数: {len(train_data)}, 输入维度: {input_size}")
    
    # 持续训练直到达到目标时间
    while time.time() - start_time < target_duration:
        epoch += 1
        epoch_loss = 0.0
        
        # 学习率衰减
        if epoch % 10 == 0:
            nn_d1.decay_learning_rate(epoch)
            nn_d2.decay_learning_rate(epoch)
            nn_d3.decay_learning_rate(epoch)
        
        # 遍历所有训练样本
        for sample in train_data:
            # 训练 D1 网络
            out1 = nn_d1.forward(sample["inputs"])
            target1 = one_hot_encode(sample["d1"])
            nn_d1.backward(target1)
            
            # 训练 D2 网络
            out2 = nn_d2.forward(sample["inputs"])
            target2 = one_hot_encode(sample["d2"])
            nn_d2.backward(target2)
            
            # 训练 D3 网络
            out3 = nn_d3.forward(sample["inputs"])
            target3 = one_hot_encode(sample["d3"])
            nn_d3.backward(target3)
            
            # 计算损失 (用于监控收敛)
            for k in range(10):
                epoch_loss += (target1[k] - out1[k]) ** 2
                epoch_loss += (target2[k] - out2[k]) ** 2
                epoch_loss += (target3[k] - out3[k]) ** 2
            
            samples_processed += 1
            
            # 检查时间
            if samples_processed % 500 == 0:
                if time.time() - start_time >= target_duration:
                    break
        
        total_loss = epoch_loss / len(train_data)
        
        if time.time() - start_time >= target_duration:
            break
            
        if epoch % 10 == 0:
            elapsed = time.time() - start_time
            lr = nn_d1.learning_rate
            print(f"[训练] 轮次 {epoch}, 样本 {samples_processed}, 损失 {total_loss:.4f}, LR {lr:.5f}, 耗时 {elapsed:.1f}s/{target_duration}s")

    # 预测下一期
    last_seq = []
    for i in range(effective_seq_len):
        item = data[-(effective_seq_len - i)]
        last_seq.extend([item["d1"]/9.0, item["d2"]/9.0, item["d3"]/9.0])
    
    # 获取预测概率
    prob_d1 = nn_d1.forward(last_seq)
    prob_d2 = nn_d2.forward(last_seq)
    prob_d3 = nn_d3.forward(last_seq)
    
    # 选择概率最大的数字
    d1 = prob_d1.index(max(prob_d1))
    d2 = prob_d2.index(max(prob_d2))
    d3 = prob_d3.index(max(prob_d3))
    
    total_time = time.time() - start_time
    print(f"[训练] ✅ 深度 BPNN 训练完成")
    print(f"[训练]    总轮次: {epoch}, 总样本: {samples_processed}, 最终损失: {total_loss:.4f}")
    print(f"[训练]    总耗时: {total_time:.1f}s")
    print(f"[训练]    D1 概率分布: max={max(prob_d1):.3f}, 预测={d1}")
    print(f"[训练]    D2 概率分布: max={max(prob_d2):.3f}, 预测={d2}")
    print(f"[训练]    D3 概率分布: max={max(prob_d3):.3f}, 预测={d3}")
    
    return d1, d2, d3


def save_prediction(issue: str, d1: int, d2: int, d3: int, hostname: str = None, model_type: str = "pure_python"):
    """保存预测结果为 JSON 格式 (供 GitHub Actions 收集)"""
    import json
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # 使用传入的 hostname，否则使用系统 hostname
    if hostname is None:
        hostname = os.uname().nodename
    
    result = {
        "timestamp": timestamp,
        "hostname": hostname,
        "issue": issue,
        "d1": d1,
        "d2": d2,
        "d3": d3,
        "model_type": model_type
    }
    
    # 保存到固定位置供回传
    result_file = Path("/tmp/prediction_result.json")
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    # 同时追加到本地日志
    with open(PREDICTION_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{timestamp} | {hostname} | 预测({issue}后): {d1} {d2} {d3}\n")
    
    print(f"[预测] 结果已保存到 {result_file}")


# ============================================
# 第四步：内存活动
# ============================================

def memory_activity(duration: int = 180):
    """内存压力测试 - 增强版"""
    print(f"\n[内存] 开始内存活动 ({duration}秒)...")
    
    try:
        mem_avail = 0
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    mem_avail = int(line.split()[1]) * 1024
                    break
        
        # 分配 35% 可用内存，最大 3GB (增加一点比例)
        target_size = int(mem_avail * 0.35)
        # 限制在 reasonable 范围
        size = min(3 * 1024 * 1024 * 1024, max(100 * 1024 * 1024, target_size))
        
        print(f"[内存] 分配 {size / 1024 / 1024:.0f} MB")
        
        # 使用 bytearray 分配内存
        b = bytearray(size)
        
        # 填充数据
        for i in range(0, size, 4096):
            b[i] = 1
            
        print("[内存] 内存已分配，开始活跃读写...")
        
        start = time.time()
        end = start + duration
        
        # 动态步长，确保每轮循环既有访问又有一定CPU
        step = 1024 # 比之前的 4096 更密集
        
        while time.time() < end:
            # 遍历并修改内存，防止被 swap out，同时消耗 CPU
            # 这个循环在 Python 中会比较慢，本身就是 CPU 负载
            count = 0
            for i in range(0, size, step):
                b[i] = (b[i] + 1) & 0xFF
                count += 1
                # 每修改 10000 次检查时间，避免卡太久
                if count % 10000 == 0 and time.time() > end:
                    break
            
            elapsed = time.time() - start
            left = duration - elapsed
            if left > 0:
                 # 稍微休眠让系统喘息，防止 SSH 断连，但时间很短
                time.sleep(0.1) 
                if int(elapsed) % 30 == 0:
                    print(f"[内存] 运行中... 剩余 {left:.0f}s")
        
        print("[内存] ✅ 内存活动完成")
        del b
        
    except Exception as e:
        print(f"[内存] ❌ 内存活动出错: {e}")


# ============================================
# 主程序
# ============================================

def run_training_process(hostname, data, latest_issue, target_duration):
    """单独的训练进程函数"""
    print(f"[进程] 启动训练进程 (PID: {os.getpid()})")
    
    # 注意：多进程中如果不重新设置随机种子，可能产生相同结果
    random.seed(os.getpid() + time.time())
    
    seq_len = min(50, len(data) - 10)  # 使用更长的序列
    
    # 纯 Python BPNN 训练
    d1, d2, d3 = train_pure_python(data, seq_len, target_duration)
    
    # 只有主进程负责保存预测结果到文件（通过 hostname 区分或仅主进程保存）
    return d1, d2, d3

def main(hostname: str = None):
    print("\n" + "=" * 60)
    print("开始保活任务")
    if hostname:
        print(f"主机名称: {hostname}")
    print("=" * 60)
    
    # 检查并清理重复进程
    current_pid = os.getpid()
    print(f"\n[启动] 当前进程 PID: {current_pid}")
    print("[启动] 检查是否存在重复的保活进程...")
    
    try:
        # 查找本项目的保活进程 (匹配实际运行的命令)
        result = subprocess.run(
            ["pgrep", "-f", "scripts/remote_keepalive.py"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            pids = [int(p.strip()) for p in result.stdout.strip().split('\n') if p.strip()]
            other_pids = [p for p in pids if p != current_pid]
            
            if other_pids:
                print(f"[启动] ⚠️ 发现 {len(other_pids)} 个重复进程: {other_pids}")
                for pid in other_pids:
                    try:
                        os.kill(pid, 9)  # SIGKILL
                        print(f"[启动] ✅ 已终止进程 {pid}")
                    except ProcessLookupError:
                        print(f"[启动] 进程 {pid} 已不存在")
                    except PermissionError:
                        print(f"[启动] ⚠️ 无权限终止进程 {pid}")
                # 等待进程清理
                time.sleep(1)
            else:
                print("[启动] ✅ 无重复进程")
        else:
            print("[启动] ✅ 无重复进程")
    except Exception as e:
        print(f"[启动] 检查进程时出错: {e}")
    
    # 初始系统状态
    os.system("uname -a")
    os.system("uptime")
    get_system_stats()  # 任务开始前的资源状态
    
    # 0. 安全检测 (必须在保活任务之前执行)
    try:
        from security_check import run_security_checks
        issues, has_critical = run_security_checks(hostname)
        if issues:  # 任何安全问题都中止保活
            print("\n" + "!" * 60)
            print(f"⛔ 发现 {len(issues)} 个安全问题，中止保活任务！")
            print("请先处理安全问题后再运行保活。")
            print("!" * 60)
            return
        print("\n✅ 安全检测通过，开始保活任务...")
    except Exception as e:
        print(f"\n[安全] ⚠️ 安全检测出错: {e}")
        # 安全检测失败不阻止保活，仅警告
    
    # 1. 自适应资源检测
    cpu_count = os.cpu_count() or 1
    
    mem_total_kb = 0
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                mem_total_kb = int(line.split()[1])
                break
    mem_total_gb = mem_total_kb / 1024 / 1024
    
    print("\n" + "-" * 40)
    print(f"硬件检测: CPU={cpu_count}核, 内存={mem_total_gb:.1f}GB")
    
    # 策略决策: 多进程策略 (避免过高或过低)
    # 目标: 让 CPU 达到 50-75%，既满足保活要求又避免触发风控
    if cpu_count >= 3:
        training_processes = cpu_count - 1  # 3核用2进程(66%), 4核用3进程(75%)
    else:
        training_processes = 1  # 2核用1进程 (50%)，避免100%触发风控
    
    print(f"策略调整: {cpu_count}核CPU → 启动 {training_processes} 个并发训练进程 (目标CPU 50-75%)")

    print("-" * 40)
    
    # 2. 加载数据
    print("\n" + "-" * 40)
    print("第一步: 加载福彩3D历史数据")
    print("-" * 40)
    
    history = load_history()
    
    if len(history) < 50:
        print(f"[错误] 数据不足 ({len(history)} 期)")
        return
    
    latest_issue = history[-1]["issue"]
    
    # 3. BPNN 训练和预测 (支持多进程)
    print("\n" + "-" * 40)
    print("第二步: BPNN 模型训练与预测")
    print("-" * 40)
    
    target_duration = 300  # 5分钟深度训练
    d1, d2, d3 = 0, 0, 0
    
    if training_processes > 1:
        from multiprocessing import Pool
        
        with Pool(processes=training_processes) as pool:
            results = []
            for i in range(training_processes):
                results.append(pool.apply_async(run_training_process, (hostname, history, latest_issue, target_duration)))
            
            # 等待所有进程完成
            final_results = [r.get() for r in results]
            
            # 使用第一个进程的结果作为最终预测
            d1, d2, d3 = final_results[0]
            print(f"[主进程] 所有训练进程已完成")
            
    else:
        # 单进程模式直接运行
        d1, d2, d3 = train_pure_python(history, min(50, len(history) - 10), target_duration)

    # 训练后的资源状态
    get_system_stats()
    
    # 预测目标是下一期 (当前最新期 + 1)
    next_issue = str(int(latest_issue) + 1)
    
    print("\n" + "=" * 60)
    print(f"🎯 预测结果 (第 {next_issue} 期)")
    print(f"   预测号码: {d1}  {d2}  {d3}")
    print("=" * 60)
    
    save_prediction(next_issue, d1, d2, d3, hostname=hostname)
    
    # 4. 内存活动 (自适应)
    print("\n" + "-" * 40)
    print("第三步: 神经网络数据缓存 (Deep Learning Cache)")
    print("-" * 40)
    
    # 内存策略 (用户指定: 激进模式，占用所有空闲内存，仅预留 3GB 给系统)
    mem_avail_kb = 0
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                mem_avail_kb = int(line.split()[1])
                break
    
    mem_avail_bytes = mem_avail_kb * 1024
    reserved_bytes = 5 * 1024 * 1024 * 1024  # 5GB 预留给系统和其他业务 (用户调整)
    
    # 目标占用 = 可用 - 预留
    target_mem_size = mem_avail_bytes - reserved_bytes
    
    # 兜底逻辑：如果剩余空间不足 3GB，则至少运行 512MB
    if target_mem_size < 512 * 1024 * 1024:
        final_size = 512 * 1024 * 1024 # 最小 512MB
        print(f"[缓存] ⚠️ 系统可用内存紧张 ({mem_avail_bytes/1024/1024:.0f}MB < 预留5GB)，强制最小缓存: 512 MB")
    else:
        final_size = target_mem_size
        
    print(f"[缓存] 策略: 激进模式 (可用 {mem_avail_bytes/1024/1024:.0f}MB - 预留 5120MB)")
    print(f"[缓存] 构建历史模式矩阵: {final_size/1024/1024:.0f} MB")
    
    memory_activity_run(final_size, 180)
    
    # 最终资源状态
    get_system_stats()
    
    # 完成
    print("\n" + "=" * 60)
    print(f"保活任务完成")
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

def memory_activity_run(size, duration):
    """实际执行内存活动 - 模拟矩阵运算缓存"""
    try:
        # 模拟：初始化大矩阵用于存储历史模式权重
        print(f"[缓存]正在分配神经元权重矩阵 ({size/1024/1024:.0f} MB)...")
        b = bytearray(size)
        
        # 填充模拟数据 (Patterns)
        print("[缓存] 正在生成随机模式数据以填充矩阵...")
        # Step 1: 快速填充基础数据
        step_init = 4096
        for i in range(0, size, step_init): 
            b[i] = i % 255
            
        print("[缓存] ✅ 矩阵初始化完成，开始活跃权重更新 (Active Weight Updates)...")
        start = time.time()
        end = start + duration
        
        # 动态步长
        step = 1024
        
        while time.time() < end:
            count = 0
            # 模拟矩阵权重更新操作
            for i in range(0, size, step):
                # 简单的异或操作模拟权重调整
                b[i] = (b[i] ^ 0xFF) & 0xFF
                count += 1
                if count % 20000 == 0 and time.time() > end: break
            
            elapsed = time.time() - start
            left = duration - elapsed
            if left > 0:
                time.sleep(0.1) 
                if int(elapsed) % 30 == 0:
                    print(f"[缓存] 权重更新中... 剩余 {left:.0f}s")
        del b
        print("[缓存] ✅ 训练数据缓存释放完毕")
    except Exception as e:
        print(f"[缓存] ❌ 矩阵运算出错: {e}")


# ============================================
# 福彩3D 数据分析任务 (AMD64 专用 - Micro Mode)
# ============================================

class LotteryTask:
    """
    福彩3D 数据分析与发布任务
    - 下载/解压/解析 2GB SQL 文件
    - 流式处理防止 OOM
    - 生成统计报表
    """
    def __init__(self, work_dir="/tmp/lottery_task"):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(exist_ok=True, parents=True)
        self.password = "sw@63828".encode('utf-8')
        
    def run(self, hostname=None):
        print("\n" + "=" * 40)
        print("🦄 启动 Micro Mode: 福彩3D 数据分析任务")
        print("=" * 40)
        
        try:
            # 1. 获取最新 Release 下载地址
            print("[Lottery] 正在获取最新数据库备份地址...")
            import json
            import urllib.request
            
            api_url = "https://api.github.com/repos/suwei8/lotto_ai3_v2-Backup_data/releases/latest"
            try:
                with urllib.request.urlopen(api_url) as response:
                    data = json.loads(response.read().decode())
                    assets = data.get("assets", [])
                    if not assets:
                        print("[Lottery] ❌ 未找到 Release Assets")
                        return False
                    download_url = assets[0]["browser_download_url"]
                    file_name = assets[0]["name"]
                    print(f"[Lottery] 目标文件: {file_name}")
            except Exception as e:
                print(f"[Lottery] API 请求失败: {e} (使用默认备份)")
                # Fallback to hardcoded example if API fails
                download_url = "https://github.com/suwei8/lotto_ai3_v2-Backup_data/releases/download/backup-20251213/lotto_20251213_backup.zip"
                file_name = "lotto_20251213_backup.zip"

            zip_path = self.work_dir / file_name
            
            # 2. 下载 (大流量)
            print(f"[Lottery] 开始下载 (制造网络负载): {download_url}")
            start_t = time.time()
            subprocess.run(["curl", "-L", "-o", str(zip_path), download_url], check=True)
            dl_time = time.time() - start_t
            size_mb = zip_path.stat().st_size / 1024 / 1024
            print(f"[Lottery] ✅ 下载完成: {size_mb:.2f}MB, 耗时 {dl_time:.1f}s, Speed: {size_mb/dl_time:.2f}MB/s")
            
            # 3. 解压 (CPU 密集)
            print("[Lottery] 开始解密与解压 (CPU 密集)...")
            # 使用系统 unzip (Python zipfile 处理加密可能有兼容问题)
            # 注意: 如果是 7z 格式的 zip，unzip 可能不行。这里假设是标准 zip。
            # 如果 unzip 不支持 AES，则可能失败。尝试使用 python zipfile。
            extracted_sql = None
            
            try:
                import zipfile
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    # 寻找最大的 .sql 文件
                    sql_files = [f for f in zf.namelist() if f.endswith('.sql')]
                    if not sql_files:
                        print("[Lottery] ❌ 未找到 .sql 文件")
                        return False
                    
                    target_sql = sql_files[0] 
                    print(f"[Lottery] 正在解压: {target_sql} (密码保护)")
                    # ZipFile setpassword 需要 bytes
                    zf.setpassword(self.password)
                    zf.extract(target_sql, path=self.work_dir)
                    extracted_sql = self.work_dir / target_sql
            except RuntimeError as e: # Bad password or encryption
                 print(f"[Lottery] Python解压失败 (可能是AES加密): {e}. 尝试系统 7z/unzip...")
                 # try 7z if available
                 if subprocess.run(["which", "7z"], capture_output=True).returncode == 0:
                     subprocess.run(["7z", "x", f"-p{self.password.decode()}", "-y", f"-o{self.work_dir}", str(zip_path)], check=True)
                     # Find sql again
                     for f in self.work_dir.glob("*.sql"):
                         extracted_sql = f
                         break
                 elif subprocess.run(["which", "unzip"], capture_output=True).returncode == 0:
                      subprocess.run(["unzip", "-P", self.password.decode(), "-o", str(zip_path), "-d", str(self.work_dir)], check=True)
                      for f in self.work_dir.glob("*.sql"):
                         extracted_sql = f
                         break
            
            if not extracted_sql or not extracted_sql.exists():
                print("[Lottery] ❌ 解压失败，跳过后续分析")
                return False
                
            print(f"[Lottery] ✅ 解压完成: {extracted_sql.name} ({extracted_sql.stat().st_size/1024/1024:.2f} MB)")
            
            # 4.5. Release 流量循环 (Upload -> Sleep -> Delete)
            print("[Lottery] 执行 GitHub Release 流量模拟...")
            # CSV 必须存在
            csv_path = Path("/tmp/lottery_stats.csv") 
            if csv_path.exists():
                self.release_ops(zip_path, csv_path, hostname=hostname)
            
            # 5. 清理 (保持环境整洁)
            try:
                if zip_path.exists(): os.remove(zip_path)
                if extracted_sql and extracted_sql.exists(): os.remove(extracted_sql)
                if csv_path.exists(): os.remove(csv_path)
                print("[Lottery] 🧹 临时文件已清理")
            except: pass
            
            return True
            
        except Exception as e:
            print(f"[Lottery] ❌ 任务执行出错: {e}")
            import traceback
            traceback.print_exc()
            return False

    def release_ops(self, zip_file, csv_file, hostname=None):
        """执行 Release 上传与删除循环 (模拟上传流量)"""
        token = os.environ.get("GITHUB_TOKEN")
        owner = os.environ.get("REPO_OWNER")
        repo = os.environ.get("REPO_NAME")
        
        if not token or not owner or not repo:
            print("[Lottery] ⚠️ 缺少 GITHUB_TOKEN/REPO 信息，跳过 Release 操作")
            return
            
        print("\n" + "-" * 30)
        print("[Lottery] 启动 Release 流量模拟循环 (Upload -> Sleep -> Delete)")
        print("-" * 30)
        
        # 确保 urllib/json 可用
        import json
        import urllib.request
        
        tag_name = f"lottery-ops-{hostname or 'unknown'}-{int(time.time())}"
        release_name = f"Lottery Data Backup - {hostname}"
        
        try:
            # 1. 创建 Release
            print(f"[Lottery] 创建 Release: {tag_name}")
            create_url = f"https://api.github.com/repos/{owner}/{repo}/releases"
            data = {
                "tag_name": tag_name,
                "target_commitish": "main",
                "name": release_name,
                "body": f"Temporary release for traffic simulation. Host: {hostname}",
                "draft": False,
                "prerelease": True
            }
            
            req = urllib.request.Request(create_url, data=json.dumps(data).encode(), headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json"
            })
            
            release_id = None
            upload_url_template = ""
            
            try:
                with urllib.request.urlopen(req) as resp:
                    release_info = json.loads(resp.read().decode())
                    upload_url_template = release_info["upload_url"] 
                    release_id = release_info["id"]
            except urllib.error.HTTPError as e:
                print(f"[Lottery] 创建 Release 失败: {e.code} {e.read().decode()}")
                return

            upload_base = upload_url_template.split('{')[0]
            
            # 2. 上传文件 (CSV & Large Zip)
            files_to_upload = [csv_file]
            if zip_file and zip_file.exists():
                files_to_upload.append(zip_file)
                
            for fpath in files_to_upload:
                if not fpath.exists(): continue
                
                print(f"[Lottery] 正在上传: {fpath.name} ({fpath.stat().st_size/1024/1024:.2f} MB)...")
                # Header: Content-Type: application/octet-stream
                dest_url = f"{upload_base}?name={fpath.name}"
                
                # curl call
                cmd = [
                    "curl", "-s", "-S", "-X", "POST",
                    "-H", f"Authorization: token {token}",
                    "-H", "Content-Type: application/octet-stream",
                    "--data-binary", f"@{str(fpath)}",
                    dest_url
                ]
                # 允许上传耗时较长
                p = subprocess.run(cmd, capture_output=True, text=True)
                if p.returncode == 0:
                    print(f"[Lottery] ✅ 上传成功: {fpath.name}")
                else:
                    print(f"[Lottery] ❌ 上传失败: {p.stderr}")

            # 3. 停留 (保持 Release 存在)
            print("[Lottery] ⏳ 保持 Release 存在 5 分钟 (流量模拟)...")
            time.sleep(300)
            
            # 4. 删除 Release & Tag
            print("[Lottery] 清理 Release...")
            if release_id:
                del_url = f"https://api.github.com/repos/{owner}/{repo}/releases/{release_id}"
                req_del = urllib.request.Request(del_url, method="DELETE", headers={
                    "Authorization": f"token {token}"
                })
                try:
                    with urllib.request.urlopen(req_del):
                        print(f"[Lottery] Release {release_id} 已删除")
                except Exception as e:
                    print(f"[Lottery] Release 删除失败: {e}")
                
            # 删除 Tag
            print(f"[Lottery] 清理 Tag: {tag_name}")
            tag_url = f"https://api.github.com/repos/{owner}/{repo}/git/refs/tags/{tag_name}"
            req_tag = urllib.request.Request(tag_url, method="DELETE", headers={
                "Authorization": f"token {token}"
            })
            try:
                with urllib.request.urlopen(req_tag):
                    print(f"[Lottery] Tag {tag_name} 已删除")
            except:
                print(f"[Lottery] Tag 删除可能有延迟或失败 (非致命)")
                
        except Exception as e:
            print(f"[Lottery] ❌ Release 操作流程异常: {e}")

    def stream_parse_and_stats(self, sql_file):
        """流式解析 SQL 并统计福彩3D数据"""
        stats_cnt = 0
        target_table = "lottery_results_3d"
        # 仅保留最近 200 条数据用于分析
        recent_data = []
        
        start_t = time.time()
        
        # 逐行读取，防止 OOM
        with open(sql_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if target_table in line and "INSERT INTO" in line:
                    # 粗略解析 VALUES
                    # 假设格式: VALUES (id, 'issue', 'd1', 'd2', 'd3', ...)
                    try:
                        # 查找第一个 ( 和最后一个 )
                        start = line.find('(')
                        end = line.rfind(')')
                        if start != -1 and end != -1:
                            values = line[start+1:end].split(',')
                            if len(values) >= 5: # 至少包含期号和三个球
                                # 清洗引号
                                row = [v.strip().strip("'").strip('"') for v in values]
                                # 假设 1=issue, 2=d1, 3=d2, 4=d3 (根据实际结构可能调整，这里做盲猜解析)
                                # 也可以通过正则更精确提取，这里为了 CPU 负载，用 split 足够
                                # 简单的有效性检查: d1/d2/d3 应该是 0-9
                                if row[2].isdigit() and row[3].isdigit() and row[4].isdigit():
                                    recent_data.append({
                                        "issue": row[1],
                                        "d1": int(row[2]),
                                        "d2": int(row[3]),
                                        "d3": int(row[4])
                                    })
                                    if len(recent_data) > 200:
                                        recent_data.pop(0) # 保持窗口大小
                                    stats_cnt += 1
                    except:
                        pass
                
                # 每 10000 行 插入微小 sleep 模拟 CPU 呼吸
                if stats_cnt % 5000 == 0 and stats_cnt > 0:
                     time.sleep(0.001)

        print(f"[Lottery] ✅ 解析完成，提取记录: {stats_cnt} 条, 耗时 {time.time()-start_t:.1f}s")
        
        if recent_data:
            print("[Lottery] 执行 200 期形态分析...")
            # 统计组三/组六/豹子
            z3, z6, bz = 0, 0, 0
            for item in recent_data:
                nums = sorted([item["d1"], item["d2"], item["d3"]])
                if nums[0] == nums[1] == nums[2]:
                    bz += 1
                elif nums[0] == nums[1] or nums[1] == nums[2]:
                    z3 += 1
                else:
                    z6 += 1
            
            print(f"[Lottery] 统计结果 (近 {len(recent_data)} 期):")
            print(f"   豹子: {bz} ({bz/len(recent_data)*100:.1f}%)")
            print(f"   组三: {z3} ({z3/len(recent_data)*100:.1f}%)")
            print(f"   组六: {z6} ({z6/len(recent_data)*100:.1f}%)")
            
            # 保存到 CSV (Micro Mode 结果)
            csv_path = Path("/tmp/lottery_stats.csv")
            with open(csv_path, 'w') as f:
                f.write("timestamp,bz_count,z3_count,z6_count,sample_size\n")
                f.write(f"{datetime.now()},{bz},{z3},{z6},{len(recent_data)}\n")
            print(f"[Lottery] 统计报表已生成: {csv_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='福彩3D BPNN 预测保活脚本')
    parser.add_argument('--hostname', '-n', type=str, default=None,
                        help='主机名称 (用于预测结果记录)')
    args = parser.parse_args()

    # 硬件检测
    mem_total_kb = 0
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                mem_total_kb = int(line.split()[1])
                break
    mem_total_gb = mem_total_kb / 1024 / 1024
    
    # Micro Mode 判定 (内存小于 2GB)
    if mem_total_gb < 2.0:
        print("\n" + "*" * 50)
        print(f"🚀 检测到低配实例 ({mem_total_gb:.1f}GB < 2.0GB)")
        print("🚀 自动切换至 Micro Mode (微创保活模式)")
        print("*" * 50)
        
        # 1. 内存占位 (静态引擎) - 40% Available
        mem_avail_kb = 0
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    mem_avail_kb = int(line.split()[1])
                    break
        target_size = int(mem_avail_kb * 1024 * 0.40) # 40%
        print(f"[Micro] 分配基础内存底座: {target_size/1024/1024:.0f} MB (40%)")
        # 申请并保持内存
        buffer = bytearray(target_size)
        for i in range(0, len(buffer), 4096): buffer[i] = 1 # 触碰以实际分配
        
        # 2. 执行 Lottery 任务 (动态引擎)
        task = LotteryTask()
        task.run(hostname=args.hostname)
        
        # 3. 释放内存
        del buffer
        print("[Micro] ✅ 任务完成，资源释放")
        
    else:
        # 正常模式 (High Spec)
        main(hostname=args.hostname)
