---
description: 通过SSH部署Cloudflare Tunnel并创建SSH隧道
---

# 部署 Cloudflare Tunnel SSH 隧道

此工作流用于通过 SSH 登录远程实例，自动安装部署 Cloudflare Tunnel 并创建 SSH 隧道。

## 输入参数

启动时在 workflows 面板提供：
- **ssh_ip**: 远程实例 IP 地址
- **ssh_password**: SSH 密码
- **tunnel_tag_name**: 隧道标签名称（如 `singapore-West9`）

默认值：
- **ssh_username**: `root`

## Actions Secrets（使用 hhwpxh.com 域名账号的 secrets）

- `CF_ACCOUNT_ID`: Cloudflare 账户 ID
- `CF_API_EMAIL`: Cloudflare API 邮箱
- `CF_API_KEY`: Cloudflare Global API Key
- `CF_ZONE_ID`: 域名 Zone ID
- `SSH_USERNAME`: 创建普通用户的用户名
- `SSH_PASSWORD`: 创建普通用户的密码
- `TELEGRAM_BOT_TOKEN`: Telegram 机器人 Token
- `TELEGRAM_CHAT_ID`: Telegram 聊天 ID

---

## 步骤 1：通过 SSH 登录远程实例

// turbo
```bash
# 在 GitHub Actions runner 上安装 sshpass
sudo apt-get update -qq && sudo apt-get install -y -qq sshpass jq

# 配置 SSH 选项
mkdir -p ~/.ssh
cat >> ~/.ssh/config << 'EOF'
Host *
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
  LogLevel ERROR
EOF
```

定义 SSH 连接命令（后续步骤中复用）：
```bash
SSH_OPTS="-o ConnectTimeout=30 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ServerAliveInterval=30"
SSH_CMD="sshpass -p \"${ssh_password}\" ssh $SSH_OPTS ${ssh_username}@${ssh_ip}"
```

## 步骤 2：安装 Cloudflared 连接器

通过 SSH 在远程主机上执行：

// turbo
```bash
sshpass -p "${ssh_password}" ssh $SSH_OPTS ${ssh_username}@${ssh_ip} "
  # 添加 Cloudflare GPG 密钥
  sudo mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-public-v2.gpg | sudo tee /usr/share/keyrings/cloudflare-public-v2.gpg >/dev/null
  
  # 添加 repo 到 apt 源
  echo 'deb [signed-by=/usr/share/keyrings/cloudflare-public-v2.gpg] https://pkg.cloudflare.com/cloudflared any main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
  
  # 安装 cloudflared
  sudo apt-get update && sudo apt-get install -y cloudflared
  
  # 验证安装
  cloudflared --version
"
```

## 步骤 3：通过 Cloudflare API 创建 Tunnel

### 3.1 生成隧道名称

```bash
# 隧道名称格式: {tunnel_tag_name}-{ssh_ip}
TUNNEL_NAME="${tunnel_tag_name}-${ssh_ip}"
echo "Tunnel Name: $TUNNEL_NAME"
```

### 3.2 调用 Cloudflare API 创建隧道

// turbo
```bash
# 创建隧道 (类型: cloudflared, 配置来源: cloudflare)
CREATE_RESULT=$(curl -s -X POST "https://api.cloudflare.com/client/v4/accounts/${CF_ACCOUNT_ID}/cfd_tunnel" \
  -H "Authorization: Bearer ${CF_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"${TUNNEL_NAME}\", \"config_src\": \"cloudflare\"}")

# 检查是否成功
if echo "$CREATE_RESULT" | jq -e '.success' > /dev/null; then
  TUNNEL_ID=$(echo "$CREATE_RESULT" | jq -r '.result.id')
  echo "✅ Tunnel 创建成功: $TUNNEL_ID"
else
  echo "❌ Tunnel 创建失败:"
  echo "$CREATE_RESULT" | jq '.errors'
  # 检查是否因重名失败，尝试获取已存在的隧道
  TUNNEL_ID=$(curl -s "https://api.cloudflare.com/client/v4/accounts/${CF_ACCOUNT_ID}/cfd_tunnel?name=${TUNNEL_NAME}" \
    -H "Authorization: Bearer ${CF_API_KEY}" | jq -r '.result[0].id // empty')
  if [ -n "$TUNNEL_ID" ]; then
    echo "⚠️ 使用已存在的 Tunnel: $TUNNEL_ID"
  else
    echo "❌ 无法创建或获取 Tunnel"
    exit 1
  fi
fi
```

