let activityChart = null;
let audioAnalysisPollTimer = null;
let videoAnalysisPollTimer = null;
let activeEventFilter = false;
let selectedEventId = null;

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
        setText('agent-summary-text', data.summary_text, 'Đang tải dữ liệu báo cáo...');

        renderActivityChart(data.hourly_distribution, data.hourly_anomalies);
    } catch (err) {
        console.error('Error fetching summary:', err);
    }
}

// Fetch Anomaly & Metadata Events Feed
async function fetchEvents(onlyAnomalies = false) {
    activeEventFilter = onlyAnomalies;
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
            <button class="btn-clip-play vss-view-cam-btn" onclick="openCameraVss(${ev.channel}); event.stopPropagation();" title="Xem trực tiếp trên giao diện NVIDIA VSS Blueprint">
                📹 Xem Camera VSS
            </button>
            ${hasClip ? `<button class="btn-clip-play" onclick="openClipModal(${ev.id}, '${ev.clip_filename}', '${ev.description}'); event.stopPropagation();">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg> Xem 10s Clip
            </button>` : ''}
        </div>
    `;
    card.addEventListener('click', () => openCameraVss(ev.channel));
    return card;
}

function setEventFilter(button, onlyAnomalies) {
    document.querySelectorAll('.filter-btn').forEach(item => item.classList.remove('active'));
    button?.classList.add('active');
    fetchEvents(onlyAnomalies);
}

function filterVisibleEvents(query) {
    const normalized = (query || '').trim().toLocaleLowerCase('vi');
    document.querySelectorAll('#events-container .event-item').forEach(card => {
        card.hidden = Boolean(normalized) && !card.textContent.toLocaleLowerCase('vi').includes(normalized);
    });
}

function selectEventForAgent(event, card) {
    selectedEventId = event.id;
    document.querySelectorAll('#events-container .event-item').forEach(item => item.classList.remove('is-selected'));
    card?.classList.add('is-selected');
    setText('agent-event-id', `#${event.id}`);
    setText('agent-source', 'NVR metadata');
    const workerStatus = event.video_analysis?.status || event.audio_analysis?.status || 'Chưa phân tích';
    setText('agent-status', formatVideoAnalysisStatus(event.video_analysis) || formatAudioStatus(event.audio_analysis) || workerStatus);
    const clipState = event.clip_filename ? 'Có clip evidence.' : 'Chưa có clip evidence.';
    setText('agent-context', `${event.description || 'Không có mô tả.'} Camera Ch ${String(event.channel || 0).padStart(2, '0')} · ${event.timestamp || 'Không rõ thời gian'}. ${clipState}`);
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
    videoElem.muted = false;
    videoElem.volume = 1.0;
    videoElem.load();
    const playPromise = videoElem.play();
    if (playPromise !== undefined) {
        playPromise.catch(e => {
            console.log('Unmuted autoplay prevented by browser policy, muting for preview:', e);
            videoElem.muted = true;
            videoElem.play().catch(err => console.log('Playback error:', err));
        });
    }

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
        try {
            const ev = JSON.parse(event.data);
            console.log('Realtime event received:', ev);

            // Update overview tab feed
            const container = document.getElementById('events-container');
            if (container) {
                const previous = container.querySelector(`[data-event-id="${ev.id}"]`);
                if (previous) previous.remove();
                container.insertBefore(createEventCard(ev), container.firstChild);
            }

            // Keep VSS middle column clean: do NOT auto-insert realtime metadata unless requested by user or Vision Agent
            fetchDailySummary();
        } catch (err) {
            console.error('Error handling WebSocket event:', err);
        }
    };

    ws.onclose = () => {
        setTimeout(initWebSocket, 5000);
    };
}

// ==========================================================================
// NVIDIA VSS BLUEPRINT | VISION SEARCH INTERFACE CONTROLLER
// Direct clone of vendor/nvidia-video-search-and-summarization
// ==========================================================================

let currentVssChannel = 11;
let vssSourceType = 'video_file'; // 'video_file' or 'rtsp'
let vssSelectedChannels = [];     // Array of channel numbers selected in filter
let vssStartDate = null;
let vssEndDate = null;
let vssMinSimilarity = 0.70;
let vssTopK = 24;
let vssQuickFilter = 'all';        // 'all', 'confirmed', 'anomalies', 'human', 'vehicle', 'audio'
let vssChatSidebarCollapsed = false;
let vssChatContextItems = [];     // Injected via '+ Chat' button

