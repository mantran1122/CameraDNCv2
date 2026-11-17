import express from "express";
import fs from "node:fs";
import path from "node:path";
import { Zalo, ThreadType, LoginQRCallbackEventType } from "zca-js";
import qrcode from "qrcode-terminal";

const PORT = parseInt(process.env.PORT || "5055", 10);
const DATA_DIR = process.env.DATA_DIR || "./data";
if (!fs.existsSync(DATA_DIR)) {
    try { fs.mkdirSync(DATA_DIR, { recursive: true }); } catch (e) {}
}

const APPSTATE_FILE = path.resolve(DATA_DIR, "appstate.json");
const CONFIG_FILE = path.resolve(DATA_DIR, "zalo_config.json");
const QR_FILE = path.resolve(DATA_DIR, "qr.png");

// Đọc cấu hình nhóm mục tiêu (nếu đã lưu từ trước)
let bridgeConfig = {
    targetGroupId: process.env.ZALO_GROUP_ID || "",
    groupName: "",
    inviteLink: process.env.ZALO_GROUP_LINK || "https://zalo.me/g/libazgippahcfbk99qkc"
};

if (fs.existsSync(CONFIG_FILE)) {
    try {
        const saved = JSON.parse(fs.readFileSync(CONFIG_FILE, "utf-8"));
        bridgeConfig = { ...bridgeConfig, ...saved };
    } catch (e) {
        console.warn("[ZaloBridge] Không đọc được zalo_config.json:", e.message);
    }
}

function saveConfig() {
    try {
        fs.writeFileSync(CONFIG_FILE, JSON.stringify(bridgeConfig, null, 2), "utf-8");
    } catch (e) {
        console.error("[ZaloBridge] Lỗi lưu config:", e);
    }
}

console.log("=============================================================");
console.log("🚀 KHỞI ĐỘNG ZALO GROUP ALERT BRIDGE CHO CAMERADNCV2");
console.log("=============================================================");

let api = null;
const zalo = new Zalo();

