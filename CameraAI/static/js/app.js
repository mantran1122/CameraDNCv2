let activityChart = null;
let audioAnalysisPollTimer = null;
let videoAnalysisPollTimer = null;

document.addEventListener('DOMContentLoaded', () => {
    fetchDailySummary();
    fetchEvents();
    loadNVRConfigUI();
    renderChannelGrid();
    initWebSocket();
    const videoModal = document.getElementById('videoModal');
    videoModal?.addEventListener('click', (event) => {
        if (event.target === videoModal) closeClipModal();
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && videoModal?.classList.contains('active')) closeClipModal();
    });
});

// Populate 32 Channel Checkboxes Grid
function renderChannelGrid() {
    const grid = document.getElementById('channel-grid');
    if (!grid) return;
    grid.innerHTML = '';

    for (let i = 1; i <= 32; i++) {
        const item = document.createElement('label');
        item.style.display = 'flex';
        item.style.alignItems = 'center';
        item.style.gap = '0.3rem';
        item.style.fontSize = '0.75rem';
        item.style.cursor = 'pointer';

        item.innerHTML = `
            <input type="checkbox" class="ch-checkbox" value="${i}" checked style="cursor:pointer;">
            <span>Ch ${String(i).padStart(2, '0')}</span>
        `;
        grid.appendChild(item);
    }
}

function toggleSelectAllChannels() {
    const boxes = document.querySelectorAll('.ch-checkbox');
    const allChecked = Array.from(boxes).every(b => b.checked);
    boxes.forEach(b => b.checked = !allChecked);
}

function togglePasswordVisibility() {
    const input = document.getElementById('cfg-pass');
    if (input.type === 'password') {
        input.type = 'text';
    } else {
        input.type = 'password';
    }
}

// Load current NVR Config into UI
async function loadNVRConfigUI() {
    try {
        const res = await fetch('/api/config/nvr');
        const data = await res.json();

        document.getElementById('cfg-host').value = data.nvr_host || '192.168.1.108';
        document.getElementById('cfg-https').value = data.use_https ? 'true' : 'false';
        document.getElementById('cfg-port').value = data.nvr_port || 80;
        document.getElementById('cfg-rtsp').value = data.rtsp_port || 554;
        document.getElementById('cfg-user').value = data.nvr_user || 'admin';
        document.getElementById('cfg-demo').checked = Boolean(data.demo_mode);
        renderAbnormalBehaviorOptions(data.abnormal_behavior_options || [], data.abnormal_event_codes || []);

        // Update Header Bar
        document.getElementById('bar-nvr-host').innerText = data.nvr_host || '192.168.1.108';
        document.getElementById('bar-nvr-ports').innerText = `(HTTP: ${data.nvr_port} | RTSP: ${data.rtsp_port})`;
        
        const activeCh = data.active_channels || [];
        document.getElementById('bar-nvr-channels').innerText = `Giám sát: ${activeCh.length} / 32 Kênh Camera`;

        const badge = document.getElementById('status-badge');
        const badgeText = document.getElementById('status-text');
        if (data.demo_mode) {
            badge.className = 'status-badge demo';
            badgeText.innerText = 'CHẾ ĐỘ GIẢ LẬP (DEMO)';
        } else {
            badge.className = 'status-badge';
            badgeText.innerText = 'ĐÃ KẾT NỐI INTERNET NVR ONLINE';
        }

        // Set channel checkboxes
        if (activeCh.length > 0) {
            const boxes = document.querySelectorAll('.ch-checkbox');
            boxes.forEach(b => {
                b.checked = activeCh.includes(parseInt(b.value));
            });
        }
    } catch(err) {
        console.error('Error loading config:', err);
    }
}

// Fetch Daily Summary Metrics & AI Text
async function fetchDailySummary() {
    try {
        const res = await fetch('/api/summary/daily');
        const data = await res.json();

        document.getElementById('val-total-events').innerText = data.total_events || 0;
        document.getElementById('val-audio-anomalies').innerText = data.anomaly_audio_count || 0;
        document.getElementById('val-video-anomalies').innerText = data.anomaly_video_count || 0;
        document.getElementById('val-human-count').innerText = data.human_count || 0;

        document.getElementById('summary-text-box').innerText = data.summary_text || 'Đang tải dữ liệu báo cáo...';

        renderActivityChart(data.hourly_distribution, data.hourly_anomalies);
    } catch (err) {
        console.error('Error fetching summary:', err);
    }
}

