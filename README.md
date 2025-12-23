# OCI Keepalive Tunnel

通过 Cloudflare Tunnel + GitHub Actions 保持 OCI 实例活跃，使用**深度 BP 神经网络**进行福彩3D预测作为真实计算负载。

## 🎯 目的

替代收费的 GitHub self-hosted runners，使用免费的 GitHub-hosted runners 通过 Cloudflare Tunnel 远程执行真实计算任务，满足 Oracle Cloud **Always Free** 资源的使用要求。

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────────────┐
│                    GitHub Actions (免费)                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────┐    ┌─────────────────────┐        │
│  │ collect-data.yml    │    │ oci-keepalive.yml   │        │
│  │ 每日采集福彩3D数据   │    │ 每2小时触发保活      │        │
│  │ → 保存到 data/      │    │ → SSH到各OCI实例    │        │
│  └──────────┬──────────┘    └──────────┬──────────┘        │
│             │                          │                    │
│             ▼                          ▼                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         data/fc3d_history.csv (共享数据)             │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                  │
│                          ▼ Cloudflare Tunnel               │
│  ┌──────────────────────────────────────────────────────┐  │
│  │               OCI 实例 (ARM64)                        │  │
│  │  - git clone/pull 仓库                                │  │
│  │  - 读取 data/fc3d_history.csv                        │  │
│  │  - 运行深度 BPNN 训练 (5分钟)                         │  │
│  │  - 输出预测结果 → predictions/                       │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 📁 项目结构

```
.
├── .github/workflows/
│   ├── oci-keepalive.yml    # 保活工作流 (每2小时)
│   └── collect-data.yml     # 数据采集 (每日)
├── scripts/
│   ├── keepalive.sh         # SSH 执行入口
│   ├── remote_keepalive.py  # 深度 BPNN 预测脚本 (在OCI运行)
│   └── collect_data.py      # 数据采集脚本 (在GitHub runner运行)
├── data/
│   └── fc3d_history.csv     # 福彩3D历史数据
├── predictions/
│   └── predictions.csv      # 预测结果汇总
└── README.md
```

## 🧠 核心算法

使用**纯 Python 实现的深度 BP 神经网络**（零依赖，无需 numpy）进行预测。

### 网络架构

| 层 | 节点数 | 激活函数 |
|---|--------|---------|
| 输入层 | 150 (50期 × 3) | - |
| 隐藏层1 | 128 | ReLU |
| 隐藏层2 | 64 | ReLU |
| 输出层 | 10 | Sigmoid |

### 训练特性

- **Xavier 权重初始化**：改善梯度流动
- **学习率衰减**：随 epoch 递减，提升收敛稳定性
- **损失监控**：实时输出 MSE 损失，观察收敛过程
- **时间驱动训练**：持续训练 300 秒，确保充分收敛

## ⚙️ 配置

### Actions Secrets

| Secret 名称 | 说明 |
|-------------|------|
| `SSH_USERNAME` | SSH 用户名 (`root`) |
| `SSH_PASSWORD` | SSH 密码 |
| `HOSTS_CONFIG` | 主机列表 (JSON) |

### HOSTS_CONFIG 格式

```json
[
  {"name": "实例1", "ssh_host": "instance1-ssh.example.com"},
  {"name": "实例2", "ssh_host": "instance2-ssh.example.com"}
]
```

## 🚀 工作流

| 工作流 | 频率 | 功能 |
|--------|------|------|
| `collect-data.yml` | 每日 13:35 UTC | 采集福彩3D开奖数据 |
| `oci-keepalive.yml` | 每 2 小时 | 执行深度 BPNN 保活任务 |

## 📊 保活任务说明

每台 OCI 实例执行:

| 步骤 | 时长 | 资源消耗 | 备注 |
|------|------|----------|------|
| 深度 BPNN 训练 | **~5 分钟** | 单核 CPU 100% | 2 隐藏层，300 秒训练 |
| 内存活动 | ~3 分钟 | 25% 内存 | 动态分配，防止闲置 |
| **总计** | **~8-10 分钟** | CPU + 内存 | 满足 Always Free 保活要求 |

### 自适应资源分配

脚本自动检测实例配置并调整策略：

| 配置 | CPU 核心 | 内存 | 训练进程 | 内存分配 |
|------|----------|------|----------|----------|
| 标准型 | 2 核 | 12 GB | 1 个 | ~3 GB |
| 高配型 | 4 核 | 24 GB | 2 个 | ~6 GB |

## 📈 Oracle Cloud Always Free 合规性

### 官方回收规则

根据 [Oracle 官方文档](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)：

> **Idle Compute Instances - Reclamation of Idle Compute Instances**
>
> Idle Always Free compute instances may be reclaimed by Oracle. Oracle will deem virtual machine and bare metal compute instances as idle if, during a **7-day period**, the following are **all** true:
>
> - CPU utilization for the **95th percentile** is less than **20%**
> - Network utilization is less than **20%**
> - Memory utilization is less than **20%** (applies to **A1 shapes** only)

### 本项目达标分析

| 指标 | Oracle 阈值 | 本项目实际 | 达标状态 |
|------|-------------|-----------|----------|
| **CPU 95th 百分位** | < 20% 会被回收 | 每 2 小时单核 100% 运行 ~8 分钟 | ✅ **达标** |
| **网络利用率** | < 20% 会被回收 | Git Pull + SSH 连接 (每 2 小时) | ✅ **达标** |
| **内存利用率 (A1)** | < 20% 会被回收 | 分配 25% 总内存，活跃读写 3 分钟 | ✅ **达标** |

### 95th 百分位计算

7 天 = 10,080 分钟

- **5% 的时间** = 504 分钟
- **本项目高负载时间** = 12 次/天 × 7 天 × 8 分钟 = **672 分钟**
- **672 > 504**，因此 95th 百分位超过 20% ✅

### 合规性结论

本项目通过以下方式确保实例不会被判定为"闲置"：

1. ⚡ **高强度 CPU 负载**：深度 BPNN 训练使用纯 Python 矩阵运算，单核持续 100% 负载 5 分钟
2. 💾 **有效内存占用**：动态分配 25% 总内存，并进行活跃读写防止被 swap
3. 🌐 **定期网络活动**：每 2 小时 Git Clone/Pull + SSH 连接产生网络流量
4. 🔄 **高频率触发**：每 2 小时运行一次，每周 84 次，累计高负载 672 分钟

## 📝 License

MIT
