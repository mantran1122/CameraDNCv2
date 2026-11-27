#!/usr/bin/env bash
# ==============================================================================
# CameraAI & Zalo Bridge - Automated Disk Space Watchdog & Auto-Healing Daemon
# Runs via cron every 15 minutes to guarantee the server never hits 100% disk full.
# ==============================================================================

set -o pipefail

LOG_FILE="/var/log/camera_disk_guard.log"
TARGET_DIR="${1:-/home/dnc/projects/CameraDNCv2}"

# Fallback if directory not found
if [ ! -d "$TARGET_DIR" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    if [ -d "$SCRIPT_DIR/CameraAI" ]; then
        TARGET_DIR="$SCRIPT_DIR"
    fi
fi

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$msg"
    if [ -w "$(dirname "$LOG_FILE")" ]; then
        echo "$msg" >> "$LOG_FILE" 2>/dev/null || true
    fi
}

# 1. Get current disk usage on root partition
FREE_KB=$(df -k / | awk 'NR==2 {print $4}')
TOTAL_KB=$(df -k / | awk 'NR==2 {print $2}')
USE_PCT=$(df -k / | awk 'NR==2 {print $5}' | tr -d '%')

FREE_GB=$((FREE_KB / 1024 / 1024))
TOTAL_GB=$((TOTAL_KB / 1024 / 1024))

# Verbose flag check
VERBOSE=0
if [ "$1" == "--verbose" ] || [ "$2" == "--verbose" ]; then
    VERBOSE=1
fi

if [ "$VERBOSE" -eq 1 ]; then
    log "Disk Check: Total=${TOTAL_GB}GB, Free=${FREE_GB}GB (${FREE_KB}KB), Used=${USE_PCT}%"
fi

# Thresholds:
# Trigger cleanup if Free < 6GB or Disk Usage >= 75%
# Trigger EMERGENCY cleanup if Free < 2GB or Disk Usage >= 90%
TRIGGER_CLEANUP=0
EMERGENCY=0

if [ "$FREE_GB" -lt 6 ] || [ "$USE_PCT" -ge 75 ]; then
    TRIGGER_CLEANUP=1
fi

if [ "$FREE_GB" -lt 2 ] || [ "$USE_PCT" -ge 90 ]; then
    TRIGGER_CLEANUP=1
    EMERGENCY=1
fi

if [ "$1" == "--force" ] || [ "$2" == "--force" ]; then
    TRIGGER_CLEANUP=1
    EMERGENCY=1
    log "[FORCED] Running manual aggressive cleanup..."
fi

if [ "$TRIGGER_CLEANUP" -eq 0 ]; then
    # System is healthy, exit silently
    exit 0
fi

log "⚠️ Disk space warning: Free=${FREE_GB}GB, Used=${USE_PCT}%. Starting auto-remediation..."

# Step 1: Clean Zalo Bridge temporary clips (files older than 10 mins)
ZALO_CLIPS="$TARGET_DIR/scripts/zalo_bridge/data/clips"
if [ -d "$ZALO_CLIPS" ]; then
    ZALO_COUNT=$(find "$ZALO_CLIPS" -type f -name "*.mp4" -mmin +10 | wc -l)
    if [ "$ZALO_COUNT" -gt 0 ]; then
        find "$ZALO_CLIPS" -type f -name "*.mp4" -mmin +10 -delete
        log "✅ Purged $ZALO_COUNT temporary video clips in Zalo Bridge cache."
    fi
    if [ "$EMERGENCY" -eq 1 ]; then
        rm -rf "$ZALO_CLIPS"/* 2>/dev/null || true
        log "🚨 Emergency: Cleared all temporary clips in Zalo Bridge."
    fi
fi

# Step 2: Clean routine camera clips in CameraAI
CAMERA_CLIPS="$TARGET_DIR/CameraAI/storage/clips/cameras"
if [ -d "$CAMERA_CLIPS" ]; then
    if [ "$EMERGENCY" -eq 1 ]; then
        # In emergency (<2GB free), purge routine clips older than 24 hours
        PURGED_CAM=$(find "$CAMERA_CLIPS" -type f -name "*.mp4" -mtime +1 | wc -l)
        find "$CAMERA_CLIPS" -type f -name "*.mp4" -mtime +1 -delete 2>/dev/null || true
        log "🚨 Emergency: Purged $PURGED_CAM routine camera clips older than 24h."
    else
        # Normal cleanup, purge routine clips older than 3 days
        PURGED_CAM=$(find "$CAMERA_CLIPS" -type f -name "*.mp4" -mtime +3 | wc -l)
        find "$CAMERA_CLIPS" -type f -name "*.mp4" -mtime +3 -delete 2>/dev/null || true
        if [ "$PURGED_CAM" -gt 0 ]; then
            log "✅ Purged $PURGED_CAM routine camera clips older than 3 days."
        fi
    fi
    # Remove empty day folders
    find "$CAMERA_CLIPS" -type d -empty -delete 2>/dev/null || true
fi

# Step 3: Truncate oversized Docker container json logs (> 20MB)
if command -v docker &> /dev/null; then
    DOCKER_LOGS=$(find /var/lib/docker/containers/ -name "*-json.log" -size +20M 2>/dev/null || true)
    if [ -n "$DOCKER_LOGS" ]; then
        for f in $DOCKER_LOGS; do
            truncate -s 0 "$f" 2>/dev/null || true
            log "✅ Truncated oversized Docker log: $f"
        done
    fi

    # Prune dangling docker build cache, stopped containers, and unused old images
    docker container prune -f > /dev/null 2>&1 || true
    docker image prune -a -f --filter "until=24h" > /dev/null 2>&1 || true
    docker builder prune -a -f > /dev/null 2>&1 || true
    docker system prune -f --volumes=false > /dev/null 2>&1 || true
fi

# Step 4: Vacuum systemd journal logs to max 50MB
if command -v journalctl &> /dev/null; then
    journalctl --vacuum-time=3d --vacuum-size=50M > /dev/null 2>&1 || true
fi

# Step 5: Clean APT cache and temporary directory
if command -v apt-get &> /dev/null; then
    apt-get clean > /dev/null 2>&1 || true
fi
find /tmp -type f -atime +2 -delete 2>/dev/null || true

# Check results after remediation
NEW_FREE_KB=$(df -k / | awk 'NR==2 {print $4}')
NEW_FREE_GB=$((NEW_FREE_KB / 1024 / 1024))
NEW_USE_PCT=$(df -k / | awk 'NR==2 {print $5}' | tr -d '%')
FREED_MB=$(((NEW_FREE_KB - FREE_KB) / 1024))

log "🎉 Remediation complete. Freed: ~${FREED_MB}MB. New Free Space: ${NEW_FREE_GB}GB (Used ${NEW_USE_PCT}%)."
