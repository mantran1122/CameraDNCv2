import express from "express";
import fs from "node:fs";
import path from "node:path";
import { Zalo, ThreadType } from "zca-js";
import qrcode from "qrcode-terminal";

const PORT = parseInt(process.env.PORT || "5055", 10);
const DATA_DIR = process.env.DATA_DIR || "./";
if (!fs.existsSync(DATA_DIR)) {
    try { fs.mkdirSync(DATA_DIR, { recursive: true }); } catch (e) {}
}

const APPSTATE_FILE = fs.existsSync(path.resolve(DATA_DIR, "appstate.json"))
    ? path.resolve(DATA_DIR, "appstate.json")
    : (fs.existsSync(path.resolve("./appstate.json")) ? path.resolve("./appstate.json") : path.resolve(DATA_DIR, "appstate.json"));

const CONFIG_FILE = fs.existsSync(path.resolve(DATA_DIR, "zalo_config.json"))
    ? path.resolve(DATA_DIR, "zalo_config.json")
    : (fs.existsSync(path.resolve("./zalo_config.json")) ? path.resolve("./zalo_config.json") : path.resolve(DATA_DIR, "zalo_config.json"));

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
            console.log("\n📲 VUI LÒNG MỞ ỨNG DỤNG ZALO TRÊN ĐIỆN THOẠI VÀ QUÉT MÃ QR DƯỚI ĐÂY:");
            console.log("-------------------------------------------------------------");
            api = await zalo.loginQR({
                qrCallback: (qrData) => {
                    qrcode.generate(qrData, { small: true });
                }
            });
            console.log("-------------------------------------------------------------");
            console.log("✅ Đăng nhập Zalo thành công!");

            // Lưu appstate cho các lần sau
            try {
                const appstate = await api.getAppState();
                fs.writeFileSync(APPSTATE_FILE, JSON.stringify(appstate, null, 2), "utf-8");
                console.log("[ZaloBridge] Đã lưu phiên đăng nhập vào appstate.json!");
            } catch (e) {
                console.warn("[ZaloBridge] Không lưu được appstate:", e.message);
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

app.listen(PORT, "0.0.0.0", () => {
    console.log(`[ZaloBridge] HTTP Webhook đang lắng nghe tại: http://0.0.0.0:${PORT}/webhook`);
    initZalo();
});
