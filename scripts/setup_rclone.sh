#!/bin/bash
set -e

# Default variables
FORCE_REMOUNT=${1:-false}

echo ">>> Setting up Rclone..."

# 1. Install Rclone (from local repo binary)
CURRENT_VER=$(rclone version 2>/dev/null | head -1 | cut -d' ' -f2 || echo 'none')
if [ "$CURRENT_VER" != "v1.72.1" ]; then
    echo '  -> Improving Rclone installation (v1.72.1)...'
    if [ -f "bin/rclone-arm64.zip" ]; then
        unzip -q -o bin/rclone-arm64.zip -d /tmp/
        sudo cp /tmp/rclone-v1.72.1-linux-arm64/rclone /usr/bin/rclone
        sudo chmod 755 /usr/bin/rclone
        sudo chown root:root /usr/bin/rclone
        rm -rf /tmp/rclone-v1.72.1-linux-arm64
    else
        echo '❌ Repo binary bin/rclone-arm64.zip not found!'
        exit 1
    fi
else
    echo '  -> Rclone is up to date (v1.72.1)'
fi

# 2. Install fuse
if ! command -v fusermount >/dev/null; then
    echo '  -> Installing fuse...'
    sudo apt-get update -qq && sudo apt-get install -y -qq fuse
fi

# 3. Check Config
if [ ! -f "/etc/rclone/rclone.conf" ]; then
    echo "❌ /etc/rclone/rclone.conf not found. Please inject it before running this script."
    exit 1
fi
sudo chmod 600 /etc/rclone/rclone.conf

# 4. Create Mount Points
sudo mkdir -p /mnt/gpan
sudo mkdir -p /mnt/onedrive
sudo chmod 777 /mnt/gpan /mnt/onedrive

# 5. Systemd Service Function
create_service() {
    local REMOTE=$1
    local MOUNT_POINT=$2
    local SERVICE_NAME="rclone-${REMOTE}"
    
    echo "  -> Configuring Service: ${SERVICE_NAME}..."
    
    # Find fusermount path
    FUSERMOUNT_BIN=$(command -v fusermount || echo "/bin/fusermount")
    if [ ! -x "$FUSERMOUNT_BIN" ]; then
        if [ -x "/usr/bin/fusermount" ]; then
            FUSERMOUNT_BIN="/usr/bin/fusermount"
        else
            echo "❌ fusermount not found!"
            exit 1
        fi
    fi
    echo "     Using fusermount at: $FUSERMOUNT_BIN"

    sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=Rclone Mount for ${REMOTE}
AssertPathIsDirectory=${MOUNT_POINT}
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=root
ExecStart=/usr/bin/rclone mount ${REMOTE}: ${MOUNT_POINT} \\
    --config=/etc/rclone/rclone.conf \\
    --allow-other \\
    --allow-non-empty \\
    --vfs-cache-mode writes \\
    --transfers 4 \\
    --buffer-size 32M \\
    --low-level-retries 10 \\
    --log-level ERROR \\
    --log-file /var/log/rclone-${REMOTE}.log
ExecStop=${FUSERMOUNT_BIN} -u ${MOUNT_POINT}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    
    sudo systemctl daemon-reload
    sudo systemctl enable ${SERVICE_NAME}
    
    if sudo systemctl is-active --quiet ${SERVICE_NAME}; then
        if [ "$FORCE_REMOUNT" = "true" ]; then
            echo "     Restarting service..."
            sudo systemctl restart ${SERVICE_NAME}
        else
            echo "     Service already running (skip restart)"
        fi
    else
        echo "     Starting service..."
        sudo systemctl start ${SERVICE_NAME}
    fi
}

# 6. Setup Services
create_service "gpan" "/mnt/gpan"
create_service "onedrive" "/mnt/onedrive"

# 7. Verify
sleep 3
echo '  -> Mount Check:'
if mountpoint -q /mnt/gpan; then echo '     ✅ /mnt/gpan mounted'; else echo '     ❌ /mnt/gpan NOT mounted'; fi
if mountpoint -q /mnt/onedrive; then echo '     ✅ /mnt/onedrive mounted'; else echo '     ❌ /mnt/onedrive NOT mounted'; fi
