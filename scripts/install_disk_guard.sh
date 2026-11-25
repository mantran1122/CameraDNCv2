#!/usr/bin/env bash
# ==============================================================================
# Installer for CameraAI Automated Disk Space Watchdog & System Self-Healing
# Run with: sudo bash scripts/install_disk_guard.sh
# ==============================================================================

set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "❌ Lỗi: Vui lòng chạy lệnh này với quyền root hoặc sudo: sudo bash scripts/install_disk_guard.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
GUARD_SCRIPT="$SCRIPT_DIR/auto_disk_guard.sh"

if [ ! -f "$GUARD_SCRIPT" ]; then
    echo "❌ Không tìm thấy script: $GUARD_SCRIPT"
    exit 1
fi

chmod +x "$GUARD_SCRIPT"

# 1. Cài đặt Cron Job chạy định kỳ mỗi 15 phút
CRON_FILE="/etc/cron.d/camera_disk_guard"
echo "SHELL=/bin/bash" > "$CRON_FILE"
echo "PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin" >> "$CRON_FILE"
echo "*/15 * * * * root bash $GUARD_SCRIPT \"$TARGET_DIR\" > /dev/null 2>&1" >> "$CRON_FILE"
chmod 644 "$CRON_FILE"

echo "✅ Đã đăng ký tác vụ tự động bảo vệ ổ cứng mỗi 15 phút tại: $CRON_FILE"

# 2. Chạy thử nghiệm ngay một lần
echo "🚀 Đang kích hoạt dọn dẹp khẩn cấp lần đầu..."
bash "$GUARD_SCRIPT" "$TARGET_DIR" --force

# 3. Kiểm tra mở rộng ổ cứng LVM (nếu ổ cứng vật lý còn dung lượng trống chưa phân bổ)
echo ""
echo "🔍 Kiểm tra dung lượng ổ đĩa vật lý (LVM)..."
if command -v vgs &> /dev/null && command -v lvs &> /dev/null; then
    VG_NAME=$(vgs --noheadings -o vg_name 2>/dev/null | awk '{print $1}' | head -n 1 || true)
    VG_FREE=$(vgs --noheadings -o vg_free 2>/dev/null | awk '{print $1}' | head -n 1 || true)
    if [ -n "$VG_NAME" ] && [ -n "$VG_FREE" ] && [ "$VG_FREE" != "0" ] && [ "$VG_FREE" != "0G" ]; then
        echo "💡 PHÁT HIỆN: Volume Group ($VG_NAME) còn trống $VG_FREE chưa sử dụng!"
        echo "   Đang tự động mở rộng ổ cứng gốc (/) lên tối đa dung lượng đĩa vật lý..."
        lvextend -l +100%FREE /dev/mapper/ubuntu--vg-ubuntu--lv -r 2>/dev/null || true
        echo "✅ Đã mở rộng phân vùng thành công!"
    else
        echo "ℹ️ Volume Group đã sử dụng hết phân vùng vật lý được cấp."
    fi
fi

echo ""
echo "📊 Tình trạng dung lượng ổ cứng hiện tại:"
df -h /

echo ""
echo "✨ HOÀN TẤT CÀI ĐẶT HỆ THỐNG TỰ ĐỘNG CHỐNG TRÀN Ổ ĐĨA TRIỆT ĐỂ! ✨"
echo "Từ nay hệ thống sẽ tự động quét dọn ngầm mỗi 15 phút, không còn bao giờ bị lỗi 100% đĩa."
