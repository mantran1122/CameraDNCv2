"""
Zalo Group Webhook Bridge Microservice.
Nhận webhook POST từ Camera AI DNC và đẩy tin nhắn cảnh báo đỏ vào Zalo Group.

Cách chạy:
    python bridge.py
Mặc định lắng nghe tại: http://127.0.0.1:5000/webhook
"""

import os
import json
import logging
from typing import Dict, Any
import requests
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ZaloBridge")

app = Flask(__name__)

# Cấu hình Zalo (nếu dùng Zalo OA hoặc Zalo Chatbot API)
ZALO_OA_ACCESS_TOKEN = os.getenv("ZALO_OA_ACCESS_TOKEN", "").strip()
ZALO_GROUP_ID = os.getenv("ZALO_GROUP_ID", "").strip()
BRIDGE_SECRET = os.getenv("ZALO_WEBHOOK_SECRET", "").strip()


@app.route("/webhook", methods=["POST"])
def zalo_webhook_handler():
    """Nhận cảnh báo đỏ từ Camera AI."""
    # Kiểm tra secret token nếu có
    if BRIDGE_SECRET:
        auth_header = request.headers.get("Authorization", "")
        expected = f"Bearer {BRIDGE_SECRET}"
        if auth_header != expected:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401

    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    message = payload.get("message") or payload.get("text") or payload.get("content") or "Cảnh báo an ninh!"
    cam_name = payload.get("camera_name", "Camera")
    clip_url = payload.get("clip_url", "")
    event_code = payload.get("event_code", "Alert")

    logger.info(f"[ZaloBridge] Nhận cảnh báo: {cam_name} | {event_code}")
    print("\n" + "=" * 60)
    print("🚨 CẢNH BÁO ĐỎ TỪ CAMERA AI DNC:")
    print(f"Nội dung: {message}")
    if clip_url:
        print(f"Link video: {clip_url}")
    print("=" * 60 + "\n")

    # Nếu có token Zalo OA: gửi qua Open API của Zalo
    if ZALO_OA_ACCESS_TOKEN and ZALO_GROUP_ID:
        try:
            oa_url = "https://openapi.zalo.me/v2.0/oa/message"
            oa_payload = {
                "recipient": {"group_id": ZALO_GROUP_ID},
                "message": {"text": message}
            }
            oa_headers = {
                "Content-Type": "application/json",
                "access_token": ZALO_OA_ACCESS_TOKEN
            }
            resp = requests.post(oa_url, json=oa_payload, headers=oa_headers, timeout=10)
            logger.info(f"[ZaloBridge] Đã chuyển tiếp tới Zalo OA (HTTP {resp.status_code}): {resp.text[:200]}")
        except Exception as err:
            logger.error(f"[ZaloBridge] Lỗi chuyển tiếp Zalo OA: {err}")

    return jsonify({
        "status": "success",
        "message": "Đã tiếp nhận cảnh báo đỏ thành công!",
        "camera": cam_name,
        "event_code": event_code
    }), 200


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok", "service": "Zalo Group Bridge"}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    logger.info(f"Khởi động Zalo Group Bridge trên cổng {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
