import time
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model_runner import CosmosVideoAnalyzer


def main() -> None:
    print("load_start", flush=True)
    analyzer = CosmosVideoAnalyzer(
        model_id="nvidia/Cosmos-Reason2-2B",
        max_new_tokens=32,
        dtype="bfloat16",
        backend="vllm",
        gpu_memory_utilization=0.77,
        max_model_len=52224,
    )
    print("load_done", flush=True)
    time.sleep(30)
    del analyzer
    print("done", flush=True)


if __name__ == "__main__":
    main()