### 3.3 获取 Tunnel Token

// turbo
```bash
# 获取 Tunnel Token
TOKEN_RESULT=$(curl -s "https://api.cloudflare.com/client/v4/accounts/${CF_ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}/token" \
  -H "Authorization: Bearer ${CF_API_KEY}")

TUNNEL_TOKEN=$(echo "$TOKEN_RESULT" | jq -r '.result // empty')

if [ -z "$TUNNEL_TOKEN" ]; then
  echo "❌ 获取 Tunnel Token 失败"
  echo "$TOKEN_RESULT" | jq '.errors'
  exit 1
fi
echo "✅ Tunnel Token 获取成功"
```

### 3.4 在远程主机安装 Tunnel 服务

// turbo
```bash
sshpass -p "${ssh_password}" ssh $SSH_OPTS ${ssh_username}@${ssh_ip} "
  # 停止并删除可能存在的旧服务
  sudo cloudflared service uninstall 2>/dev/null || true
  
  # 安装 Tunnel 服务
  sudo cloudflared service install ${TUNNEL_TOKEN}
  
  # 检查服务状态
  sleep 5
  sudo systemctl status cloudflared || true
"
```

## 步骤 4：配置 SSH Public Hostname

### 4.1 生成 Hostname

```bash
# SSH hostname 格式: {tunnel_tag_name}-ssh.hhwpxh.com
SSH_HOSTNAME="${tunnel_tag_name}-ssh"
FULL_HOSTNAME="${SSH_HOSTNAME}.hhwpxh.com"
echo "SSH Hostname: $FULL_HOSTNAME"
```

### 4.2 更新 Tunnel Ingress 配置

// turbo
```bash
# 配置 Tunnel ingress 规则（SSH 服务）
CONFIG_RESULT=$(curl -s -X PUT "https://api.cloudflare.com/client/v4/accounts/${CF_ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}/configurations" \
  -H "Authorization: Bearer ${CF_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{
    \"config\": {
      \"ingress\": [
        {
          \"hostname\": \"${FULL_HOSTNAME}\",
          \"service\": \"ssh://localhost:22\"
        },
        {
          \"service\": \"http_status:404\"
        }
      ]
    }
  }")

if echo "$CONFIG_RESULT" | jq -e '.success' > /dev/null; then
  echo "✅ Ingress 配置成功"
else
  echo "❌ Ingress 配置失败:"
  echo "$CONFIG_RESULT" | jq '.errors'
  exit 1
fi
```

### 4.3 等待隧道连接建立

// turbo
```bash
echo "等待隧道连接建立..."
sleep 15

# 检查隧道状态
sshpass -p "${ssh_password}" ssh $SSH_OPTS ${ssh_username}@${ssh_ip} "
  sudo systemctl status cloudflared
  cloudflared tunnel info 2>/dev/null || true
"
```

## 步骤 5：测试隧道连接

### 5.1 在 Runner 上通过 Cloudflared 测试 SSH 连接

