#!/bin/bash
# 移除 set -e 以防止并行任务失败导致脚本提前退出
set -uo pipefail

# ============================================
# OCI Keepalive Script via Cloudflare Tunnel
# ============================================

RESULTS_FILE="/tmp/keepalive_results.txt"
REMOTE_SCRIPT="scripts/remote_keepalive.py"
MAX_PARALLEL=5  # 最大并行数 (增加到5)

# 初始化结果文件
echo "| Host | Status | Duration |" > "$RESULTS_FILE"
echo "|------|--------|----------|" >> "$RESULTS_FILE"

# 解析主机配置
HOSTS=$(echo "$HOSTS_CONFIG" | jq -c '.[]')

# 创建临时目录存放日志
LOG_DIR=$(mktemp -d)
trap "rm -rf $LOG_DIR" EXIT

# 执行单个主机的保活
run_keepalive() {
    local name="$1"
    local ssh_host="$2"
    local port="$3"
    local log_file="$LOG_DIR/${name}.log"
    local start_time=$(date +%s)
    
    echo "[$(date '+%H:%M:%S')] Starting keepalive for $name via $ssh_host (port $port)" | tee -a "$log_file"
    
    # 启动 cloudflared tunnel（后台运行）
    cloudflared access ssh --hostname "$ssh_host" --url "ssh://127.0.0.1:$port" > "$log_file.tunnel" 2>&1 &
    local tunnel_pid=$!
    
    # 等待隧道建立（增加等待时间）
    echo "[$name] Waiting for tunnel to establish..." | tee -a "$log_file"
    sleep 5
    
    # 检查隧道是否建立成功
    if ! kill -0 $tunnel_pid 2>/dev/null; then
        echo "[$name] Tunnel process died" | tee -a "$log_file"
        cat "$log_file.tunnel" >> "$log_file" 2>/dev/null || true
        echo "| $name | ❌ Tunnel Failed | - |" >> "$RESULTS_FILE"
        return 0  # 返回0避免影响其他并行任务
    fi
    
    echo "[$name] Tunnel established (PID: $tunnel_pid)" | tee -a "$log_file"
    
    # 测试 SSH 连接
    local status="❌ Failed"
    local ssh_opts="-o ConnectTimeout=30 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
    
    # 先测试简单命令
    if sshpass -p "$SSH_PASSWORD" ssh $ssh_opts -p "$port" "${SSH_USERNAME}@127.0.0.1" "echo 'SSH OK'" >> "$log_file" 2>&1; then
        echo "[$name] SSH connection successful" | tee -a "$log_file"
        
        # 克隆或更新公开仓库 (使用用户主目录)
        echo "[$name] Syncing repository..." | tee -a "$log_file"
        
        if sshpass -p "$SSH_PASSWORD" ssh $ssh_opts -p "$port" "${SSH_USERNAME}@127.0.0.1" '
            REPO_DIR="$HOME/oci-keepalive"
            REPO_URL="https://github.com/suwei8/oci-keepalive-tunnel.git"
            if [ -d "$REPO_DIR/.git" ]; then
                cd "$REPO_DIR" && git pull --quiet 2>/dev/null || (git fetch --all && git reset --hard origin/main)
            else
                rm -rf "$REPO_DIR"
                git clone --depth 1 "$REPO_URL" "$REPO_DIR"
            fi
            echo "Repo synced to $REPO_DIR"
        ' >> "$log_file" 2>&1; then
            echo "[$name] Repository synced, executing..." | tee -a "$log_file"
            
            # 执行保活脚本
            if timeout 720 sshpass -p "$SSH_PASSWORD" ssh $ssh_opts -p "$port" "${SSH_USERNAME}@127.0.0.1" \
                "cd \$HOME/oci-keepalive && python3 scripts/remote_keepalive.py --hostname '$name'" >> "$log_file" 2>&1; then
                status="✅ Success"
                echo "[$name] Keepalive completed successfully" | tee -a "$log_file"
                
                # 回传预测结果
                echo "[$name] Fetching prediction result..." | tee -a "$log_file"
                mkdir -p predictions
                local safe_name=$(echo "$name" | tr ' ' '_')
                if sshpass -p "$SSH_PASSWORD" scp $ssh_opts -P "$port" \
                    "${SSH_USERNAME}@127.0.0.1:/tmp/prediction_result.json" \
                    "predictions/${safe_name}.json" >> "$log_file" 2>&1; then
                    echo "[$name] Prediction result fetched" | tee -a "$log_file"
                else
                    echo "[$name] Failed to fetch prediction (may not exist)" | tee -a "$log_file"
                fi
            else
                echo "[$name] Keepalive script execution failed" | tee -a "$log_file"
            fi
        else
            echo "[$name] Failed to sync repository" | tee -a "$log_file"
        fi
    else
        echo "[$name] SSH connection failed" | tee -a "$log_file"
        # 输出隧道日志帮助调试
        echo "[$name] Tunnel log:" | tee -a "$log_file"
        cat "$log_file.tunnel" >> "$log_file" 2>/dev/null || true
    fi
    
    # 清理隧道
    kill $tunnel_pid 2>/dev/null || true
    wait $tunnel_pid 2>/dev/null || true
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    echo "| $name | $status | ${duration}s |" >> "$RESULTS_FILE"
    
    echo "[$(date '+%H:%M:%S')] Completed $name: $status (${duration}s)" | tee -a "$log_file"
    
    # 输出日志内容到 stdout 便于在 Actions 中查看
    echo "=== [$name] Full Log ===" 
    cat "$log_file"
    echo "=== [$name] End Log ==="
}