// Tab Switching Logic
function switchTab(tabId) {
    document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
    document.querySelectorAll(".tab-btn").forEach(el => el.classList.remove("active"));

    const target = document.getElementById(tabId);
    if (target) target.classList.add("active");

    const btnOverview = document.getElementById("btn-tab-overview");
    const btnLive = document.getElementById("btn-tab-live");

    if (tabId === "tab-overview") {
        btnOverview?.classList.add("active");
    } else if (tabId === "tab-live") {
        btnLive?.classList.add("active");
        initVssVisionSearch();
        executeVssSearch();
    }
}

// Initialize Vision Search Component & Populate Channel Selectors
function initVssVisionSearch() {
    const channelSelect = document.getElementById("vss-filter-channels");
    const quickSelect = document.getElementById("vss-quick-cam-select");

    if (channelSelect && channelSelect.options.length === 0) {
        channelSelect.innerHTML = '';
        for (let i = 1; i <= 32; i++) {
            const opt = document.createElement("option");
            opt.value = i;
            opt.innerText = `Camera Kênh ${String(i).padStart(2, '0')}${i === 11 || i === 18 ? ' (🟢 Online)' : ''}`;
            channelSelect.appendChild(opt);
        }
    }

    if (quickSelect && quickSelect.options.length === 0) {
        quickSelect.innerHTML = '';
        for (let i = 1; i <= 32; i++) {
            const opt = document.createElement("option");
            opt.value = i;
            opt.innerText = `Kênh ${String(i).padStart(2, '0')}`;
            quickSelect.appendChild(opt);
        }
        quickSelect.value = currentVssChannel;
    }
}

// Source Type Selection (Video vs RTSP)
function setVssSourceType(type) {
    vssSourceType = type;
    document.getElementById("btn-source-video")?.classList.toggle("active", type === 'video_file');
    document.getElementById("btn-source-rtsp")?.classList.toggle("active", type === 'rtsp');

    const liveBadge = document.getElementById("vss-header-live-badge");
    const liveLabel = document.getElementById("vss-header-live-label");
    const rtspPreview = document.getElementById("vss-rtsp-preview-box");

    if (type === 'rtsp') {
        if (liveLabel) liveLabel.innerText = "RTSP STREAMING ACTIVE";
        if (rtspPreview) rtspPreview.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } else {
        if (liveLabel) liveLabel.innerText = "RECORDED CLIPS SEARCH";
    }

    renderVssActiveChips();
    executeVssSearch();
}

// Toggle Filter Popover Dialog
function toggleVssFilterPopover() {
    const popover = document.getElementById("vss-filter-popover");
    if (!popover) return;
    const isHidden = popover.style.display === "none" || !popover.style.display;
    popover.style.display = isHidden ? "flex" : "none";
}

// Apply Filters from Popover
function applyVssFilters() {
    const channelSelect = document.getElementById("vss-filter-channels");
    if (channelSelect) {
        vssSelectedChannels = Array.from(channelSelect.selectedOptions).map(o => parseInt(o.value));
    }

    const startInput = document.getElementById("vss-filter-start-date");
    vssStartDate = startInput?.value || null;

    const endInput = document.getElementById("vss-filter-end-date");
    vssEndDate = endInput?.value || null;

    const simInput = document.getElementById("vss-filter-similarity");
    vssMinSimilarity = parseFloat(simInput?.value || 0.70);

    const topKSelect = document.getElementById("vss-filter-topk");
    vssTopK = parseInt(topKSelect?.value || 24);

    toggleVssFilterPopover();
    renderVssActiveChips();
    executeVssSearch();
}

