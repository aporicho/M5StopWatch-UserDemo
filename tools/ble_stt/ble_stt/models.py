from __future__ import annotations

import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from .config import UserConfig, config_dir, model_cache_dir
from .recognizers import configure_hf_environment, prepare_recognizer, resolve_engine, resolve_model

if TYPE_CHECKING:
    from .model_progress import ModelProgressReporter


DEFAULT_MODEL = "small"
DEFAULT_ENGINE = "auto"
BUNDLED_MODEL = "small"

MODEL_PRESETS: tuple[dict[str, str], ...] = (
    {
        "id": "small",
        "label": "Small",
        "description": "Fast starter model",
    },
    {
        "id": "medium",
        "label": "Medium",
        "description": "Balanced accuracy",
    },
    {
        "id": "large",
        "label": "Large",
        "description": "Best accuracy",
    },
    {
        "id": "turbo",
        "label": "Turbo",
        "description": "Large-v3 Turbo",
    },
)

FASTER_WHISPER_REPOSITORIES = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}

MODEL_WEIGHT_SUFFIXES = (".bin", ".gguf", ".npz", ".pt", ".pth", ".safetensors")


@dataclass(frozen=True)
class ModelStatus:
    selected: str
    engine: str
    requested_engine: str
    resolved: str
    source: str
    state: str
    installed: bool
    disk_bytes: int
    cache_dir: str
    update_available: bool
    message: str

    @property
    def ready(self) -> bool:
        return self.installed and self.state in {"ready", "update_available"}

    def to_dict(self) -> dict[str, object]:
        return {
            "selected": self.selected,
            "engine": self.engine,
            "requested_engine": self.requested_engine,
            "resolved": self.resolved,
            "source": self.source,
            "state": self.state,
            "installed": self.installed,
            "disk_bytes": self.disk_bytes,
            "cache_dir": self.cache_dir,
            "update_available": self.update_available,
            "message": self.message,
        }


def preset_ids() -> set[str]:
    return {preset["id"] for preset in MODEL_PRESETS}


def selected_model(config: UserConfig | object | None = None) -> tuple[str, str]:
    config = config or UserConfig()
    engine = str(config.get("engine", DEFAULT_ENGINE))
    configured_model = config.get("model")
    if configured_model:
        return engine, str(configured_model)
    try:
        resolved_engine = resolve_engine(engine)
        if bundled_model_path(resolved_engine, DEFAULT_MODEL) is None:
            legacy_model = _first_cached_model(resolved_engine)
            if legacy_model:
                return engine, legacy_model
    except Exception:
        pass
    model = DEFAULT_MODEL
    return engine, model


def model_metadata_path(config: UserConfig | object | None = None) -> Path:
    path = getattr(config, "path", None)
    if isinstance(path, Path):
        return path.with_name("ble-stt-models.json")
    return config_dir() / "ble-stt-models.json"


def read_model_metadata(config: UserConfig | object | None = None) -> dict[str, Any]:
    path = model_metadata_path(config)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"schema": 1, "models": {}}
    if not isinstance(value, dict):
        return {"schema": 1, "models": {}}
    models = value.get("models")
    if not isinstance(models, dict):
        value["models"] = {}
    value.setdefault("schema", 1)
    return value


def write_model_metadata(value: dict[str, Any], config: UserConfig | object | None = None) -> None:
    path = model_metadata_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def model_key(engine: str, model: str) -> str:
    return f"{engine}:{model}"


def _metadata_entry(config: UserConfig | object, engine: str, model: str) -> dict[str, Any] | None:
    value = read_model_metadata(config).get("models", {}).get(model_key(engine, model))
    return value if isinstance(value, dict) else None


def _set_metadata_entry(config: UserConfig | object, engine: str, model: str, entry: dict[str, Any]) -> None:
    metadata = read_model_metadata(config)
    models = metadata.setdefault("models", {})
    models[model_key(engine, model)] = entry
    write_model_metadata(metadata, config)


def _delete_metadata_entry(config: UserConfig | object, engine: str, model: str) -> None:
    metadata = read_model_metadata(config)
    metadata.setdefault("models", {}).pop(model_key(engine, model), None)
    write_model_metadata(metadata, config)


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def _is_local_path(value: str) -> bool:
    return value.startswith((".", "/", "~")) or "\\" in value


