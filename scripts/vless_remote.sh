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

# Install basic tools
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq curl openssl uuid-runtime

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

# Cleanup old process if running
# Stop systemd service if exists (cleanup previous installs)
if command -v systemctl >/dev/null 2>&1; then
    if [ -n "$SUDO" ]; then
       $SUDO systemctl stop xray || true
       $SUDO systemctl disable xray || true
    else
       systemctl stop xray || true
       systemctl disable xray || true
    fi
fi

# Kill any existing xray process
if [ -n "$SUDO" ]; then
   $SUDO pkill -f xray || true
else
   pkill -f xray || true
fi

# Download and Unzip
curl -L -s "$DOWNLOAD_URL" -o xray.zip
# Install unzip if missing
if ! command -v unzip >/dev/null 2>&1; then
    if [ -n "$SUDO" ]; then
        $SUDO apt-get update -qq && $SUDO apt-get install -y -qq unzip
    fi
fi
unzip -o -q xray.zip
rm xray.zip
chmod +x xray

# Generate UUID and Keys using the downloaded binary
KEYS=$(./xray x25519)
PRIVATE_KEY=$(echo "$KEYS" | grep -i "Private" | head -n1 | awk -F: '{print $2}' | xargs)
PUBLIC_KEY=$(echo "$KEYS" | grep -i "Public" | head -n1 | awk -F: '{print $2}' | xargs)
UUID=$(uuidgen)

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

# Start Xray in background (nohup)
# Use sudo if port 443 requires it (usually yes)
if [ -n "$SUDO" ]; then
  touch run.log
  nohup $SUDO ./xray run -c config.json > run.log 2>&1 &
else
  nohup ./xray run -c config.json > run.log 2>&1 &
fi

# Wait a bit to ensure start
sleep 2

# Check if running
if ! pgrep -f "$WORK_DIR/xray" > /dev/null; then
  echo "Failed to start Xray"
  cat run.log
  exit 1
fi

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
