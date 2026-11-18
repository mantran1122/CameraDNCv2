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
let currentQrDataUri = null;
const zalo = new Zalo({ selfListen: true });

async function resolveGroupTarget() {
    if (!api) return;

    // 0. Tự động tham gia nhóm nếu có link mời
    if (bridgeConfig.inviteLink) {
        try {
            console.log(`[ZaloBridge] Đang tự động tham gia nhóm qua link: ${bridgeConfig.inviteLink}...`);
            await api.joinGroupLink(bridgeConfig.inviteLink);
            console.log(`[ZaloBridge] ✅ Đã tự động tham gia nhóm Zalo thành công!`);
        } catch (joinErr) {
            // Code 178: Đã là thành viên; Code 240: Chờ duyệt thành viên
            console.log(`[ZaloBridge] Trạng thái tham gia nhóm: ${joinErr.message}`);
        }
    }

    // 1. Nếu có link mời, lấy thông tin nhóm
    if (bridgeConfig.inviteLink) {
        try {
            console.log(`[ZaloBridge] Đang kiểm tra liên kết nhóm từ link: ${bridgeConfig.inviteLink}...`);
            const linkInfo = await api.getGroupLinkInfo({ link: bridgeConfig.inviteLink });
            if (linkInfo && linkInfo.groupId) {
                bridgeConfig.targetGroupId = String(linkInfo.groupId);
                bridgeConfig.groupName = linkInfo.name || "Nhóm Cảnh Báo Camera DNC";
                saveConfig();
                console.log(`[ZaloBridge] 🔗 Tự động liên kết thành công với nhóm: "${bridgeConfig.groupName}" (ID: ${bridgeConfig.targetGroupId})`);
            }
        } catch (e) {
            console.warn("[ZaloBridge] Không thể tự động phân giải group link:", e.message);
        }
    }

    // 2. Quét danh sách các nhóm mà Bot đã tham gia thực tế
    try {
        const allGroups = await api.getAllGroups();
        const groupIds = Object.keys(allGroups?.gridVerMap || {});
        console.log(`[ZaloBridge] Bot hiện đang có mặt trong ${groupIds.length} nhóm Zalo.`);
        if (groupIds.length === 1 && !bridgeConfig.targetGroupId) {
            bridgeConfig.targetGroupId = groupIds[0];
            try {
                const gInfo = await api.getGroupInfo(groupIds[0]);
                bridgeConfig.groupName = gInfo?.gridInfoMap?.[groupIds[0]]?.name || "Nhóm Cảnh Báo DNC";
            } catch (e) {}
            saveConfig();
            console.log(`[ZaloBridge] 🔗 Tự động liên kết nhóm duy nhất của Bot: "${bridgeConfig.groupName}" (ID: ${bridgeConfig.targetGroupId})`);
        }
    } catch (e) {
        console.warn("[ZaloBridge] Không thể quét danh sách nhóm của bot:", e.message);
    }
}