async function initZalo() {
    try {
        if (fs.existsSync(APPSTATE_FILE)) {
            console.log("[ZaloBridge] Đang khôi phục phiên đăng nhập từ appstate.json...");
            const appstate = JSON.parse(fs.readFileSync(APPSTATE_FILE, "utf-8"));
            try {
                api = await zalo.login(appstate);
                console.log("✅ Đăng nhập Zalo thành công từ phiên đã lưu!");
            } catch (err) {
                console.warn("[ZaloBridge] Phiên đăng nhập cũ đã hết hạn, cần quét mã QR mới:", err.message);
                api = null;
            }
        }

        if (!api) {
            console.log("\n📲 VUI LÒNG MỞ ỨNG DỤNG ZALO TRÊN ĐIỆN THOẠI ĐỂ QUÉT MÃ QR:");
            console.log(`🌐 Bạn có thể mở trực tiếp link trên trình duyệt để quét: http://<IP_SERVER>:${PORT}/login`);
            console.log(`📁 File ảnh QR cũng được lưu tại: ${QR_FILE}`);
            console.log("-------------------------------------------------------------");

            api = await zalo.loginQR(
                {
                    qrPath: QR_FILE
                },
                async (event) => {
                    switch (event.type) {
                        case LoginQRCallbackEventType.QRCodeGenerated:
                            console.log(`[ZaloBridge] 📸 Mã QR mới đã được tạo! Mở http://<IP_SERVER>:${PORT}/login để xem ảnh và quét.`);
                            if (event.actions && typeof event.actions.saveToFile === "function") {
                                await event.actions.saveToFile(QR_FILE);
                            }
                            break;
                        case LoginQRCallbackEventType.QRCodeScanned:
                            console.log(`[ZaloBridge] 📱 Đã quét QR thành công bởi [${event.data?.display_name || "Người dùng"}]. Vui lòng bấm Đăng nhập trên điện thoại!`);
                            break;
                        case LoginQRCallbackEventType.QRCodeExpired:
                            console.log("[ZaloBridge] ⏳ Mã QR đã hết hạn. Đang tự động làm mới mã QR...");
                            if (event.actions && typeof event.actions.retry === "function") {
                                event.actions.retry();
                            }
                            break;
                        case LoginQRCallbackEventType.QRCodeDeclined:
                            console.log("[ZaloBridge] ⚠️ Bạn đã từ chối đăng nhập trên điện thoại.");
                            break;
                        case LoginQRCallbackEventType.GotLoginInfo:
                            console.log("[ZaloBridge] 🎉 Đăng nhập thành công! Đang lưu phiên làm việc...");
                            try {
                                fs.writeFileSync(APPSTATE_FILE, JSON.stringify(event.data, null, 2), "utf-8");
                                console.log(`[ZaloBridge] ✅ Đã lưu phiên đăng nhập thành công vào ${APPSTATE_FILE}!`);
                            } catch (err) {
                                console.warn("[ZaloBridge] Lỗi lưu appstate.json:", err.message);
                            }
                            break;
                    }
                }
            );
            console.log("-------------------------------------------------------------");
            console.log("✅ Đăng nhập Zalo thành công!");
        }

        // Tự động liên kết nhóm từ Link mời Zalo nếu có
        if (api && bridgeConfig.inviteLink && !bridgeConfig.targetGroupId) {
            try {
                console.log(`[ZaloBridge] Đang kiểm tra liên kết nhóm từ link: ${bridgeConfig.inviteLink}...`);
                const linkInfo = await api.getGroupLinkInfo({ link: bridgeConfig.inviteLink });
                if (linkInfo && linkInfo.groupId) {
                    bridgeConfig.targetGroupId = linkInfo.groupId;
                    bridgeConfig.groupName = linkInfo.name || "Nhóm Cảnh Báo";
                    saveConfig();
                    console.log(`[ZaloBridge] 🔗 Tự động liên kết thành công với nhóm: "${bridgeConfig.groupName}" (ID: ${bridgeConfig.targetGroupId})`);
                    api.sendMessage(
                        {
                            msg: `✅ ĐÃ LIÊN KẾT NHÓM THÀNH CÔNG!\nKể từ bây giờ, mọi cảnh báo đỏ từ hệ thống Camera AI DNC sẽ tự động được gửi vào nhóm "${bridgeConfig.groupName}".`
                        },
                        bridgeConfig.targetGroupId,
                        ThreadType.Group
                    ).catch(() => {});
                }
            } catch (e) {
                console.warn("[ZaloBridge] Không thể tự động phân giải group link:", e.message);
            }
        }

        // Lắng nghe tin nhắn để tự động liên kết nhóm
        if (api.listener) {
            api.listener.on("message", (msg) => {
                if (msg.type === ThreadType.Group) {
                    const text = String(msg.data?.content || "").trim();
                    const senderName = msg.data?.dName || "Người dùng";

                    // Khi ai đó gõ /setalert hoặc /start trong nhóm
                    if (text === "/setalert" || text === "/start" || text === "/link") {
                        bridgeConfig.targetGroupId = msg.threadId;
                        saveConfig();
                        console.log(`[ZaloBridge] 🔗 Đã liên kết nhóm Zalo ID: ${msg.threadId}`);

                        api.sendMessage(
                            {
                                msg: `✅ ĐÃ LIÊN KẾT NHÓM THÀNH CÔNG!\nKể từ bây giờ, mọi cảnh báo đỏ (Ẩu đả, Đột nhập, Âm thanh bất thường) từ hệ thống Camera AI DNC sẽ tự động được gửi vào nhóm này.\n(Người cấu hình: ${senderName})`
                            },
                            msg.threadId,
                            ThreadType.Group
                        ).catch(console.error);
                    }
                }
            });

            api.listener.start();
            console.log("[ZaloBridge] Bộ lắng nghe tin nhắn đã khởi động.");
            console.log(`[ZaloBridge] 👉 Hướng dẫn: Bạn hãy vào Nhóm Zalo (https://zalo.me/g/libazgippahcfbk99qkc) và gõ: /setalert để kích hoạt.`);
        }

    } catch (error) {
        console.error("❌ Lỗi khởi tạo Zalo:", error);
    }
}

// Khởi tạo Express HTTP Webhook Server
const app = express();
app.use(express.json());

