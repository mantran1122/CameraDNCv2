"""Multi-channel Alert Dispatcher for CameraAI.

Dispatches high-severity alerts (Nhãn Đỏ) to external channels:
- Telegram Group Bot
- Zalo Group Webhook Bridge
- Gmail SMTP

Runs asynchronously in background worker threads with built-in deduplication
so the main NVR ingestion loop and WebSocket broadcasts remain unblocked.
"""

import email.message
import json
import logging
import os
import smtplib
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests

import config

logger = logging.getLogger("alert_dispatcher")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Cooldown per (channel, event_code) in seconds to prevent spamming group chats
ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "20"))
_last_sent_cache: Dict[tuple, float] = {}
_cache_lock = threading.Lock()


def _is_cooling_down(channel: int, event_code: str) -> bool:
    now = time.time()
    key = (channel, str(event_code))
    with _cache_lock:
        last = _last_sent_cache.get(key, 0.0)
        if now - last < ALERT_COOLDOWN_SECONDS:
            return True
        _last_sent_cache[key] = now
        # Clean old keys (> 1 hour)
        expired = [k for k, v in _last_sent_cache.items() if now - v > 3600]
        for k in expired:
            _last_sent_cache.pop(k, None)
    return False


def _get_camera_name(channel: int) -> str:
    cam_names = getattr(config, "CAMERA_NAMES", {})
    if isinstance(cam_names, dict):
        return cam_names.get(str(channel)) or cam_names.get(channel) or f"Camera Kênh {channel:02d}"
    return f"Camera Kênh {channel:02d}"


def _get_event_label(event_code: str) -> str:
    options = getattr(config, "ABNORMAL_BEHAVIOR_OPTIONS", [])
    for opt in options:
        if opt.get("code") == event_code:
            return opt.get("label", event_code)
    return event_code


