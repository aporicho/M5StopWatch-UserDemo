import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { chmodSync, copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { arch, platform, tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// b9000 is the newest upstream package in our compatibility window that is
// built for macOS 14. Newer official artifacts currently require macOS 26.
const LLAMA_VERSION = "b9000";
const assets = {
  "darwin-arm64": ["llama-b9000-bin-macos-arm64.tar.gz", "e4531e819dd9fe4add199db998df55cf8bd20e18a67cbd1449b49409dc01c642"],
  "darwin-x64": ["llama-b9000-bin-macos-x64.tar.gz", "82b81368266b6290509c221484df073624c5325239d6f375d60589fa760519bc"],
  "linux-arm64": ["llama-b9000-bin-ubuntu-arm64.tar.gz", "575bc6c6d7171475846b96476470612d1158870506fb52fd11cf0d9cceb511b4"],
  "linux-x64": ["llama-b9000-bin-ubuntu-x64.tar.gz", "4cd8ffbb0425c49c50b56ff6b3d0a9add9ad1ae469611b9edd038e20d6cdab36"],
  "win32-arm64": ["llama-b9000-bin-win-cpu-arm64.zip", "bdb73edd8b05b9d5a0ba860e98e312f5c8aa591300a851b6c2d7359a139536f3"],
  "win32-x64": ["llama-b9000-bin-win-cpu-x64.zip", "8294e287933d3212aa93a32e1ceb800722bede14d9692d405679d4ba77cf05db"],
};

const here = dirname(fileURLToPath(import.meta.url));
const output = resolve(
  process.env.BLE_STT_LLAMA_OUTPUT || join(here, "..", "src-tauri", "resources", "llama")
);
if (process.env.BLE_STT_SKIP_LLAMA_RUNTIME === "1") {
  rmSync(output, { recursive: true, force: true });
  mkdirSync(output, { recursive: true });
  writeFileSync(join(output, ".gitkeep"), "");
  console.log("Skipping outer llama.cpp runtime; the signed nested helper owns it.");
  process.exit(0);
}
const key = `${platform()}-${arch()}`;
const selected = assets[key];
if (!selected) {
  console.error(`No pinned llama.cpp runtime for ${key}`);
  process.exit(1);
}
const [asset, expectedSha256] = selected;
const url = `https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_VERSION}/${asset}`;
const temporary = join(tmpdir(), `m5stopwatch-llama-${process.pid}-${Date.now()}`);
const archive = join(temporary, asset);
const extracted = join(temporary, "extracted");

function walk(root) {
  const result = [];
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) result.push(...walk(path));
    else result.push(path);
  }
  return result;
}

try {
  mkdirSync(extracted, { recursive: true });
  console.log(`Downloading pinned llama.cpp ${LLAMA_VERSION}: ${asset}`);
  execFileSync("curl", ["-fL", "--retry", "3", "-o", archive, url], { stdio: "inherit" });
  const actualSha256 = createHash("sha256").update(readFileSync(archive)).digest("hex");
  if (actualSha256 !== expectedSha256) {
    throw new Error(`llama.cpp archive SHA-256 mismatch: ${actualSha256}`);
  }
  execFileSync("tar", ["-xf", archive, "-C", extracted], { stdio: "inherit" });
  const files = walk(extracted);
  const serverName = platform() === "win32" ? "llama-server.exe" : "llama-server";
  const server = files.find((path) => basename(path) === serverName && statSync(path).isFile());
  if (!server) throw new Error(`Archive does not contain ${serverName}`);
  const runtimeRoot = dirname(server);
  const runtimeFiles = readdirSync(runtimeRoot).filter((name) => {
    if (name === serverName || name === "LICENSE") return true;
    if (platform() === "darwin") return name.endsWith(".dylib") || name.endsWith(".metal");
    if (platform() === "win32") return name.toLowerCase().endsWith(".dll");
    return name.includes(".so");
  });
  rmSync(output, { recursive: true, force: true });
  mkdirSync(output, { recursive: true });
  for (const name of runtimeFiles) copyFileSync(join(runtimeRoot, name), join(output, name));
  if (platform() !== "win32") chmodSync(join(output, serverName), 0o755);
  writeFileSync(
    join(output, "runtime.json"),
    JSON.stringify({ version: LLAMA_VERSION, asset, sha256: expectedSha256, source: url }, null, 2) + "\n"
  );
  if (!existsSync(join(output, serverName))) throw new Error("llama-server copy failed");
  console.log(`Prepared llama.cpp runtime: ${output}`);
} finally {
  rmSync(temporary, { recursive: true, force: true });
}
