from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import UserConfig, model_cache_dir
from .preferences import (
    DEFAULT_CORRECTION_FILE,
    DEFAULT_CORRECTION_MODEL,
    DEFAULT_CORRECTION_REPOSITORY,
    read_voice_preferences,
    save_voice_preferences,
)
from .recognizers import configure_hf_environment

if TYPE_CHECKING:
    from .model_progress import ModelProgressReporter


MAX_CORRECTION_MODEL_BYTES = 1_000_000_000


@dataclass(frozen=True)
class CorrectionModelPreset:
    id: str
    display_name: str
    description: str
    repository: str
    filename: str
    revision: str
    sha256: str
    expected_bytes: int


CORRECTION_MODEL_PRESETS: tuple[CorrectionModelPreset, ...] = (
    CorrectionModelPreset(
        id="lite",
        display_name="Qwen3.5-0.8B Q4",
        description="Smallest recommended model",
        repository=DEFAULT_CORRECTION_REPOSITORY,
        filename=DEFAULT_CORRECTION_FILE,
        revision="8fea620810c4afa23dd6443f999a48574c1611a3",
        sha256="57d1997790d1744fba5b40a7317df71ea5e2acee28c47e78f0cce39c0703f8cf",
        expected_bytes=563_036_064,
    ),
    CorrectionModelPreset(
        id="balanced",
        display_name="Qwen2.5-1.5B Q3_K_M",
        description="Better correction, still under 1 GB",
        repository="Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        filename="qwen2.5-1.5b-instruct-q3_k_m.gguf",
        revision="91cad51170dc346986eccefdc2dd33a9da36ead9",
        sha256="58cb5c05ecef48e82961f1a2be6544145ea26136f69dddda4bbbd092f0e4b993",
        expected_bytes=924_455_968,
    ),
)
CORRECTION_MODEL_PRESET_MAP = {preset.id: preset for preset in CORRECTION_MODEL_PRESETS}
DEFAULT_CORRECTION_PRESET = CORRECTION_MODEL_PRESET_MAP[DEFAULT_CORRECTION_MODEL]
CORRECTION_MODEL_DIRECTORY = "correction"
CORRECTION_METADATA_FILE = "model.json"
DEFAULT_CORRECTION_DISPLAY_NAME = DEFAULT_CORRECTION_PRESET.display_name
DEFAULT_CORRECTION_REVISION = DEFAULT_CORRECTION_PRESET.revision
DEFAULT_CORRECTION_SHA256 = DEFAULT_CORRECTION_PRESET.sha256
DEFAULT_CORRECTION_EXPECTED_BYTES = DEFAULT_CORRECTION_PRESET.expected_bytes
LLAMA_RUNTIME_VERSION = "b9000"
LLAMA_RUNTIME_ASSETS = {
    "darwin-arm64": ("llama-b9000-bin-macos-arm64.tar.gz", "e4531e819dd9fe4add199db998df55cf8bd20e18a67cbd1449b49409dc01c642"),
    "darwin-x64": ("llama-b9000-bin-macos-x64.tar.gz", "82b81368266b6290509c221484df073624c5325239d6f375d60589fa760519bc"),
    "linux-arm64": ("llama-b9000-bin-ubuntu-arm64.tar.gz", "575bc6c6d7171475846b96476470612d1158870506fb52fd11cf0d9cceb511b4"),
    "linux-x64": ("llama-b9000-bin-ubuntu-x64.tar.gz", "4cd8ffbb0425c49c50b56ff6b3d0a9add9ad1ae469611b9edd038e20d6cdab36"),
    "win32-arm64": ("llama-b9000-bin-win-cpu-arm64.zip", "bdb73edd8b05b9d5a0ba860e98e312f5c8aa591300a851b6c2d7359a139536f3"),
    "win32-x64": ("llama-b9000-bin-win-cpu-x64.zip", "8294e287933d3212aa93a32e1ceb800722bede14d9692d405679d4ba77cf05db"),
}


@dataclass(frozen=True)
class CorrectionModelStatus:
    model: str
    repository: str
    filename: str
    display_name: str
    state: str
    installed: bool
    disk_bytes: int
    expected_disk_bytes: int
    stale_disk_bytes: int
    path: str
    revision: str | None
    sha256: str | None
    runtime_available: bool
    runtime_path: str | None
    message: str

    @property
    def ready(self) -> bool:
        return self.installed and self.runtime_available

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "ready": self.ready}


