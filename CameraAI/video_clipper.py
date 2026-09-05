import subprocess
import os
from urllib.parse import quote
from datetime import datetime, timedelta
import cv2
import numpy as np

import config
from clip_storage import resolve_clip_path


def _remove_partial_clip(output_path: str) -> None:
    """Remove an incomplete FFmpeg output after a failed production capture."""
    try:
        if os.path.exists(output_path):
            os.remove(output_path)
    except OSError as exc:
        print(f"[VideoClipper Warning] Could not remove partial clip {output_path}: {exc}")


def _has_expected_duration(output_path: str) -> bool:
    """Reject truncated NVR playback responses instead of serving a short clip."""
    try:
        result = subprocess.run(
            [
                config.FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", output_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        duration = float(result.stdout.strip()) if result.returncode == 0 else 0.0
        return duration >= max(0.0, config.CLIP_DURATION_SEC - 0.5)
    except (OSError, subprocess.SubprocessError, ValueError):
        return False

def generate_synthetic_anomaly_clip(
    output_path: str,
    channel: int,
    event_type: str,
    event_code: str,
    timestamp_str: str,
    duration_sec: int = 10
):
    """
    Generates a 10-second synthetic video clip with dynamic overlays, bounding boxes,
    and audio decibel waveform indicator encoded in H.264 (AVC) MP4 format for full HTML5 browser compatibility.
    """
    width, height = 864, 480
    fps = 25
    total_frames = duration_sec * fps
    
    # Try using imageio with bundled FFmpeg for genuine H.264 mp4
    writer = None
    cv_out = None
    use_imageio = False
    
    try:
        import imageio
        writer = imageio.get_writer(
            output_path,
            fps=fps,
            format='FFMPEG',
            mode='I',
            codec='libx264',
            pixelformat='yuv420p',
            macro_block_size=16
        )
        use_imageio = True
    except Exception as e:
        print(f"[VideoClipper] imageio FFmpeg writer failed: {e}, falling back to cv2.VideoWriter")
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        cv_out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        use_imageio = False

    # Random seed based on output_path for visual consistency
    np.random.seed(abs(hash(output_path)) % (2**32))
    bg_color = (20, 24, 33)
    
    is_audio = "audio" in str(event_type).lower() or "sound" in str(event_code).lower()
    
    for frame_idx in range(total_frames):
        frame = np.full((height, width, 3), bg_color, dtype=np.uint8)
        
        # Grid lines
        for x in range(0, width, 80):
            cv2.line(frame, (x, 0), (x, height), (35, 42, 54), 1)
        for y in range(0, height, 60):
            cv2.line(frame, (0, y), (width, y), (35, 42, 54), 1)
            
        t_sec = frame_idx / fps
        
        # HUD overlay header
        cv2.rectangle(frame, (0, 0), (width, 40), (10, 12, 18), -1)
        hud_text = f"CAM {channel:02d} | DHI-NVR5832-EI2 ({config.NVR_HOST}) | {timestamp_str}"
        cv2.putText(frame, hud_text, (15, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 200), 1, cv2.LINE_AA)
        
        # REC Indicator
        if (frame_idx // 12) % 2 == 0:
            cv2.circle(frame, (width - 30, 20), 8, (0, 0, 255), -1)
        cv2.putText(frame, "REC 10s EVENT CLIP", (width - 180, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        
        if is_audio:
            # Sound Waveform
            cv2.rectangle(frame, (50, 120), (width - 50, 360), (30, 35, 48), -1)
            cv2.rectangle(frame, (50, 120), (width - 50, 360), (255, 60, 60), 2)
            
            center_y = 240
            wave_color = (0, 165, 255) if frame_idx < total_frames/2 else (0, 0, 255)
            
            num_bars = 40
            bar_w = (width - 140) // num_bars
            for b in range(num_bars):
                dist_from_apex = abs(t_sec - 5.0)
                intensity = max(0.1, 1.0 - (dist_from_apex / 4.0))
                noise = np.sin(frame_idx * 0.2 + b * 0.5) * np.cos(b * 0.3)
                h_bar = int(abs(noise) * 100 * intensity + 10)
                
                bx = 70 + b * bar_w
                cv2.rectangle(frame, (bx, center_y - h_bar), (bx + bar_w - 4, center_y + h_bar), wave_color, -1)
                
            db_level = int(75 + 25 * max(0, 1.0 - abs(t_sec - 5.0)/3.0) + np.random.randint(-3, 3))
            cv2.putText(frame, f"AUDIO ANOMALY DETECTED: {event_code} ({db_level} dB)", (65, 155), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
            cv2.putText(frame, f"NVR Internet Stream ({config.NVR_HOST}:{config.RTSP_PORT})", (65, 340), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
        else:
            progress = frame_idx / total_frames
            bx = int(100 + progress * (width - 300))
            by = int(180 + np.sin(progress * np.pi * 2) * 30)
            bw, bh = 120, 200
            
            box_color = (0, 0, 255) if (frame_idx // 6) % 2 == 0 else (0, 165, 255)
            cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), box_color, 2)
            
            cv2.rectangle(frame, (bx, by - 25), (bx + bw, by), box_color, -1)
            cv2.putText(frame, f"{event_code} 98.4%", (bx + 5, by - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
            
            zone_pts = np.array([[80, 150], [width-80, 150], [width-100, height-60], [100, height-60]], np.int32)
            cv2.polylines(frame, [zone_pts], isClosed=True, color=(0, 255, 255), thickness=1)
            cv2.putText(frame, f"INTERNET NVR ZONE - {config.NVR_HOST}", (120, 175), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
            
        cv2.putText(frame, f"Dahua WizMind AI - RTSP Internet Playback Buffer ({config.NVR_HOST})", (15, height - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (120, 140, 160), 1, cv2.LINE_AA)
        
        if use_imageio and writer is not None:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            writer.append_data(rgb_frame)
        elif cv_out is not None:
            cv_out.write(frame)
        
    if use_imageio and writer is not None:
        writer.close()
    elif cv_out is not None:
        cv_out.release()

def clip_event_video(
    channel: int,
    event_timestamp: datetime,
    output_filename: str,
    event_type: str = "video_anomaly",
    event_code: str = "Intrusion"
) -> str | None:
    """
    Extracts a 10-second MP4 video clip from Dahua NVR RTSP playback stream over WAN/Internet.
    """
    full_output_path = str(resolve_clip_path(output_filename))
    os.makedirs(os.path.dirname(full_output_path), exist_ok=True)
    
    start_time = event_timestamp - timedelta(seconds=config.PRE_BUFFER_SEC)
    end_time = event_timestamp + timedelta(seconds=config.POST_BUFFER_SEC)
    
    start_str = start_time.strftime("%Y_%m_%d_%H_%M_%S")
    end_str = end_time.strftime("%Y_%m_%d_%H_%M_%S")
    timestamp_display = event_timestamp.strftime("%Y-%m-%d %H:%M:%S")
    
    rtsp_user = quote(str(config.NVR_USER), safe="")
    rtsp_password = quote(str(config.NVR_PASSWORD), safe="")
    rtsp_url = (
        f"rtsp://{rtsp_user}:{rtsp_password}@{config.NVR_HOST}:{config.RTSP_PORT}"
        f"/cam/playback?channel={channel}&starttime={start_str}&endtime={end_str}"
    )
    
    if config.DEMO_MODE:
        generate_synthetic_anomaly_clip(
            full_output_path, channel, event_type, event_code, timestamp_display, duration_sec=config.CLIP_DURATION_SEC
        )
        return output_filename

    cmd = [
        config.FFMPEG_PATH,
        "-y",
        "-rtsp_transport", "tcp",
        "-fflags", "+genpts",
        "-i", rtsp_url,
        "-t", str(config.CLIP_DURATION_SEC),
        "-c:v", "libx264",
        "-c:a", "aac",
        "-preset", "ultrafast",
        "-movflags", "+faststart",
        full_output_path
    ]
    
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
        if res.returncode == 0 and os.path.exists(full_output_path) and _has_expected_duration(full_output_path):
            return output_filename
        print(
            "[FFmpeg Warning] WAN/RTSP clip extraction failed, timed out, or returned a short clip; "
            "no incomplete clip will be stored in production."
        )
        _remove_partial_clip(full_output_path)
        return None
    except Exception as e:
        print(f"[FFmpeg Exception] {e}. No clip will be stored in production.")
        _remove_partial_clip(full_output_path)
        return None
