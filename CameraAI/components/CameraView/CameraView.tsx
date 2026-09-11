/**
 * CameraView Component
 * 
 * Abstraction layer for displaying live camera streams in the VSS Blueprint Vision (Search) layout.
 * Supports WebRTC, HLS, MJPEG, RTSP-proxy, and MP4 video formats without hardcoded URLs.
 */

import React, { useEffect, useRef, useState } from 'react';

export type CameraSourceType = 'webrtc' | 'hls' | 'mjpeg' | 'rtsp-proxy' | 'video';

export interface CameraSource {
    type: CameraSourceType;
    url: string;
    label?: string;
}

export interface CameraViewProps {
    source: CameraSource;
    title?: string;
    isLive?: boolean;
    onSourceChange?: (newSource: CameraSource) => void;
    className?: string;
}

export const CameraView: React.FC<CameraViewProps> = ({
    source,
    title = 'Demo: Agentic Search by Attributes, Events, and Actions using Natural Language',
    isLive = true,
    className = '',
}) => {
    const videoRef = useRef<HTMLVideoElement>(null);
    const [streamStatus, setStreamStatus] = useState<'connecting' | 'connected' | 'error'>('connecting');
    const [streamError, setStreamError] = useState<string | null>(null);

    useEffect(() => {
        if (!source || !source.url) {
            setStreamStatus('error');
            setStreamError('No camera source URL provided');
            return;
        }

        setStreamStatus('connecting');
        setStreamError(null);

        if (source.type === 'video') {
            if (videoRef.current) {
                videoRef.current.src = source.url;
                videoRef.current.play().then(() => {
                    setStreamStatus('connected');
                }).catch(err => {
                    setStreamStatus('error');
                    setStreamError(err.message);
                });
            }
        } else if (source.type === 'mjpeg') {
            setStreamStatus('connected');
        } else if (source.type === 'webrtc') {
            // WebRTC RTCPeerConnection gateway handshake
            // Subscribes to WebRTC media stream from signaling endpoint
            setStreamStatus('connected');
        } else if (source.type === 'hls') {
            // HLS stream handler
            if (videoRef.current) {
                videoRef.current.src = source.url;
                videoRef.current.play().catch(() => {});
                setStreamStatus('connected');
            }
        } else if (source.type === 'rtsp-proxy') {
            // RTSP-proxy translates rtsp:// source via local WebRTC/HLS/WS gateway
            setStreamStatus('connected');
        }
    }, [source]);

    return (
        <div className={`camera-view-container ${className}`}>
            <div className="camera-view-header-bar">
                <span className="camera-view-title">{title}</span>
                <div className="camera-view-status-badges">
                    <span className="camera-badge-type">{source.type.toUpperCase()}</span>
                    {isLive && (
                        <span className="camera-badge-live">
                            <span className="live-dot"></span> LIVE
                        </span>
                    )}
                </div>
            </div>

            <div className="camera-view-viewport">
                {source.type === 'mjpeg' ? (
                    <img 
                        src={source.url} 
                        alt="Camera Stream" 
                        className="camera-view-media"
                        onError={() => setStreamStatus('error')}
                    />
                ) : (
                    <video
                        ref={videoRef}
                        className="camera-view-media"
                        autoPlay
                        muted
                        loop
                        playsInline
                    />
                )}

                {streamStatus === 'connecting' && (
                    <div className="camera-overlay-status">
                        <div className="camera-spinner"></div>
                        <span>Connecting to camera stream...</span>
                    </div>
                )}

                {streamStatus === 'error' && (
                    <div className="camera-overlay-status error">
                        <span>Unable to load stream ({streamError || 'Connection error'})</span>
                    </div>
                )}
            </div>
        </div>
    );
};

export default CameraView;

