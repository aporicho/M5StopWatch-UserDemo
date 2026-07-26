import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const desktopRoot = resolve(here, "..");
const bleRoot = resolve(desktopRoot, "..");
const engine = process.platform === "darwin" ? "mlx" : "faster-whisper";
const repo = engine === "mlx" ? "mlx-community/whisper-small-mlx" : "Systran/faster-whisper-small";
const target = process.env.BLE_STT_STARTER_MODEL_DIR
  ? resolve(process.env.BLE_STT_STARTER_MODEL_DIR)
  : join(bleRoot, "starter-models", engine, "small");
const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");

mkdirSync(target, { recursive: true });

const code = `
import sys
from huggingface_hub import snapshot_download

repo, target = sys.argv[1], sys.argv[2]
snapshot_download(repo_id=repo, revision="main", local_dir=target)
print(f"Prepared starter model {repo} at {target}")
`;

execFileSync(python, ["-c", code, repo, target], { stdio: "inherit" });
