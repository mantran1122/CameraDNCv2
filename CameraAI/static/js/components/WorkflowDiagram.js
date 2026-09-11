/**
 * WorkflowDiagram Component Module
 * 
 * Renders the exact NVIDIA VSS Blueprint Agentic Search Architecture & Workflow Diagram:
 * Query -> Video Agent (LLM, Attributes, Actions, VIOS, VLM) -> Elasticsearch -> Output
 * 
 * Optimized for REAL-TIME SYNCHRONIZED EXECUTION:
 * - Accurately tracks actual backend pipeline stages (no premature timeouts).
 * - Nodes pulse and stay active during real Server 4x H200 inference and video processing.
 * - Displays exact model specs (Qwen 3.8-27B 4x H200, 32 Dense Frames).
 */

class WorkflowDiagram {
    constructor(container, options = {}) {
        this.container = typeof container === 'string' ? document.querySelector(container) : container;
        this.activeNode = options.activeNode || null;
        this._autoResetTimer = null;
        this.render();
        this.attachInteractions();
    }

    render() {
        if (!this.container) return;

        this.container.innerHTML = `
            <style>
                @keyframes wfNodePulsingGlow {
                    0% {
                        stroke: #76b900;
                        stroke-width: 2.5px;
                        fill: #143818;
                        filter: drop-shadow(0 0 5px rgba(118, 185, 0, 0.6));
                    }
                    50% {
                        stroke: #a3e635;
                        stroke-width: 3.8px;
                        fill: #1c5225;
                        filter: drop-shadow(0 0 20px rgba(163, 230, 53, 0.98));
                    }
                    100% {
                        stroke: #76b900;
                        stroke-width: 2.5px;
                        fill: #143818;
                        filter: drop-shadow(0 0 5px rgba(118, 185, 0, 0.6));
                    }
                }
                @keyframes wfDotBlink {
                    0%, 100% { opacity: 1; transform: scale(1.1); box-shadow: 0 0 6px #76b900; }
                    50% { opacity: 0.3; transform: scale(0.8); box-shadow: 0 0 14px #a3e635; }
                }
                .wf-node-pulsing {
                    animation: none !important;
                }
                .wf-node-pulsing rect,
                .wf-rect-pulsing,
                rect.wf-rect-pulsing {
                    animation: wfNodePulsingGlow 0.85s infinite ease-in-out !important;
                }
                .wf-status-dot-pulsing {
                    background: #a3e635 !important;
                    animation: wfDotBlink 0.75s infinite ease-in-out !important;
                }
            </style>
            <div class="workflow-diagram-card">
                <div class="workflow-header-strip">
                    <div class="workflow-status-badge">
                        <span class="wf-status-dot"></span>
                        <span class="wf-status-text" id="wf-status-indicator">PIPELINE READY</span>
                    </div>
                    <button class="wf-test-flow-btn" onclick="window.workflowDiagramInstance?.testPipelineFlow()" title="Chạy mô phỏng luồng Pipeline">
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                        <span>Demo Flow</span>
                    </button>
                </div>
                <svg class="workflow-svg-viewport" viewBox="0 0 960 410" preserveAspectRatio="xMidYMid meet">
                    <defs>
                        <!-- Arrow Markers -->
                        <marker id="wf-arrow-gray" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                            <path d="M0,0 L6,3 L0,6 Z" fill="#475569" />
                        </marker>
                        <marker id="wf-arrow-green" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                            <path d="M0,0 L6,3 L0,6 Z" fill="#76b900" />
                        </marker>
                        <marker id="wf-arrow-orange" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                            <path d="M0,0 L6,3 L0,6 Z" fill="#f97316" />
                        </marker>
                        <marker id="wf-arrow-purple" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                            <path d="M0,0 L6,3 L0,6 Z" fill="#c084fc" />
                        </marker>
                        <marker id="wf-arrow-pink" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                            <path d="M0,0 L6,3 L0,6 Z" fill="#f43f5e" />
                        </marker>
                        <marker id="wf-arrow-cyan" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                            <path d="M0,0 L6,3 L0,6 Z" fill="#38bdf8" />
                        </marker>

                        <!-- Subtle Card Shadow -->
                        <filter id="wf-node-shadow" x="-10%" y="-10%" width="120%" height="120%">
                            <feDropShadow dx="0" dy="3" stdDeviation="4" flood-color="#000000" flood-opacity="0.45" />
                        </filter>

                        <!-- Neon Green Active Glow Filter -->
                        <filter id="wf-node-glow-green" x="-30%" y="-30%" width="160%" height="160%">
                            <feDropShadow dx="0" dy="0" stdDeviation="6" flood-color="#76b900" flood-opacity="0.9" />
                        </filter>

                        <!-- Subtle Blue Glow for Video Agent -->
                        <filter id="wf-node-glow-blue" x="-20%" y="-20%" width="140%" height="140%">
                            <feDropShadow dx="0" dy="0" stdDeviation="5" flood-color="#3b82f6" flood-opacity="0.6" />
                        </filter>
                    </defs>

                    <!-- Connector Paths with explicit IDs for dynamic animation -->
                    <g class="wf-connectors">
                        <!-- Query -> Video Agent -->
                        <path id="conn-query-agent" d="M140,215 L195,215" stroke="#475569" stroke-width="1.8" fill="none" marker-end="url(#wf-arrow-gray)" />

                        <!-- Video Agent -> LLM (Up) -->
                        <path id="conn-agent-llm" d="M265,180 L265,110" stroke="#475569" stroke-width="1.8" fill="none" marker-end="url(#wf-arrow-gray)" />

                        <!-- Video Agent -> Attributes curve -->
                        <path id="conn-agent-attrs" d="M335,200 C375,200 405,120 465,120" stroke="#475569" stroke-width="1.8" fill="none" marker-end="url(#wf-arrow-orange)" />

                        <!-- Video Agent -> Actions straight -->
                        <path id="conn-agent-actions" d="M335,215 L465,215" stroke="#475569" stroke-width="1.8" fill="none" marker-end="url(#wf-arrow-purple)" />

                        <!-- Video Agent -> VIOS curve -->
                        <path id="conn-agent-vios" d="M335,230 C375,230 405,310 465,310" stroke="#475569" stroke-width="1.8" fill="none" marker-end="url(#wf-arrow-pink)" />

                        <!-- VIOS -> VLM -->
                        <path id="conn-vios-vlm" d="M575,310 L645,310" stroke="#475569" stroke-width="1.8" fill="none" marker-end="url(#wf-arrow-gray)" />

                        <!-- Attributes -> Elasticsearch curve -->
                        <path id="conn-attrs-es" d="M575,120 C610,120 620,205 645,205" stroke="#475569" stroke-width="1.8" fill="none" marker-end="url(#wf-arrow-gray)" />

                        <!-- Actions -> Elasticsearch straight -->
                        <path id="conn-actions-es" d="M575,215 L645,215" stroke="#475569" stroke-width="1.8" fill="none" marker-end="url(#wf-arrow-gray)" />

                        <!-- VLM -> Elasticsearch curve loop -->
                        <path id="conn-vlm-es" d="M755,310 C785,310 785,245 755,225" stroke="#475569" stroke-width="1.5" stroke-dasharray="4 3" fill="none" />

                        <!-- Elasticsearch -> Output -->
                        <path id="conn-es-out" d="M755,215 L820,215" stroke="#475569" stroke-width="1.8" fill="none" marker-end="url(#wf-arrow-cyan)" />
                    </g>

                    <!-- Path Labels -->
                    <g class="wf-labels" text-anchor="middle" font-size="11" font-family="'Inter', system-ui, sans-serif" font-weight="500">
                        <text x="405" y="112" fill="#f97316">Attributes</text>
                        <text x="405" y="126" fill="#94a3b8" font-size="9">(Search)</text>

                        <text x="405" y="208" fill="#c084fc">Actions</text>
                        <text x="405" y="222" fill="#94a3b8" font-size="9">(Search)</text>

                        <text x="405" y="298" fill="#f43f5e">Critique /</text>
                        <text x="405" y="312" fill="#f43f5e" font-size="9.5">Video Understanding</text>
                    </g>

                    <!-- Nodes -->
                    <!-- 1. Query -->
                    <g class="wf-node" id="node-query" transform="translate(45, 182)" filter="url(#wf-node-shadow)">
                        <rect width="95" height="66" rx="8" fill="#131926" stroke="#26334a" stroke-width="1.5" />
                        <text x="47.5" y="31" text-anchor="middle" fill="#f1f5f9" font-size="13" font-weight="600" font-family="'Inter', sans-serif">Query</text>
                        <text x="47.5" y="48" text-anchor="middle" fill="#94a3b8" font-size="10" font-family="'Inter', sans-serif">User Input</text>
                    </g>

                    <!-- 2. Video Agent -->
                    <g class="wf-node" id="node-video-agent" transform="translate(195, 178)" filter="url(#wf-node-shadow)">
                        <rect width="140" height="74" rx="8" fill="#151d2c" stroke="#3b82f6" stroke-width="1.8" />
                        <text x="70" y="33" text-anchor="middle" fill="#ffffff" font-size="14" font-weight="700" font-family="'Inter', sans-serif">Video Agent</text>
                        <text x="70" y="52" text-anchor="middle" fill="#4ade80" font-size="10.5" font-weight="600" font-family="'Inter', sans-serif">Plan → Act → Reflect</text>
                    </g>

                    <!-- 3. LLM (Planning / Reasoning) -->
                    <g class="wf-node" id="node-llm" transform="translate(205, 42)" filter="url(#wf-node-shadow)">
                        <rect width="120" height="66" rx="8" fill="#131926" stroke="#26334a" stroke-width="1.5" />
                        <text x="60" y="24" text-anchor="middle" fill="#f1f5f9" font-size="12" font-weight="700" font-family="'Inter', sans-serif">LLM</text>
                        <text x="60" y="40" text-anchor="middle" fill="#94a3b8" font-size="9.5" font-family="'Inter', sans-serif">Qwen 3.8-27B</text>
                        <text x="60" y="54" text-anchor="middle" fill="#84cc16" font-size="9" font-weight="600" font-family="'Inter', sans-serif">Server 4x H200</text>
                    </g>

                    <!-- 4. Attributes -->
                    <g class="wf-node" id="node-attributes" transform="translate(465, 87)" filter="url(#wf-node-shadow)">
                        <rect width="110" height="66" rx="8" fill="#131926" stroke="#26334a" stroke-width="1.5" />
                        <text x="55" y="26" text-anchor="middle" fill="#f1f5f9" font-size="13" font-weight="600" font-family="'Inter', sans-serif">Attributes</text>
                        <text x="55" y="42" text-anchor="middle" fill="#94a3b8" font-size="10" font-family="'Inter', sans-serif">C-RADIO</text>
                        <text x="55" y="55" text-anchor="middle" fill="#f97316" font-size="10" font-weight="600" font-family="'Inter', sans-serif">SigLIP2</text>
                    </g>

                    <!-- 5. Actions (Dense Frames) -->
                    <g class="wf-node" id="node-actions" transform="translate(465, 182)" filter="url(#wf-node-shadow)">
                        <rect width="110" height="66" rx="8" fill="#131926" stroke="#26334a" stroke-width="1.5" />
                        <text x="55" y="25" text-anchor="middle" fill="#f1f5f9" font-size="12.5" font-weight="600" font-family="'Inter', sans-serif">Actions</text>
                        <text x="55" y="41" text-anchor="middle" fill="#94a3b8" font-size="9.5" font-family="'Inter', sans-serif">Dense Frames</text>
                        <text x="55" y="54" text-anchor="middle" fill="#c084fc" font-size="9.5" font-weight="600" font-family="'Inter', sans-serif">32 Frames / Clip</text>
                    </g>

                    <!-- 6. VIOS (Video Storage & Clip Retrieval) -->
                    <g class="wf-node" id="node-vios" transform="translate(465, 277)" filter="url(#wf-node-shadow)">
                        <rect width="110" height="66" rx="8" fill="#131926" stroke="#26334a" stroke-width="1.5" />
                        <text x="55" y="26" text-anchor="middle" fill="#f1f5f9" font-size="13" font-weight="600" font-family="'Inter', sans-serif">VIOS</text>
                        <text x="55" y="41" text-anchor="middle" fill="#94a3b8" font-size="9" font-family="'Inter', sans-serif">Video IO & Storage</text>
                        <text x="55" y="54" text-anchor="middle" fill="#94a3b8" font-size="9" font-family="'Inter', sans-serif">Clip Retrieval</text>
                    </g>

                    <!-- 7. VLM (Qwen 3.8-27B 4x H200 Vision Critic) -->
                    <g class="wf-node" id="node-vlm" transform="translate(645, 277)" filter="url(#wf-node-shadow)">
                        <rect width="110" height="66" rx="8" fill="#131926" stroke="#26334a" stroke-width="1.5" />
                        <text x="55" y="24" text-anchor="middle" fill="#f1f5f9" font-size="12.5" font-weight="700" font-family="'Inter', sans-serif">VLM</text>
                        <text x="55" y="40" text-anchor="middle" fill="#94a3b8" font-size="9.5" font-family="'Inter', sans-serif">Qwen 3.8-27B</text>
                        <text x="55" y="54" text-anchor="middle" fill="#f43f5e" font-size="9" font-weight="600" font-family="'Inter', sans-serif">Server 4x H200</text>
                    </g>

                    <!-- 8. Elasticsearch / DB -->
                    <g class="wf-node" id="node-elasticsearch" transform="translate(645, 178)" filter="url(#wf-node-shadow)">
                        <rect width="110" height="74" rx="8" fill="#131926" stroke="#26334a" stroke-width="1.5" />
                        <text x="55" y="27" text-anchor="middle" fill="#f1f5f9" font-size="12.5" font-weight="600" font-family="'Inter', sans-serif">Elasticsearch</text>
                        <text x="55" y="44" text-anchor="middle" fill="#94a3b8" font-size="10" font-family="'Inter', sans-serif">KNN Search</text>
                        <text x="55" y="58" text-anchor="middle" fill="#38bdf8" font-size="10" font-weight="600" font-family="'Inter', sans-serif">Vector DB</text>
                    </g>

                    <!-- 9. Output -->
                    <g class="wf-node" id="node-output" transform="translate(820, 185)" filter="url(#wf-node-shadow)">
                        <rect width="90" height="60" rx="8" fill="#131926" stroke="#26334a" stroke-width="1.5" />
                        <text x="45" y="28" text-anchor="middle" fill="#f1f5f9" font-size="13" font-weight="600" font-family="'Inter', sans-serif">Output</text>
                        <text x="45" y="45" text-anchor="middle" fill="#38bdf8" font-size="10" font-weight="600" font-family="'Inter', sans-serif">Results</text>
                    </g>
                </svg>
            </div>
        `;
    }