// Reset Filters
function resetVssFilters() {
    vssSelectedChannels = [];
    vssStartDate = null;
    vssEndDate = null;
    vssMinSimilarity = 0.70;
    vssTopK = 24;

    const channelSelect = document.getElementById("vss-filter-channels");
    if (channelSelect) {
        Array.from(channelSelect.options).forEach(o => o.selected = false);
    }
    const startInput = document.getElementById("vss-filter-start-date");
    if (startInput) startInput.value = "";
    const endInput = document.getElementById("vss-filter-end-date");
    if (endInput) endInput.value = "";
    const simInput = document.getElementById("vss-filter-similarity");
    if (simInput) simInput.value = 0.70;
    const simVal = document.getElementById("vss-filter-sim-val");
    if (simVal) simVal.innerText = "0.70";
    const topKSelect = document.getElementById("vss-filter-topk");
    if (topKSelect) topKSelect.value = "24";

    toggleVssFilterPopover();
    renderVssActiveChips();
    executeVssSearch();
}

// Render Active Filter Chips
function renderVssActiveChips() {
    const container = document.getElementById("vss-active-chips-container");
    const countBadge = document.getElementById("vss-filter-badge-count");
    if (!container) return;

    let chips = [];

    if (vssSourceType === 'rtsp') {
        chips.push({ key: 'source', label: 'Nguồn: RTSP', val: 'rtsp' });
    }

    if (vssSelectedChannels.length > 0) {
        chips.push({
            key: 'channels',
            label: `Kênh: ${vssSelectedChannels.map(c => `Ch ${String(c).padStart(2, '0')}`).join(', ')}`,
            val: 'channels'
        });
    }

    if (vssStartDate) {
        chips.push({ key: 'start', label: `Từ: ${vssStartDate.replace('T', ' ')}`, val: 'start' });
    }

    if (vssEndDate) {
        chips.push({ key: 'end', label: `Đến: ${vssEndDate.replace('T', ' ')}`, val: 'end' });
    }

    if (vssMinSimilarity > 0.70) {
        chips.push({ key: 'sim', label: `Sim ≥ ${vssMinSimilarity.toFixed(2)}`, val: 'sim' });
    }

    if (countBadge) {
        if (chips.length > 0) {
            countBadge.style.display = "inline-block";
            countBadge.innerText = chips.length;
        } else {
            countBadge.style.display = "none";
        }
    }

    if (chips.length === 0) {
        container.innerHTML = '<div class="vss-chip-placeholder">Chưa áp dụng bộ lọc</div>';
        return;
    }

    container.innerHTML = '';
    chips.forEach(chip => {
        const div = document.createElement("div");
        div.className = "vss-active-tag";
        div.innerHTML = `
            <span>${chip.label}</span>
            <button type="button" class="vss-active-tag-remove" onclick="removeVssFilterTag('${chip.key}'); event.stopPropagation();">×</button>
        `;
        container.appendChild(div);
    });
}

// Remove single filter tag
function removeVssFilterTag(key) {
    if (key === 'source') {
        setVssSourceType('video_file');
        return;
    }
    if (key === 'channels') {
        vssSelectedChannels = [];
        const sel = document.getElementById("vss-filter-channels");
        if (sel) Array.from(sel.options).forEach(o => o.selected = false);
    }
    if (key === 'start') {
        vssStartDate = null;
        const inp = document.getElementById("vss-filter-start-date");
        if (inp) inp.value = "";
    }
    if (key === 'end') {
        vssEndDate = null;
        const inp = document.getElementById("vss-filter-end-date");
        if (inp) inp.value = "";
    }
    if (key === 'sim') {
        vssMinSimilarity = 0.70;
        const inp = document.getElementById("vss-filter-similarity");
        if (inp) inp.value = 0.70;
        const val = document.getElementById("vss-filter-sim-val");
        if (val) val.innerText = "0.70";
    }
    renderVssActiveChips();
    executeVssSearch();
}

// Quick filter shortcuts bar
function setVssQuickFilter(btn, filter) {
    document.querySelectorAll(".vss-qchip").forEach(c => c.classList.remove("active"));
    btn?.classList.add("active");
    vssQuickFilter = filter;
    executeVssSearch();
}