// Fetch Anomaly & Metadata Events Feed
async function fetchEvents(onlyAnomalies = false) {
    try {
        const url = onlyAnomalies ? '/api/events?only_anomalies=true&limit=50' : '/api/events?limit=50';
        const res = await fetch(url);
        const data = await res.json();

        const container = document.getElementById('events-container');
        container.innerHTML = '';

        if (!data.events || data.events.length === 0) {
            container.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 2rem;">Chưa có sự kiện ghi nhận.</div>';
            return;
        }

        data.events.forEach(ev => {
            container.appendChild(createEventCard(ev));
        });
    } catch (err) {
        console.error('Error fetching events:', err);
    }
}

// Create DOM Card for Event Item
function createEventCard(ev) {
    const card = document.createElement('div');
    card.className = `event-item ${ev.event_type}`;
    card.dataset.eventId = ev.id;

    let badgeClass = 'badge-info';
    let badgeLabel = ev.event_code;
    if (ev.event_type === 'audio_anomaly') {
        badgeClass = 'badge-audio';
        badgeLabel = `ÂM THANH: ${ev.event_code}`;
    } else if (ev.event_type === 'video_anomaly') {
        badgeClass = 'badge-video';
        badgeLabel = `VIDEO: ${ev.event_code}`;
    }

    const hasClip = Boolean(ev.clip_filename);
    const audioStatus = formatAudioStatus(ev.audio_analysis);

    card.innerHTML = `
        <div class="event-top">
            <span class="event-badge ${badgeClass}">${badgeLabel}</span>
            <span class="event-time">${ev.timestamp}</span>
        </div>
        <div class="event-desc">${ev.description}</div>
        <div class="event-bottom">
            <span>Camera Ch ${String(ev.channel).padStart(2, '0')} ${ev.audio_level_db ? `| 🔊 ${ev.audio_level_db} dB` : ''}</span>
            ${audioStatus ? `<span class="audio-status">${audioStatus}</span>` : ''}
            ${hasClip ? `<button class="btn-clip-play" onclick="openClipModal(${ev.id}, '${ev.clip_filename}', '${ev.description}')">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg> Xem 10s Clip
            </button>` : ''}
        </div>
    `;
    return card;
}

function renderAbnormalBehaviorOptions(options, selectedCodes) {
    const grid = document.getElementById('abnormal-behavior-grid');
    if (!grid) return;
    const selected = new Set(selectedCodes);
    grid.replaceChildren();
    options.forEach(({code, label}) => {
        const option = document.createElement('label');
        option.className = 'abnormal-behavior-option';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'abnormal-behavior-checkbox';
        checkbox.value = code;
        checkbox.checked = selected.has(code);
        option.append(checkbox, document.createTextNode(` ${label}`));
        grid.appendChild(option);
    });
}

function formatAudioStatus(analysis) {
    if (!analysis) return '';
    const labels = {
        not_analyzed: 'Chưa phân tích',
        processing: 'Đang kiểm tra video',
        video_missing: 'Không tìm thấy video evidence',
        extracting_audio: 'Đang tách âm thanh',
        transcribing: 'Đang phân tích âm thanh',
        analyzing: 'Đang tạo gợi ý AI',
        no_audio_track: 'Video không có kênh âm thanh',
        audio_too_quiet: 'Âm thanh quá nhỏ',
        no_speech_detected: 'Không phát hiện giọng nói',
        stt_failed: 'STT không thể hoàn tất',
        transcribed: 'Đã có transcript, chưa có gợi ý AI',
        completed: 'Đã phân tích',
    };
    return labels[analysis.status] || analysis.status;
}

function setText(id, value, fallback = '-') {
    const element = document.getElementById(id);
    if (element) element.textContent = value || fallback;
}

