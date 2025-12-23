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
        # 查找所有 remote_keepalive.py 进程
        result = subprocess.run(
            ["pgrep", "-f", "remote_keepalive.py"],
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
    if cpu_count >= 4:
        training_processes = cpu_count - 1  # 4核用3进程 (75%)
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
    
    print("\n" + "=" * 60)
    print(f"🎯 预测结果 (第 {latest_issue} 期之后)")
    print(f"   预测号码: {d1}  {d2}  {d3}")
    print("=" * 60)
    
    save_prediction(latest_issue, d1, d2, d3, hostname=hostname)
    
    # 4. 内存活动 (自适应)
    print("\n" + "-" * 40)
    print("第三步: 内存活动 (自适应)")
    print("-" * 40)
    
    # 内存策略：根据 CPU 核心数调整，避免满载
    # 4核机器训练进程已占用较多内存，降低额外分配
    if cpu_count >= 4:
        mem_percent = 0.12  # 4核机器: 12% (~3GB for 24GB)
        mem_cap = 3 * 1024 * 1024 * 1024  # 上限 3GB
    else:
        mem_percent = 0.20  # 2核机器: 20% (~2.4GB for 12GB)
        mem_cap = 2 * 1024 * 1024 * 1024  # 上限 2GB
    
    target_mem_size = int(mem_total_kb * 1024 * mem_percent)
    
    # 安全上限和下限 (500MB)
    safe_mem_size = min(mem_cap, max(500 * 1024 * 1024, target_mem_size))
    
    # 检查可用内存，防止 OOM (保留 30%)
    mem_avail_kb = 0
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                mem_avail_kb = int(line.split()[1])
                break
    
    safe_limit = int(mem_avail_kb * 1024 * 0.7)  # 只用可用内存的 70%
    final_size = min(safe_mem_size, safe_limit)
    
    print(f"[内存] 策略: 目标{int(mem_percent*100)}%({target_mem_size/1024/1024:.0f}MB), 上限{mem_cap/1024/1024/1024:.0f}GB, 可用{safe_limit/1024/1024:.0f}MB")
    print(f"[内存] 最终执行: {final_size/1024/1024:.0f} MB")
    
    memory_activity_run(final_size, 180)
    
    # 最终资源状态
    get_system_stats()
    
    # 完成
    print("\n" + "=" * 60)
    print(f"保活任务完成")
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

def memory_activity_run(size, duration):
    """实际执行内存活动"""
    try:
        b = bytearray(size)
        # 填充
        for i in range(0, size, 4096): b[i] = 1
            
        print("[内存] 内存已分配，开始活跃读写...")
        start = time.time()
        end = start + duration
        step = 1024
        
        while time.time() < end:
            count = 0
            for i in range(0, size, step):
                b[i] = (b[i] + 1) & 0xFF
                count += 1
                if count % 10000 == 0 and time.time() > end: break
            
            elapsed = time.time() - start
            left = duration - elapsed
            if left > 0:
                time.sleep(0.1) 
                if int(elapsed) % 30 == 0:
                    print(f"[内存] 运行中... 剩余 {left:.0f}s")
        del b
        print("[内存] ✅ 内存活动完成")
    except Exception as e:
        print(f"[内存] ❌ 内存活动出错: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='福彩3D BPNN 预测保活脚本')
    parser.add_argument('--hostname', '-n', type=str, default=None,
                        help='主机名称 (用于预测结果记录)')
    args = parser.parse_args()
    main(hostname=args.hostname)