// Execute Vision Search
async function executeVssSearch() {
    const queryInput = document.getElementById("vss-search-input");
    const query = (queryInput?.value || "").trim().toLowerCase();

    const emptyState = document.getElementById("vss-empty-state");
    const resultsGrid = document.getElementById("vss-results-grid");
    const searchBtn = document.getElementById("vss-search-btn");

    if (searchBtn) {
        searchBtn.disabled = true;
        searchBtn.innerText = "Searching...";
    }

    try {
        let apiUrl = `/api/events?limit=${vssTopK}`;
        if (vssSelectedChannels.length === 1) {
            apiUrl += `&channel=${vssSelectedChannels[0]}`;
        }
        if (vssQuickFilter === 'anomalies') {
            apiUrl += `&only_anomalies=true`;
        }

        const res = await fetch(apiUrl);
        const data = await res.json();
        const events = data.events || [];

        // Client-side filtering matching vendor SearchComponent
        const filtered = events.filter(ev => {
            const ch = ev.channel;
            if (vssSelectedChannels.length > 1 && !vssSelectedChannels.includes(ch)) {
                return false;
            }

            const sim = Number(ev.similarity) || 0.85;
            if (sim < vssMinSimilarity) return false;

            const critic = ev.critic_result?.result || 'unverified';
            if (vssQuickFilter === 'confirmed' && critic !== 'confirmed') {
                return false;
            }

            if (vssQuickFilter === 'human') {
                const desc = (ev.description || '').toLowerCase();
                const code = (ev.event_code || '').toLowerCase();
                if (!desc.includes('người') && !desc.includes('human') && !code.includes('human')) return false;
            } else if (vssQuickFilter === 'vehicle') {
                const desc = (ev.description || '').toLowerCase();
                const code = (ev.event_code || '').toLowerCase();
                if (!desc.includes('xe') && !desc.includes('vehicle') && !code.includes('vehicle')) return false;
            } else if (vssQuickFilter === 'audio') {
                if (ev.event_type !== 'audio_anomaly') return false;
            }

            if (query) {
                const matchStr = `${ev.description || ''} ${ev.event_code || ''} ${ev.video_name || ''} ${ev.timestamp || ''}`.toLowerCase();
                if (!matchStr.includes(query)) return false;
            }

            return true;
        });

        renderVideoSearchList(filtered);
    } catch (err) {
        console.error("VSS Vision Search Error:", err);
        if (emptyState) emptyState.style.display = "flex";
        if (resultsGrid) {
            resultsGrid.style.display = "none";
            resultsGrid.innerHTML = "";
        }
    } finally {
        if (searchBtn) {
            searchBtn.disabled = false;
            searchBtn.innerText = "Search";
        }
    }
}

// Render Video Search Results Grid (matching VideoSearchList.tsx)
function renderVideoSearchList(events) {
    const emptyState = document.getElementById("vss-empty-state");
    const resultsGrid = document.getElementById("vss-results-grid");

    if (!events || events.length === 0) {
        if (emptyState) emptyState.style.display = "flex";
        if (resultsGrid) {
            resultsGrid.style.display = "none";
            resultsGrid.innerHTML = "";
        }
        return;
    }

    if (emptyState) emptyState.style.display = "none";
    if (resultsGrid) {
        resultsGrid.style.display = "grid";
        resultsGrid.innerHTML = "";
        events.forEach((ev, idx) => {
            resultsGrid.appendChild(createVssVideoCard(ev, idx));
        });
    }
}