def _safe_remove(path: Path, allowed_roots: Iterable[Path]) -> None:
    target = path.expanduser().resolve()
    roots = [root.expanduser().resolve() for root in allowed_roots]
    if not any(target == root or root in target.parents for root in roots):
        raise RuntimeError(f"refusing to delete path outside the model cache: {target}")
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()


def bundled_models_root() -> Path | None:
    explicit = os.environ.get("BLE_STT_BUNDLED_MODELS")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))

    executable = Path(sys.executable)
    for ancestor in executable.parents:
        candidates.append(ancestor / "resources" / "models")
        candidates.append(ancestor / "models")
        if ancestor.name == "Contents":
            candidates.append(ancestor / "Resources" / "resources" / "models")
            candidates.append(ancestor / "Resources" / "models")

    source_root = Path(__file__).resolve().parents[1]
    candidates.append(source_root / "desktop" / "src-tauri" / "resources" / "models")

    for path in candidates:
        if path.exists() and path.is_dir():
            return path
    return None


def bundled_model_path(engine: str, model: str) -> Path | None:
    root = bundled_models_root()
    if root is None or model != BUNDLED_MODEL:
        return None
    path = root / engine / model
    return path if path.exists() and path.is_dir() else None


def bundled_cache_path(engine: str, model: str) -> Path:
    return model_cache_dir() / "bundled" / engine / model


def ensure_bundled_model(engine: str, model: str) -> Path:
    source = bundled_model_path(engine, model)
    if source is None:
        raise RuntimeError(f"bundled {model} model is not available for {engine}")
    target = bundled_cache_path(engine, model)
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp")
    shutil.rmtree(temporary, ignore_errors=True)
    shutil.copytree(source, temporary, symlinks=True)
    temporary.replace(target)
    return target


def repository_for_model(engine: str, model: str) -> str | None:
    if _is_local_path(model):
        return None
    resolved = resolve_model(engine, model)
    if "/" in resolved:
        return resolved
    if engine == "faster-whisper":
        return FASTER_WHISPER_REPOSITORIES.get(resolved)
    return None


def _repo_cache_name(repo: str) -> str:
    return f"models--{repo.replace('/', '--')}"


def _repo_cache_paths(repo: str) -> tuple[Path, ...]:
    root = model_cache_dir()
    name = _repo_cache_name(repo)
    return (
        root / "hub" / name,
        root / name,
    )


