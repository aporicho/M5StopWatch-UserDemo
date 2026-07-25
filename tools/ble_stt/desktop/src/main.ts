import { invoke } from "@tauri-apps/api/core";

type HelperResult = {
  ok: boolean;
  code: number | null;
  stdout: string;
  stderr: string;
};

type StatusLine = {
  ok: boolean;
  label: string;
  detail: string;
};

type PermissionStatus = {
  ok: boolean;
  message: string;
};

type StatusPayload = {
  overall: {
    code: string;
    label: string;
    ready: boolean;
  };
  service: {
    installed: boolean;
    running: boolean;
    error: string | null;
  };
  voice: {
    ready: boolean;
    runtime_ok: boolean;
    message: string;
  };
  watch: {
    paired: boolean;
    id: string | null;
    label: string;
  };
  recognition: {
    engine: string;
    model: string;
  };
  permissions: {
    input: PermissionStatus;
    bluetooth: PermissionStatus;
  };
  logs: {
    directory: string;
    latest_event: string | null;
  };
  lines: StatusLine[];
};

type StatusEnvelope = {
  ok: boolean;
  version: string;
  status: StatusPayload;
};

type LogEntry = {
  source: string;
  line: string;
};

type LogsEnvelope = {
  ok: boolean;
  logs: {
    directory: string;
    entries: LogEntry[];
  };
};

type ServiceEnvelope = {
  ok: boolean;
  action: string;
  message: string;
};

const POLL_MS = 3000;
const LOG_LINES = 160;
const SERVICE_SETTLE_MS = 2500;

let latestStatus: StatusEnvelope | null = null;
let latestLogs: LogsEnvelope | null = null;
let refreshTimer: number | null = null;
let permissionRestartInFlight = false;

function byId<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`missing element #${id}`);
  }
  return element as T;
}

function parseHelperJson<T>(result: HelperResult): T {
  const text = result.stdout.trim();
  if (!text) {
    const detail = result.stderr.trim() || `helper exited with ${result.code ?? "unknown"}`;
    throw new Error(detail);
  }
  try {
    return JSON.parse(text) as T;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`invalid helper JSON: ${detail}`);
  }
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function showMessage(text: string, level: "info" | "error" = "info") {
  const element = byId<HTMLElement>("message");
  element.textContent = text;
  element.dataset.level = level;
  element.hidden = false;
}

function clearMessage() {
  byId<HTMLElement>("message").hidden = true;
}

function setButtonsDisabled(disabled: boolean) {
  document.querySelectorAll<HTMLButtonElement>("button").forEach((button) => {
    button.disabled = disabled;
  });
}

function renderStatus(payload: StatusEnvelope) {
  latestStatus = payload;
  const status = payload.status;
  const state = byId<HTMLElement>("overall-state");
  state.textContent = status.overall.label;
  state.dataset.state = status.overall.code;

  byId<HTMLElement>("last-updated").textContent = new Date().toLocaleTimeString();
  byId<HTMLElement>("bluetooth-detail").textContent = status.permissions.bluetooth.message;
  byId<HTMLElement>("input-detail").textContent = status.permissions.input.message;
  byId<HTMLElement>("log-directory").textContent = status.logs.directory;

  const list = byId<HTMLElement>("status-list");
  list.replaceChildren(
    ...status.lines.map((line) => {
      const wrapper = document.createElement("div");
      wrapper.className = "status-row";

      const term = document.createElement("dt");
      term.textContent = line.label;

      const detail = document.createElement("dd");
      detail.textContent = line.detail;

      const mark = document.createElement("span");
      mark.className = line.ok ? "dot ok" : "dot fail";
      mark.title = line.ok ? "OK" : "Needs attention";

      wrapper.append(mark, term, detail);
      return wrapper;
    }),
  );
}

function renderLogs(payload: LogsEnvelope) {
  latestLogs = payload;
  const lines = payload.logs.entries.map((entry) => `[${entry.source}] ${entry.line}`);
  byId<HTMLElement>("log-directory").textContent = payload.logs.directory;
  byId<HTMLPreElement>("logs").textContent = lines.length ? lines.join("\n") : "No logs yet";
}

async function loadStatus() {
  const result = await invoke<HelperResult>("helper_status");
  const payload = parseHelperJson<StatusEnvelope>(result);
  renderStatus(payload);
}

async function loadLogs() {
  const result = await invoke<HelperResult>("helper_logs", { lines: LOG_LINES });
  const payload = parseHelperJson<LogsEnvelope>(result);
  renderLogs(payload);
}