// Create 280px Video Card matching vendor VideoSearchList.tsx
function createVssVideoCard(ev, idx) {
    const card = document.createElement("div");
    const critic = ev.critic_result?.result || 'unverified';
    card.className = `vss-card critic-${critic}`;
    card.dataset.eventId = ev.id;

    const videoName = ev.video_name || `Camera Kênh ${String(ev.channel || 1).padStart(2, '0')}`;
    const timestamp = ev.timestamp || '--:--:--';
    const timeOnly = timestamp.split(' ')[1] || timestamp;
    const similarity = (Number(ev.similarity) || 0.85).toFixed(2);

    const criticBadgeText = critic === 'confirmed' ? '✓ Confirmed' : critic === 'rejected' ? '✗ Rejected' : '? Unverified';
    const criticBadgeClass = `vss-critic-badge ${critic}`;

    // Criteria chips
    const criteriaMet = ev.critic_result?.criteria_met || {};
    let criteriaHtml = '';
    const entries = Object.entries(criteriaMet);
    if (entries.length > 0) {
        criteriaHtml = `
            <div class="vss-criteria-list">
                ${entries.map(([crit, met]) => `
                    <span class="vss-criteria-pill ${met ? 'met' : ''}">${met ? '✓' : '✗'} ${crit}</span>
                `).join('')}
            </div>
        `;
    }

    // Video Thumbnail URL (use live frame or fallback snapshot)
    const thumbUrl = `/api/stream/live/${ev.channel || 11}?t=${Date.now()}`;

    card.innerHTML = `
        <div class="vss-card-header">
            <h3 class="vss-card-title" title="${videoName}">${videoName}</h3>
            <button type="button" class="vss-card-chat-btn" id="btn-chat-${ev.id}" onclick="addVssCardToChat(${JSON.stringify(ev).replace(/"/g, '&quot;')}, this); event.stopPropagation();">
                + Chat
            </button>
        </div>
        <div class="vss-card-thumb-wrap" onclick="handleVssCardPlay(${JSON.stringify(ev).replace(/"/g, '&quot;')})">
            <img src="${thumbUrl}" class="vss-card-thumb-img" alt="${videoName}" onerror="this.src='/static/img/cam_placeholder.jpg'; this.onerror=null;" />
            <div class="vss-card-play-btn" title="Phát video evidence 10s">
                <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
            </div>
            <div class="vss-card-thumb-meta">
                <span>${timeOnly}</span>
                <span title="${ev.description || ''}">ⓘ</span>
            </div>
        </div>
        <div class="vss-card-body">
            <div class="vss-card-desc" title="${ev.description || ''}">
                ${ev.description || 'Sự kiện ghi nhận từ camera Dahua'}
            </div>
            <div class="vss-card-score-row">
                <span>Similarity:</span>
                <span class="vss-card-similarity">${similarity}</span>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span class="${criticBadgeClass}">${criticBadgeText}</span>
            </div>
            ${criteriaHtml}
        </div>
    `;

    return card;
}

// Handle Play Video on Card
function handleVssCardPlay(ev) {
    if (ev.clip_filename) {
        openClipModal(ev.id, ev.clip_filename, `${ev.video_name || 'Camera'} - ${ev.description || ''}`);
    } else {
        // Switch quick preview to this channel and notify user
        onVssQuickCamChanged(ev.channel || 11);
        sendVssAgentSuggestion(`Phân tích video clip cho Sự kiện #${ev.id} trên Kênh ${ev.channel || 11}`);
    }
}

// Add Card Context into Vision Agent Chat (matching AddContextButton in vendor VideoSearchList.tsx)
function addVssCardToChat(ev, btn) {
    if (btn) {
        btn.innerHTML = `✓ Added`;
        btn.classList.add("added");
        setTimeout(() => {
            btn.innerHTML = `+ Chat`;
            btn.classList.remove("added");
        }, 2000);
    }

    // Ensure chat sidebar is open
    if (vssChatSidebarCollapsed) {
        toggleVssChatSidebar();
    }

    // Add context to input
    const input = document.getElementById("vss-agent-input");
    if (input) {
        input.value = `Giải thích sự kiện #${ev.id} (${ev.description}) trên ${ev.video_name}: `;
        input.focus();
    }

    // Add context notification bubble in chat
    const chatContainer = document.getElementById("vss-chat-messages");
    const welcomeScreen = document.getElementById("vss-agent-welcome");
    if (welcomeScreen) welcomeScreen.style.display = "none";

    if (chatContainer) {
        const notice = document.createElement("div");
        notice.className = "vss-chat-bubble agent thinking";
        notice.style.fontSize = "0.76rem";
        notice.style.borderColor = "#76b900";
        notice.innerHTML = `📎 <strong>Đã gắn ngữ cảnh:</strong> ${ev.video_name} · [#${ev.id}] ${ev.description} (${ev.timestamp})`;
        chatContainer.appendChild(notice);

        const conv = document.getElementById("vss-agent-conversation");
        if (conv) conv.scrollTop = conv.scrollHeight;
    }
}

// Quick RTSP Preview Camera Change
function onVssQuickCamChanged(channel) {
    currentVssChannel = parseInt(channel) || 11;
    const player = document.getElementById("vss-quick-player");
    if (player) {
        player.src = `/api/stream/live/${currentVssChannel}?t=${Date.now()}`;
    }
    const label = document.getElementById("vss-quick-live-label");
    if (label) {
        label.innerText = `Ch ${String(currentVssChannel).padStart(2, '0')}`;
    }
    const quickSelect = document.getElementById("vss-quick-cam-select");
    if (quickSelect) {
        quickSelect.value = currentVssChannel;
    }
}