function renderAudioAnalysis(analysis) {
    const status = formatAudioStatus(analysis);
    setText('clip-audio-status', status, 'Chưa có dữ liệu');
    const transcriptFallbacks = {
        not_analyzed: 'Chưa chạy phân tích. Bấm nút để bắt đầu.',
        video_missing: 'Không tìm thấy video evidence của cảnh báo.',
        no_audio_track: 'Video không chứa kênh âm thanh nên không thể tạo transcript.',
        audio_too_quiet: 'Có kênh âm thanh nhưng âm lượng quá nhỏ hoặc gần như im lặng.',
        no_speech_detected: 'Có âm thanh nhưng không phát hiện lời nói có thể nhận dạng.',
        stt_failed: 'Speech-to-text không thể hoàn tất. Xem lỗi bên dưới.',
    };
    const transcriptFallback = transcriptFallbacks[analysis?.status] || 'Chưa có transcript.';
    setText('clip-audio-transcript', analysis?.transcript, transcriptFallback);
    const suggestion = analysis?.suggestion;
    setText('clip-audio-summary', suggestion?.summary, 'Chưa có gợi ý.');
    setText('clip-audio-risk', suggestion?.risk_level, '-');
    setText('clip-audio-action', suggestion?.recommended_action, 'Chưa có hành động đề xuất.');
    setText('clip-audio-error', analysis?.error_message, '');

    const list = document.getElementById('clip-audio-evidence');
    if (!list) return;
    list.replaceChildren();
    (suggestion?.evidence || []).forEach(item => {
        const row = document.createElement('li');
        row.textContent = `${item.source}: ${item.detail}`;
        list.appendChild(row);
    });
    if (!list.children.length) {
        const row = document.createElement('li');
        row.textContent = analysis?.status === 'completed' ? 'Không có evidence.' : 'Chưa có evidence vì phân tích chưa hoàn tất.';
        list.appendChild(row);
    }
}

function renderAudioAnalysisAction(ev) {
    const button = document.getElementById('analyze-audio-btn');
    if (!button) return;
    const isAnomaly = ev && ['audio_anomaly', 'video_anomaly'].includes(ev.event_type);
    const canAnalyse = isAnomaly && Boolean(ev?.clip_filename);
    const status = ev?.audio_analysis?.status;
    button.dataset.eventId = ev?.id || '';
    button.hidden = !isAnomaly;
    button.disabled = !canAnalyse || ['processing', 'extracting_audio', 'transcribing', 'analyzing', 'completed', 'no_audio_track', 'audio_too_quiet', 'no_speech_detected'].includes(status);
    button.textContent = ['video_missing', 'stt_failed', 'transcribed'].includes(status) ? '↻ Phân tích lại âm thanh' : '🎙 Phân tích âm thanh';
}

function formatVideoAnalysisStatus(analysis) {
    if (!analysis) return '';
    const labels = {
        not_analyzed: 'Chưa phân tích',
        processing: 'Đang xếp hàng',
        extracting_frames: 'Đang lấy frame đại diện',
        analyzing_frames: 'Cosmos đang phân tích video',
        video_missing: 'Không tìm thấy video evidence',
        failed: 'Phân tích video thất bại',
        completed: 'Đã phân tích video',
    };
    return labels[analysis.status] || analysis.status;
}

function renderVideoAnalysis(analysis) {
    setText('clip-video-analysis-status', formatVideoAnalysisStatus(analysis), 'Chưa có dữ liệu');
    setText('clip-video-analysis-summary', analysis?.summary, analysis?.status === 'not_analyzed' ? 'Bấm nút để bắt đầu.' : 'Chưa có kết quả.');
    setText('clip-video-analysis-risk', analysis?.risk_level, '-');
    const events = (analysis?.events || []).map(item => `${item.label}: ${item.count}`).join(', ');
    setText('clip-video-analysis-events', events, 'Không ghi nhận đối tượng.');
    setText('clip-video-analysis-frames', analysis?.frames?.length ? String(analysis.frames.length) : '', '-');
    setText('clip-video-analysis-error', analysis?.error_message, '');
}

function renderVideoAnalysisAction(ev) {
    const button = document.getElementById('analyze-video-btn');
    if (!button) return;
    const isAnomaly = ev && ['audio_anomaly', 'video_anomaly'].includes(ev.event_type);
    const status = ev?.video_analysis?.status;
    button.dataset.eventId = ev?.id || '';
    button.hidden = !isAnomaly;
    button.disabled = !ev?.clip_filename || ['processing', 'extracting_frames', 'analyzing_frames', 'completed'].includes(status);
    button.textContent = ['video_missing', 'failed'].includes(status) ? '↻ Thử lại video' : '🎬 Phân tích video';
}

