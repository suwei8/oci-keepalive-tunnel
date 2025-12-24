#!/bin/bash
#!/bin/bash
set -e

# Check root
if [ "$EUID" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    echo "Error: Need root or sudo"
    exit 1
  fi
else
  SUDO=""
fi

# Install dependencies
if [ -n "$SUDO" ]; then
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq curl openssl uuid-runtime unzip psmisc
else
    apt-get update -qq
    apt-get install -y -qq curl openssl uuid-runtime unzip psmisc
fi

# Detect Architecture
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
  # AMD64
  DOWNLOAD_URL="https://github.com/XTLS/Xray-core/releases/download/v25.12.8/Xray-linux-64.zip"
elif [ "$ARCH" = "aarch64" ]; then
  # ARM64
  DOWNLOAD_URL="https://github.com/XTLS/Xray-core/releases/download/v25.12.8/Xray-linux-arm64-v8a.zip"
else
  echo "Unsupported Architecture: $ARCH"
  exit 1
fi

# Prepare directory (ephemeral)
WORK_DIR="$HOME/vless_tmp"
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

# Destroy persistent service if exists
if [ -f "/etc/systemd/system/xray.service" ] || [ -f "/lib/systemd/system/xray.service" ]; then
    echo "removing persistent xray service..."
    if [ -n "$SUDO" ]; then
        $SUDO systemctl stop xray || true
        $SUDO systemctl disable xray || true
        $SUDO rm -f /etc/systemd/system/xray.service
        $SUDO rm -f /lib/systemd/system/xray.service
        $SUDO systemctl daemon-reload
    else
        systemctl stop xray || true
        systemctl disable xray || true
        rm -f /etc/systemd/system/xray.service
        rm -f /lib/systemd/system/xray.service
        systemctl daemon-reload
    fi
fi

# Force kill port 443 (Loop until free)
# ... (existing loop logic is fine, let's keep it but simplified since service is gone)
echo "Debug: Processes on port 443:"
if [ -n "$SUDO" ]; then
   $SUDO ss -tulpn | grep :443 || echo "No process found on 443 via ss"
   
   MAX_RETRIES=10
   while $SUDO ss -tulpn | grep -q :443; do
       echo "Port 443 still in use. Killing processes..."
       $SUDO fuser -k -9 443/tcp || true
       $SUDO pkill -9 -x xray || true
       sleep 1
       MAX_RETRIES=$((MAX_RETRIES-1))
       if [ $MAX_RETRIES -le 0 ]; then
           echo "Failed to free port 443."
           exit 1
       fi
   done
else
   ss -tulpn | grep :443 || echo "No process found on 443 via ss"
   
   MAX_RETRIES=10
   while ss -tulpn | grep -q :443; do
       echo "Port 443 still in use. Killing processes..."
       fuser -k -9 443/tcp || true
       pkill -9 -x xray || true
       sleep 1
       MAX_RETRIES=$((MAX_RETRIES-1))
       if [ $MAX_RETRIES -le 0 ]; then
           echo "Failed to free port 443."
           exit 1
       fi
   done
fi
echo "Port 443 is free."
sleep 1

# Download and Unzip
curl -L -s "$DOWNLOAD_URL" -o xray.zip
unzip -o -q xray.zip
rm xray.zip
chmod +x xray

# Generate UUID and Keys using the downloaded binary
KEYS=$(./xray x25519)
PRIVATE_KEY=$(echo "$KEYS" | grep -i "PrivateKey" | head -n1 | awk -F: '{print $2}' | xargs)
PUBLIC_KEY=$(echo "$KEYS" | grep -i "Password" | head -n1 | awk -F: '{print $2}' | xargs)
UUID=$(uuidgen)

if [ -z "$PRIVATE_KEY" ] || [ -z "$PUBLIC_KEY" ] || [ -z "$UUID" ]; then
    echo "Error: Failed to generate keys or UUID"
    echo "KEYS raw output: $KEYS"
    exit 1
fi

PORT=443
SNI="www.apple.com"

# Generate Config (local file)
cat > config.json <<EOF
{
  "log": {
    "loglevel": "none"
  },
  "inbounds": [
    {
      "port": $PORT,
      "protocol": "vless",
      "settings": {
        "clients": [
          {
            "id": "$UUID",
            "flow": "xtls-rprx-vision"
          }
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "$SNI:443",
          "xver": 0,
          "serverNames": [
            "$SNI"
          ],
          "privateKey": "$PRIVATE_KEY",
          "shortIds": [
            ""
          ]
        }
      }
    }
  ],
  "outbounds": [
    {
      "protocol": "freedom",
      "tag": "direct"
    }
  ]
}
EOF

# Test config validity first
echo "Testing Xray config..."
if [ -n "$SUDO" ]; then
  if ! $SUDO ./xray run -test -c config.json 2>&1 | tee config_test.log; then
    echo "Config test failed:"
    cat config_test.log
    exit 1
  fi
else
  if ! ./xray run -test -c config.json 2>&1 | tee config_test.log; then
    echo "Config test failed:"
    cat config_test.log
    exit 1
  fi
fi

# Start Xray in background
echo "Starting Xray..."
if [ -n "$SUDO" ]; then
  nohup $SUDO ./xray run -c config.json > run.log 2> error.log &
  XRAY_PID=$!
else
  nohup ./xray run -c config.json > run.log 2> error.log &
  XRAY_PID=$!
fi

# Wait for Xray to bind to port 443 (retry for up to 10 seconds)
echo "Waiting for Xray to listen on port 443..."
MAX_WAIT=10
COUNTER=0
while [ $COUNTER -lt $MAX_WAIT ]; do
  if [ -n "$SUDO" ]; then
    if $SUDO ss -tulpn | grep -q ":443.*xray"; then
      echo "✓ Xray listening on port 443"
      break
    fi
  else
    if ss -tulpn | grep -q ":443.*xray"; then
      echo "✓ Xray listening on port 443"
      break
    fi
  fi
  
  sleep 1
  COUNTER=$((COUNTER+1))
  echo "Still waiting... ($COUNTER/$MAX_WAIT)"
done

# Final verification
if [ -n "$SUDO" ]; then
  if ! $SUDO ss -tulpn | grep -q ":443.*xray"; then
    echo "✗ Xray failed to bind to port 443 after ${MAX_WAIT}s"
    echo "=== run.log ==="
    cat run.log
    echo "=== error.log ==="
    cat error.log
    echo "=== Process check ==="
    ps aux | grep [x]ray || echo "No xray process"
    echo "=== Port status ==="
    $SUDO ss -tulpn | grep :443 || echo "Nothing on port 443"
    exit 1
  fi
else
  if ! ss -tulpn | grep -q ":443.*xray"; then
    echo "✗ Xray failed to bind to port 443 after ${MAX_WAIT}s"
    echo "=== run.log ==="
    cat run.log
    echo "=== error.log ==="
    cat error.log
    exit 1
  fi
fi

echo "✓ Xray started successfully"

# Get IP
PUBLIC_IP=$(curl -s -4 ip.sb)

# Output info for client (masked markers)
echo "---VLESS_INFO_START---"
echo "IP=$PUBLIC_IP"
echo "PORT=$PORT"
echo "UUID=$UUID"
echo "PUBLIC_KEY=$PUBLIC_KEY"
echo "SNI=$SNI"
echo "---VLESS_INFO_END---"
