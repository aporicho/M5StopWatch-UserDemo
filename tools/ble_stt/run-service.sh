#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$(basename -- "${SCRIPT_DIR}")" == "bin" ]]; then
    VENV="$(dirname -- "${SCRIPT_DIR}")"
else
    VENV="${SCRIPT_DIR}/.venv"
fi

# NVIDIA's pip wheels keep their shared libraries outside the normal loader
# path. Discover them before Python starts, as required by CTranslate2.
if CUDA_LIBRARY_PATH="$(${VENV}/bin/python -c '
from importlib.util import find_spec

paths = []
for package in ("nvidia.cublas.lib", "nvidia.cudnn.lib"):
    spec = find_spec(package)
    if spec is None or spec.submodule_search_locations is None:
        raise RuntimeError(f"CUDA runtime package {package} was not found")
    paths.append(next(iter(spec.submodule_search_locations)))
print(":".join(paths))
' 2>/dev/null)"; then
    export LD_LIBRARY_PATH="${CUDA_LIBRARY_PATH}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
fi

exec "${VENV}/bin/ble-stt" run "$@"