async function requestVideoAnalysis() {
    const button = document.getElementById('analyze-video-btn');
    const eventId = button?.dataset.eventId;
    if (!eventId || button.disabled) return;
    button.disabled = true;
    button.textContent = '⏳ Đang xếp hàng...';
    try {
        const response = await fetch(`/api/events/${encodeURIComponent(eventId)}/video-analysis`, {method: 'POST'});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Không thể tạo job phân tích video.');
        renderVideoAnalysis(data.video_analysis);
        startVideoAnalysisPolling(eventId);
    } catch (error) {
        button.disabled = false;
        button.textContent = '🎬 Phân tích video';
        setText('clip-video-analysis-error', error.message);
    }
}

function startVideoAnalysisPolling(eventId) {
    if (videoAnalysisPollTimer) clearInterval(videoAnalysisPollTimer);
    const terminalStatuses = new Set(['not_analyzed', 'video_missing', 'failed', 'completed']);
    let attempts = 0;
    const refresh = async () => {
        attempts += 1;
        try {
            const response = await fetch(`/api/events/${encodeURIComponent(eventId)}`);
            if (!response.ok) throw new Error('Không thể cập nhật trạng thái phân tích video.');
            const event = await response.json();
            renderVideoAnalysis(event.video_analysis);
            renderVideoAnalysisAction(event);
            if (terminalStatuses.has(event.video_analysis?.status) || attempts >= 300) {
                clearInterval(videoAnalysisPollTimer);
                videoAnalysisPollTimer = null;
            }
        } catch (error) {
            if (attempts >= 300) {
                clearInterval(videoAnalysisPollTimer);
                videoAnalysisPollTimer = null;
                setText('clip-video-analysis-error', error.message);
            }
        }
    };
    refresh();
    videoAnalysisPollTimer = setInterval(refresh, 1000);
}

async function requestAudioAnalysis() {
    const button = document.getElementById('analyze-audio-btn');
    const eventId = button?.dataset.eventId;
    if (!eventId || button.disabled) return;
    button.disabled = true;
    button.textContent = '⏳ Đang xếp hàng...';
    try {
        const response = await fetch(`/api/events/${encodeURIComponent(eventId)}/audio-analysis`, {method: 'POST'});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Không thể tạo job phân tích.');
        renderAudioAnalysis(data.audio_analysis);
        renderAudioAnalysisAction({...data, id: Number(eventId), event_type: 'audio_anomaly', clip_filename: true});
        startAudioAnalysisPolling(eventId);
    } catch (error) {
        button.disabled = false;
        button.textContent = '🎙 Phân tích âm thanh';
        setText('clip-audio-error', error.message);
    }
}

function startAudioAnalysisPolling(eventId) {
    if (audioAnalysisPollTimer) clearInterval(audioAnalysisPollTimer);
    const terminalStatuses = new Set([
        'not_analyzed', 'video_missing', 'no_audio_track', 'audio_too_quiet',
        'no_speech_detected', 'stt_failed', 'transcribed', 'completed',
    ]);
    let attempts = 0;
    const refresh = async () => {
        attempts += 1;
        try {
            const response = await fetch(`/api/events/${encodeURIComponent(eventId)}`);
            if (!response.ok) throw new Error('Không thể cập nhật trạng thái phân tích.');
            const event = await response.json();
            renderAudioAnalysis(event.audio_analysis);
            renderAudioAnalysisAction(event);
            if (terminalStatuses.has(event.audio_analysis?.status) || attempts >= 150) {
                clearInterval(audioAnalysisPollTimer);
                audioAnalysisPollTimer = null;
            }
        } catch (error) {
            if (attempts >= 150) {
                clearInterval(audioAnalysisPollTimer);
                audioAnalysisPollTimer = null;
                setText('clip-audio-error', error.message);
            }
        }
    };
    refresh();
    audioAnalysisPollTimer = setInterval(refresh, 1000);
}