// Giao diện web hiển thị mã QR để quét bằng điện thoại
app.get("/login", (req, res) => {
    res.setHeader("Content-Type", "text/html; charset=utf-8");
    res.send(`<!DOCTYPE html>
<html>
<head>
    <title>Zalo Bot Login QR - Camera DNC</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="5">
    <style>
        body { background: #111827; color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }
        .card { background: #1f2937; border-radius: 16px; padding: 28px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); border: 1px solid #374151; max-width: 420px; width: 100%; text-align: center; }
        h1 { font-size: 20px; margin-bottom: 8px; color: #60a5fa; }
        p { font-size: 14px; color: #9ca3af; margin-bottom: 20px; line-height: 1.5; }
        .qr-wrap { background: #fff; padding: 16px; border-radius: 12px; display: inline-block; box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
        img { width: 260px; height: 260px; display: block; border-radius: 4px; }
        .footer { margin-top: 18px; font-size: 13px; color: #10b981; }
        .instruction { text-align: left; background: #374151; padding: 12px 16px; border-radius: 8px; font-size: 13px; color: #d1d5db; margin-top: 20px; }
        code { background: #111827; color: #34d399; padding: 2px 6px; border-radius: 4px; font-weight: bold; }
    </style>
</head>
<body>
    <div class="card">
        <h1>📲 Đăng Nhập Bot Zalo</h1>
        <p>Mở Zalo trên điện thoại, bấm biểu tượng <b>Quét mã QR</b> để quét mã dưới đây:</p>
        <div class="qr-wrap">
            <img src="/qr?t=${Date.now()}" alt="Mã QR Zalo (Đang tạo...)">
        </div>
        <div class="instruction">
            <b>👉 Các bước thực hiện:</b>
            <ol style="margin: 8px 0 0 18px; padding: 0; line-height: 1.6;">
                <li>Dùng Zalo quét mã và chọn <b>Đăng nhập</b>.</li>
                <li>Vào nhóm Zalo gửi tin nhắn: <code>/setalert</code>.</li>
            </ol>
        </div>
        <div class="footer">⚡ Trang tự động làm mới mỗi 5 giây</div>
    </div>
</body>
</html>`);
});

// Trả về file ảnh QR png trực tiếp
app.get("/qr", (req, res) => {
    const candidates = [
        QR_FILE,
        path.resolve("./qr.png"),
        path.resolve("/app/qr.png"),
        path.resolve("/app/data/qr.png")
    ];
    for (const c of candidates) {
        if (fs.existsSync(c)) {
            res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate, private");
            res.setHeader("Content-Type", "image/png");
            return res.sendFile(c);
        }
    }
    res.status(404).send("Mã QR chưa sẵn sàng hoặc Bot đã đăng nhập thành công.");
});

// Endpoint nhận Webhook từ Camera AI
app.post("/webhook", async (req, res) => {
    const payload = req.body || {};
    const text = payload.message || payload.text || payload.content || "🚨 Cảnh báo an ninh từ Camera AI!";
    const camName = payload.camera_name || "Camera";
    const clipUrl = payload.clip_url || "";
    const eventCode = payload.event_code || "Alert";

    console.log(`[Webhook] Nhận cảnh báo: ${camName} [${eventCode}]`);

    if (!api) {
        return res.status(503).json({
            status: "error",
            message: "Bot Zalo chưa được đăng nhập (Cần quét mã QR trên server)."
        });
    }

    const groupId = bridgeConfig.targetGroupId;
    if (!groupId) {
        return res.status(400).json({
            status: "error",
            message: "Chưa xác định Nhóm Zalo đích. Hãy vào nhóm https://zalo.me/g/libazgippahcfbk99qkc và gõ /setalert để liên kết."
        });
    }

    try {
        let msgToSend = text;
        if (clipUrl && !msgToSend.includes(clipUrl)) {
            msgToSend += `\n🎬 Xem video: ${clipUrl}`;
        }

        await api.sendMessage(
            { msg: msgToSend },
            groupId,
            ThreadType.Group
        );

        console.log(`[ZaloBridge] ✅ Đã gửi cảnh báo vào nhóm Zalo (${groupId})!`);
        return res.json({
            status: "success",
            message: "Đã gửi cảnh báo đỏ vào Zalo Group thành công!",
            group_id: groupId
        });
    } catch (sendErr) {
        console.error("[ZaloBridge] ❌ Lỗi gửi tin nhắn Zalo:", sendErr);
        return res.status(500).json({
            status: "error",
            message: "Lỗi gửi tin nhắn Zalo: " + sendErr.message
        });
    }
});

// Endpoint kiểm tra trạng thái
app.get("/health", (req, res) => {
    res.json({
        status: "ok",
        zalo_connected: !!api,
        target_group_id: bridgeConfig.targetGroupId || "Chưa liên kết (Gõ /setalert trong nhóm)",
        invite_link: bridgeConfig.inviteLink
    });
});

process.on("SIGINT", () => {
    console.log("\n[ZaloBridge] Nhận tín hiệu SIGINT (Ctrl+C), đang tắt bridge...");
    process.exit(0);
});
process.on("SIGTERM", () => {
    console.log("\n[ZaloBridge] Nhận tín hiệu SIGTERM, đang tắt bridge...");
    process.exit(0);
});

app.listen(PORT, "0.0.0.0", () => {
    console.log(`[ZaloBridge] HTTP Webhook đang lắng nghe tại: http://0.0.0.0:${PORT}/webhook`);
    initZalo();
});