    attachInteractions() {
        if (!this.container) return;
        const nodes = this.container.querySelectorAll('.wf-node');
        nodes.forEach(n => {
            n.addEventListener('click', () => {
                this.highlightNode(n.id);
                this.updateStatusText(`INSPECT: ${n.id.replace('node-', '').toUpperCase()}`);
            });
        });
    }

    updateStatusText(text, isGreen = true, isError = false) {
        const ind = this.container?.querySelector('#wf-status-indicator');
        const dot = this.container?.querySelector('.wf-status-dot');
        if (ind) ind.innerText = text;
        if (dot) {
            if (isError) {
                dot.style.backgroundColor = '#ef4444';
                dot.style.boxShadow = '0 0 6px #ef4444';
            } else if (isGreen) {
                dot.style.backgroundColor = '#76b900';
                dot.style.boxShadow = '0 0 6px #76b900';
            } else {
                dot.style.backgroundColor = '#38bdf8';
                dot.style.boxShadow = '0 0 6px #38bdf8';
            }
        }
    }

    /**
     * Set exact pipeline stage in real-time synchronization with actual backend operations.
     * @param {string} stage - 'ready' | 'query' | 'agent_planning' | 'llm_reasoning' | 'search_retrieval' | 'critic_eval' | 'vios' | 'vlm_dense_frames' | 'output' | 'error'
     * @param {string} customStatus - Custom Vietnamese status text
     * @param {boolean} isPulsing - Whether the main node should pulse continuously (for long-running operations)
     */
    setStage(stage, customStatus = '', isPulsing = false) {
        if (!this.container) return;

        if (this._autoResetTimer) {
            clearTimeout(this._autoResetTimer);
            this._autoResetTimer = null;
        }

        const dot = this.container.querySelector('.wf-status-dot');
        if (dot) {
            if (isPulsing || ['llm_reasoning', 'vlm_dense_frames'].includes(stage)) {
                dot.classList.add('wf-status-dot-pulsing');
            } else {
                dot.classList.remove('wf-status-dot-pulsing');
            }
        }

        switch (stage) {
            case 'ready':
            case 'idle':
                this.resetState();
                this.updateStatusText('PIPELINE READY');
                break;

            case 'query':
                this.highlightStage(['node-query'], [], false);
                this.updateStatusText(customStatus || 'BƯỚC 1: TIẾP NHẬN TRUY VẤN (QUERY)');
                break;

            case 'agent_planning':
                this.highlightStage(['node-video-agent'], ['conn-query-agent'], false);
                this.updateStatusText(customStatus || 'BƯỚC 2: VIDEO AGENT LẬP KẾ HOẠCH (PLANNING)');
                break;

            case 'llm_reasoning':
                // LLM active on Server 4x H200 (pulsing while request is in-flight)
                this.highlightStage(['node-video-agent', 'node-llm'], ['conn-query-agent', 'conn-agent-llm'], isPulsing, 'node-llm');
                this.updateStatusText(customStatus || 'BƯỚC 3: SERVER 4x H200 (QWEN 3.8-27B) ĐANG SUY LUẬN...');
                break;

            case 'search_retrieval':
                // Parallel search: Attributes, Actions, VIOS
                this.highlightStage(
                    ['node-video-agent', 'node-attributes', 'node-actions', 'node-vios'],
                    ['conn-query-agent', 'conn-agent-attrs', 'conn-agent-actions', 'conn-agent-vios'],
                    false
                );
                this.updateStatusText(customStatus || 'BƯỚC 3: TRUY XUẤT CSDL VIDEO, ACTIONS & VIOS CLIPS...');
                break;

            case 'critic_eval':
                // Elasticsearch KNN + VLM Critic verification
                this.highlightStage(
                    ['node-elasticsearch', 'node-vlm'],
                    ['conn-attrs-es', 'conn-actions-es', 'conn-vios-vlm', 'conn-vlm-es'],
                    false
                );
                this.updateStatusText(customStatus || 'BƯỚC 4: CRITIC AGENT XÁC MINH CLIPS (VLM)...');
                break;

            case 'vios':
                // Extracting clip files
                this.highlightStage(['node-vios'], ['conn-agent-vios'], false);
                this.updateStatusText(customStatus || 'BƯỚC 1: VIOS CẮT 32 FRAMES TỪ CLIP...');
                break;

            case 'vlm_dense_frames':
                // Multimodal dense frame analysis on Server 4x H200
                this.highlightStage(['node-video-agent', 'node-vios', 'node-vlm'], ['conn-agent-vios', 'conn-vios-vlm'], isPulsing, 'node-vlm');
                this.updateStatusText(customStatus || 'BƯỚC 2: SERVER 4x H200 PHÂN TÍCH 32 FRAMES THỊ GIÁC...');
                break;

            case 'output':
                this.highlightStage(['node-output'], ['conn-es-out'], false);
                this.updateStatusText(customStatus || 'HOÀN TẤT KẾT QUẢ (OUTPUT)');
                // Auto reset to ready after 4s
                this._autoResetTimer = setTimeout(() => {
                    this.setStage('ready');
                }, 4000);
                break;

            case 'error':
                this.resetState(false);
                this.updateStatusText(customStatus || 'LỖI TIẾN TRÌNH (ERROR)', false, true);
                break;

            default:
                break;
        }
    }

