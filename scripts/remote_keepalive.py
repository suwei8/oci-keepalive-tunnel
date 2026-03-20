#!/usr/bin/env python3
"""
福彩3D 深度 BPNN 预测保活脚本
- 从仓库 data/ 目录读取历史数据
- 运行深度 BP 神经网络训练 (2 隐藏层)
- 产生节流式、本地化的 CPU/内存活动
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
    
    # CPU 使用率 (1 秒窗口，避免单次读取 /proc/stat 的累计口径失真)
    try:
        usage = check_current_cpu_usage()
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

def check_current_cpu_usage() -> float:
    """实时检测当前 CPU 使用率 (1秒窗口)"""
    try:
        def get_cpu_times():
            with open("/proc/stat", "r") as f:
                parts = f.readline().split()[1:]
                idle = float(parts[3])
                total = sum(float(x) for x in parts)
                return idle, total
                
        idle1, total1 = get_cpu_times()
        time.sleep(1.0)
        idle2, total2 = get_cpu_times()
        
        idle_delta = idle2 - idle1
        total_delta = total2 - total1
        
        if total_delta > 0:
            return 100.0 * (1.0 - idle_delta / total_delta)
    except Exception as e:
        print(f"[警告] 读取 CPU 状态失败: {e}")
    return 0.0

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

def train_pure_python(
    data: List[dict],
    seq_len: int,
    target_duration: int = 180,
    throttle_every: int = 80,
    throttle_sleep: float = 0.03,
) -> Tuple[int, int, int]:
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

            # 通过短暂休眠打散连续高占用，避免形成长时间接近满核的挖矿特征
            if throttle_every > 0 and samples_processed % throttle_every == 0:
                time.sleep(throttle_sleep)
            
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

def memory_activity(duration: int = 120):
    """内存压力测试 - 增强版"""
    print(f"\n[内存] 开始内存活动 ({duration}秒)...")
    
    try:
        mem_avail = 0
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    mem_avail = int(line.split()[1]) * 1024
                    break
        
        # 只使用温和内存底座，避免激进占满空闲内存
        target_size = int(mem_avail * 0.12)
        size = min(768 * 1024 * 1024, max(128 * 1024 * 1024, target_size))
        
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
                time.sleep(0.2)
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
    d1, d2, d3 = train_pure_python(
        data,
        seq_len,
        target_duration,
        throttle_every=100,
        throttle_sleep=0.03,
    )
    
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
        # 只清理真正的 Python 保活实例，避免误杀外层 timeout/bash 包装进程。
        result = subprocess.run(
            ["ps", "-eo", "pid=,comm=,args="],
            capture_output=True, text=True
        )
        other_pids = []
        for line in result.stdout.strip().splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) < 3:
                continue
            pid_str, comm, args = parts
            if not pid_str.isdigit():
                continue
            pid = int(pid_str)
            if pid == current_pid:
                continue
            if not comm.startswith("python"):
                continue
            if "scripts/remote_keepalive.py" not in args:
                continue
            other_pids.append(pid)

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
            time.sleep(1)
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
        if has_critical:
            print("\n" + "!" * 60)
            print(f"⛔ 发现 {len(issues)} 个安全问题，其中包含严重风险，中止保活任务！")
            print("请先处理安全问题后再运行保活。")
            print("!" * 60)
            return
        if issues:
            print(f"\n⚠️ 发现 {len(issues)} 个非严重安全问题，继续执行保活任务...")
        print("\n✅ 安全检测通过，开始保活任务...")
    except Exception as e:
        print(f"\n[安全] ⚠️ 安全检测出错: {e}")
        # 安全检测失败不阻止保活，仅警告
    
    # 1. 自适应资源检测
    cpu_count = os.cpu_count() or 1
    
    print("\n" + "-" * 40)
    print("环境负载与安全检测...")
    current_cpu_usage = check_current_cpu_usage()
    print(f"[环境] 当前系统 CPU 负载: {current_cpu_usage:.1f}%")
    
    if current_cpu_usage > 60.0:
        print("\n" + "!" * 60)
        print(f"⛔ 系统当前负载过高 (>60%)，主动触发防封号保护机制！")
        print("为避免叠加高负载触发 OCI 风控强关机，本次保活任务主动退出。")
        print("!" * 60)
        return
        
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
    
    target_duration = 180  # 3分钟节流训练
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
        d1, d2, d3 = train_pure_python(
            history,
            min(50, len(history) - 10),
            target_duration,
            throttle_every=100,
            throttle_sleep=0.03,
        )

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
    print("第三步: 历史数据缓存维护")
    print("-" * 40)
    
    # 内存策略：仅保留温和的活跃缓存，不再做激进占用
    mem_avail_kb = 0
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                mem_avail_kb = int(line.split()[1])
                break
    
    mem_avail_bytes = mem_avail_kb * 1024
    target_mem_size = int(mem_avail_bytes * 0.12)
    final_size = min(768 * 1024 * 1024, max(128 * 1024 * 1024, target_mem_size))

    print(f"[缓存] 策略: 温和模式 (可用 {mem_avail_bytes/1024/1024:.0f}MB, 使用约 12%)")
    print(f"[缓存] 构建历史模式缓存: {final_size/1024/1024:.0f} MB")

    memory_activity_run(final_size, 120)
    
    # 最终资源状态
    get_system_stats()
    
    # 完成
    print("\n" + "=" * 60)
    print(f"保活任务完成")
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

def memory_activity_run(size, duration):
    """实际执行温和内存活动，维持短时缓存读写"""
    try:
        # 模拟：初始化大矩阵用于存储历史模式权重
        print(f"[缓存] 正在分配历史模式缓存 ({size/1024/1024:.0f} MB)...")
        b = bytearray(size)
        
        # 填充模拟数据 (Patterns)
        print("[缓存] 正在填充缓存页...")
        # Step 1: 快速填充基础数据
        step_init = 4096
        for i in range(0, size, step_init): 
            b[i] = i % 255
            
        print("[缓存] ✅ 缓存初始化完成，开始温和读写保活...")
        start = time.time()
        end = start + duration
        
        # 动态步长
        step = 1024
        
        while time.time() < end:
            count = 0
            for i in range(0, size, step):
                b[i] = (b[i] ^ 0xFF) & 0xFF
                count += 1
                if count % 20000 == 0 and time.time() > end: break
            
            elapsed = time.time() - start
            left = duration - elapsed
            if left > 0:
                time.sleep(0.2)
                if int(elapsed) % 30 == 0:
                    print(f"[缓存] 缓存维护中... 剩余 {left:.0f}s")
        del b
        print("[缓存] ✅ 缓存释放完毕")
    except Exception as e:
        print(f"[缓存] ❌ 缓存维护出错: {e}")


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
    cpu_count = os.cpu_count() or 1

    # ==========================================
    # Nano Mode (内存 ≤ 1GB) — 超低配保活
    # ==========================================
    if mem_total_gb <= 1.0:
        print("\n" + "*" * 50)
        print(f"🔬 检测到超低配实例 ({mem_total_gb:.1f}GB, {cpu_count}核)")
        print("🔬 自动切换至 Nano Mode (超轻量保活模式)")
        print("*" * 50)

        # 安全检测 (best effort)
        try:
            from security_check import run_security_checks
            issues, has_critical = run_security_checks(args.hostname)
            if has_critical:
                print(f"⛔ 发现 {len(issues)} 个安全问题，其中包含严重风险，中止保活任务！")
                sys.exit(0)
            if issues:
                print(f"⚠️ 发现 {len(issues)} 个非严重安全问题，继续执行保活任务...")
            print("✅ 安全检测通过")
        except Exception as e:
            print(f"[安全] ⚠️ 安全检测出错: {e}")

        # CPU 负载检查
        current_cpu = check_current_cpu_usage()
        print(f"[Nano] 当前 CPU 负载: {current_cpu:.1f}%")
        if current_cpu > 60.0:
            print("⛔ CPU 负载过高，跳过本次保活")
            sys.exit(0)

        os.system("uname -a")
        os.system("uptime")
        get_system_stats()

        # === 1. 轻量内存占位 (20% 可用内存) ===
        mem_avail_kb = 0
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    mem_avail_kb = int(line.split()[1])
                    break
        target_mem = int(mem_avail_kb * 1024 * 0.20)  # 20% 可用内存
        target_mem = max(target_mem, 64 * 1024 * 1024)  # 最小 64MB
        target_mem = min(target_mem, 200 * 1024 * 1024)  # 最大 200MB
        print(f"[Nano] 分配轻量内存底座: {target_mem/1024/1024:.0f} MB (20%)")
        buffer = bytearray(target_mem)
        for i in range(0, len(buffer), 4096):
            buffer[i] = 1

        # === 2. 轻量 BPNN 训练 (缩小网络 + 节流 CPU) ===
        print("\n[Nano] 启动轻量 BPNN 训练...")
        history = load_history()
        d1, d2, d3 = 0, 0, 0

        if len(history) >= 50:
            seq_len = min(20, len(history) - 10)  # 缩短序列
            nano_duration = 180  # 3 分钟

            # 使用更小的网络: input -> 32 -> 16 -> 10
            input_size = seq_len * 3
            nn_d1 = DeepBPNN(input_size, 32, 16, 10, learning_rate=0.05)
            nn_d2 = DeepBPNN(input_size, 32, 16, 10, learning_rate=0.05)
            nn_d3 = DeepBPNN(input_size, 32, 16, 10, learning_rate=0.05)

            # 准备训练数据
            train_data = []
            for i in range(len(history) - seq_len):
                inputs = []
                for j in range(seq_len):
                    item = history[i + j]
                    inputs.extend([item["d1"]/9.0, item["d2"]/9.0, item["d3"]/9.0])
                target = history[i + seq_len]
                train_data.append({
                    "inputs": inputs,
                    "d1": target["d1"], "d2": target["d2"], "d3": target["d3"]
                })

            print(f"[Nano] 网络: {input_size}→32→16→10, 样本: {len(train_data)}, 目标: {nano_duration}s")

            start_time = time.time()
            epoch = 0
            samples = 0

            while time.time() - start_time < nano_duration:
                epoch += 1
                for sample in train_data:
                    out1 = nn_d1.forward(sample["inputs"])
                    nn_d1.backward(one_hot_encode(sample["d1"]))
                    out2 = nn_d2.forward(sample["inputs"])
                    nn_d2.backward(one_hot_encode(sample["d2"]))
                    out3 = nn_d3.forward(sample["inputs"])
                    nn_d3.backward(one_hot_encode(sample["d3"]))
                    samples += 1

                    # CPU 节流: 主动打散连续高占用
                    if samples % 50 == 0:
                        time.sleep(0.08)

                    if samples % 200 == 0 and time.time() - start_time >= nano_duration:
                        break

                if epoch % 20 == 0:
                    elapsed = time.time() - start_time
                    print(f"[Nano] 轮次 {epoch}, 样本 {samples}, 耗时 {elapsed:.0f}s/{nano_duration}s")

            # 预测
            last_seq = []
            for i in range(seq_len):
                item = history[-(seq_len - i)]
                last_seq.extend([item["d1"]/9.0, item["d2"]/9.0, item["d3"]/9.0])
            prob_d1 = nn_d1.forward(last_seq)
            prob_d2 = nn_d2.forward(last_seq)
            prob_d3 = nn_d3.forward(last_seq)
            d1 = prob_d1.index(max(prob_d1))
            d2 = prob_d2.index(max(prob_d2))
            d3 = prob_d3.index(max(prob_d3))

            total_time = time.time() - start_time
            print(f"[Nano] ✅ 训练完成: {epoch} 轮, {samples} 样本, {total_time:.0f}s")
            print(f"[Nano] 预测: {d1} {d2} {d3}")
        else:
            print("[Nano] 数据不足，使用随机占位训练")
            # 即使没有数据也要消耗时间
            start_time = time.time()
            while time.time() - start_time < 180:
                _ = [random.random() ** 0.5 for _ in range(10000)]
                time.sleep(0.15)

        # === 3. 轻量内存活动 (温和读写 3 分钟) ===
        print("\n[Nano] 轻量内存活动 (120s)...")
        mem_start = time.time()
        mem_end = mem_start + 120
        step = 4096  # 较大步长减少 CPU 消耗
        while time.time() < mem_end:
            for i in range(0, len(buffer), step):
                buffer[i] = (buffer[i] + 1) & 0xFF
                if time.time() > mem_end:
                    break
            time.sleep(0.5)  # 大量休眠降低 CPU 占用
            elapsed = time.time() - mem_start
            if int(elapsed) % 60 == 0 and int(elapsed) > 0:
                print(f"[Nano] 内存活动中... 剩余 {120 - elapsed:.0f}s")

        print("[Nano] ✅ 内存活动完成")

        # 保存预测结果
        next_issue = str(int(history[-1]["issue"]) + 1) if history else "99999"
        save_prediction(next_issue, d1, d2, d3, hostname=args.hostname, model_type="nano_mode")

        get_system_stats()
        del buffer
        print("\n[Nano] ✅ Nano Mode 保活任务完成")

    # ==========================================
    # Micro Mode (1GB < 内存 < 2GB) — 低配保活
    # ==========================================
    elif mem_total_gb < 2.0:
        print("\n" + "*" * 50)
        print(f"🚀 检测到低配实例 ({mem_total_gb:.1f}GB < 2.0GB)")
        print("🚀 自动切换至 Micro Mode (微创保活模式)")
        print("*" * 50)
        
        # 1. 温和内存底座
        mem_avail_kb = 0
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    mem_avail_kb = int(line.split()[1])
                    break
        target_size = int(mem_avail_kb * 1024 * 0.15)
        target_size = min(256 * 1024 * 1024, max(96 * 1024 * 1024, target_size))
        print(f"[Micro] 分配基础内存底座: {target_size/1024/1024:.0f} MB (~15%)")
        # 申请并保持内存
        buffer = bytearray(target_size)
        for i in range(0, len(buffer), 4096): buffer[i] = 1 # 触碰以实际分配

        # 2. 本地数据分析与节流训练，避免大流量下载/上传模拟
        history = load_history()
        d1, d2, d3 = 0, 0, 0
        if len(history) >= 50:
            statistical_analysis(history[-200:])
            d1, d2, d3 = train_pure_python(
                history,
                min(30, len(history) - 10),
                target_duration=180,
                throttle_every=60,
                throttle_sleep=0.05,
            )
            next_issue = str(int(history[-1]["issue"]) + 1)
        else:
            next_issue = "99999"

        save_prediction(next_issue, d1, d2, d3, hostname=args.hostname, model_type="micro_mode")
        
        # 3. 释放内存
        del buffer
        print("[Micro] ✅ 任务完成，资源释放")
        
    # ==========================================
    # Normal Mode (内存 ≥ 2GB) — 标准保活
    # ==========================================
    else:
        main(hostname=args.hostname)
