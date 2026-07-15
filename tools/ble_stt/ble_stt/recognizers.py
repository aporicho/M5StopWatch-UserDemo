from __future__ import annotations

import os
import platform
import sys
from typing import Any

from .config import model_cache_dir
from .types import Recognizer, TranscriptSegment


MLX_MODELS = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}


def resolve_engine(
    requested: str,
    platform_name: str | None = None,
    machine: str | None = None,
) -> str:
    if requested != "auto":
        return requested
    platform_name = platform_name or sys.platform
    machine = (machine or platform.machine()).lower()
    if platform_name == "darwin" and machine == "arm64":
        return "mlx"
    return "faster-whisper"


def resolve_model(engine: str, model_name: str) -> str:
    if engine != "mlx":
        return model_name
    if "/" in model_name or model_name.startswith(('.', '/')):
        return model_name
    try:
        return MLX_MODELS[model_name]
    except KeyError as exc:
        supported = ", ".join(sorted(MLX_MODELS))
        raise ValueError(f"unknown MLX model '{model_name}'; use a repository/path or one of: {supported}") from exc


class _SimplifyingRecognizer:
    def __init__(self) -> None:
        from opencc import OpenCC

        self.simplifier = OpenCC("tw2sp")

    def _segments(self, values: Any) -> list[TranscriptSegment]:
        result: list[TranscriptSegment] = []
        for item in values:
            if isinstance(item, dict):
                start, end, text = item.get("start", 0), item.get("end", 0), item.get("text", "")
            else:
                start, end, text = item.start, item.end, item.text
            result.append(TranscriptSegment(float(start), float(end), self.simplifier.convert(str(text))))
        return result


class FasterWhisperRecognizer(_SimplifyingRecognizer):
    def __init__(self, model_name: str, device: str, cpu_threads: int) -> None:
        super().__init__()
        from faster_whisper import WhisperModel

        kwargs: dict[str, Any] = {"cpu_threads": cpu_threads, "num_workers": 1}
        if device == "auto":
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                try:
                    print(f"[model] loading {model_name} on CUDA")
                    self.model = WhisperModel(model_name, device="cuda", compute_type="float16", **kwargs)
                    self.device = "cuda"
                except Exception as exc:
                    print(f"[model] CUDA initialization failed ({exc}); falling back to CPU INT8")
                    self.model = WhisperModel(model_name, device="cpu", compute_type="int8", **kwargs)
                    self.device = "cpu"
            else:
                print("[model] CUDA unavailable; using CPU INT8")
                self.model = WhisperModel(model_name, device="cpu", compute_type="int8", **kwargs)
                self.device = "cpu"
        else:
            compute_type = "float16" if device == "cuda" else "int8"
            print(f"[model] loading {model_name} on {device} ({compute_type})")
            self.model = WhisperModel(model_name, device=device, compute_type=compute_type, **kwargs)
            self.device = device
        print(f"[model] ready on {self.device}")

    def transcribe(self, pcm: list[int]) -> list[TranscriptSegment]:
        import numpy as np

        if not pcm:
            return []
        audio = np.asarray(pcm, dtype=np.float32) / 32768.0
        segments, _ = self.model.transcribe(
            audio,
            language=None,
            task="transcribe",
            beam_size=1,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        return self._segments(segments)


class MlxWhisperRecognizer(_SimplifyingRecognizer):
    def __init__(self, model_name: str) -> None:
        super().__init__()
        if sys.platform != "darwin" or platform.machine().lower() != "arm64":
            raise RuntimeError("MLX Whisper requires Apple Silicon macOS")
        import mlx_whisper

        self.module = mlx_whisper
        self.model_name = resolve_model("mlx", model_name)
        print(f"[model] MLX ready; model {self.model_name} will be downloaded on first transcription")

    def transcribe(self, pcm: list[int]) -> list[TranscriptSegment]:
        import numpy as np

        if not pcm:
            return []
        audio = np.asarray(pcm, dtype=np.float32) / 32768.0
        result = self.module.transcribe(
            audio,
            path_or_hf_repo=self.model_name,
            language=None,
            task="transcribe",
            beam_size=1,
            temperature=0.0,
            condition_on_previous_text=True,
            verbose=None,
        )
        return self._segments(result.get("segments", []))


def create_recognizer(engine: str, model_name: str, device: str, cpu_threads: int) -> Recognizer:
    os.environ.setdefault("HF_HOME", str(model_cache_dir()))
    selected = resolve_engine(engine)
    if selected == "mlx":
        return MlxWhisperRecognizer(model_name)
    return FasterWhisperRecognizer(model_name, device, cpu_threads)


def prepare_recognizer(engine: str, model_name: str, device: str, cpu_threads: int) -> str:
    """Download, load, and minimally exercise the selected recognition model."""
    selected = resolve_engine(engine)
    resolved = resolve_model(selected, model_name)
    print(f"[model] preparing {resolved} with {selected}")
    recognizer = create_recognizer(selected, model_name, device, cpu_threads)
    # MLX downloads lazily in transcribe; faster-whisper downloads in its
    # constructor. A second of silence validates the complete local pipeline.
    recognizer.transcribe([0] * 16000)
    print(f"[model] {resolved} is downloaded and verified")
    return resolved