def send_telegram_alert(payload: Dict[str, Any]) -> bool:
    """Send high-priority alert to a configured Telegram Group/Chat."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        return False

    channel = payload.get("channel", 0)
    event_code = payload.get("event_code", "Unknown")
    cam_name = _get_camera_name(channel)
    label = _get_event_label(event_code)
    ts = payload.get("timestamp", "")
    desc = payload.get("description", "")
    clip_url = payload.get("clip_url", "")
    app_base = os.getenv("CAMERAAI_BASE_URL", "").rstrip("/")

    full_clip_url = urljoin(f"{app_base}/", clip_url.lstrip("/")) if (app_base and clip_url) else clip_url

    text = (
        f"🚨 <b>[CẢNH BÁO ĐỎ - AN NINH DNC]</b>\n"
        f"📹 <b>Vị trí:</b> {cam_name} (Kênh {channel:02d})\n"
        f"⚠️ <b>Hành vi:</b> {label} (<code>{event_code}</code>)\n"
        f"⏰ <b>Thời gian:</b> {ts}\n"
        f"📝 <b>Chi tiết:</b> {desc}\n"
    )
    if full_clip_url:
        text += f"🎬 <b>Xem clip:</b> <a href=\"{full_clip_url}\">Bấm vào đây để mở video</a>\n"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    body = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        resp = requests.post(url, json=body, timeout=8)
        if resp.status_code == 200:
            logger.info(f"[AlertDispatcher] Sent Telegram alert for ch={channel}, code={event_code}")
            return True
        logger.warning(f"[AlertDispatcher] Telegram error HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        logger.error(f"[AlertDispatcher] Telegram connection error: {exc}")
    return False


def send_zalo_webhook_alert(payload: Dict[str, Any]) -> bool:
    """Send alert payload to a Zalo Group Bot / Webhook relay bridge."""
    webhook_url = os.getenv("ZALO_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return False

    channel = payload.get("channel", 0)
    event_code = payload.get("event_code", "Unknown")
    cam_name = _get_camera_name(channel)
    label = _get_event_label(event_code)
    ts = payload.get("timestamp", "")
    desc = payload.get("description", "")
    clip_url = payload.get("clip_url", "")
    app_base = os.getenv("CAMERAAI_BASE_URL", "").rstrip("/")
    full_clip_url = urljoin(f"{app_base}/", clip_url.lstrip("/")) if (app_base and clip_url) else clip_url

    msg_text = f"🚨 [CẢNH BÁO ĐỎ] {label} tại {cam_name} lúc {ts}.\nChi tiết: {desc}"
    if full_clip_url:
        msg_text += f"\nXem video clip: {full_clip_url}"

    body = {
        "event_type": "high_security_alert",
        "severity": "high",
        "camera_name": cam_name,
        "channel": channel,
        "event_code": event_code,
        "label": label,
        "timestamp": ts,
        "description": desc,
        "clip_url": full_clip_url,
        "message": msg_text,
        "text": msg_text,
        "content": msg_text,
        "msg": msg_text,
    }

    headers = {"Content-Type": "application/json"}
    zalo_token = os.getenv("ZALO_WEBHOOK_SECRET", "").strip()
    if zalo_token:
        headers["Authorization"] = f"Bearer {zalo_token}"

    try:
        resp = requests.post(webhook_url, json=body, headers=headers, timeout=8)
        if resp.status_code in (200, 201, 202, 204):
            logger.info(f"[AlertDispatcher] Sent Zalo Webhook alert for ch={channel}, code={event_code}")
            return True
        logger.warning(f"[AlertDispatcher] Zalo Webhook error HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        if "127.0.0.1:5055" in webhook_url or "localhost:5055" in webhook_url:
            for alt in ["http://zalo-bridge:5055/webhook", "http://host.docker.internal:5055/webhook"]:
                try:
                    resp = requests.post(alt, json=body, headers=headers, timeout=8)
                    if resp.status_code in (200, 201, 202, 204):
                        logger.info(f"[AlertDispatcher] Sent Zalo Webhook alert via fallback {alt}")
                        return True
                except Exception:
                    pass
        logger.error(f"[AlertDispatcher] Zalo Webhook connection error: {exc}")
    return False


def test_zalo_webhook(webhook_url: Optional[str] = None, token: Optional[str] = None) -> Dict[str, Any]:
    """Test connectivity to Zalo webhook bridge."""
    target_url = (webhook_url or os.getenv("ZALO_WEBHOOK_URL", "")).strip()
    if not target_url:
        return {"success": False, "message": "Chưa cấu hình ZALO_WEBHOOK_URL trong .env"}

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    msg_text = f"🚨 [TEST CẢNH BÁO] Hệ thống Camera AI DNC kết nối thành công tới Zalo Group lúc {now_str}."
    body = {
        "event_type": "test_alert",
        "severity": "high",
        "camera_name": "Camera 11 - Quản lý HSSV",
        "channel": 11,
        "event_code": "AudioMutation",
        "label": "Âm thanh bất thường (Test)",
        "timestamp": now_str,
        "description": "Thử nghiệm kết nối bắn cảnh báo đỏ tự động vào Zalo Group",
        "message": msg_text,
        "text": msg_text,
        "content": msg_text,
        "msg": msg_text,
    }

    headers = {"Content-Type": "application/json"}
    secret = (token or os.getenv("ZALO_WEBHOOK_SECRET", "")).strip()
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    try:
        resp = requests.post(target_url, json=body, headers=headers, timeout=8)
        if resp.status_code in (200, 201, 202, 204):
            return {"success": True, "status_code": resp.status_code, "message": "Đã gửi tin nhắn thử nghiệm thành công tới Zalo Group!"}
        return {"success": False, "status_code": resp.status_code, "message": f"Zalo Webhook phản hồi mã lỗi {resp.status_code}: {resp.text[:200]}"}
    except Exception as exc:
        if "127.0.0.1:5055" in target_url or "localhost:5055" in target_url:
            for alt in ["http://zalo-bridge:5055/webhook", "http://host.docker.internal:5055/webhook"]:
                try:
                    resp = requests.post(alt, json=body, headers=headers, timeout=8)
                    if resp.status_code in (200, 201, 202, 204):
                        return {"success": True, "status_code": resp.status_code, "message": f"Đã gửi tin nhắn thử nghiệm thành công tới Zalo Group (qua container link {alt})!"}
                except Exception:
                    pass
        return {"success": False, "message": f"Không thể kết nối tới Zalo Webhook ({target_url}): {exc}"}


def send_email_alert(payload: Dict[str, Any]) -> bool:
    """Send high-priority alert email to administrators via SMTP."""
    smtp_server = os.getenv("SMTP_SERVER", "").strip()
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    if not smtp_server or not smtp_user:
        return False

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")

    raw_recipients = os.getenv("ALERT_EMAIL_RECIPIENTS", "").strip()
    recipients = [r.strip() for r in raw_recipients.split(",") if r.strip()]
    if not recipients:
        recipients = getattr(config, "GOOGLE_ADMIN_EMAILS", [])
    if not recipients:
        return False

    channel = payload.get("channel", 0)
    event_code = payload.get("event_code", "Unknown")
    cam_name = _get_camera_name(channel)
    label = _get_event_label(event_code)
    ts = payload.get("timestamp", "")
    desc = payload.get("description", "")
    clip_url = payload.get("clip_url", "")
    app_base = os.getenv("CAMERAAI_BASE_URL", "").rstrip("/")
    full_clip_url = urljoin(f"{app_base}/", clip_url.lstrip("/")) if (app_base and clip_url) else clip_url

    subject = f"[CẢNH BÁO ĐỎ AN NINH] {label} tại {cam_name} ({ts})"

    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #1f2937;">
        <div style="max-width: 600px; margin: 0 auto; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden;">
            <div style="background-color: #dc2626; color: #ffffff; padding: 16px 20px;">
                <h2 style="margin: 0; font-size: 1.25rem;">🚨 CẢNH BÁO AN NINH CẤP CAO (NHÃN ĐỎ)</h2>
            </div>
            <div style="padding: 20px;">
                <p>Hệ thống AI giám sát Camera DNC vừa ghi nhận một sự kiện bất thường có mức độ nghiêm trọng cao:</p>
                <table style="width: 100%; border-collapse: collapse; margin-top: 12px; margin-bottom: 20px;">
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #f3f4f6; font-weight: bold; width: 140px;">Vị trí camera:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #f3f4f6;">{cam_name} (Kênh {channel:02d})</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #f3f4f6; font-weight: bold;">Hành vi cảnh báo:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #f3f4f6; color: #dc2626; font-weight: bold;">{label} ({event_code})</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #f3f4f6; font-weight: bold;">Thời gian phát hiện:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #f3f4f6;">{ts}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #f3f4f6; font-weight: bold;">Chi tiết mô tả:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #f3f4f6;">{desc}</td>
                    </tr>
                </table>
                {"<p><a href='" + full_clip_url + "' style='display: inline-block; background: #2563eb; color: #ffffff; padding: 10px 18px; text-decoration: none; border-radius: 6px; font-weight: bold;'>Xem Video Bằng Chứng</a></p>" if full_clip_url else ""}
                <p style="font-size: 0.85rem; color: #6b7280; margin-top: 24px; border-top: 1px solid #e5e7eb; padding-top: 12px;">
                    Email này được phát tự động từ hệ thống Camera DNC AI. Vui lòng kiểm tra hiện trường hoặc liên hệ bảo vệ trực ban nếu cần xử lý khẩn cấp.
                </p>
            </div>
        </div>
    </body>
    </html>
    """

    msg = email.message.EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = ", ".join(recipients)
    msg.set_content(f"[CẢNH BÁO ĐỎ] {label} tại {cam_name} lúc {ts}. Chi tiết: {desc}\nXem clip: {full_clip_url}")
    msg.add_alternative(html_content, subtype="html")

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
            if use_tls:
                server.starttls()
            if smtp_password:
                server.login(smtp_user, smtp_password)
            server.send_message(msg)
        logger.info(f"[AlertDispatcher] Sent email alert to {recipients} for ch={channel}, code={event_code}")
        return True
    except Exception as exc:
        logger.error(f"[AlertDispatcher] Email send error: {exc}")
    return False


def dispatch_high_severity_alert_async(event_payload: Dict[str, Any]) -> None:
    """Entry point: Dispatches red alerts to all enabled channels asynchronously."""
    severity = str(event_payload.get("severity") or "").lower()
    event_code = str(event_payload.get("event_code") or "")
    critical_codes = {"Fight", "Intrusion", "CrossLine", "AudioMutation", "SoundDetection"}

    # Only dispatch if explicitly severity == 'high' or is in critical abnormal behaviors
    if severity != "high" and event_code not in critical_codes:
        return

    channel = int(event_payload.get("channel") or 0)
    if _is_cooling_down(channel, event_code):
        logger.debug(f"[AlertDispatcher] ch={channel}, code={event_code} is cooling down, skipped group alert.")
        return

    def _worker():
        payload = dict(event_payload)
        # 1. Telegram Group Bot
        send_telegram_alert(payload)
        # 2. Zalo Group Webhook
        send_zalo_webhook_alert(payload)
        # 3. Email Gmail
        send_email_alert(payload)

    t = threading.Thread(target=_worker, daemon=True, name=f"alert-dispatch-{channel}-{event_code}")
    t.start()
