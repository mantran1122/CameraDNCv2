# Camera AI v2

Camera AI v2 keeps the existing CameraAI and Cosmos model pipelines while
building a new three-column operator UI: camera/analysis flow, metadata search,
and an AI agent panel.

## What is included

- `CameraAI/`: FastAPI, Dahua/NVR metadata listener, event store, clip capture,
  audio and video workers.
- `cosmos_code_base/`: the existing Cosmos reasoning/search worker source.
- `docs/`: migration and product plan.
- `vendor/nvidia-video-search-and-summarization/`: exact NVIDIA VSS source,
  fixed to a known upstream commit and used as the UI base (Git submodule).

## Safety of local data

This repository deliberately excludes live camera configuration, credentials,
API keys, databases, generated clips, model weights and caches. Configure an
operator machine from `CameraAI/.env.example` or the local dashboard.

Read [the migration plan](docs/01_hom_nay/CAMERA_AI_V2_MIGRATION_PLAN.md)
before changing the model pipeline or adding the new UI.

## Clone with the NVIDIA UI source

```bash
git clone --recurse-submodules https://github.com/mantran1122/CameraDNCv2.git
# Existing checkout:
git submodule update --init --recursive
```

The VSS UI source remains under NVIDIA's upstream license and attribution.

# Synology File Station storage

CameraAI can use Synology File Station over HTTPS as the primary evidence-file
backend while keeping a local cache for FFmpeg and AI workers. Configure the
git-ignored `CameraAI/.env` file:

```dotenv
CAMERAAI_STORAGE_BACKEND=synology
CAMERAAI_CLIPS_DIR=storage/clips
CAMERAAI_SYNOLOGY_URL=https://nas.example:5001
CAMERAAI_SYNOLOGY_USERNAME=camera-service
CAMERAAI_SYNOLOGY_PASSWORD=change-me
CAMERAAI_SYNOLOGY_SHARE=Ai-Camera
CAMERAAI_SYNOLOGY_ROOT=CameraAI/clips
CAMERAAI_SYNOLOGY_VERIFY_TLS=true
```

New clips are captured into the cache and then uploaded to File Station. When
a clip is absent locally, `/clips/...` downloads it from Synology on demand.
Expired clips are removed from both locations. Use a trusted NAS certificate
and keep TLS verification enabled in production whenever possible.

## Run on a Windows LAN or routed private network

From `CameraAI`, run `Chay_Server_Windows.bat`. The application listens on all
network interfaces at port 8000. Other computers can then open:

```text
http://<IP-of-this-computer>:8000/login
```

The Windows firewall rule should allow inbound TCP 8000 only on Domain and
Private profiles. Login is enforced by a signed, HTTP-only session cookie;
requests to application pages and APIs without a valid session are redirected
to `/login` or rejected with HTTP 401. Set a unique `CAMERAAI_SESSION_SECRET`
when deploying multiple instances; a single-machine install creates a local
git-ignored secret automatically.

This address is reachable only when the client has a route to the computer
(same LAN, VPN, or router port forwarding). For public Internet access, put an
HTTPS reverse proxy or VPN in front of the app instead of exposing plain HTTP.