def correction_model_dir(platform_name: str | None = None) -> Path:
    return model_cache_dir(platform_name) / CORRECTION_MODEL_DIRECTORY


def correction_model_preset(
    model: str | None = None,
    config: UserConfig | None = None,
) -> CorrectionModelPreset:
    selected = model or read_voice_preferences(config).correction.model
    try:
        return CORRECTION_MODEL_PRESET_MAP[selected]
    except KeyError as exc:
        raise ValueError(f"unknown correction model: {selected}") from exc


def correction_model_path(
    platform_name: str | None = None,
    model: str | None = None,
) -> Path:
    preset = correction_model_preset(model)
    return correction_model_dir(platform_name) / "models" / preset.filename


def correction_metadata_path(platform_name: str | None = None) -> Path:
    return correction_model_dir(platform_name) / CORRECTION_METADATA_FILE


def _correction_repo_cache(preset: CorrectionModelPreset, platform_name: str | None = None) -> Path:
    name = f"models--{preset.repository.replace('/', '--')}"
    return correction_model_dir(platform_name) / "hub" / name


def correction_runtime_dir(platform_name: str | None = None) -> Path:
    return correction_model_dir(platform_name) / "runtime"


def _stale_model_paths(platform_name: str | None = None) -> list[Path]:
    directory = correction_model_dir(platform_name) / "models"
    if not directory.exists():
        return []
    known_files = {preset.filename for preset in CORRECTION_MODEL_PRESETS}
    return [
        path
        for path in directory.glob("*.gguf")
        if path.name not in known_files and path.is_file()
    ]


