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

# Install Xray (official script)
echo ">>> Installing Xray..."
curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh -o install-release.sh
chmod +x install-release.sh
$SUDO ./install-release.sh install
rm install-release.sh

# Generate Config
UUID=$(uuidgen)

# Generate KeyPair (using xray binary)
KEYS=$(/usr/local/bin/xray x25519)
echo "Generated Keys: $KEYS"

# Parse keys more robustly
PRIVATE_KEY=$(echo "$KEYS" | grep -i "Private" | head -n1 | awk -F: '{print $2}' | xargs)
PUBLIC_KEY=$(echo "$KEYS" | grep -i "Public" | head -n1 | awk -F: '{print $2}' | xargs)

PORT=443
SNI="www.apple.com"

# Config JSON
# Use tee to write as root
cat <<EOF | $SUDO tee /usr/local/etc/xray/config.json > /dev/null
{
  "log": {
    "loglevel": "warning"
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

# Restart Xray
$SUDO systemctl restart xray
$SUDO systemctl enable xray

# Get IP
PUBLIC_IP=$(curl -s -4 ip.sb)

# Output info for client
echo "---VLESS_INFO_START---"
echo "IP=$PUBLIC_IP"
echo "PORT=$PORT"
echo "UUID=$UUID"
echo "PUBLIC_KEY=$PUBLIC_KEY"
echo "SNI=$SNI"
echo "---VLESS_INFO_END---"
