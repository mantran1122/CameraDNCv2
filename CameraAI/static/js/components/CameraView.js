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

class CameraView {
    constructor(container, options = {}) {
        this.container = typeof container === 'string' ? document.querySelector(container) : container;
        this.source = options.source || { type: 'mjpeg', url: '/api/stream/live/11', label: 'Camera 11 - Live RTSP' };
        this.isLive = options.isLive !== false;
        this.availableSources = options.availableSources || [
            { type: 'mjpeg', url: '/api/stream/live/11', label: 'Camera 11 - Live RTSP' },
            { type: 'video', url: '/clips/cameras/cam-011/2026/09/07/evt_cam-011_20260907T092333_6.mp4', label: 'Cam 11 - Event Clip (Recorded)' }
        ];

        this.render();
        this.loadNvrConfig();
    }

    async loadNvrConfig() {
        try {
            const resp = await fetch('/api/config/nvr');
            if (!resp.ok) return;
            const cfg = await resp.json();
            const channels = cfg.active_channels || [11];
            
            const liveSources = channels.map(ch => ({
                type: 'mjpeg',
                url: `/api/stream/live/${ch}`,
                label: `Camera ${ch < 10 ? '0' + ch : ch} - Live RTSP`
            }));

            const recordedSources = [
                { type: 'video', url: '/clips/cameras/cam-011/2026/09/07/evt_cam-011_20260907T092333_6.mp4', label: 'Cam 11 - Event Clip (Recorded)' },
                { type: 'video', url: '/clips/cameras/cam-011/2026/09/07/evt_cam-011_20260907T092542_55.mp4', label: 'Cam 11 - Aisle Movement' }
            ];

            this.availableSources = [...liveSources, ...recordedSources];
            this.source = this.availableSources[0];

            this.updatePickerOptions();
            this.setSource(this.source);
        } catch (e) {
            console.warn('[CameraView] Could not load NVR config, using defaults:', e);
        }
    }

    addRecordedClips(items) {
        if (!items || !items.length) return;
        const clipSources = items.filter(it => it.video_url).slice(0, 10).map(item => ({
            type: 'video',
            url: item.video_url,
            label: `${item.title || ('Clip #' + item.event_id)} (${item.start_time || ''})`
        }));
        const existingUrls = new Set(this.availableSources.map(s => s.url));
        const newSources = clipSources.filter(s => !existingUrls.has(s.url));
        if (newSources.length > 0) {
            this.availableSources = [...this.availableSources, ...newSources];
            this.updatePickerOptions();
        }
    }

    updatePickerOptions() {
        const picker = this.container ? this.container.querySelector('#camera-source-picker') : null;
        if (!picker) return;

        picker.innerHTML = this.availableSources.map((s, idx) => `
            <option value="${idx}" ${s.url === this.source.url ? 'selected' : ''}>
                ${this.escapeHtml(s.label || s.url)} [${s.type.toUpperCase()}]
            </option>
        `).join('');
    }

    render() {
        if (!this.container) return;

        this.container.innerHTML = `
            <div class="camera-view-card">
                <div class="camera-view-top-bar">
                    <div class="camera-view-controls-wrap" style="width: 100%; display: flex; align-items: center; justify-content: space-between;">
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color: var(--text-sub);">
                                <path d="M23 7l-7 5 7 5V7z"></path>
                                <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
                            </svg>
                            <select class="camera-source-select" id="camera-source-picker">
                                ${this.availableSources.map((s, idx) => `
                                    <option value="${idx}" ${s.url === this.source.url ? 'selected' : ''}>
                                        ${this.escapeHtml(s.label || s.url)} [${s.type.toUpperCase()}]
                                    </option>
                                `).join('')}
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
                        ${this.source.type.toUpperCase()}
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
            const str = (this.source.url || '') + ' ' + (this.source.label || '');
            const m = str.match(/(?:live|cam|channel)[\/_ -]*0*(\d+)/i);
            if (m) return parseInt(m[1]);
        }
        return 11;
    }

    bindEvents() {
        const picker = this.container.querySelector('#camera-source-picker');
        if (picker) {
            picker.addEventListener('change', (e) => {
                const selected = this.availableSources[parseInt(e.target.value)];
                if (selected) {
                    this.setSource(selected);
                    window.currentActiveChannel = this.getCurrentChannel();
                    console.log(`[CameraView] Switched to Channel ${window.currentActiveChannel}`);
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