def _read_metadata(platform_name: str | None = None) -> dict[str, Any]:
    try:
        value = json.loads(correction_metadata_path(platform_name).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_metadata(value: dict[str, Any], platform_name: str | None = None) -> None:
    path = correction_metadata_path(platform_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _model_metadata(preset: CorrectionModelPreset, platform_name: str | None = None) -> dict[str, Any]:
    metadata = _read_metadata(platform_name)
    models = metadata.get("models")
    if isinstance(models, dict):
        value = models.get(preset.id)
        return value if isinstance(value, dict) else {}
    if metadata.get("filename") == preset.filename:
        return metadata
    return {}


def _write_model_metadata(
    preset: CorrectionModelPreset,
    value: dict[str, Any] | None,
    platform_name: str | None = None,
) -> None:
    metadata = _read_metadata(platform_name)
    models = metadata.get("models")
    if not isinstance(models, dict):
        models = {}
        if metadata.get("filename"):
            for candidate in CORRECTION_MODEL_PRESETS:
                if metadata.get("filename") == candidate.filename:
                    models[candidate.id] = metadata
                    break
    if value is None:
        models.pop(preset.id, None)
    else:
        models[preset.id] = value
    _write_metadata({"schema": 2, "models": models}, platform_name)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _llama_server_name(platform_name: str | None = None) -> str:
    return "llama-server.exe" if (platform_name or sys.platform) == "win32" else "llama-server"


def bundled_llama_server_candidates(platform_name: str | None = None) -> list[Path]:
    name = _llama_server_name(platform_name)
    candidates: list[Path] = []
    explicit = os.environ.get("BLE_STT_LLAMA_SERVER")
    if explicit:
        candidates.append(Path(explicit).expanduser())

    executable = Path(sys.executable).resolve()
    for ancestor in (executable.parent, *executable.parents):
        candidates.extend(
            (
                ancestor / name,
                ancestor / "llama" / name,
                ancestor / "resources" / "llama" / name,
                ancestor / "Resources" / "llama" / name,
            )
        )
    source_root = Path(__file__).resolve().parent.parent
    candidates.extend(
        (
            source_root / "vendor" / "llama" / name,
            source_root / "desktop" / "src-tauri" / "resources" / "llama" / name,
            correction_runtime_dir(platform_name) / name,
        )
    )
    discovered = shutil.which(name)
    if discovered:
        candidates.append(Path(discovered))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def llama_server_path(platform_name: str | None = None) -> Path | None:
    for candidate in bundled_llama_server_candidates(platform_name):
        if candidate.exists() and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def correction_model_status(
    config: UserConfig | None = None,
    platform_name: str | None = None,
    model: str | None = None,
) -> CorrectionModelStatus:
    preset = correction_model_preset(model, config)
    path = correction_model_path(platform_name, preset.id)
    metadata = _model_metadata(preset, platform_name)
    runtime = llama_server_path(platform_name)
    installed = path.exists() and path.is_file() and path.stat().st_size > 0
    root = correction_model_dir(platform_name)
    partial_bytes = max(
        (
            _tree_size(_correction_repo_cache(preset, platform_name)),
            _tree_size(root / "model-staging" / preset.filename),
        ),
        default=0,
    )
    stale_disk_bytes = sum(candidate.stat().st_size for candidate in _stale_model_paths(platform_name))
    state = "ready" if installed else ("partial" if partial_bytes else ("legacy" if stale_disk_bytes else "missing"))
    message = (
        f"{preset.display_name} ready"
        if installed
        else (
            f"{preset.display_name} download is incomplete; continue installation"
            if partial_bytes
            else (
                f"legacy correction model found; replace it with {preset.display_name}"
                if stale_disk_bytes
                else f"{preset.display_name} is not installed"
            )
        )
    )
    if installed:
        recorded_size = int(metadata.get("size", 0) or 0)
        recorded_sha256 = str(metadata.get("sha256", "") or "").casefold()
        recorded_revision = str(metadata.get("revision", "") or "")
        if (
            path.stat().st_size != preset.expected_bytes
            or recorded_size != preset.expected_bytes
            or recorded_sha256 != preset.sha256.casefold()
            or recorded_revision != preset.revision
        ):
            installed = False
            state = "partial"
            message = f"{preset.display_name} failed pinned metadata checks; use Repair"
    if installed and runtime is None:
        state = "runtime_missing"
        message = "llama-server runtime is not bundled"
    return CorrectionModelStatus(
        model=preset.id,
        repository=preset.repository,
        filename=preset.filename,
        display_name=preset.display_name,
        state=state,
        installed=installed,
        disk_bytes=path.stat().st_size if path.exists() else partial_bytes,
        expected_disk_bytes=preset.expected_bytes,
        stale_disk_bytes=stale_disk_bytes,
        path=str(path),
        revision=str(metadata.get("revision")) if metadata.get("revision") else None,
        sha256=str(metadata.get("sha256")) if metadata.get("sha256") else None,
        runtime_available=runtime is not None,
        runtime_path=str(runtime) if runtime else None,
        message=message,
    )


def list_correction_models(config: UserConfig | None = None) -> list[dict[str, Any]]:
    return [
        {
            "id": preset.id,
            "label": preset.display_name,
            "description": preset.description,
            "status": correction_model_status(config, model=preset.id).to_dict(),
        }
        for preset in CORRECTION_MODEL_PRESETS
    ]


def _remote_metadata(
    preset: CorrectionModelPreset | None = None,
) -> tuple[str | None, str | None, int | None]:
    preset = preset or DEFAULT_CORRECTION_PRESET
    if preset.expected_bytes > MAX_CORRECTION_MODEL_BYTES:
        raise RuntimeError("configured correction model exceeds the 1 GB product limit")
    configure_hf_environment()
    from huggingface_hub import HfApi

    info = HfApi().model_info(
        preset.repository,
        revision=preset.revision,
        files_metadata=True,
    )
    digest: str | None = None
    size: int | None = None
    for sibling in info.siblings or ():
        if getattr(sibling, "rfilename", None) != preset.filename:
            continue
        lfs = getattr(sibling, "lfs", None)
        digest = str(getattr(lfs, "sha256", "") or "") or None
        raw_size = getattr(lfs, "size", None) or getattr(sibling, "size", None)
        size = int(raw_size) if raw_size is not None else None
        break
    revision = str(info.sha) if getattr(info, "sha", None) else None
    if revision != preset.revision:
        raise RuntimeError("correction model revision does not match the pinned revision")
    if size != preset.expected_bytes or size > MAX_CORRECTION_MODEL_BYTES:
        raise RuntimeError("correction model size does not match the pinned size")
    if not digest or digest.casefold() != preset.sha256.casefold():
        raise RuntimeError("correction model SHA-256 does not match the pinned digest")
    return revision, digest, size


def _download_model(
    preset: CorrectionModelPreset,
    revision: str,
    destination: Path,
    cache: Path,
    progress: ModelProgressReporter | None = None,
) -> Path:
    configure_hf_environment()
    from huggingface_hub import hf_hub_download

    arguments = {
        "repo_id": preset.repository,
        "filename": preset.filename,
        "revision": revision,
        "local_dir": destination,
        "cache_dir": cache,
    }
    if progress is None:
        return Path(hf_hub_download(**arguments))
    with progress.monitor_download(
        (cache / f"models--{preset.repository.replace('/', '--')}", destination),
        preset.expected_bytes,
        component="model",
    ):
        return Path(hf_hub_download(**arguments))


def _tree_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def _runtime_asset_key(platform_name: str | None = None, machine: str | None = None) -> str:
    system = platform_name or sys.platform
    raw_machine = (machine or platform.machine()).lower()
    architecture = "arm64" if raw_machine in {"arm64", "aarch64"} else "x64"
    if system not in {"darwin", "linux", "win32"}:
        raise RuntimeError(f"no correction runtime is available for {system}")
    key = f"{system}-{architecture}"
    if key not in LLAMA_RUNTIME_ASSETS:
        raise RuntimeError(f"no correction runtime is available for {key}")
    return key


def _download_file(
    url: str,
    destination: Path,
    progress: ModelProgressReporter | None = None,
) -> None:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "M5StopWatch/ble-stt"})
            with urllib.request.urlopen(request, timeout=60) as response:
                raw_total = response.headers.get("Content-Length")
                total = int(raw_total) if raw_total and raw_total.isdigit() else None
                with destination.open("wb") as stream:
                    downloaded = 0
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
                        downloaded += len(chunk)
                        if progress:
                            progress.emit(
                                "downloading",
                                component="runtime",
                                downloaded_bytes=downloaded,
                                total_bytes=total,
                                cancellable=True,
                                force=False,
                            )
                if progress:
                    progress.emit(
                        "downloading",
                        component="runtime",
                        downloaded_bytes=downloaded,
                        total_bytes=total,
                        cancellable=True,
                    )
            return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(1 + attempt)
    raise RuntimeError(f"could not download correction runtime: {last_error}")


