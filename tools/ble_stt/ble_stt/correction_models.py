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
from typing import Any

from .config import UserConfig, model_cache_dir
from .preferences import DEFAULT_CORRECTION_FILE, DEFAULT_CORRECTION_REPOSITORY
from .recognizers import configure_hf_environment


CORRECTION_MODEL_DIRECTORY = "correction"
CORRECTION_METADATA_FILE = "model.json"
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
    repository: str
    filename: str
    state: str
    installed: bool
    disk_bytes: int
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


def correction_model_path(platform_name: str | None = None) -> Path:
    return correction_model_dir(platform_name) / "models" / DEFAULT_CORRECTION_FILE


def correction_metadata_path(platform_name: str | None = None) -> Path:
    return correction_model_dir(platform_name) / CORRECTION_METADATA_FILE


def correction_runtime_dir(platform_name: str | None = None) -> Path:
    return correction_model_dir(platform_name) / "runtime"


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
) -> CorrectionModelStatus:
    del config  # Reserved for future per-model selection without changing this interface.
    path = correction_model_path(platform_name)
    metadata = _read_metadata(platform_name)
    runtime = llama_server_path(platform_name)
    installed = path.exists() and path.is_file() and path.stat().st_size > 0
    state = "ready" if installed else "missing"
    message = "correction model ready" if installed else "correction model is not installed"
    if installed and metadata.get("sha256"):
        recorded_size = int(metadata.get("size", 0) or 0)
        if recorded_size and path.stat().st_size != recorded_size:
            installed = False
            state = "partial"
            message = "correction model size does not match metadata; use Repair"
    if installed and runtime is None:
        state = "runtime_missing"
        message = "llama-server runtime is not bundled"
    return CorrectionModelStatus(
        repository=DEFAULT_CORRECTION_REPOSITORY,
        filename=DEFAULT_CORRECTION_FILE,
        state=state,
        installed=installed,
        disk_bytes=path.stat().st_size if path.exists() else 0,
        path=str(path),
        revision=str(metadata.get("revision")) if metadata.get("revision") else None,
        sha256=str(metadata.get("sha256")) if metadata.get("sha256") else None,
        runtime_available=runtime is not None,
        runtime_path=str(runtime) if runtime else None,
        message=message,
    )


def _remote_metadata() -> tuple[str | None, str | None, int | None]:
    configure_hf_environment()
    from huggingface_hub import HfApi

    info = HfApi().model_info(DEFAULT_CORRECTION_REPOSITORY, revision="main", files_metadata=True)
    digest: str | None = None
    size: int | None = None
    for sibling in info.siblings or ():
        if getattr(sibling, "rfilename", None) != DEFAULT_CORRECTION_FILE:
            continue
        lfs = getattr(sibling, "lfs", None)
        digest = str(getattr(lfs, "sha256", "") or "") or None
        raw_size = getattr(lfs, "size", None) or getattr(sibling, "size", None)
        size = int(raw_size) if raw_size is not None else None
        break
    return str(info.sha) if getattr(info, "sha", None) else None, digest, size


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


def _download_file(url: str, destination: Path) -> None:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "M5StopWatch/ble-stt"})
            with urllib.request.urlopen(request, timeout=60) as response:
                with destination.open("wb") as stream:
                    shutil.copyfileobj(response, stream, length=1024 * 1024)
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
        _download_file(url, archive)
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


def install_correction_model(config: UserConfig | None = None) -> CorrectionModelStatus:
    del config
    configure_hf_environment()
    from huggingface_hub import hf_hub_download

    install_correction_runtime()

    revision, expected_sha256, expected_size = _remote_metadata()
    destination = correction_model_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    downloaded = Path(
        hf_hub_download(
            repo_id=DEFAULT_CORRECTION_REPOSITORY,
            filename=DEFAULT_CORRECTION_FILE,
            revision=revision or "main",
            local_dir=destination.parent,
            cache_dir=correction_model_dir() / "hub",
        )
    )
    if downloaded.resolve() != destination.resolve():
        shutil.copy2(downloaded, destination)
    if expected_size is not None and destination.stat().st_size != expected_size:
        raise RuntimeError("downloaded correction model has an unexpected size")
    actual_sha256 = sha256_file(destination)
    if expected_sha256 and actual_sha256.casefold() != expected_sha256.casefold():
        destination.unlink(missing_ok=True)
        raise RuntimeError("downloaded correction model failed SHA-256 verification")
    _write_metadata(
        {
            "schema": 1,
            "repository": DEFAULT_CORRECTION_REPOSITORY,
            "filename": DEFAULT_CORRECTION_FILE,
            "revision": revision,
            "sha256": expected_sha256 or actual_sha256,
            "size": destination.stat().st_size,
            "installed_at": time.time(),
        }
    )
    for stale_model in destination.parent.glob("*.gguf"):
        if stale_model != destination:
            stale_model.unlink(missing_ok=True)
    return correction_model_status()


def delete_correction_model(config: UserConfig | None = None) -> CorrectionModelStatus:
    del config
    root = correction_model_dir()
    shutil.rmtree(root / "models", ignore_errors=True)
    shutil.rmtree(root / "hub", ignore_errors=True)
    (root / CORRECTION_METADATA_FILE).unlink(missing_ok=True)
    return correction_model_status()


def repair_correction_model(config: UserConfig | None = None) -> CorrectionModelStatus:
    delete_correction_model(config)
    return install_correction_model(config)


def update_correction_model(config: UserConfig | None = None) -> CorrectionModelStatus:
    return install_correction_model(config)
