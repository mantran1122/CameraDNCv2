/**
 * WorkflowDiagram Component
 * 
 * Renders the exact NVIDIA VSS Blueprint Agentic Search Architecture & Workflow Diagram
 * matching media_1788859433087.png:
 * Query -> Video Agent (LLM, Attributes, Actions, VIOS, VLM) -> Elasticsearch -> Output
 */

import React from 'react';

export interface WorkflowDiagramProps {
    activeNodeId?: string;
    isProcessing?: boolean;
    className?: string;
}

export const WorkflowDiagram: React.FC<WorkflowDiagramProps> = ({
    activeNodeId,
    isProcessing = false,
    className = '',
}) => {
    return (
        <div className={`workflow-diagram-container ${className}`}>
            <svg 
                className="workflow-diagram-svg" 
                viewBox="0 0 960 440" 
                preserveAspectRatio="xMidYMid meet"
            >
                <defs>
                    <!-- Marker for arrows -->
                    <marker id="arrow-gray" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                        <path d="M0,0 L6,3 L0,6 Z" fill="#475569" />
                    </marker>
                    <marker id="arrow-green" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                        <path d="M0,0 L6,3 L0,6 Z" fill="#76b900" />
                    </marker>
                    <marker id="arrow-orange" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                        <path d="M0,0 L6,3 L0,6 Z" fill="#f97316" />
                    </marker>
                    <marker id="arrow-purple" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                        <path d="M0,0 L6,3 L0,6 Z" fill="#c084fc" />
                    </marker>
                    <marker id="arrow-pink" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                        <path d="M0,0 L6,3 L0,6 Z" fill="#f43f5e" />
                    </marker>
                    <marker id="arrow-cyan" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                        <path d="M0,0 L6,3 L0,6 Z" fill="#38bdf8" />
                    </marker>

                    <!-- Filter for node card glow -->
                    <filter id="node-shadow" x="-10%" y="-10%" width="120%" height="120%">
                        <feDropShadow dx="0" dy="4" stdDeviation="6" flood-color="#000000" flood-opacity="0.5" />
                    </filter>
                </defs>

                <!-- Flow Connections / Paths -->
                <g className="workflow-connectors">
                    <!-- Query -> Video Agent -->
                    <path d="M150,230 L200,230" stroke="#475569" strokeWidth="1.8" fill="none" markerEnd="url(#arrow-gray)" />

                    <!-- Video Agent -> LLM (Upwards) -->
                    <path d="M265,190 L265,115" stroke="#475569" strokeWidth="1.8" fill="none" markerEnd="url(#arrow-gray)" />

                    <!-- Video Agent -> Attributes (Search) curve -->
                    <path d="M335,215 C380,215 410,130 470,130" stroke="#475569" strokeWidth="1.8" fill="none" markerEnd="url(#arrow-orange)" />
                    <!-- Video Agent -> Actions (Search) straight -->
                    <path d="M335,230 L470,230" stroke="#475569" strokeWidth="1.8" fill="none" markerEnd="url(#arrow-purple)" />

                    <!-- Video Agent -> VIOS curve -->
                    <path d="M335,245 C380,245 410,335 470,335" stroke="#475569" strokeWidth="1.8" fill="none" markerEnd="url(#arrow-pink)" />

                    <!-- VIOS -> VLM -->
                    <path d="M580,335 L650,335" stroke="#475569" strokeWidth="1.8" fill="none" markerEnd="url(#arrow-gray)" />

                    <!-- Attributes -> Elasticsearch curve -->
                    <path d="M580,130 C615,130 625,220 650,220" stroke="#475569" strokeWidth="1.8" fill="none" markerEnd="url(#arrow-gray)" />

                    <!-- Actions -> Elasticsearch straight -->
                    <path d="M580,230 L650,230" stroke="#475569" strokeWidth="1.8" fill="none" markerEnd="url(#arrow-gray)" />

                    <!-- VLM -> Elasticsearch loop / output -->
                    <path d="M760,335 C790,335 790,260 760,240" stroke="#475569" strokeWidth="1.5" strokeDasharray="4 3" fill="none" />

                    <!-- Elasticsearch -> Output -->
                    <path d="M760,230 L825,230" stroke="#475569" strokeWidth="1.8" fill="none" markerEnd="url(#arrow-cyan)" />
                </g>

                <!-- Connecting Path Labels -->
                <g className="workflow-path-labels" textAnchor="middle" fontSize="11" fontFamily="Inter, sans-serif" fontWeight="500">
                    <text x="410" y="122" fill="#f97316">Attributes</text>
                    <text x="410" y="136" fill="#94a3b8" fontSize="9">(Search)</text>

                    <text x="410" y="222" fill="#c084fc">Actions</text>
                    <text x="410" y="236" fill="#94a3b8" fontSize="9">(Search)</text>

                    <text x="410" y="322" fill="#f43f5e">Critique /</text>
                    <text x="410" y="336" fill="#f43f5e" fontSize="10">Video Understanding</text>
                </g>

                <!-- Diagram Nodes -->
                <!-- 1. Query Node -->
                <g className="workflow-node" transform="translate(50, 195)" filter="url(#node-shadow)">
                    <rect width="100" height="70" rx="8" fill="#131926" stroke="#26334a" strokeWidth="1.5" />
                    <text x="50" y="32" textAnchor="middle" fill="#f1f5f9" fontSize="13" fontWeight="600" fontFamily="Inter, sans-serif">Query</text>
                    <text x="50" y="50" textAnchor="middle" fill="#94a3b8" fontSize="10" fontFamily="Inter, sans-serif">User Input</text>
                </g>

                <!-- 2. Video Agent Node -->
                <g className="workflow-node active" transform="translate(200, 190)" filter="url(#node-shadow)">
                    <rect width="135" height="80" rx="8" fill="#151d2c" stroke="#3b82f6" strokeWidth="1.8" />
                    <text x="67" y="34" textAnchor="middle" fill="#ffffff" fontSize="14" fontWeight="700" fontFamily="Inter, sans-serif">Video Agent</text>
                    <text x="67" y="54" textAnchor="middle" fill="#4ade80" fontSize="10.5" fontWeight="600" fontFamily="Inter, sans-serif">Plan → Act → Reflect</text>
                </g>

                <!-- 3. LLM (Planning) Node -->
                <g className="workflow-node" transform="translate(205, 45)" filter="url(#node-shadow)">
                    <rect width="125" height="70" rx="8" fill="#131926" stroke="#26334a" strokeWidth="1.5" />
                    <text x="62" y="28" textAnchor="middle" fill="#f1f5f9" fontSize="13" fontWeight="600" fontFamily="Inter, sans-serif">LLM</text>
                    <text x="62" y="44" textAnchor="middle" fill="#94a3b8" fontSize="10" fontFamily="Inter, sans-serif">Qwen 3.5</text>
                    <text x="62" y="58" textAnchor="middle" fill="#84cc16" fontSize="10" fontWeight="600" fontFamily="Inter, sans-serif">Planning</text>
                </g>

                <!-- 4. Attributes Node -->
                <g className="workflow-node" transform="translate(470, 95)" filter="url(#node-shadow)">
                    <rect width="110" height="70" rx="8" fill="#131926" stroke="#26334a" strokeWidth="1.5" />
                    <text x="55" y="28" textAnchor="middle" fill="#f1f5f9" fontSize="13" fontWeight="600" fontFamily="Inter, sans-serif">Attributes</text>
                    <text x="55" y="44" textAnchor="middle" fill="#94a3b8" fontSize="10" fontFamily="Inter, sans-serif">C-RADIO</text>
                    <text x="55" y="58" textAnchor="middle" fill="#f97316" fontSize="10" fontWeight="600" fontFamily="Inter, sans-serif">SigLIP2</text>
                </g>

                <!-- 5. Actions Node -->
                <g className="workflow-node" transform="translate(470, 195)" filter="url(#node-shadow)">
                    <rect width="110" height="70" rx="8" fill="#131926" stroke="#26334a" strokeWidth="1.5" />
                    <text x="55" y="28" textAnchor="middle" fill="#f1f5f9" fontSize="13" fontWeight="600" fontFamily="Inter, sans-serif">Actions</text>
                    <text x="55" y="44" textAnchor="middle" fill="#94a3b8" fontSize="10" fontFamily="Inter, sans-serif">Cosmos Embed</text>
                    <text x="55" y="58" textAnchor="middle" fill="#c084fc" fontSize="10" fontWeight="600" fontFamily="Inter, sans-serif">Vectorization</text>
                </g>

                <!-- 6. VIOS Node -->
                <g className="workflow-node" transform="translate(470, 300)" filter="url(#node-shadow)">
                    <rect width="110" height="70" rx="8" fill="#131926" stroke="#26334a" strokeWidth="1.5" />
                    <text x="55" y="28" textAnchor="middle" fill="#f1f5f9" fontSize="13" fontWeight="600" fontFamily="Inter, sans-serif">VIOS</text>
                    <text x="55" y="44" textAnchor="middle" fill="#94a3b8" fontSize="9.5" fontFamily="Inter, sans-serif">Video IO & Storage</text>
                    <text x="55" y="58" textAnchor="middle" fill="#94a3b8" fontSize="9.5" fontFamily="Inter, sans-serif">Clip Retrieval</text>
                </g>

                <!-- 7. VLM Node -->
                <g className="workflow-node" transform="translate(650, 300)" filter="url(#node-shadow)">
                    <rect width="110" height="70" rx="8" fill="#131926" stroke="#26334a" strokeWidth="1.5" />
                    <text x="55" y="28" textAnchor="middle" fill="#f1f5f9" fontSize="13" fontWeight="600" fontFamily="Inter, sans-serif">VLM</text>
                    <text x="55" y="44" textAnchor="middle" fill="#94a3b8" fontSize="10" fontFamily="Inter, sans-serif">Qwen 3.5</text>
                    <text x="55" y="58" textAnchor="middle" fill="#f43f5e" fontSize="10" fontWeight="600" fontFamily="Inter, sans-serif">Critique</text>
                </g>

                <!-- 8. Elasticsearch Node -->
                <g className="workflow-node" transform="translate(650, 192)" filter="url(#node-shadow)">
                    <rect width="110" height="76" rx="8" fill="#131926" stroke="#26334a" strokeWidth="1.5" />
                    <text x="55" y="28" textAnchor="middle" fill="#f1f5f9" fontSize="12.5" fontWeight="600" fontFamily="Inter, sans-serif">Elasticsearch</text>
                    <text x="55" y="46" textAnchor="middle" fill="#94a3b8" fontSize="10" fontFamily="Inter, sans-serif">KNN Search</text>
                    <text x="55" y="60" textAnchor="middle" fill="#38bdf8" fontSize="10" fontWeight="600" fontFamily="Inter, sans-serif">Vector DB</text>
                </g>

                <!-- 9. Output Node -->
                <g className="workflow-node" transform="translate(825, 198)" filter="url(#node-shadow)">
                    <rect width="95" height="65" rx="8" fill="#131926" stroke="#26334a" strokeWidth="1.5" />
                    <text x="47" y="30" textAnchor="middle" fill="#f1f5f9" fontSize="13" fontWeight="600" fontFamily="Inter, sans-serif">Output</text>
                    <text x="47" y="48" textAnchor="middle" fill="#38bdf8" fontSize="10" fontWeight="600" fontFamily="Inter, sans-serif">Results</text>
                </g>
            </svg>
        </div>
    );
};

export default WorkflowDiagram;