// Render Chart.js Timeline
function renderActivityChart(hourlyAll, hourlyAnomalies) {
    const ctx = document.getElementById('activityChart').getContext('2d');
    const labels = Array.from({length: 24}, (_, i) => `${String(i).padStart(2, '0')}:00`);

    if (activityChart) {
        activityChart.destroy();
    }

    activityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Sự kiện Bất thường (Audio/Video)',
                    data: hourlyAnomalies || Array(24).fill(0),
                    borderColor: '#ef4444',
                    backgroundColor: 'rgba(239, 68, 68, 0.25)',
                    fill: true,
                    tension: 0.3,
                    borderWidth: 2
                },
                {
                    label: 'Tổng Metadata Hoạt động',
                    data: hourlyAll || Array(24).fill(0),
                    borderColor: '#6366f1',
                    backgroundColor: 'rgba(99, 102, 241, 0.1)',
                    fill: true,
                    tension: 0.3,
                    borderWidth: 2
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: '#9ca3af', font: { family: 'Inter' } } }
            },
            scales: {
                x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#9ca3af' } },
                y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#9ca3af', beginAtZero: true } }
            }
        }
    });
}

// Test NVR Connection UI
async function testNVRConnectionUI() {
    const banner = document.getElementById('test-result-banner');
    banner.style.display = 'block';
    banner.style.background = 'rgba(99, 102, 241, 0.2)';
    banner.style.color = '#a5b4fc';
    banner.style.border = '1px solid rgba(99, 102, 241, 0.4)';
    banner.innerText = '⏳ Đang thử kết nối tới đầu ghi Dahua qua Internet... Vui lòng chờ vài giây.';

    const payload = getFormPayload();

    try {
        const res = await fetch('/api/config/nvr/test', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        const data = await res.json();

        if (data.success) {
            banner.style.background = 'rgba(16, 185, 129, 0.2)';
            banner.style.color = '#6ee7b7';
            banner.style.border = '1px solid rgba(16, 185, 129, 0.4)';
            banner.innerHTML = `<strong>${data.message}</strong><br>Thiết bị: ${data.device_model || 'DHI-NVR5832-EI2'} | S/N: ${data.serial_number || 'N/A'}`;
        } else {
            banner.style.background = 'rgba(239, 68, 68, 0.2)';
            banner.style.color = '#fca5a5';
            banner.style.border = '1px solid rgba(239, 68, 68, 0.4)';
            banner.innerHTML = `<strong>${data.message}</strong>`;
        }
    } catch(err) {
        banner.style.background = 'rgba(239, 68, 68, 0.2)';
        banner.style.color = '#fca5a5';
        banner.innerText = '❌ Lỗi kết nối tới Web Server!';
    }
}

function testActiveConnection() {
    openConfigModal();
    testNVRConnectionUI();
}

function getFormPayload() {
    const activeCh = Array.from(document.querySelectorAll('.ch-checkbox:checked')).map(b => parseInt(b.value));
    const abnormalEventCodes = Array.from(document.querySelectorAll('.abnormal-behavior-checkbox:checked')).map(b => b.value);
    return {
        nvr_host: document.getElementById('cfg-host').value.trim(),
        use_https: document.getElementById('cfg-https').value === 'true',
        nvr_port: parseInt(document.getElementById('cfg-port').value),
        rtsp_port: parseInt(document.getElementById('cfg-rtsp').value),
        nvr_user: document.getElementById('cfg-user').value.trim(),
        nvr_password: document.getElementById('cfg-pass').value,
        active_channels: activeCh,
        demo_mode: document.getElementById('cfg-demo').checked,
        abnormal_event_codes: abnormalEventCodes
    };
}

// Save Configuration Form
async function saveNVRConfig(e) {
    e.preventDefault();
    const payload = getFormPayload();

    try {
        const res = await fetch('/api/config/nvr', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        alert(data.message);
        loadNVRConfigUI();
        closeConfigModal();
    } catch(err) {
        alert('Lỗi lưu cấu hình!');
    }
}

// Modal Clip Player
async function openClipModal(eventId, clipFilename, description) {
    document.getElementById('modal-event-title').innerText = description || 'Trình phát Video 10s Bất thường';
    
    const videoElem = document.getElementById('modal-video-player');
    const sourceElem = document.getElementById('modal-video-source');
    
    const clipUrl = `/clips/${clipFilename.split('/').map(encodeURIComponent).join('/')}`;
    if (sourceElem) {
        sourceElem.src = clipUrl;
    }
    videoElem.src = clipUrl;
    videoElem.load();
    videoElem.play().catch(e => console.log('Autoplay prevented:', e));

    try {
        const res = await fetch(`/api/events/${eventId}`);
        const ev = await res.json();
        
        document.getElementById('clip-detail-ch').innerText = `Ch ${String(ev.channel).padStart(2, '0')}`;
        document.getElementById('clip-detail-time').innerText = ev.timestamp;
        document.getElementById('clip-detail-type').innerText = `${ev.event_code} (${ev.event_type})`;
        document.getElementById('clip-detail-audio').innerText = ev.audio_level_db ? `${ev.audio_level_db} dB` : 'N/A';
        renderAudioAnalysis(ev.audio_analysis);
        renderAudioAnalysisAction(ev);
        renderVideoAnalysis(ev.video_analysis);
        renderVideoAnalysisAction(ev);
    } catch(e) {}

    document.getElementById('videoModal').classList.add('active');
}

function closeClipModal() {
    if (audioAnalysisPollTimer) {
        clearInterval(audioAnalysisPollTimer);
        audioAnalysisPollTimer = null;
    }
    if (videoAnalysisPollTimer) {
        clearInterval(videoAnalysisPollTimer);
        videoAnalysisPollTimer = null;
    }
    const videoElem = document.getElementById('modal-video-player');
    if (videoElem) {
        videoElem.pause();
        videoElem.src = '';
    }
    document.getElementById('videoModal').classList.remove('active');
}

function openConfigModal() {
    document.getElementById('configModal').classList.add('active');
}

function closeConfigModal() {
    document.getElementById('configModal').classList.remove('active');
}

// WebSocket Setup
function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onmessage = (event) => {
        const ev = JSON.parse(event.data);
        console.log('Realtime event received:', ev);

        const container = document.getElementById('events-container');
        const previous = container.querySelector(`[data-event-id="${ev.id}"]`);
        if (previous) previous.remove();
        container.insertBefore(createEventCard(ev), container.firstChild);

        fetchDailySummary();
    };

    ws.onclose = () => {
        setTimeout(initWebSocket, 5000);
    };
}

// Tab Switching Logic
function switchTab(tabId) {
    // Hide all tabs
    document.querySelectorAll(".tab-content").forEach(el => {
        el.classList.remove("active");
    });
    // Remove active class from buttons
    document.querySelectorAll(".tab-btn").forEach(el => {
        el.classList.remove("active");
    });

    // Show target tab
    document.getElementById(tabId).classList.add("active");
    
    // Set active button
    if (tabId === "tab-overview") {
        document.getElementById("btn-tab-overview").classList.add("active");
    } else if (tabId === "tab-live") {
        document.getElementById("btn-tab-live").classList.add("active");
        populateLiveCamSelect();
    }
}

function populateLiveCamSelect() {
    const select = document.getElementById("live-cam-select");
    if (select.children.length > 0) return; // already populated

    const activeCh = Array.from(document.querySelectorAll(".ch-checkbox:checked")).map(b => parseInt(b.value));
    
    if (activeCh.length === 0) {
        const opt = document.createElement("option");
        opt.innerText = "Kh�ng c� camera n�o du?c ch?n";
        select.appendChild(opt);
        return;
    }

    activeCh.forEach(ch => {
        const opt = document.createElement("option");
        opt.value = ch;
        opt.innerText = `Camera K�nh ${String(ch).padStart(2, "0")}`;
        select.appendChild(opt);
    });
}



document.addEventListener("DOMContentLoaded", () => {
    const select = document.getElementById("live-cam-select");
    if(select) {
        select.addEventListener("change", (e) => {
            const channel = e.target.value;
            const player = document.getElementById("live-video-player");
            if(channel) {
                // Th�m timestamp d? tr�nh cache
                player.src = `/api/stream/live/${channel}?t=${new Date().getTime()}`;
            } else {
                player.src = "";
            }
        });
    }
});

// Override populateLiveCamSelect to trigger stream on load
const originalPopulateLiveCamSelect = populateLiveCamSelect;
populateLiveCamSelect = function() {
    originalPopulateLiveCamSelect();
    const select = document.getElementById("live-cam-select");
    const player = document.getElementById("live-video-player");
    if(select && select.value && (!player.src || player.src.includes("undefined") || player.src === window.location.href)) {
        player.src = `/api/stream/live/${select.value}?t=${new Date().getTime()}`;
    }
}


