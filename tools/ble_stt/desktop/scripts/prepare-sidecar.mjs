import { chmodSync, copyFileSync, cpSync, existsSync, mkdirSync, rmSync, statSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const desktopRoot = resolve(here, "..");
const bleRoot = resolve(desktopRoot, "..");
const resourceRoot = resolve(desktopRoot, "src-tauri", "resources", "ble-stt-helper");
const helperName = process.platform === "win32" ? "m5stopwatch-ble-stt.exe" : "m5stopwatch-ble-stt";

function appBundleForPath(path) {
  let current = dirname(path);
  while (current && current !== dirname(current)) {
    if (basename(current).endsWith(".app")) {
      return current;
    }
    current = dirname(current);
  }
  return null;
}

const explicit = process.env.BLE_STT_SIDECAR ? [resolve(process.env.BLE_STT_SIDECAR)] : [];
const candidates = [
  ...explicit,
  join(bleRoot, "dist-macos", "M5StopWatch.app", "Contents", "MacOS", "M5StopWatch"),
  join(bleRoot, "dist-macos", "M5StopWatch", "M5StopWatch"),
  join(bleRoot, "dist-linux", "m5stopwatch-ble-stt", "m5stopwatch-ble-stt"),
  join(bleRoot, "dist-linux", "m5stopwatch-ble-stt"),
  join(bleRoot, "dist-windows", "M5StopWatch", "m5stopwatch-ble-stt.exe"),
  join(bleRoot, "dist-windows", "m5stopwatch-ble-stt.exe"),
];
const sourceBinary = candidates.find((path) => existsSync(path) && statSync(path).isFile());

if (!sourceBinary) {
  console.error("Could not find a packaged ble-stt helper.");
  console.error("Set BLE_STT_SIDECAR to the helper binary, or build the platform helper first.");
  process.exit(1);
}

const sourceDir = dirname(sourceBinary);
const hasPyInstallerInternal = existsSync(join(sourceDir, "_internal"));
const sourceApp = process.platform === "darwin" ? appBundleForPath(sourceBinary) : null;

rmSync(resourceRoot, { recursive: true, force: true });
mkdirSync(resourceRoot, { recursive: true });

if (sourceApp) {
  const targetApp = join(resourceRoot, basename(sourceApp));
  execFileSync("/usr/bin/ditto", ["--noextattr", "--noqtn", sourceApp, targetApp], { stdio: "inherit" });
  execFileSync("/usr/bin/xattr", ["-cr", targetApp], { stdio: "ignore" });
  chmodSync(join(targetApp, "Contents", "MacOS", basename(sourceBinary)), 0o755);
} else if (hasPyInstallerInternal) {
  for (const entry of ["_internal", basename(sourceBinary)]) {
    cpSync(join(sourceDir, entry), join(resourceRoot, entry), { recursive: true });
  }
  copyFileSync(sourceBinary, join(resourceRoot, helperName));
} else {
  copyFileSync(sourceBinary, join(resourceRoot, helperName));
}

if (process.platform !== "win32") {
  if (existsSync(join(resourceRoot, helperName))) {
    chmodSync(join(resourceRoot, helperName), 0o755);
  }
  if (hasPyInstallerInternal && existsSync(join(resourceRoot, basename(sourceBinary)))) {
    chmodSync(join(resourceRoot, basename(sourceBinary)), 0o755);
  }
}

console.log(`Prepared helper resource: ${resourceRoot}`);
