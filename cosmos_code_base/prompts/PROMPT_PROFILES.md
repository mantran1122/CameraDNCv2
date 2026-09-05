# Prompt profiles

Choose a profile without editing code.

```powershell
# Live single-frame analysis
$env:COSMOS_LIVE_PROMPT_PROFILE = "comprehensive"

# Playback/chunk analysis
$env:COSMOS_CHUNK_PROMPT_PROFILE = "comprehensive"
```

Available values: `comprehensive`, `classroom`, `security`, `safety`, `crowd_operations`, `traffic`, `admissions`, `student_affairs`.

`COSMOS_LIVE_PROMPT_PROFILE=admissions` remains the default to preserve the existing admissions-camera behaviour. For a general-purpose camera, use `comprehensive`. Prompt profiles are evidence-based: they improve what the model checks, but do not make an invisible event detectable.

`student_affairs` is reserved for the stateful pilot: it must receive only
verified rule-engine events, never use a single image to infer attendance,
entry/exit, identity, or duration. Restart the live service after changing an
environment variable so the selected profile is reported consistently.