async function initZalo() {
    try {
        if (fs.existsSync(APPSTATE_FILE)) {
            console.log("[ZaloBridge] Đang khôi phục phiên đăng nhập từ appstate.json...");
            try {
                const appstate = JSON.parse(fs.readFileSync(APPSTATE_FILE, "utf-8"));
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
                            if (event.data?.image) {
                                currentQrDataUri = event.data.image;
                            }
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

        // Tự động giải quyết nhóm mục tiêu
        await resolveGroupTarget();

        // Lắng nghe tin nhắn để tự động liên kết nhóm (hỗ trợ cả tài khoản bot tự gõ /setalert nhờ selfListen: true)
        if (api && api.listener) {
            api.listener.on("message", async (msg) => {
                try {
                    let text = "";
                    if (typeof msg.data?.content === "string") {
                        text = msg.data.content.trim();
                    } else if (msg.data?.content && typeof msg.data.content === "object") {
                        text = String(msg.data.content.title || msg.data.content.description || "").trim();
                    }
                    const lower = text.toLowerCase();
                    const senderName = msg.data?.dName || "Người dùng";

                    // Khi người dùng (hoặc chính bot) gõ /setalert, /start, /link
                    if (lower.startsWith("/setalert") || lower.startsWith("/start") || lower.startsWith("/link") || lower === "setalert") {
                        if (msg.type === ThreadType.Group) {
                            bridgeConfig.targetGroupId = String(msg.threadId);
                            try {
                                const groupInfo = await api.getGroupInfo(msg.threadId);
                                const info = groupInfo?.gridInfoMap?.[msg.threadId];
                                if (info?.name) bridgeConfig.groupName = info.name;
                            } catch (e) {}
                            saveConfig();
                            console.log(`[ZaloBridge] 🔗 Đã liên kết nhóm Zalo ID: ${msg.threadId} ("${bridgeConfig.groupName}") từ tin nhắn của ${senderName}`);

                            await api.sendMessage(
                                {
                                    msg: `✅ ĐÃ LIÊN KẾT NHÓM CẢNH BÁO CAMERA DNC THÀNH CÔNG!\n` +
                                         `📌 Nhóm: ${bridgeConfig.groupName || msg.threadId}\n` +
                                         `👤 Người kích hoạt: ${senderName}\n\n` +
                                         `Kể từ bây giờ, mọi sự kiện báo động đỏ (Ẩu đả, Đột nhập, Âm thanh bất thường...) cấu hình trên Admin sẽ tự động gửi video và thông tin vào nhóm này.`
                                },
                                msg.threadId,
                                ThreadType.Group
                            ).catch(console.error);
                        } else {
                            await api.sendMessage(
                                {
                                    msg: `⚠️ Lệnh này cần được gửi trong NHÓM Zalo bạn muốn nhận cảnh báo (không phải tin nhắn riêng). Hãy vào nhóm và gõ: /setalert`
                                },
                                msg.threadId,
                                ThreadType.User
                            ).catch(console.error);
                        }
                    }
                } catch (msgErr) {
                    console.error("[ZaloBridge] Lỗi xử lý tin nhắn lắng nghe:", msgErr);
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

// Giao diện web hiển thị mã QR để quét bằng điện thoại (Tự động cập nhật trạng thái)
app.get("/login", (req, res) => {
    res.setHeader("Content-Type", "text/html; charset=utf-8");
    res.send(`<!DOCTYPE html>
<html>
<head>
    <title>Zalo Bot Login - Camera DNC</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background: #0f172a; color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }
        .card { background: #1e293b; border-radius: 16px; padding: 28px; box-shadow: 0 10px 25px rgba(0,0,0,0.6); border: 1px solid #334155; max-width: 440px; width: 100%; text-align: center; }
        h1 { font-size: 20px; margin-bottom: 8px; color: #38bdf8; display: flex; align-items: center; justify-content: center; gap: 8px; }
        p { font-size: 14px; color: #94a3b8; margin-bottom: 20px; line-height: 1.5; }
        .qr-wrap { background: #fff; padding: 16px; border-radius: 12px; display: inline-block; box-shadow: 0 4px 12px rgba(0,0,0,0.3); min-height: 260px; min-width: 260px; }
        img { width: 260px; height: 260px; display: block; border-radius: 4px; }
        .success-box { background: #064e3b; border: 1px solid #059669; color: #a7f3d0; padding: 20px; border-radius: 12px; margin-bottom: 16px; }
        .instruction { text-align: left; background: #334155; padding: 14px 16px; border-radius: 10px; font-size: 13px; color: #cbd5e1; margin-top: 20px; }
        code { background: #0f172a; color: #34d399; padding: 2px 6px; border-radius: 4px; font-weight: bold; }
        .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #ef4444; margin-right: 6px; }
        .status-dot.active { background: #10b981; }
    </style>
</head>
<body>
    <div class="card">
        <h1>📲 Zalo Bot Alert Bridge</h1>
        <div id="content">
            <p>Đang kiểm tra kết nối tới Bot Zalo...</p>
        </div>
        <div class="instruction">
            <b>👉 Các bước kích hoạt:</b>
            <ol style="margin: 8px 0 0 18px; padding: 0; line-height: 1.6;">
                <li>Dùng Zalo trên điện thoại quét mã QR và chọn <b>Đăng nhập</b>.</li>
                <li>Vào nhóm Zalo nhận cảnh báo và gửi: <code>/setalert</code>.</li>
            </ol>
        </div>
    </div>

    <script>
        async function updateStatus() {
            try {
                const res = await fetch('/health?t=' + Date.now());
                const data = await res.json();
                const container = document.getElementById('content');
                if (data.zalo_connected) {
                    let groupInfo = data.target_group_id ?
                        '<p style="color:#34d399;font-weight:bold;">Đã liên kết nhóm: ' + (data.group_name || data.target_group_id) + '</p>' :
                        '<p style="color:#fbbf24;">Bot đã đăng nhập! Vui lòng vào nhóm Zalo gửi <code>/setalert</code> để liên kết.</p>';
                    container.innerHTML = \`
                        <div class="success-box">
                            <h2 style="margin:0 0 8px 0;font-size:18px;color:#34d399;">✅ Đã Đăng Nhập Zalo Thành Công!</h2>
                            \${groupInfo}
                        </div>
                    \`;
                } else {
                    container.innerHTML = \`
                        <p>Mở Zalo trên điện thoại, bấm biểu tượng <b>Quét mã QR</b> để đăng nhập:</p>
                        <div class="qr-wrap">
                            <img src="/qr?t=\${Date.now()}" alt="Mã QR Zalo (Đang tạo...)">
                        </div>
                        <p style="margin-top:12px;font-size:12px;color:#64748b;">Mã QR tự động làm mới nếu hết hạn.</p>
                    \`;
                }
            } catch (e) {
                console.error(e);
            }
        }
        updateStatus();
        setInterval(updateStatus, 3000);
    </script>
</body>
</html>`);
});

// Trả về file ảnh QR png trực tiếp hoặc dữ liệu base64
app.get("/qr", (req, res) => {
    if (currentQrDataUri && currentQrDataUri.startsWith("data:image/png;base64,")) {
        const base64Data = currentQrDataUri.replace(/^data:image\/png;base64,/, "");
        const imgBuffer = Buffer.from(base64Data, "base64");
        res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate, private");
        res.setHeader("Content-Type", "image/png");
        return res.send(imgBuffer);
    }
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

// Endpoint cấu hình thủ công Group ID
app.post("/set-group", (req, res) => {
    const { groupId, groupName } = req.body || {};
    if (!groupId) {
        return res.status(400).json({ error: "groupId is required" });
    }
    bridgeConfig.targetGroupId = String(groupId).trim();
    if (groupName) bridgeConfig.groupName = String(groupName).trim();
    saveConfig();
    return res.json({
        success: true,
        target_group_id: bridgeConfig.targetGroupId,
        group_name: bridgeConfig.groupName
    });
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

        const targetId = String(groupId).trim();
        try {
            await api.sendMessage(
                msgToSend,
                targetId,
                ThreadType.Group
            );
        } catch (groupSendErr) {
            // Nếu lỗi Tham số không hợp lệ, thử gọi joinGroupLink rồi gửi lại
            if (String(groupSendErr.message).includes("Tham số không hợp lệ") && bridgeConfig.inviteLink) {
                console.log(`[ZaloBridge] Gửi tin thất bại do chưa vào nhóm, đang thử tự động tham gia nhóm: ${bridgeConfig.inviteLink}...`);
                try {
                    await api.joinGroupLink(bridgeConfig.inviteLink);
                    await new Promise(r => setTimeout(r, 1000));
                } catch (jErr) {}
                // Thử gửi lại lần 2
                await api.sendMessage(
                    msgToSend,
                    targetId,
                    ThreadType.Group
                );
            } else {
                throw groupSendErr;
            }
        }

        console.log(`[ZaloBridge] ✅ Đã gửi cảnh báo vào nhóm Zalo (${targetId})!`);
        return res.json({
            status: "success",
            message: "Đã gửi cảnh báo đỏ vào Zalo Group thành công!",
            group_id: targetId
        });
    } catch (sendErr) {
        console.error("[ZaloBridge] ❌ Lỗi gửi tin nhắn Zalo:", sendErr);
        const errMsg = String(sendErr.message || sendErr);
        if (errMsg.includes("zpw_sek") || errMsg.includes("1105") || errMsg.includes("không đúng")) {
            console.warn("[ZaloBridge] ⚠️ Phiên Zalo (zpw_sek) đã hết hạn/bị đá do đăng nhập Web ở nơi khác. Đang tự động dọn dẹp để tạo mã QR mới...");
            api = null;
            try {
                if (fs.existsSync(APPSTATE_FILE)) fs.unlinkSync(APPSTATE_FILE);
            } catch (err) {}
            setTimeout(() => { initZalo(); }, 1000);
            return res.status(401).json({
                status: "error",
                message: "Phiên Zalo bị đá do tài khoản vừa đăng nhập Web ở nơi khác (zpw_sek bị thu hồi). Hãy mở http://192.168.100.40.nip.io:5055/login để quét mã QR lại. (Khuyên dùng SIM phụ làm Bot để không bao giờ bị đá)."
            });
        }
        if (errMsg.includes("Tham số không hợp lệ") || errMsg.includes("Invalid parameter")) {
            return res.status(400).json({
                status: "error",
                message: "Tài khoản Bot chưa có trong nhóm hoặc đang chờ duyệt. Bạn chỉ cần vào Zalo lấy nick chính bấm [Thêm Thành Viên] rồi add nick Bot này vào nhóm là xong ngay!"
            });
        }
        return res.status(500).json({
            status: "error",
            message: "Lỗi gửi tin nhắn Zalo: " + errMsg
        });
    }
});

// Endpoint kiểm tra trạng thái
app.get("/health", async (req, res) => {
    let connected = !!api;
    if (api) {
        try {
            await api.fetchAccountInfo();
        } catch (checkErr) {
            const checkMsg = String(checkErr.message || checkErr);
            if (checkMsg.includes("zpw_sek") || checkMsg.includes("1105")) {
                console.warn("[ZaloBridge] ⚠️ /health phát hiện zpw_sek đã hết hạn. Đang reset phiên...");
                api = null;
                connected = false;
                try {
                    if (fs.existsSync(APPSTATE_FILE)) fs.unlinkSync(APPSTATE_FILE);
                } catch (err) {}
                setTimeout(() => { initZalo(); }, 1000);
            }
        }
    }
    res.json({
        status: "ok",
        zalo_connected: connected,
        target_group_id: bridgeConfig.targetGroupId || "",
        group_name: bridgeConfig.groupName || "",
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