// Toggle Quick Player Fullscreen
function toggleQuickPlayerFullscreen() {
    const player = document.getElementById("vss-quick-player");
    if (!player) return;
    if (!document.fullscreenElement) {
        if (player.requestFullscreen) player.requestFullscreen();
        else if (player.webkitRequestFullscreen) player.webkitRequestFullscreen();
    } else {
        if (document.exitFullscreen) document.exitFullscreen();
    }
}
// Toggle Vision Agent Sidebar Collapse (matching TabWithChatSidebarLayout.tsx)
function toggleVssChatSidebar() {
    const sidebar = document.getElementById("vss-chat-sidebar");
    const floatBtn = document.getElementById("vss-floating-chat-btn");
    const chevron = document.getElementById("vss-agent-chevron-icon");

    vssChatSidebarCollapsed = !vssChatSidebarCollapsed;

    if (sidebar) {
        sidebar.classList.toggle("collapsed", vssChatSidebarCollapsed);
    }
    if (floatBtn) {
        floatBtn.style.display = vssChatSidebarCollapsed ? "flex" : "none";
    }
    if (chevron) {
        chevron.style.transform = vssChatSidebarCollapsed ? "rotate(180deg)" : "rotate(0deg)";
    }
}

// Vision Agent: Send suggestion chip directly
function sendVssAgentSuggestion(text) {
    const input = document.getElementById("vss-agent-input");
    if (input) input.value = text;
    sendVssAgentMessage();
}

function formatVssAgentReply(text) {
    if (!text) return 'Đã ghi nhận thông tin.';
    const escaped = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    return escaped
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/\n/g, '<br>');
}

// Vision Agent: Send Message & Chat
async function sendVssAgentMessage() {
    const input = document.getElementById("vss-agent-input");
    const query = (input?.value || "").trim();
    if (!query) return;

    input.value = "";

    const welcomeScreen = document.getElementById("vss-agent-welcome");
    if (welcomeScreen) welcomeScreen.style.display = "none";

    const chatContainer = document.getElementById("vss-chat-messages");
    const conversationArea = document.getElementById("vss-agent-conversation");
    if (!chatContainer) return;

    // Append User Bubble
    const userBubble = document.createElement("div");
    userBubble.className = "vss-chat-bubble user";
    userBubble.innerText = query;
    chatContainer.appendChild(userBubble);

    // Append Thinking Bubble
    const thinkingBubble = document.createElement("div");
    thinkingBubble.className = "vss-chat-bubble agent thinking";
    thinkingBubble.innerText = "Vision Agent đang truy vấn CSDL và phân tích...";
    chatContainer.appendChild(thinkingBubble);
    if (conversationArea) {
        conversationArea.scrollTop = conversationArea.scrollHeight;
    }

    try {
        const res = await fetch("/api/agent/query", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query: query, channel: currentVssChannel })
        });
        const data = await res.json();

        thinkingBubble.className = "vss-chat-bubble agent";
        thinkingBubble.innerHTML = `
            <div class="agent-tag">⚡ ${data.source || 'Vision Agent'} (Kênh ${String(data.channel || currentVssChannel).padStart(2, '0')})</div>
            <div>${formatVssAgentReply(data.reply)}</div>
        `;

        // Synchronize matched events to the VideoSearchList grid!
        if (data.matched_events && data.matched_events.length > 0) {
            renderVideoSearchList(data.matched_events);
        }
    } catch (err) {
        thinkingBubble.className = "vss-chat-bubble agent";
        thinkingBubble.innerHTML = `<div style="color:#f87171;">Lỗi kết nối tới Vision Agent backend. Vui lòng thử lại.</div>`;
    }

    if (conversationArea) {
        conversationArea.scrollTo({
            top: conversationArea.scrollHeight,
            behavior: 'smooth'
        });
    }
}

// Global initialization
document.addEventListener("DOMContentLoaded", () => {
    initVssVisionSearch();
});
