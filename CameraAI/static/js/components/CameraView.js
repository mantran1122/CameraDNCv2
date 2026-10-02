/**
 * CameraView Component Module
 * 
 * Abstraction layer for displaying real-time camera streams in the VSS Blueprint layout.
 * Supports:
 * - 'mjpeg': HTTP MJPEG multipart real-time stream from /api/stream/live/{channel}
 * - 'video': HTML5 video clip loop (mp4)
 * - 'webrtc': WebRTC RTCPeerConnection stream
 * - 'rtsp-proxy': Local RTSP gateway proxy stream
 */

(function () {
    'use strict';

    const OFFICIAL_CAMERA_NAMES = {
        1: "1.T1. ĐÀO TẠO VÀ NCKH CAM1",
        2: "2.T1. ĐÀO TẠO VÀ NCKH CAM2",
        3: "3.T1. TTĐT CHUẨN ĐẦU RA CAM1",
        4: "4.T1. TTĐT CHUẨN ĐẦU RA CAM2",
        5: "5.T1. TVTS VÀ HƯỚNG NGHIỆP CAM1",
        6: "6.T1. TVTS VÀ HƯỚNG NGHIỆP CAM2",
        7: "7.T1. TÀI CHÍNH-KẾ HOẠCH CAM1",
        8: "8.T1. TÀI CHÍNH-KẾ HOẠCH CAM2",
        9: "9.T1. TỔ CHỨC - HÀNH CHÍNH CAM1",
        10: "10.T1. TỔ CHỨC - HÀNH CHÍNH CAM2",
        11: "11.T1. QUẢN LÝ HSSV",
        12: "12.T1. QTTB",
        13: "13.TH. KHOA KINH TẾ",
        14: "14.HAM. KHOA CƠ BẢN",
        15: "15.HAM. QTKQ",
        16: "16.T1. Y TẾ",
        17: "17.T1. PHÒNG HỌP",
        18: "18.T1. SẢNH CAM1",
        19: "19.T1. SẢNH CAM2",
        20: "20.T1. SẢNH CAM3",
        21: "21.T1. HÀNH LANG TCHC",
        22: "22.T1. HL ĐÀO TẠO",
        23: "23.T1. HÀNH LANG CHỦ TỊCH",
        24: "24.T1. HÀNH LANG HIỆU TRƯỞNG",
        25: "25",
        26: "26",
        27: "27",
        28: "28",
        29: "Channel29",
        30: "30",
        31: "31",
        32: "32"
    };

    function formatCameraLabel(channel, rawName) {
        const chNum = parseInt(channel, 10);
        const code = `D${String(chNum).padStart(2, '0')}`;
        const name = rawName || OFFICIAL_CAMERA_NAMES[chNum] || `Kênh ${String(chNum).padStart(2, '0')}`;
        if (name.startsWith(code)) return name;
        return `${code} - ${name}`;
    }

    class CameraView {
        constructor(container, options = {}) {
            this.container = typeof container === 'string' ? document.querySelector(container) : container;

            const defaultChannels = [3, 11, 18, 19, 20];
            const defaultSources = defaultChannels.map(ch => ({
                type: 'mjpeg',
                channel: ch,
                url: `/api/stream/live/${ch}`,
                label: formatCameraLabel(ch)
            }));

            this.availableSources = options.availableSources || defaultSources;
            this.source = options.source || this.availableSources.find(s => s.channel === 11) || this.availableSources[0];
            this.isLive = options.isLive !== false;

            this.render();
            this.loadNvrConfig();
        }

        async loadNvrConfig() {
            try {
                let cameras = [];
                // 1. Fetch user allowed cameras with explicit display names & permissions
                try {
                    const allowedResp = await fetch('/api/user/allowed-cameras');
                    if (allowedResp.ok) {
                        const allowedData = await allowedResp.json();
                        if (allowedData && Array.isArray(allowedData.cameras) && allowedData.cameras.length > 0) {
                            cameras = allowedData.cameras.map(c => ({
                                channel: c.channel,
                                name: c.name || formatCameraLabel(c.channel, c.raw_name)
                            }));
                        }
                    }
                } catch (e) {
                    console.warn('[CameraView] Could not fetch allowed cameras:', e);
                }

                // 2. If no cameras from allowed-cameras, fall back to /api/config/nvr
                if (cameras.length === 0) {
                    const resp = await fetch('/api/config/nvr');
                    if (resp.ok) {
                        const cfg = await resp.json();
                        const channels = cfg.active_channels || [3, 11, 18, 19, 20];
                        const names = cfg.camera_names || {};
                        cameras = channels.map(ch => ({
                            channel: ch,
                            name: formatCameraLabel(ch, names[String(ch)])
                        }));
                    }
                }

                if (cameras.length > 0) {
                    const liveSources = cameras.map(c => ({
                        type: 'mjpeg',
                        channel: c.channel,
                        url: `/api/stream/live/${c.channel}`,
                        label: c.name
                    }));

                    this.availableSources = [...liveSources];

                    // Keep selected source if still in available sources
                    const currentChannel = this.getCurrentChannel();
                    const matched = this.availableSources.find(s => s.channel === currentChannel || s.url === this.source.url);
                    this.source = matched || this.availableSources[0];

                    this.updatePickerOptions();
                    this.setSource(this.source);
                }
            } catch (e) {
                console.warn('[CameraView] Error loading NVR config:', e);
            }
        }

        addRecordedClips(items) {
            // Không đưa danh sách video clip sự kiện vào dropdown chọn camera
            return;
        }

        buildPickerOptionsHtml() {
            const liveSources = this.availableSources.filter(s => s.type === 'mjpeg' || (s.url && s.url.includes('/api/stream/live/')));
            return liveSources.map(s => {
                const idx = this.availableSources.indexOf(s);
                return `<option value="${idx}" ${s.url === this.source.url ? 'selected' : ''}>${this.escapeHtml(s.label || s.url)}</option>`;
            }).join('');
        }

        updatePickerOptions() {
            const picker = this.container ? this.container.querySelector('#camera-source-picker') : null;
            if (!picker) return;
            picker.innerHTML = this.buildPickerOptionsHtml();
        }

        render() {
            if (!this.container) return;

            this.container.innerHTML = `
                <div class="camera-view-card">
                    <div class="camera-view-top-bar">
                        <div class="camera-view-controls-wrap" style="width: 100%; display: flex; align-items: center; justify-content: space-between;">
                            <div style="display: flex; align-items: center; gap: 0.5rem; flex: 1; min-width: 0;">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color: var(--text-sub); flex-shrink: 0;">
                                    <path d="M23 7l-7 5 7 5V7z"></path>
                                    <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
                                </svg>
                                <select class="camera-source-select" id="camera-source-picker" style="max-width: 320px; font-weight: 600;">
                                    ${this.buildPickerOptionsHtml()}
                                </select>
                            </div>
                            <span class="camera-badge-live">
                                <span class="camera-live-dot"></span> LIVE
                            </span>
                        </div>
                    </div>

                    <div class="camera-media-frame" id="camera-media-frame">
                        ${this.buildMediaElement(this.source)}
                        <div class="camera-stream-badge-overlay" id="stream-badge-overlay">
                            ${this.source.type === 'mjpeg' ? 'LIVE RTSP' : this.source.type.toUpperCase()}
                        </div>
                        <div class="camera-status-overlay" id="camera-status-overlay" style="display: none;">
                            <div class="camera-spinner"></div>
                            <span id="camera-status-text">Connecting to stream...</span>
                        </div>
                    </div>
                </div>
            `;

            this.bindEvents();
        }

        buildMediaElement(source) {
            if (source.type === 'mjpeg' || (source.url && source.url.includes('/api/stream/live/'))) {
                return `<img id="camera-mjpeg-player" class="camera-player-element" src="${source.url}" alt="${this.escapeHtml(source.label || 'Live Camera')}" />`;
            } else {
                return `
                    <video id="camera-video-player" class="camera-player-element" autoplay muted loop playsinline>
                        <source src="${source.url}" type="video/mp4">
                    </video>
                `;
            }
        }

        getCurrentChannel() {
            if (this.source) {
                if (this.source.channel) return this.source.channel;
                const str = (this.source.url || '') + ' ' + (this.source.label || '');
                const m = str.match(/(?:live|cam|channel)[\/_ -]*0*(\d+)/i);
                if (m) return parseInt(m[1], 10);
            }
            return 11;
        }

        bindEvents() {
            const picker = this.container.querySelector('#camera-source-picker');
            if (picker) {
                picker.addEventListener('change', (e) => {
                    const selected = this.availableSources[parseInt(e.target.value, 10)];
                    if (selected) {
                        this.setSource(selected);
                        window.currentActiveChannel = this.getCurrentChannel();
                        console.log(`[CameraView] Switched to Channel ${window.currentActiveChannel}: ${selected.label}`);
                    }
                });
            }

            window.currentActiveChannel = this.getCurrentChannel();
            this.bindPlayerEvents();
        }

        bindPlayerEvents() {
            const video = this.container.querySelector('#camera-video-player');
            if (video) {
                video.addEventListener('waiting', () => this.showStatus('Buffering...'));
                video.addEventListener('playing', () => this.hideStatus());
                video.addEventListener('error', () => {
                    this.showStatus('Stream reconnecting...');
                    setTimeout(() => this.hideStatus(), 1500);
                });
            }

            const img = this.container.querySelector('#camera-mjpeg-player');
            if (img) {
                let checkLoadedInterval = setInterval(() => {
                    if (img.naturalWidth > 0) {
                        this.hideStatus();
                        clearInterval(checkLoadedInterval);
                    }
                }, 400);
                setTimeout(() => {
                    clearInterval(checkLoadedInterval);
                    this.hideStatus();
                }, 6000);

                img.onload = () => this.hideStatus();
                img.onerror = () => {
                    this.showStatus('Đang kết nối luồng NVR RTSP...');
                    setTimeout(() => {
                        if (this.source && (this.source.type === 'mjpeg' || this.source.url.includes('/api/stream/live/'))) {
                            img.src = this.source.url + (this.source.url.includes('?') ? '&' : '?') + 't=' + Date.now();
                        }
                    }, 2000);
                };
            }
        }

        setSource(newSource) {
            this.source = newSource;
            const frame = this.container.querySelector('#camera-media-frame');
            const badge = this.container.querySelector('#stream-badge-overlay');

            if (badge) {
                badge.innerText = newSource.type === 'mjpeg' ? 'LIVE RTSP' : newSource.type.toUpperCase();
            }

            if (frame) {
                const overlay = frame.querySelector('#camera-status-overlay');
                const overlayHtml = overlay ? overlay.outerHTML : '';
                const badgeHtml = badge ? badge.outerHTML : '';

                frame.innerHTML = this.buildMediaElement(newSource) + badgeHtml + overlayHtml;
                this.bindPlayerEvents();
            }
        }

        showStatus(msg) {
            const overlay = this.container.querySelector('#camera-status-overlay');
            const text = this.container.querySelector('#camera-status-text');
            if (overlay && text) {
                text.innerText = msg;
                overlay.style.display = 'flex';
            }
        }

        hideStatus() {
            const overlay = this.container.querySelector('#camera-status-overlay');
            if (overlay) {
                overlay.style.display = 'none';
            }
        }

        escapeHtml(str) {
            return (str || '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
        }
    }

    window.CameraView = CameraView;
})();