    /**
     * Internal stage highlighter
     */
    highlightStage(nodeIds = [], connIds = [], isPulsing = false, pulseNodeId = null) {
        if (!this.container) return;

        // Reset previous highlights to base style
        this.resetState(false);

        // Highlight active nodes
        nodeIds.forEach(nid => {
            const target = this.container.querySelector(`#${nid}`);
            if (target) {
                target.setAttribute('filter', 'url(#wf-node-glow-green)');
                const rect = target.querySelector('rect');
                if (rect) {
                    rect.setAttribute('stroke', '#76b900');
                    rect.setAttribute('stroke-width', '2.5');
                }
                if (isPulsing && (nid === pulseNodeId || !pulseNodeId)) {
                    target.classList.add('wf-node-pulsing');
                    if (rect) rect.classList.add('wf-rect-pulsing');
                }
            }
        });

        // Highlight active connectors
        connIds.forEach(cid => {
            const conn = this.container.querySelector(`#${cid}`);
            if (conn) {
                conn.setAttribute('stroke', '#76b900');
                conn.setAttribute('stroke-width', '2.6');
                conn.setAttribute('marker-end', 'url(#wf-arrow-green)');
            }
        });
    }

    highlightNode(nodeId) {
        if (!this.container) return;
        this.resetState(false);
        if (!nodeId) return;

        const target = this.container.querySelector(`#${nodeId}`);
        if (target) {
            target.setAttribute('filter', 'url(#wf-node-glow-green)');
            const rect = target.querySelector('rect');
            if (rect) {
                rect.setAttribute('stroke', '#76b900');
                rect.setAttribute('stroke-width', '2.5');
            }
        }
    }