def _repo_cache_path(repo: str) -> Path:
    candidates = _repo_cache_paths(repo)
    for path in candidates:
        if _latest_complete_snapshot(path) is not None:
            return path
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def _has_incomplete_files(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        return any(path.rglob("*.incomplete"))
    except OSError:
        return True


def _snapshot_directories(cache_path: Path) -> list[Path]:
    snapshots = cache_path / "snapshots"
    if not snapshots.exists():
        return []
    try:
        return sorted(
            (path for path in snapshots.iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return []


def _snapshot_has_model_weights(snapshot: Path) -> bool:
    try:
        entries = list(snapshot.iterdir())
    except OSError:
        return False
    for path in entries:
        if path.name.startswith("."):
            continue
        if path.suffix.lower() not in MODEL_WEIGHT_SUFFIXES:
            continue
        try:
            if path.exists() and path.stat().st_size > 0:
                return True
        except OSError:
            continue
    return False


def _latest_complete_snapshot(cache_path: Path) -> Path | None:
    if not cache_path.exists() or _has_incomplete_files(cache_path):
        return None
    for snapshot in _snapshot_directories(cache_path):
        if _snapshot_has_model_weights(snapshot):
            return snapshot
    return None


def _downloaded_cache_status(cache_path: Path) -> tuple[bool, str, str, Path]:
    if not cache_path.exists():
        return False, "missing", "model cache is missing", cache_path
    if not _has_incomplete_files(cache_path) and _snapshot_has_model_weights(cache_path):
        return True, "ready", "model ready", cache_path
    snapshot = _latest_complete_snapshot(cache_path)
    if snapshot is not None:
        return True, "ready", "model ready", snapshot
    return False, "partial", "model download is incomplete; use Repair", cache_path


def _first_cached_model(engine: str) -> str | None:
    for model in ("medium", "small", "large", "turbo"):
        repo = repository_for_model(engine, model)
        if repo and _latest_complete_snapshot(_repo_cache_path(repo)) is not None:
            return model
    return None


def _metadata_revision(repo: str | None) -> str | None:
    if repo is None:
        return None
    try:
        configure_hf_environment()
        from huggingface_hub import HfApi

        info = HfApi().model_info(repo, revision="main")
        return str(info.sha) if info.sha else None
    except Exception:
        return None


def _repository_total_bytes(repo: str) -> int | None:
    try:
        configure_hf_environment()
        from huggingface_hub import HfApi

        info = HfApi().model_info(repo, revision="main", files_metadata=True)
        sizes = [int(size) for sibling in (info.siblings or ()) if (size := getattr(sibling, "size", None))]
        return sum(sizes) or None
    except Exception:
        return None


def _download_snapshot(repo: str, progress: ModelProgressReporter | None = None) -> None:
    configure_hf_environment()
    from huggingface_hub import snapshot_download

    hub_cache = model_cache_dir() / "hub"
    hub_cache.mkdir(parents=True, exist_ok=True)
    total_bytes = _repository_total_bytes(repo)
    cache_path = hub_cache / _repo_cache_name(repo)
    if progress is None:
        snapshot_download(repo_id=repo, cache_dir=str(hub_cache), revision="main")
        return
    with progress.monitor_download((cache_path / "blobs",), total_bytes, component="model"):
        snapshot_download(repo_id=repo, cache_dir=str(hub_cache), revision="main")


def runtime_model_name(engine_request: str, model: str, config: UserConfig | object | None = None) -> str:
    engine = resolve_engine(engine_request)
    if _is_local_path(model) or "/" in model:
        return str(Path(model).expanduser()) if _is_local_path(model) else model
    status = model_status(config or UserConfig(), engine_request, model)
    if status.source == "bundled" and status.installed:
        return str(ensure_bundled_model(engine, model))
    if status.source == "downloaded" and status.installed:
        cache_path = Path(status.cache_dir)
        if _snapshot_has_model_weights(cache_path):
            return str(cache_path)
        snapshot = _latest_complete_snapshot(cache_path)
        return str(snapshot or status.resolved)
    if not status.ready:
        raise RuntimeError(f"{status.message}; install or repair {model} in the desktop app")
    return resolve_model(engine, model)


def model_status(
    config: UserConfig | object | None = None,
    engine_request: str | None = None,
    model: str | None = None,
) -> ModelStatus:
    config = config or UserConfig()
    configured_engine, configured_model = selected_model(config)
    engine_request = engine_request or configured_engine
    model = model or configured_model
    try:
        engine = resolve_engine(engine_request)
        resolved = resolve_model(engine, model)
    except Exception as exc:
        return ModelStatus(
            selected=model,
            engine="unknown",
            requested_engine=engine_request,
            resolved=str(exc),
            source="missing",
            state="error",
            installed=False,
            disk_bytes=0,
            cache_dir=str(model_cache_dir()),
            update_available=False,
            message=str(exc),
        )

    if _is_local_path(model):
        path = Path(model).expanduser()
        installed = path.exists()
        return ModelStatus(
            selected=model,
            engine=engine,
            requested_engine=engine_request,
            resolved=str(path),
            source="custom",
            state="ready" if installed else "missing",
            installed=installed,
            disk_bytes=_directory_size(path),
            cache_dir=str(path),
            update_available=False,
            message="custom model ready" if installed else "custom model path does not exist",
        )

    entry = _metadata_entry(config, engine, model)
    if entry:
        source = str(entry.get("source", "downloaded"))
        raw_cache_path = str(entry.get("cache_path", ""))
        repo = repository_for_model(engine, model)
        cache_path = Path(raw_cache_path).expanduser() if raw_cache_path else (_repo_cache_path(repo) if repo else model_cache_dir())
        if source == "custom" and repo is not None:
            source = "downloaded"
            entry = {**entry, "source": source, "cache_path": str(cache_path)}
            _set_metadata_entry(config, engine, model, entry)
        if source == "downloaded":
            installed, state, message, effective_cache_path = _downloaded_cache_status(cache_path)
            installed = bool(entry.get("installed", True)) and installed
            if not installed and state == "ready":
                state = "missing"
                message = "model cache is missing"
        else:
            effective_cache_path = cache_path
            cache_exists = cache_path.exists() if cache_path.as_posix() else True
            installed = bool(entry.get("installed", True)) and cache_exists
            state = "ready" if installed else "missing"
            message = "model ready" if installed else "model cache is missing"
        update_available = bool(entry.get("update_available", False))
        return ModelStatus(
            selected=model,
            engine=engine,
            requested_engine=engine_request,
            resolved=str(entry.get("resolved", resolved)),
            source=source,
            state="update_available" if installed and update_available else state,
            installed=installed,
            disk_bytes=_directory_size(cache_path) if cache_path.as_posix() else 0,
            cache_dir=str(effective_cache_path) if effective_cache_path.as_posix() else str(model_cache_dir()),
            update_available=update_available,
            message=(
                "model update available"
                if installed and update_available
                else message
            ),
        )

    prepared = str(config.get("prepared_model", ""))
    if prepared and prepared == resolved:
        repo = repository_for_model(engine, model)
        cache_path = _repo_cache_path(repo) if repo else model_cache_dir()
        installed, state, message, effective_cache_path = _downloaded_cache_status(cache_path)
        return ModelStatus(
            selected=model,
            engine=engine,
            requested_engine=engine_request,
            resolved=resolved,
            source="downloaded",
            state=state,
            installed=installed,
            disk_bytes=_directory_size(cache_path),
            cache_dir=str(effective_cache_path),
            update_available=False,
            message=message,
        )

    repo = repository_for_model(engine, model)
    if repo:
        cache_path = _repo_cache_path(repo)
        if cache_path.exists():
            installed, state, message, effective_cache_path = _downloaded_cache_status(cache_path)
            return ModelStatus(
                selected=model,
                engine=engine,
                requested_engine=engine_request,
                resolved=resolved,
                source="downloaded",
                state=state,
                installed=installed,
                disk_bytes=_directory_size(cache_path),
                cache_dir=str(effective_cache_path),
                update_available=False,
                message=message,
            )

    if model == BUNDLED_MODEL:
        copied = bundled_cache_path(engine, model)
        bundled = bundled_model_path(engine, model)
        if copied.exists() or bundled is not None:
            cache_path = copied if copied.exists() else bundled
            return ModelStatus(
                selected=model,
                engine=engine,
                requested_engine=engine_request,
                resolved=str(copied),
                source="bundled",
                state="ready",
                installed=True,
                disk_bytes=_directory_size(cache_path),
                cache_dir=str(copied),
                update_available=False,
                message="bundled starter model ready",
            )

    return ModelStatus(
        selected=model,
        engine=engine,
        requested_engine=engine_request,
        resolved=resolved,
        source="missing",
        state="missing",
        installed=False,
        disk_bytes=0,
        cache_dir=str(model_cache_dir()),
        update_available=False,
        message="model is not installed",
    )


def record_model_ready(
    engine_request: str,
    model: str,
    resolved: str,
    *,
    config: UserConfig | object | None = None,
    source: str = "downloaded",
    cache_path: Path | None = None,
    revision: str | None = None,
) -> ModelStatus:
    config = config or UserConfig()
    engine = resolve_engine(engine_request)
    repo = repository_for_model(engine, model)
    entry = {
        "engine": engine,
        "model": model,
        "resolved": resolved,
        "source": source,
        "installed": True,
        "cache_path": str(cache_path or (_repo_cache_path(repo) if repo else model_cache_dir())),
        "revision": revision,
        "update_available": False,
        "updated_at": time.time(),
    }
    _set_metadata_entry(config, engine, model, entry)
    return model_status(config, engine_request, model)


def use_model(model: str, engine: str = DEFAULT_ENGINE, config: UserConfig | None = None) -> ModelStatus:
    config = config or UserConfig()
    config.set("engine", engine)
    config.set("model", model)
    return model_status(config, engine, model)


def install_model(
    model: str,
    engine: str = DEFAULT_ENGINE,
    device: str = "auto",
    cpu_threads: int | None = None,
    *,
    config: UserConfig | None = None,
    progress: ModelProgressReporter | None = None,
) -> ModelStatus:
    config = config or UserConfig()
    if progress:
        progress.emit("preparing", cancellable=True)
    resolved_engine = resolve_engine(engine)
    if model == BUNDLED_MODEL and bundled_model_path(resolved_engine, model) is not None:
        if progress:
            progress.emit("installing")
        path = ensure_bundled_model(resolved_engine, model)
        return record_model_ready(engine, model, str(path), config=config, source="bundled", cache_path=path)

    repo = repository_for_model(resolved_engine, model)
    revision = None
    if repo is not None:
        _download_snapshot(repo, progress)
        if progress:
            progress.emit("verifying")
        installed, _, message, _ = _downloaded_cache_status(_repo_cache_path(repo))
        if not installed:
            raise RuntimeError(message)
        revision = _metadata_revision(repo)
    if progress:
        progress.emit("installing")
    threads = cpu_threads or max(1, (os.cpu_count() or 4) // 2)
    resolved = prepare_recognizer(engine, model, device, threads)
    return record_model_ready(engine, model, resolved, config=config, source="downloaded", revision=revision)


def repair_model(
    model: str,
    engine: str = DEFAULT_ENGINE,
    device: str = "auto",
    cpu_threads: int | None = None,
    *,
    config: UserConfig | None = None,
    progress: ModelProgressReporter | None = None,
) -> ModelStatus:
    config = config or UserConfig()
    if progress:
        progress.emit("preparing", cancellable=True)
    resolved_engine = resolve_engine(engine)
    repo = repository_for_model(resolved_engine, model)
    if repo is not None:
        for path in _repo_cache_paths(repo):
            shutil.rmtree(path, ignore_errors=True)
        _delete_metadata_entry(config, resolved_engine, model)
    if model == BUNDLED_MODEL and bundled_model_path(resolved_engine, model) is not None:
        shutil.rmtree(bundled_cache_path(resolved_engine, model), ignore_errors=True)
    return install_model(model, engine, device, cpu_threads, config=config, progress=progress)


def check_updates(config: UserConfig | None = None) -> ModelStatus:
    config = config or UserConfig()
    engine_request, model = selected_model(config)
    status = model_status(config, engine_request, model)
    if not status.installed or status.source == "custom":
        return status
    repo = repository_for_model(status.engine, model)
    latest_revision = _metadata_revision(repo)
    entry = _metadata_entry(config, status.engine, model)
    if latest_revision and entry:
        entry["update_available"] = bool(entry.get("revision") and entry.get("revision") != latest_revision)
        entry["latest_revision"] = latest_revision
        _set_metadata_entry(config, status.engine, model, entry)
        return model_status(config, engine_request, model)
    return status


def update_model(
    model: str,
    engine: str = DEFAULT_ENGINE,
    device: str = "auto",
    cpu_threads: int | None = None,
    *,
    config: UserConfig | None = None,
    progress: ModelProgressReporter | None = None,
) -> ModelStatus:
    config = config or UserConfig()
    status = install_model(model, engine, device, cpu_threads, config=config, progress=progress)
    entry = _metadata_entry(config, status.engine, model)
    if entry:
        entry["update_available"] = False
        _set_metadata_entry(config, status.engine, model, entry)
    return model_status(config, engine, model)


def delete_model(model: str, engine: str = DEFAULT_ENGINE, *, config: UserConfig | None = None) -> ModelStatus:
    config = config or UserConfig()
    resolved_engine = resolve_engine(engine)
    configured_engine, configured_model = selected_model(config)
    if model == configured_model and resolve_engine(configured_engine) == resolved_engine:
        from .service import ServiceManager

        if ServiceManager().is_active():
            raise RuntimeError("stop the service before deleting the active model")

    status = model_status(config, engine, model)
    if status.source == "bundled":
        raise RuntimeError("bundled Small starter model cannot be deleted")
    entry = _metadata_entry(config, resolved_engine, model)
    repo = repository_for_model(resolved_engine, model)
    if entry and entry.get("cache_path"):
        _safe_remove(Path(str(entry["cache_path"])), (model_cache_dir(),))
    elif repo:
        for path in _repo_cache_paths(repo):
            if path.exists():
                _safe_remove(path, (model_cache_dir(),))
    _delete_metadata_entry(config, resolved_engine, model)
    return model_status(config, engine, model)


def list_models(config: UserConfig | None = None) -> list[dict[str, object]]:
    config = config or UserConfig()
    engine_request, _ = selected_model(config)
    values: list[dict[str, object]] = []
    for preset in MODEL_PRESETS:
        status = model_status(config, engine_request, preset["id"])
        values.append({**preset, "status": status.to_dict()})
    return values