```bash
# 安装 cloudflared (如果 runner 上没有)
if ! command -v cloudflared &> /dev/null; then
  sudo cp bin/cloudflared /usr/local/bin/cloudflared 2>/dev/null || \
    (curl -fsSL https://pkg.cloudflare.com/cloudflared-linux-amd64 -o /tmp/cloudflared && \
     chmod +x /tmp/cloudflared && sudo mv /tmp/cloudflared /usr/local/bin/cloudflared)
fi

# 启动本地 SSH 隧道
cloudflared access ssh --hostname ${FULL_HOSTNAME} --url ssh://127.0.0.1:2202 &
TUNNEL_PID=$!
sleep 5

# 测试 SSH 连接
if sshpass -p "${ssh_password}" ssh $SSH_OPTS -p 2202 ${ssh_username}@127.0.0.1 "echo 'SSH via Tunnel OK'"; then
  echo "✅ 隧道 SSH 连接测试成功"
  CONNECTION_OK="true"
else
  echo "❌ 隧道 SSH 连接测试失败"
  CONNECTION_OK="false"
fi

# 清理隧道
kill $TUNNEL_PID 2>/dev/null || true
```

## 步骤 6：创建普通用户（连接成功后执行）

如果步骤 5 连接成功：

```bash
if [ "$CONNECTION_OK" = "true" ]; then
  sshpass -p "${ssh_password}" ssh $SSH_OPTS ${ssh_username}@${ssh_ip} "
    # 创建用户 (使用 Actions secrets 中的 SSH_USERNAME 和 SSH_PASSWORD)
    USERNAME='${SSH_USERNAME}'
    PASSWORD='${SSH_PASSWORD}'
    
    # 检查用户是否存在
    if id \"\$USERNAME\" &>/dev/null; then
      echo \"用户 \$USERNAME 已存在\"
    else
      # 创建用户
      sudo useradd -m -s /bin/bash \"\$USERNAME\"
      echo \"\${USERNAME}:\${PASSWORD}\" | sudo chpasswd
      echo \"✅ 用户 \$USERNAME 已创建\"
    fi
    
    # 配置免密 sudo
    echo \"\${USERNAME} ALL=(ALL) NOPASSWD:ALL\" | sudo tee /etc/sudoers.d/\${USERNAME}
    sudo chmod 440 /etc/sudoers.d/\${USERNAME}
    echo \"✅ 已配置免密 sudo\"
  "
fi
```

## 步骤 7：发送 Telegram 通知

// turbo
```bash
TIMESTAMP=$(date -u +'%Y-%m-%d %H:%M UTC')

if [ "$CONNECTION_OK" = "true" ]; then
  STATUS_EMOJI="✅"
  STATUS_TEXT="成功"
else
  STATUS_EMOJI="❌"
  STATUS_TEXT="失败"
fi

MSG=$(printf "${STATUS_EMOJI} *Cloudflare Tunnel 部署${STATUS_TEXT}*\n\n📅 %s\n🏷️ 隧道名称: \`%s\`\n🌐 SSH Hostname: \`%s\`\n🖥️ 服务器 IP: \`%s\`\n\n📝 *连接方式:*\n\`\`\`\ncloudflared access ssh --hostname %s --url ssh://127.0.0.1:2202\nssh -p 2202 %s@127.0.0.1\n\`\`\`" \
  "$TIMESTAMP" \
  "$TUNNEL_NAME" \
  "$FULL_HOSTNAME" \
  "$ssh_ip" \
  "$FULL_HOSTNAME" \
  "${SSH_USERNAME}")

curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d chat_id="${TELEGRAM_CHAT_ID}" \
  -d parse_mode="Markdown" \
  --data-urlencode "text=${MSG}" > /dev/null

echo "✅ Telegram 通知已发送"
```

---

## 完整 GitHub Actions 工作流参考

此工作流应创建为 `.github/workflows/deploy-cf-tunnel.yml`：

```yaml
name: Deploy Cloudflare Tunnel SSH

on:
  workflow_dispatch:
    inputs:
      ssh_ip:
        description: '远程实例 IP 地址'
        required: true
      ssh_password:
        description: 'SSH 密码'
        required: true
      tunnel_tag_name:
        description: '隧道标签名称 (如 singapore-West9)'
        required: true
      ssh_username:
        description: 'SSH 用户名'
        required: false
        default: 'root'

jobs:
  deploy:
    name: Deploy CF Tunnel
    runs-on: ubuntu-latest
    timeout-minutes: 30
    
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
      
      # ... 按上述步骤实现
```
