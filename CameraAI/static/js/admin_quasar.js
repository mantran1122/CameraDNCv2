/**
 * Camera AI DNC - Quasar Admin Control Center
 * Complete Vue 3 + Quasar UMD Application Logic
 */

(function () {
    const { createApp, ref, reactive, computed, onMounted } = Vue;

    const app = createApp({
        setup() {
            const $q = Quasar.useQuasar();

            // Navigation & Layout
            const leftDrawerOpen = ref(true);
            const activeTab = ref('nvr'); // 'nvr' | 'users' | 'security' | 'ai'
            const adminUsername = ref('aicamera');

            // Top Status & Badges
            const nvrStatus = reactive({
                isDemo: false,
                connected: false,
                statusText: 'Đang kết nối NVR...'
            });

            // Camera Data & Matrix
            const allCameras = ref([]);
            const cameraPresets = ref({
                all: [],
                lobby: [],
                office: [],
                corridor: [],
                active_now: []
            });

            const activeChannelsCount = computed(() => {
                return allCameras.value.filter(c => c.is_active).length;
            });

            // Tab 1: NVR Configuration & Listener
            const nvrForm = reactive({
                nvr_host: '',
                nvr_port: 80,
                rtsp_port: 554,
                nvr_user: '',
                nvr_password: '',
                use_https: false,
                demo_mode: false,
                abnormal_event_codes: []
            });
            const showNvrPassword = ref(false);
            const testingNVR = ref(false);
            const savingNVR = ref(false);
            const testResult = ref(null);

            const listenerStatus = reactive({
                listener: { is_running: false },
                queue_size: 0,
                nas_health: { backend: 'Local Storage' }
            });

            const retentionDays = ref(30);
            const purgingStorage = ref(false);
            const purgeResult = ref(null);

            // Tab 2: Users & RBAC Matrix
            const systemUsers = ref([]);
            const savingUser = ref(false);
            const showDialogPass = ref(false);

            const userColumns = [
                { name: 'username', label: 'Tài khoản', field: 'username', sortable: true, align: 'left' },
                { name: 'full_name', label: 'Họ và tên / Phòng ban', field: 'full_name', sortable: true, align: 'left' },
                { name: 'role', label: 'Vai trò', field: 'role', sortable: true, align: 'center' },
                { name: 'channels', label: 'Quyền Camera (RBAC)', field: 'allowed_channels', align: 'left' },
                { name: 'created_at', label: 'Thời gian tạo', field: 'created_at', sortable: true, align: 'left' },
                { name: 'actions', label: 'Thao tác', field: 'actions', align: 'center' }
            ];

            const roleOptions = [
                { label: 'Quản trị viên (Admin) - Toàn quyền', value: 'admin' },
                { label: 'Người trực / Vận hành (Operator)', value: 'operator' },
                { label: 'Người xem (Viewer) - Chỉ xem', value: 'viewer' }
            ];

            const userDialog = reactive({
                show: false,
                isEdit: false,
                form: {
                    username: '',
                    full_name: '',
                    password: '',
                    role: 'viewer',
                    allowed_channels: []
                }
            });

            // Tab 3: Security & IP Management
            const activeSessions = ref([]);
            const lockouts = ref([]);
            const auditLogs = ref([]);

            const sessionColumns = [
                { name: 'client_ip', label: 'Địa chỉ IP', field: 'client_ip', sortable: true, align: 'left' },
                { name: 'username', label: 'Tài khoản', field: 'username', sortable: true, align: 'left' },
                { name: 'role', label: 'Vai trò', field: 'role', sortable: true, align: 'center' },
                { name: 'user_agent', label: 'Trình duyệt / Thiết bị', field: 'user_agent', align: 'left' },
                { name: 'last_active', label: 'Hoạt động gần nhất', field: 'last_active', sortable: true, align: 'left' },
                { name: 'actions', label: 'Thao tác', align: 'center' }
            ];

            const auditColumns = [
                { name: 'timestamp', label: 'Thời gian', field: 'timestamp', sortable: true, align: 'left' },
                { name: 'username', label: 'Tài khoản', field: 'username', sortable: true, align: 'left' },
                { name: 'ip_address', label: 'Địa chỉ IP', field: 'ip_address', sortable: true, align: 'left' },
                { name: 'status', label: 'Kết quả', field: 'status', align: 'center' },
                { name: 'user_agent', label: 'Thiết bị', field: 'user_agent', align: 'left' }
            ];

            // Tab 4: AI & Prompt Profiles
            const geminiConfig = reactive({
                selected_model: 'GLM-5.3-Flash',
                api_key: '',
                has_api_key: false,
                source: ''
            });
            const geminiModelOptions = [
                'GLM-5.3-Flash',
                'Qwen3.8-27B',
                'Qwen2.5-VL-72B-Instruct',
                'Qwen2.5-VL-7B-Instruct',
                'Qwen2.5-72B-Instruct'
            ];
            const showGeminiKey = ref(false);
            const savingGemini = ref(false);

            const cosmosPrompt = reactive({
                selected: 'student_affairs',
                profiles: []
            });
            const currentPromptText = ref('');
            const savingCosmos = ref(false);
            const uploadPromptFile = ref(null);
            const uploadingPrompt = ref(false);

            // Change Admin Password Dialog
            const changeAdminPassDialog = reactive({
                show: false,
                username: 'aicamera',
                newPassword: ''
            });
            const savingAdminPass = ref(false);

            // ================= METHODS =================

            // Load Initial Data
            const checkAuthAndInit = async () => {
                try {
                    const res = await fetch('/api/user/allowed-cameras');
                    if (res.status === 401 || res.status === 403) {
                        window.location.href = '/login?next=/admin';
                        return;
                    }
                    const data = await res.json();
                    if (!data.is_admin) {
                        window.location.href = '/?error=permission_denied';
                        return;
                    }
                    adminUsername.value = data.username || 'aicamera';
                    changeAdminPassDialog.username = adminUsername.value;
                } catch (e) {
                    console.error('Lỗi kiểm tra quyền Admin:', e);
                }

                await Promise.allSettled([
                    fetchNVRConfig(),
                    fetchCameras(),
                    fetchListenerStatus(),
                    fetchUsers(),
                    fetchSecurityData(),
                    fetchAuditLogs(),
                    fetchGeminiConfig(),
                    fetchCosmosConfig()
                ]);
            };

            // NVR Configuration Methods
            const fetchNVRConfig = async () => {
                try {
                    const res = await fetch('/api/config/nvr');
                    if (!res.ok) throw new Error('Không thể tải cấu hình NVR');
                    const data = await res.json();
                    nvrForm.nvr_host = data.nvr_host || '';
                    nvrForm.nvr_port = data.nvr_port || 80;
                    nvrForm.rtsp_port = data.rtsp_port || 554;
                    nvrForm.nvr_user = data.nvr_user || '';
                    nvrForm.use_https = !!data.use_https;
                    nvrForm.demo_mode = !!data.demo_mode;
                    nvrForm.abnormal_event_codes = data.abnormal_event_codes || [];

                    nvrStatus.isDemo = nvrForm.demo_mode;
                    if (nvrForm.demo_mode) {
                        nvrStatus.connected = true;
                        nvrStatus.statusText = 'Giả lập (Demo Mode)';
                    } else {
                        nvrStatus.connected = true;
                        nvrStatus.statusText = `${nvrForm.nvr_host}:${nvrForm.nvr_port} (Sẵn sàng)`;
                    }
                } catch (e) {
                    nvrStatus.connected = false;
                    nvrStatus.statusText = 'Lỗi kết nối NVR';
                    console.error(e);
                }
            };

            const testNVRConnection = async () => {
                testingNVR.value = true;
                testResult.value = null;
                try {
                    const res = await fetch('/api/config/nvr/test', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(nvrForm)
                    });
                    const data = await res.json();
                    testResult.value = data;
                    if (data.success) {
                        $q.notify({ type: 'positive', message: data.message || 'Kết nối NVR thành công!' });
                        nvrStatus.connected = true;
                        nvrStatus.statusText = `${nvrForm.nvr_host}:${nvrForm.nvr_port} (Online)`;
                    } else {
                        $q.notify({ type: 'negative', message: data.message || 'Kết nối NVR thất bại!' });
                        nvrStatus.connected = false;
                        nvrStatus.statusText = 'Ngoại tuyến';
                    }
                } catch (e) {
                    testResult.value = { success: false, message: 'Lỗi mạng khi kiểm tra kết nối NVR: ' + e.message };
                    $q.notify({ type: 'negative', message: testResult.value.message });
                } finally {
                    testingNVR.value = false;
                }
            };

            const saveNVRConfig = async () => {
                savingNVR.value = true;
                try {
                    const res = await fetch('/api/config/nvr', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(nvrForm)
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.error || data.detail || 'Lỗi lưu NVR');
                    $q.notify({ type: 'positive', message: data.message || 'Đã lưu cấu hình NVR thành công!' });
                    await fetchNVRConfig();
                    await fetchListenerStatus();
                } catch (e) {
                    $q.notify({ type: 'negative', message: e.message });
                } finally {
                    savingNVR.value = false;
                }
            };

            const fetchListenerStatus = async () => {
                try {
                    const res = await fetch('/api/admin/listener-status');
                    if (res.ok) {
                        const data = await res.json();
                        Object.assign(listenerStatus, data);
                    }
                } catch (e) {
                    console.error('Lỗi listener status:', e);
                }
            };

            const confirmPurgeStorage = () => {
                $q.dialog({
                    title: 'Xác nhận Dọn rác Lưu trữ',
                    message: `Bạn có chắc chắn muốn dọn sạch các sự kiện và clip video cũ hơn ${retentionDays.value} ngày không? Dữ liệu này không thể khôi phục.`,
                    cancel: true,
                    persistent: true,
                    dark: true,
                    ok: { label: 'Dọn rác ngay', color: 'amber-9' }
                }).onOk(async () => {
                    purgingStorage.value = true;
                    try {
                        const res = await fetch(`/api/admin/storage/purge-retention?days=${retentionDays.value}`, {
                            method: 'POST'
                        });
                        const data = await res.json();
                        purgeResult.value = data;
                        $q.notify({
                            type: 'positive',
                            message: `Đã dọn dẹp ${data.deleted_events || 0} sự kiện và ${data.deleted_clips || 0} clip cũ!`
                        });
                    } catch (e) {
                        $q.notify({ type: 'negative', message: 'Lỗi khi dọn dẹp lưu trữ: ' + e.message });
                    } finally {
                        purgingStorage.value = false;
                    }
                });
            };

            // Camera Matrix & RBAC
            const fetchCameras = async () => {
                try {
                    const res = await fetch('/api/admin/cameras/all');
                    if (!res.ok) return;
                    const data = await res.json();
                    allCameras.value = data.cameras || [];
                    if (data.presets) {
                        cameraPresets.value = data.presets;
                    }
                } catch (e) {
                    console.error('Lỗi tải danh sách camera:', e);
                }
            };

            const fetchUsers = async () => {
                try {
                    const res = await fetch('/api/admin/users');
                    if (res.ok) {
                        systemUsers.value = await res.json();
                    }
                } catch (e) {
                    console.error('Lỗi tải danh sách users:', e);
                }
            };

            const openCreateUserDialog = () => {
                userDialog.isEdit = false;
                userDialog.form = {
                    username: '',
                    full_name: '',
                    password: '',
                    role: 'viewer',
                    allowed_channels: [1, 2, 3, 4]
                };
                showDialogPass.value = false;
                userDialog.show = true;
            };

            const openEditUserDialog = (row) => {
                userDialog.isEdit = true;
                userDialog.form = {
                    username: row.username,
                    full_name: row.full_name || '',
                    password: '',
                    role: row.role || 'viewer',
                    allowed_channels: Array.isArray(row.allowed_channels) ? [...row.allowed_channels] : []
                };
                showDialogPass.value = false;
                userDialog.show = true;
            };

            const toggleCamera = (channel) => {
                if (userDialog.form.role === 'admin') return;
                const idx = userDialog.form.allowed_channels.indexOf(channel);
                if (idx > -1) {
                    userDialog.form.allowed_channels.splice(idx, 1);
                } else {
                    userDialog.form.allowed_channels.push(channel);
                    userDialog.form.allowed_channels.sort((a, b) => a - b);
                }
            };

            const applyPreset = (presetType) => {
                if (userDialog.form.role === 'admin') return;
                if (presetType === 'all') {
                    userDialog.form.allowed_channels = Array.from({ length: 32 }, (_, i) => i + 1);
                } else if (presetType === 'none') {
                    userDialog.form.allowed_channels = [];
                } else if (cameraPresets.value[presetType]) {
                    userDialog.form.allowed_channels = [...cameraPresets.value[presetType]];
                }
            };

            const submitUserDialog = async () => {
                if (!userDialog.form.username.trim()) {
                    $q.notify({ type: 'warning', message: 'Vui lòng nhập tên đăng nhập' });
                    return;
                }
                if (!userDialog.isEdit && !userDialog.form.password) {
                    $q.notify({ type: 'warning', message: 'Vui lòng nhập mật khẩu cho tài khoản mới' });
                    return;
                }

                savingUser.value = true;
                try {
                    let url = '/api/admin/users';
                    let method = 'POST';
                    let payload = { ...userDialog.form };

                    if (userDialog.isEdit) {
                        url = `/api/admin/users/${encodeURIComponent(userDialog.form.username)}`;
                        method = 'PUT';
                        if (!payload.password) {
                            delete payload.password;
                        }
                    }

                    const res = await fetch(url, {
                        method: method,
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || data.message || 'Lỗi lưu thông tin người dùng');

                    $q.notify({ type: 'positive', message: data.message || 'Lưu tài khoản thành công!' });
                    userDialog.show = false;
                    await fetchUsers();
                } catch (e) {
                    $q.notify({ type: 'negative', message: e.message });
                } finally {
                    savingUser.value = false;
                }
            };

            const confirmDeleteUser = (row) => {
                $q.dialog({
                    title: 'Xác nhận xóa tài khoản',
                    message: `Bạn có chắc chắn muốn xóa tài khoản "${row.username}" không?`,
                    cancel: true,
                    persistent: true,
                    dark: true,
                    ok: { label: 'Xóa vĩnh viễn', color: 'negative' }
                }).onOk(async () => {
                    try {
                        const res = await fetch(`/api/admin/users/${encodeURIComponent(row.username)}`, {
                            method: 'DELETE'
                        });
                        const data = await res.json();
                        if (!res.ok) throw new Error(data.detail || 'Lỗi xóa tài khoản');
                        $q.notify({ type: 'positive', message: data.message || 'Đã xóa tài khoản' });
                        await fetchUsers();
                    } catch (e) {
                        $q.notify({ type: 'negative', message: e.message });
                    }
                });
            };

            // Tab 3: Security & Sessions
            const fetchSecurityData = async () => {
                try {
                    const [sessRes, lockRes] = await Promise.all([
                        fetch('/api/admin/security/active-sessions'),
                        fetch('/api/admin/security/lockouts')
                    ]);
                    if (sessRes.ok) {
                        const sData = await sessRes.json();
                        activeSessions.value = sData.sessions || [];
                    }
                    if (lockRes.ok) {
                        const lData = await lockRes.json();
                        lockouts.value = lData.lockouts || [];
                    }
                } catch (e) {
                    console.error('Lỗi tải dữ liệu bảo mật:', e);
                }
            };

            const fetchAuditLogs = async () => {
                try {
                    const res = await fetch('/api/admin/security/audit-logs?limit=50');
                    if (res.ok) {
                        const data = await res.json();
                        auditLogs.value = data.logs || [];
                    }
                } catch (e) {
                    console.error('Lỗi tải audit logs:', e);
                }
            };

            const revokeSession = (row) => {
                $q.dialog({
                    title: 'Xác nhận hủy phiên từ xa',
                    message: `Hủy phiên làm việc của IP ${row.client_ip} (Tài khoản: ${row.username})?`,
                    cancel: true,
                    persistent: true,
                    dark: true,
                    ok: { label: 'Đăng xuất IP này', color: 'negative' }
                }).onOk(async () => {
                    try {
                        const res = await fetch('/api/admin/security/revoke-session', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ session_key: row.session_key })
                        });
                        const data = await res.json();
                        $q.notify({ type: 'positive', message: data.message || 'Đã hủy phiên làm việc' });
                        await fetchSecurityData();
                    } catch (e) {
                        $q.notify({ type: 'negative', message: e.message });
                    }
                });
            };

            const unblockTarget = async (target) => {
                try {
                    const res = await fetch('/api/admin/security/unblock', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ target })
                    });
                    const data = await res.json();
                    $q.notify({ type: 'positive', message: data.message });
                    await fetchSecurityData();
                } catch (e) {
                    $q.notify({ type: 'negative', message: e.message });
                }
            };

            // Tab 4: AI & Cosmos Prompt
            const fetchGeminiConfig = async () => {
                try {
                    const res = await fetch('/api/admin/ai-config');
                    if (res.ok) {
                        const data = await res.json();
                        if (data.vlm) {
                            geminiConfig.selected_model = data.vlm.model_name || 'GLM-5.3-Flash';
                            geminiConfig.has_api_key = !!data.vlm.has_api_key;
                            geminiConfig.source = `VLM Server (${data.vlm.server_url})`;
                        }
                    }
                } catch (e) {
                    console.error('Lỗi tải AI config:', e);
                }
            };

            const saveGeminiConfig = async () => {
                savingGemini.value = true;
                try {
                    const payload = {
                        vlm_model_name: geminiConfig.selected_model
                    };
                    if (geminiConfig.api_key && geminiConfig.api_key.trim()) {
                        payload.vlm_api_key = geminiConfig.api_key.trim();
                    }
                    const res = await fetch('/api/admin/ai-config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Lỗi lưu cấu hình Server AI');
                    $q.notify({ type: 'positive', message: data.message || 'Đã lưu cấu hình Server AI!' });
                    geminiConfig.api_key = '';
                    await fetchGeminiConfig();
                } catch (e) {
                    $q.notify({ type: 'negative', message: e.message });
                } finally {
                    savingGemini.value = false;
                }
            };

            const fetchCosmosConfig = async () => {
                try {
                    const res = await fetch('/api/admin/cosmos/prompt-profile');
                    if (res.ok) {
                        const data = await res.json();
                        cosmosPrompt.selected = data.selected || 'student_affairs';
                        cosmosPrompt.profiles = data.profiles || [];
                        await loadPromptText(cosmosPrompt.selected);
                    }
                } catch (e) {
                    console.error('Lỗi tải Cosmos prompt:', e);
                }
            };

            const loadPromptText = async (profile) => {
                try {
                    const res = await fetch(`/api/admin/cosmos/prompt-profiles/${encodeURIComponent(profile)}`);
                    if (res.ok) {
                        const data = await res.json();
                        currentPromptText.value = data.text || '';
                    } else {
                        currentPromptText.value = 'Không tải được nội dung prompt.';
                    }
                } catch (e) {
                    currentPromptText.value = 'Lỗi kết nối khi tải prompt: ' + e.message;
                }
            };

            const onPromptProfileChange = async (newVal) => {
                await loadPromptText(newVal);
            };

            const saveCosmosPrompt = async () => {
                savingCosmos.value = true;
                try {
                    const res = await fetch('/api/admin/cosmos/prompt-profile', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ profile: cosmosPrompt.selected })
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Lỗi lưu Cosmos prompt');
                    $q.notify({ type: 'positive', message: data.message || 'Đã áp dụng Prompt Profile thành công!' });
                } catch (e) {
                    $q.notify({ type: 'negative', message: e.message });
                } finally {
                    savingCosmos.value = false;
                }
            };

            const uploadPrompt = async () => {
                if (!uploadPromptFile.value) {
                    $q.notify({ type: 'warning', message: 'Vui lòng chọn file .txt trước khi tải lên' });
                    return;
                }
                uploadingPrompt.value = true;
                try {
                    const formData = new FormData();
                    formData.append('prompt_file', uploadPromptFile.value);
                    const res = await fetch('/api/admin/cosmos/prompt-profiles/upload', {
                        method: 'POST',
                        body: formData
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Lỗi tải lên prompt');
                    $q.notify({ type: 'positive', message: data.message || 'Tải file prompt thành công!' });
                    uploadPromptFile.value = null;
                    await fetchCosmosConfig();
                } catch (e) {
                    $q.notify({ type: 'negative', message: e.message });
                } finally {
                    uploadingPrompt.value = false;
                }
            };

            // Admin Password Change
            const openChangeAdminPassDialog = () => {
                changeAdminPassDialog.newPassword = '';
                changeAdminPassDialog.show = true;
            };

            const submitChangeAdminPass = async () => {
                if (!changeAdminPassDialog.newPassword.trim()) {
                    $q.notify({ type: 'warning', message: 'Vui lòng nhập mật khẩu mới' });
                    return;
                }
                savingAdminPass.value = true;
                try {
                    const res = await fetch('/api/admin/credentials', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            username: changeAdminPassDialog.username,
                            password: changeAdminPassDialog.newPassword
                        })
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Lỗi đổi mật khẩu Admin');
                    $q.notify({ type: 'positive', message: 'Đổi mật khẩu Quản trị viên thành công!' });
                    changeAdminPassDialog.show = false;
                } catch (e) {
                    $q.notify({ type: 'negative', message: e.message });
                } finally {
                    savingAdminPass.value = false;
                }
            };

            const logout = async () => {
                try {
                    await fetch('/api/logout', { method: 'POST' });
                } catch (e) {
                    console.error('Lỗi khi logout:', e);
                }
                window.location.href = '/login';
            };

            // Lifecycle Hook
            onMounted(() => {
                checkAuthAndInit();
                // Set interval to periodically update active sessions
                setInterval(fetchSecurityData, 15000);
            });

            return {
                // Layout & Navigation
                leftDrawerOpen,
                activeTab,
                adminUsername,
                nvrStatus,
                allCameras,
                activeChannelsCount,

                // Tab 1: NVR
                nvrForm,
                showNvrPassword,
                testingNVR,
                savingNVR,
                testResult,
                listenerStatus,
                retentionDays,
                purgingStorage,
                purgeResult,
                testNVRConnection,
                saveNVRConfig,
                fetchListenerStatus,
                confirmPurgeStorage,

                // Tab 2: Users & Matrix
                systemUsers,
                userColumns,
                roleOptions,
                userDialog,
                showDialogPass,
                savingUser,
                fetchUsers,
                openCreateUserDialog,
                openEditUserDialog,
                toggleCamera,
                applyPreset,
                submitUserDialog,
                confirmDeleteUser,

                // Tab 3: Security
                activeSessions,
                lockouts,
                auditLogs,
                sessionColumns,
                auditColumns,
                fetchSecurityData,
                fetchAuditLogs,
                revokeSession,
                unblockTarget,

                // Tab 4: AI
                geminiConfig,
                geminiModelOptions,
                showGeminiKey,
                savingGemini,
                saveGeminiConfig,
                cosmosPrompt,
                currentPromptText,
                savingCosmos,
                uploadPromptFile,
                uploadingPrompt,
                onPromptProfileChange,
                saveCosmosPrompt,
                uploadPrompt,

                // Admin Pass
                changeAdminPassDialog,
                savingAdminPass,
                openChangeAdminPassDialog,
                submitChangeAdminPass,
                logout
            };
        }
    });

    app.use(Quasar, {
        config: {
            dark: true,
            notify: {
                position: 'top-right',
                timeout: 3000
            }
        },
        plugins: {
            Notify: Quasar.Notify,
            Dialog: Quasar.Dialog
        }
    });

    app.mount('#q-app');
})();
