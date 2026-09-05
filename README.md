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