# 主执行逻辑
main() {
    local port=2200
    local count=0
    local running=0
    
    echo "=========================================="
    echo "OCI Keepalive Started at $(date)"
    echo "=========================================="
    echo ""
    echo "Configuration:"
    echo "  MAX_PARALLEL: $MAX_PARALLEL"
    echo "  SSH_USERNAME: $SSH_USERNAME"
    echo "  Hosts count: $(echo "$HOSTS_CONFIG" | jq '. | length')"
    echo ""
    
    # 将所有主机读入数组
    local -a host_names=()
    local -a host_addrs=()
    
    while IFS= read -r host; do
        name=$(echo "$host" | jq -r '.name')
        ssh_host=$(echo "$host" | jq -r '.ssh_host')
        
        # 如果指定了目标主机，则只添加该主机
        if [ -n "${TARGET_HOST:-}" ] && [ "$name" != "$TARGET_HOST" ]; then
            continue
        fi
        
        host_names+=("$name")
        host_addrs+=("$ssh_host")
    done <<< "$HOSTS"
    
    local total=${#host_names[@]}
    echo "Hosts to process: $total"
    echo ""
    
    # 分批处理
    local i=0
    while [ $i -lt $total ]; do
        # 启动一批任务
        local batch_pids=()
        local batch_end=$((i + MAX_PARALLEL))
        if [ $batch_end -gt $total ]; then
            batch_end=$total
        fi
        
        echo "--- Starting batch: hosts $((i+1)) to $batch_end of $total ---"
        
        while [ $i -lt $batch_end ]; do
            port=$((port + 1))
            local name="${host_names[$i]}"
            local ssh_host="${host_addrs[$i]}"
            
            run_keepalive "$name" "$ssh_host" "$port" &
            batch_pids+=($!)
            count=$((count + 1))
            i=$((i + 1))
            
            # 小延迟避免同时启动
            sleep 1
        done
        
        # 等待这批任务完成
        echo "Waiting for batch to complete (${#batch_pids[@]} tasks)..."
        for pid in "${batch_pids[@]}"; do
            wait "$pid" 2>/dev/null || true
        done
        echo "Batch completed"
        echo ""
    done
    
    echo ""
    echo "=========================================="
    echo "OCI Keepalive Completed at $(date)"
    echo "Total hosts processed: $count"
    echo "=========================================="
    
    # 显示结果
    echo ""
    echo "Results Summary:"
    cat "$RESULTS_FILE"
}

main
