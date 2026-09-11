# Dockerfile for CameraAI (Dahua NVR AI Summarizer & Search Studio)
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Ho_Chi_Minh \
    ADMIN_DATABASE_USERNAME=admin \
    ADMIN_DATABASE_PASSWORD=namcantho@168 \
    QWEN_SERVER_URL=https://llm.ttpmsandbox.us.kg/v1 \
    QWEN_API_KEY="" \
    QWEN_MODEL_NAME=Qwen3.8-27B \
    DENSE_FRAMES_COUNT=8 \
    MAX_VLM_FRAMES=8 \
    INTERNAL_AUDIO_SERVER_URL=https://llm.ttpmsandbox.us.kg/v1/audio \
    INTERNAL_AUDIO_SERVER_API_KEY="" \
    INTERNAL_AUDIO_MODEL_NAME="Internal Audio AI (Server H200)" \
    USE_DEEPFILTER=true

# Install system dependencies:
# - ffmpeg / ffprobe for RTSP capture, video clipping & audio extraction
# - libgl1, libglib2.0-0 for OpenCV headless
# - curl for container health checks
# - tzdata for Asia/Ho_Chi_Minh timezone
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    curl \
    tzdata \
    && ln -fs /usr/share/zoneinfo/$TZ /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python packages first for optimal Docker layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -U pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . /app/

# Ensure storage directories exist
RUN mkdir -p /app/storage/clips

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/search || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