def _validate_archive_paths(names: list[str], destination: Path) -> None:
    root = destination.resolve()
    for name in names:
        resolved = (destination / name).resolve()
        if resolved != root and root not in resolved.parents:
            raise RuntimeError("correction runtime archive contains an unsafe path")


def _extract_runtime_archive(archive: Path, destination: Path) -> None:
    if archive.suffix.casefold() == ".zip":
        with zipfile.ZipFile(archive) as bundle:
            _validate_archive_paths(bundle.namelist(), destination)
            bundle.extractall(destination)
        return
    with tarfile.open(archive, "r:gz") as bundle:
        _validate_archive_paths([member.name for member in bundle.getmembers()], destination)
        try:
            bundle.extractall(destination, filter="data")
        except TypeError:  # Python 3.10/3.11 do not expose the filter argument.
            bundle.extractall(destination)


def install_correction_runtime(
    platform_name: str | None = None,
    machine: str | None = None,
    progress: ModelProgressReporter | None = None,
) -> Path:
    existing = llama_server_path(platform_name)
    if existing is not None:
        return existing
    key = _runtime_asset_key(platform_name, machine)
    asset, expected_sha256 = LLAMA_RUNTIME_ASSETS[key]
    url = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_RUNTIME_VERSION}/{asset}"
    destination = correction_runtime_dir(platform_name)
    with tempfile.TemporaryDirectory(prefix="m5stopwatch-llama-") as temporary:
        root = Path(temporary)
        archive = root / asset
        extracted = root / "extracted"
        extracted.mkdir()
        _download_file(url, archive, progress)
        if progress:
            progress.emit("verifying", component="runtime")
        if sha256_file(archive).casefold() != expected_sha256.casefold():
            raise RuntimeError("downloaded correction runtime failed SHA-256 verification")
        _extract_runtime_archive(archive, extracted)
        server_name = _llama_server_name(platform_name)
        servers = [path for path in extracted.rglob(server_name) if path.is_file()]
        if len(servers) != 1:
            raise RuntimeError(f"correction runtime archive did not contain one {server_name}")
        source = servers[0].parent
        runtime_files = []
        for path in source.iterdir():
            lower = path.name.casefold()
            if not path.is_file():
                continue
            if path.name in {server_name, "LICENSE"}:
                runtime_files.append(path)
            elif key.startswith("darwin-") and (lower.endswith(".dylib") or lower.endswith(".metal")):
                runtime_files.append(path)
            elif key.startswith("win32-") and lower.endswith(".dll"):
                runtime_files.append(path)
            elif key.startswith("linux-") and ".so" in lower:
                runtime_files.append(path)
        staging = destination.with_name("runtime.new")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        for source_path in runtime_files:
            shutil.copy2(source_path, staging / source_path.name)
        server = staging / server_name
        if not server.exists():
            raise RuntimeError("correction runtime copy failed")
        if not key.startswith("win32-"):
            server.chmod(server.stat().st_mode | 0o755)
        (staging / "runtime.json").write_text(
            json.dumps(
                {
                    "version": LLAMA_RUNTIME_VERSION,
                    "asset": asset,
                    "sha256": expected_sha256,
                    "source": url,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(destination, ignore_errors=True)
        staging.replace(destination)
    return destination / server_name


def use_correction_model(
    model: str,
    config: UserConfig | None = None,
) -> CorrectionModelStatus:
    config = config or UserConfig()
    preset = correction_model_preset(model, config)
    settings = read_voice_preferences(config).to_dict()
    settings["correction"].update(
        {
            "model": preset.id,
            "repository": preset.repository,
            "filename": preset.filename,
        }
    )
    save_voice_preferences(settings, config)
    return correction_model_status(config, model=preset.id)


def install_correction_model(
    config: UserConfig | None = None,
    model: str | None = None,
    progress: ModelProgressReporter | None = None,
) -> CorrectionModelStatus:
    config = config or UserConfig()
    preset = correction_model_preset(model, config)
    if progress:
        progress.emit("preparing", cancellable=True)
    revision, expected_sha256, expected_size = _remote_metadata(preset)
    install_correction_runtime(progress=progress)
    destination = correction_model_path(model=preset.id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    root = correction_model_dir()
    staging = root / "model-staging"
    temporary = destination.with_name(f".{destination.name}.installing")
    shutil.rmtree(staging, ignore_errors=True)
    temporary.unlink(missing_ok=True)
    completed = False
    try:
        download_arguments = (
            preset,
            revision or preset.revision,
            staging,
            root / "hub",
        )
        downloaded = (
            _download_model(*download_arguments, progress)
            if progress
            else _download_model(*download_arguments)
        )
        if progress:
            progress.emit("verifying", component="model")
        if expected_size is not None and downloaded.stat().st_size != expected_size:
            raise RuntimeError("downloaded correction model has an unexpected size")
        actual_sha256 = sha256_file(downloaded)
        if expected_sha256 and actual_sha256.casefold() != expected_sha256.casefold():
            raise RuntimeError("downloaded correction model failed SHA-256 verification")
        if progress:
            progress.emit("installing", component="model")
        # local_dir may be backed by a cache link in older huggingface_hub
        # versions. Copy into our own filesystem before deleting Hub caches.
        shutil.copy2(downloaded, temporary)
        temporary.replace(destination)
        completed = True
    finally:
        temporary.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
        if completed:
            shutil.rmtree(_correction_repo_cache(preset), ignore_errors=True)
    _write_model_metadata(
        preset,
        {
            "repository": preset.repository,
            "filename": preset.filename,
            "revision": revision,
            "sha256": preset.sha256,
            "size": destination.stat().st_size,
            "installed_at": time.time(),
        },
    )
    for stale_model in _stale_model_paths():
        stale_model.unlink(missing_ok=True)
    return correction_model_status(config, model=preset.id)


def _delete_correction_model_files(
    preset: CorrectionModelPreset,
    *,
    remove_legacy_if_missing: bool,
) -> None:
    root = correction_model_dir()
    destination = correction_model_path(model=preset.id)
    was_installed = destination.exists()
    destination.unlink(missing_ok=True)
    if remove_legacy_if_missing and not was_installed:
        for path in _stale_model_paths():
            path.unlink(missing_ok=True)
    shutil.rmtree(_correction_repo_cache(preset), ignore_errors=True)
    shutil.rmtree(root / "model-staging", ignore_errors=True)
    _write_model_metadata(preset, None)


def delete_correction_model(
    config: UserConfig | None = None,
    model: str | None = None,
) -> CorrectionModelStatus:
    config = config or UserConfig()
    preset = correction_model_preset(model, config)
    _delete_correction_model_files(preset, remove_legacy_if_missing=True)
    return correction_model_status(config, model=preset.id)


def repair_correction_model(
    config: UserConfig | None = None,
    model: str | None = None,
    progress: ModelProgressReporter | None = None,
) -> CorrectionModelStatus:
    config = config or UserConfig()
    preset = correction_model_preset(model, config)
    _delete_correction_model_files(preset, remove_legacy_if_missing=False)
    return install_correction_model(config, preset.id, progress)


def update_correction_model(
    config: UserConfig | None = None,
    model: str | None = None,
    progress: ModelProgressReporter | None = None,
) -> CorrectionModelStatus:
    return install_correction_model(config, model, progress)