function serviceNeedsInputPermissionRestart(status: StatusPayload) {
  const voiceMessage = status.voice.message.toLowerCase();
  return (
    status.service.running &&
    status.permissions.input.ok &&
    !status.voice.ready &&
    (status.overall.code === "input_blocked" || voiceMessage.includes("accessibility permission"))
  );
}

async function restartAfterInputPermissionGrant() {
  if (!latestStatus || !serviceNeedsInputPermissionRestart(latestStatus.status) || permissionRestartInFlight) {
    return false;
  }
  permissionRestartInFlight = true;
  try {
    showMessage("input permission granted; restarting service");
    const payload = await invokeServiceAction("restart");
    showMessage(payload.message, payload.ok ? "info" : "error");
    if (payload.ok) {
      await sleep(SERVICE_SETTLE_MS);
      await Promise.all([loadStatus(), loadLogs()]);
    }
    return payload.ok;
  } finally {
    permissionRestartInFlight = false;
  }
}

async function refreshAll() {
  try {
    await Promise.all([loadStatus(), loadLogs()]);
    if (await restartAfterInputPermissionGrant()) {
      return;
    }
    clearMessage();
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    showMessage(detail, "error");
  }
}

async function invokeServiceAction(action: string) {
  const result = await invoke<HelperResult>("service_action", { action });
  return parseHelperJson<ServiceEnvelope>(result);
}

async function runServiceAction(action: string) {
  setButtonsDisabled(true);
  try {
    const payload = await invokeServiceAction(action);
    showMessage(payload.message, payload.ok ? "info" : "error");
    if (payload.ok && ["install", "start", "restart"].includes(action)) {
      await sleep(SERVICE_SETTLE_MS);
    }
    await refreshAll();
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    showMessage(detail, "error");
  } finally {
    setButtonsDisabled(false);
  }
}

async function openPermission(kind: "bluetooth" | "input") {
  setButtonsDisabled(true);
  try {
    const result = await invoke<HelperResult>("open_permission", { kind });
    const payload = parseHelperJson<ServiceEnvelope>(result);
    showMessage(payload.message, payload.ok ? "info" : "error");
    if (payload.ok && kind === "input" && latestStatus?.status.service.running) {
      showMessage("input permission granted; restarting service");
      const restart = await invokeServiceAction("restart");
      showMessage(restart.message, restart.ok ? "info" : "error");
      if (restart.ok) {
        await sleep(SERVICE_SETTLE_MS);
      }
    }
    await refreshAll();
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    showMessage(detail, "error");
  } finally {
    setButtonsDisabled(false);
  }
}

async function openLogsFolder() {
  try {
    await invoke("open_logs");
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    showMessage(detail, "error");
  }
}

async function copyDiagnostics() {
  try {
    const status = latestStatus ?? parseHelperJson<StatusEnvelope>(await invoke<HelperResult>("helper_status"));
    const logs = latestLogs ?? parseHelperJson<LogsEnvelope>(await invoke<HelperResult>("helper_logs", { lines: LOG_LINES }));
    await navigator.clipboard.writeText(
      JSON.stringify(
        {
          generated_at: new Date().toISOString(),
          status,
          logs,
        },
        null,
        2,
      ),
    );
    showMessage("diagnostics copied");
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    showMessage(detail, "error");
  }
}

function bindActions() {
  byId<HTMLButtonElement>("install-service").addEventListener("click", () => runServiceAction("install"));
  byId<HTMLButtonElement>("start-service").addEventListener("click", () => runServiceAction("start"));
  byId<HTMLButtonElement>("stop-service").addEventListener("click", () => runServiceAction("stop"));
  byId<HTMLButtonElement>("restart-service").addEventListener("click", () => runServiceAction("restart"));
  byId<HTMLButtonElement>("refresh").addEventListener("click", refreshAll);
  byId<HTMLButtonElement>("open-logs").addEventListener("click", openLogsFolder);
  byId<HTMLButtonElement>("copy-diagnostics").addEventListener("click", copyDiagnostics);
  byId<HTMLButtonElement>("open-bluetooth").addEventListener("click", () => openPermission("bluetooth"));
  byId<HTMLButtonElement>("open-input").addEventListener("click", () => openPermission("input"));
}

window.addEventListener("DOMContentLoaded", () => {
  bindActions();
  refreshAll();
  refreshTimer = window.setInterval(refreshAll, POLL_MS);
});

window.addEventListener("beforeunload", () => {
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer);
  }
});