    resetState(resetText = true) {
        if (!this.container) return;

        const dot = this.container.querySelector('.wf-status-dot');
        if (dot) dot.classList.remove('wf-status-dot-pulsing');

        // Reset all nodes
        const nodes = this.container.querySelectorAll('.wf-node');
        nodes.forEach(n => {
            n.classList.remove('wf-node-pulsing');
            n.setAttribute('filter', 'url(#wf-node-shadow)');
            const rect = n.querySelector('rect');
            if (rect) {
                rect.classList.remove('wf-rect-pulsing');
                if (n.id === 'node-video-agent') {
                    rect.setAttribute('stroke', '#3b82f6');
                    rect.setAttribute('stroke-width', '1.8');
                } else {
                    rect.setAttribute('stroke', '#26334a');
                    rect.setAttribute('stroke-width', '1.5');
                }
            }
        });

        // Reset all connectors
        const conns = this.container.querySelectorAll('.wf-connectors path');
        conns.forEach(c => {
            c.setAttribute('stroke', '#475569');
            c.setAttribute('stroke-width', '1.8');
            if (c.id === 'conn-agent-attrs') c.setAttribute('marker-end', 'url(#wf-arrow-orange)');
            else if (c.id === 'conn-agent-actions') c.setAttribute('marker-end', 'url(#wf-arrow-purple)');
            else if (c.id === 'conn-agent-vios') c.setAttribute('marker-end', 'url(#wf-arrow-pink)');
            else if (c.id === 'conn-es-out') c.setAttribute('marker-end', 'url(#wf-arrow-cyan)');
            else c.setAttribute('marker-end', 'url(#wf-arrow-gray)');
        });
    }

    /**
     * Backward-compatible manual demo test flow (only triggered when user clicks Demo Flow button)
     */
    testPipelineFlow() {
        this.setStage('query', 'DEMO 1: TIẾP NHẬN TRUY VẤN');
        setTimeout(() => this.setStage('agent_planning', 'DEMO 2: VIDEO AGENT ĐIỀU PHỐI'), 600);
        setTimeout(() => this.setStage('search_retrieval', 'DEMO 3: TRUY XUẤT THUỘC TÍNH & CLIP'), 1300);
        setTimeout(() => this.setStage('critic_eval', 'DEMO 4: CRITIC AGENT ĐÁNH GIÁ'), 2100);
        setTimeout(() => this.setStage('output', 'DEMO 5: KẾT QUẢ SẴN SÀNG'), 2900);
    }
}

window.WorkflowDiagram = WorkflowDiagram;
