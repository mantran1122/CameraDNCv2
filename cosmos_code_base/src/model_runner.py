import gc
import logging
from typing import Any, List

import torch
from PIL import Image

from src.prompt import build_chunk_prompt

logger = logging.getLogger(__name__)


class CosmosVideoAnalyzer:
    def __init__(
        self,
        model_id: str,
        max_new_tokens: int = 700,
        device_map: str = "auto",
        dtype: str = "auto",
        attn_implementation: str = "sdpa",
        backend: str = "vllm",
        gpu_memory_utilization: float = 0.77,
        max_model_len: int | None = 52224,
    ):
        self.model_id = model_id
        self.max_new_tokens = max_new_tokens
        self.device_map = device_map
        self.dtype = dtype
        self.attn_implementation = attn_implementation
        self.backend = backend
        self.gpu_memory_utilization = float(gpu_memory_utilization)
        if not 0 < self.gpu_memory_utilization <= 1:
            raise ValueError("--gpu-memory-utilization must be a float in the range (0, 1], for example 0.8")
        self.max_model_len = max_model_len

        self.processor = None
        self.model = None
        self.sampling_params = None
        self.model_class_name = None

        self._load_model()

    def _torch_dtype(self):
        if self.dtype == "float16":
            return torch.float16
        if self.dtype == "bfloat16":
            return torch.bfloat16
        if self.dtype == "float32":
            return torch.float32
        return "auto"

    def _resolve_model_class(self):
        import transformers

        candidates = [
            "AutoModelForImageTextToText",
            "AutoModelForVision2Seq",
            "AutoModelForCausalLM",
        ]

        for name in candidates:
            cls = getattr(transformers, name, None)
            if cls is not None:
                self.model_class_name = name
                return cls

        raise ImportError(
            "Cannot find a suitable VLM model class in transformers. "
            "Update dependencies with: pip install -U transformers accelerate"
        )

    def _load_model(self):
        if self.backend == "vllm":
            self._load_vllm_model()
            return
        if self.backend != "transformers":
            raise ValueError(f"Unsupported model backend: {self.backend}")

        self._load_transformers_model()

    def _load_vllm_model(self):
        from transformers import AutoProcessor

        try:
            from vllm import LLM, SamplingParams
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency vllm. Install vLLM in the inference environment "
                "or run with --model-backend transformers."
            ) from exc

        print(f"Loading processor: {self.model_id}")
        self.processor = AutoProcessor.from_pretrained(
            self.model_id,
            trust_remote_code=True,
        )

        dtype = "auto" if self.dtype in {None, "auto"} else self.dtype
        print(f"Loading vLLM model: {self.model_id}")
        print(f"vLLM gpu_memory_utilization={self.gpu_memory_utilization:.2f}")
        self.model = LLM(
            model=self.model_id,
            trust_remote_code=True,
            dtype=dtype,
            gpu_memory_utilization=float(self.gpu_memory_utilization),
            max_model_len=self.max_model_len,
            limit_mm_per_prompt={"image": 64},
        )
        self.sampling_params = SamplingParams(
            temperature=0.0,
            max_tokens=int(self.max_new_tokens),
        )

    def _load_transformers_model(self):
        from transformers import AutoProcessor

        ModelClass = self._resolve_model_class()

        print(f"Loading processor: {self.model_id}")
        self.processor = AutoProcessor.from_pretrained(
            self.model_id,
            trust_remote_code=True,
        )

        print(f"Loading model: {self.model_id}")
        print(f"Using model class: {self.model_class_name}")

        model_kwargs = {
            "torch_dtype": self._torch_dtype(),
            "device_map": self.device_map,
            "trust_remote_code": True,
            "low_cpu_mem_usage": True,
        }
        if self.attn_implementation != "auto":
            model_kwargs["attn_implementation"] = self.attn_implementation

        try:
            self.model = ModelClass.from_pretrained(self.model_id, **model_kwargs)
        except (TypeError, ValueError) as exc:
            if "attn_implementation" not in model_kwargs:
                raise
            print(f"Attention implementation {self.attn_implementation} is not supported, retrying with model default.")
            model_kwargs.pop("attn_implementation", None)
            self.model = ModelClass.from_pretrained(self.model_id, **model_kwargs)

        self.model.eval()

    def generate_description(
        self,
        frames: List[Image.Image],
        start_time: str,
        end_time: str,
        force_vietnamese: bool = False,
    ) -> str:
        if not frames:
            return self._empty_frame_response(start_time, end_time)

        prompt = build_chunk_prompt(start_time, end_time)
        if force_vietnamese:
            prompt += (
                "\n\nKẾT QUẢ TRƯỚC SAI NGÔN NGỮ. Hãy tạo lại JSON từ hình ảnh. "
                "Mọi câu mô tả và phần tử danh sách bắt buộc bằng tiếng Việt có dấu. "
                "Không được chứa chữ Hán, tiếng Trung hoặc câu tiếng Anh. Chỉ trả về JSON."
            )
        if self.backend == "vllm":
            return self._generate_with_vllm(frames, prompt)
        return self._generate_with_transformers(frames, prompt)

    def generate_descriptions(self, chunk_inputs: List[dict[str, Any]]) -> List[str]:
        """Generate multiple chunk descriptions in one vLLM request batch."""
        if self.backend != "vllm":
            return [
                self.generate_description(
                    frames=item["frames"],
                    start_time=item["start_time"],
                    end_time=item["end_time"],
                )
                for item in chunk_inputs
            ]

        results = [""] * len(chunk_inputs)
        requests: List[dict[str, Any]] = []
        request_indexes: List[int] = []
        for index, item in enumerate(chunk_inputs):
            frames = item["frames"]
            start_time = item["start_time"]
            end_time = item["end_time"]
            if not frames:
                results[index] = self._empty_frame_response(start_time, end_time)
                continue

            prompt = build_chunk_prompt(start_time, end_time)
            requests.append(
                {
                    "prompt": self._build_vllm_prompt(frames, prompt),
                    "multi_modal_data": {"image": frames},
                }
            )
            request_indexes.append(index)

        if not requests:
            return results

        try:
            outputs = self.model.generate(requests, self.sampling_params)
        except Exception as exc:
            raise RuntimeError(
                "vLLM batch generate failed. Reduce --vllm-batch-size if this is caused by memory pressure. "
                f"Original error: {repr(exc)}"
            )

        for request_index, output in zip(request_indexes, outputs):
            output_text = output.outputs[0].text if output.outputs else ""
            results[request_index] = self._extract_json_text(output_text)

        return results

    def _build_vllm_prompt(self, frames: List[Image.Image], prompt: str) -> str:
        messages = [
            {
                "role": "user",
                "content": [
                    *[{"type": "image", "image": img} for img in frames],
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        if hasattr(self.processor, "apply_chat_template"):
            try:
                return self.processor.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
            except Exception:
                pass
        return prompt

    def _generate_with_vllm(self, frames: List[Image.Image], prompt: str) -> str:
        try:
            request: dict[str, Any] = {
                "prompt": self._build_vllm_prompt(frames, prompt),
                "multi_modal_data": {"image": frames},
            }
            outputs = self.model.generate([request], self.sampling_params)
            output_text = outputs[0].outputs[0].text if outputs and outputs[0].outputs else ""
            return self._extract_json_text(output_text)
        except Exception as exc:
            raise RuntimeError(
                "vLLM generate failed. Confirm this Cosmos model supports vLLM multimodal "
                f"inference and that vLLM is installed for your CUDA/Python environment. Original error: {repr(exc)}"
            )

    def _extract_json_text(self, output_text: str) -> str:
        start = output_text.find("{")
        end = output_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            output_text = output_text[start : end + 1]
        return output_text.strip()

    def _empty_frame_response(self, start_time: str, end_time: str) -> str:
        return (
            '{"start":"%s","end":"%s","description":"Không đọc được frame nào trong đoạn video này.",'
            '"people_count":"unknown","phone_detected":false,"crowd_detected":false,'
            '"objects":[],"actions":[],"scene_changes":"unknown","abnormal":false,'
            '"abnormal_type":"none","risk_level":"none",'
            '"important_event":{"has_event":false,"event":"none","timestamp":"none"},'
            '"confidence":0.0}'
        ) % (start_time, end_time)

    def _generate_with_transformers(self, frames: List[Image.Image], prompt: str) -> str:
        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        *[{"type": "image", "image": img} for img in frames],
                    ],
                }
            ]

            if hasattr(self.processor, "apply_chat_template"):
                try:
                    text = self.processor.apply_chat_template(
                        messages,
                        tokenize=False,
                        add_generation_prompt=True,
                    )
                    inputs = self.processor(
                        text=[text],
                        images=frames,
                        return_tensors="pt",
                        padding=True,
                    )
                except Exception:
                    inputs = self.processor(
                        text=prompt,
                        images=frames,
                        return_tensors="pt",
                        padding=True,
                    )
            else:
                inputs = self.processor(
                    text=prompt,
                    images=frames,
                    return_tensors="pt",
                    padding=True,
                )

            inputs = self._move_inputs_to_model_device(inputs)

            with torch.inference_mode():
                generated_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=self.max_new_tokens,
                    do_sample=False,
                )

            output_text = self.processor.batch_decode(
                generated_ids,
                skip_special_tokens=True,
            )[0]

            if prompt in output_text:
                output_text = output_text.split(prompt, 1)[-1].strip()

            start = output_text.find("{")
            end = output_text.rfind("}")
            if start != -1 and end != -1 and end > start:
                output_text = output_text[start : end + 1]

            result = output_text.strip()

            try:
                del inputs, generated_ids, output_text
            except Exception:
                pass

            return result

        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            raise RuntimeError(
                "CUDA out of memory. Reduce --sample-fps, --chunk-seconds or --max-new-tokens."
            )
        except Exception as exc:
            raise RuntimeError(
                "Model generate failed. This model may need a custom API or extra dependency. "
                f"Original error: {repr(exc)}"
            )

    def _move_inputs_to_model_device(self, inputs):
        try:
            device = next(self.model.parameters()).device
            moved = {}
            for key, value in inputs.items():
                if not hasattr(value, "to"):
                    moved[key] = value
                    continue
                try:
                    moved[key] = value.to(device, non_blocking=True)
                except TypeError:
                    moved[key] = value.to(device)
            return moved
        except Exception:
            return inputs

    def close(self) -> None:
        """Release model resources before the process exits or continues indexing."""
        try:
            if self.model is not None and hasattr(self.model, "shutdown"):
                self.model.shutdown()
            elif self.model is not None and hasattr(self.model, "llm_engine"):
                engine = getattr(self.model, "llm_engine", None)
                if engine is not None and hasattr(engine, "shutdown"):
                    engine.shutdown()
        except Exception as exc:
            logger.debug("Model shutdown error: %s", exc)

        self.model = None
        self.processor = None
        self.sampling_params = None

        try:
            from vllm.distributed.parallel_state import destroy_model_parallel

            destroy_model_parallel()
        except Exception as exc:
            logger.debug("destroy_model_parallel error: %s", exc)

        try:
            import torch.distributed as dist

            if dist.is_available() and dist.is_initialized():
                dist.destroy_process_group()
        except Exception as exc:
            logger.debug("destroy_process_group error: %s", exc)

        gc.collect()
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception as exc:
            logger.debug("CUDA cleanup error: %s", exc)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception as exc:
            logger.debug("__del__ close error: %s", exc)
