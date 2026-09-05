# Camera AI v2

Camera AI v2 keeps the existing CameraAI and Cosmos model pipelines while
building a new three-column operator UI: camera/analysis flow, metadata search,
and an AI agent panel.

## What is included

- `CameraAI/`: FastAPI, Dahua/NVR metadata listener, event store, clip capture,
  audio and video workers.
- `cosmos_code_base/`: the existing Cosmos reasoning/search worker source.
- `docs/`: migration and product plan.

## Safety of local data

This repository deliberately excludes live camera configuration, credentials,
API keys, databases, generated clips, model weights and caches. Configure an
operator machine from `CameraAI/.env.example` or the local dashboard.

Read [the migration plan](docs/01_hom_nay/CAMERA_AI_V2_MIGRATION_PLAN.md)
before changing the model pipeline or adding the new UI.
