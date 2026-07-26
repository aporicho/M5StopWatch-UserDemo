import { invoke } from "@tauri-apps/api/core"

export const POLL_MS = 3000
export const TELEMETRY_POLL_MS = 500
export const LOG_LINES = 160
export const SERVICE_SETTLE_MS = 2500
export const MODEL_IDS = ["small", "medium", "large", "turbo"] as const

export type HelperResult = {
  ok: boolean
  code: number | null
  stdout: string
  stderr: string
}

export type StatusLine = {
  ok: boolean
  label: string
  detail: string
}

export type PermissionStatus = {
  ok: boolean
  message: string
}

export type ModelStatus = {
  selected: string
  engine: string
  requested_engine: string
  resolved: string
  source: string
  state: string
  installed: boolean
  disk_bytes: number
  cache_dir: string
  update_available: boolean
  message: string
}

export type StatusPayload = {
  overall: {
    code: string
    label: string
    ready: boolean
  }
  service: {
    installed: boolean
    running: boolean
    error: string | null
  }
  voice: {
    ready: boolean
    runtime_ok: boolean
    message: string
  }
  watch: {
    paired: boolean
    id: string | null
    label: string
  }
  recognition: {
    engine: string
    model: string
  }
  model: ModelStatus
  permissions: {
    input: PermissionStatus
    bluetooth: PermissionStatus
  }
  logs: {
    directory: string
    latest_event: string | null
  }
  lines: StatusLine[]
}

export type StatusEnvelope = {
  ok: boolean
  version: string
  status: StatusPayload
}

export type LogEntry = {
  source: string
  line: string
  time?: string
  level?: string
  component?: string
  context?: string
  message?: string
}

export type StructuredLogEntry = {
  source: string
  time: string
  level: string
  component: string
  context: string
  message: string
}

export type LogsEnvelope = {
  ok: boolean
  logs: {
    directory: string
    entries: LogEntry[]
  }
}

export type RuntimeTelemetry = {
  schema: number
  stage: string
  session_id: number | null
  audio: {
    level: number
    peak: number
    seconds: number
    frames: number
  }
  recognition: {
    busy: boolean
    mode: string
  }
  last_text: {
    text: string
    final: boolean
    time: number
  } | null
  error: string | null
  updated_at: number
  stale: boolean
  age_seconds: number | null
}

export type TelemetryEnvelope = {
  ok: boolean
  telemetry: RuntimeTelemetry
}

export type ServiceAction = "install" | "start" | "stop" | "restart"
export type ModelAction = "use" | "install" | "update" | "repair" | "delete"
export type PermissionKind = "bluetooth" | "input"

export type ServiceEnvelope = {
  ok: boolean
  action: string
  message: string
}

export type ModelEnvelope = {
  ok: boolean
  action: string
  message?: string
  model: ModelStatus
}

const LOG_RECORD_PATTERN =
  /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s+([A-Z]+)\s+\[([^\]]+)\]\s+([^:]+):\s*(.*)$/

export function parseHelperJson<T>(result: HelperResult): T {
  const text = result.stdout.trim()
  if (!text) {
    const detail =
      result.stderr.trim() || `helper exited with ${result.code ?? "unknown"}`
    throw new Error(detail)
  }
  try {
    return JSON.parse(text) as T
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error)
    throw new Error(`invalid helper JSON: ${detail}`)
  }
}

export function sleep(ms: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, ms))
}

export function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) {
    return "Not installed"
  }

  const units = ["B", "KB", "MB", "GB"]
  let size = value
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`
}

export function displayLogText(value: string) {
  return value.replace(/\s+/g, " ").trim()
}

export function structuredLogEntry(entry: LogEntry): StructuredLogEntry {
  const existingMessage = entry.message ?? ""
  if (entry.time || entry.level || entry.component || existingMessage) {
    return {
      source: entry.source,
      time: entry.time || "--",
      level:
        entry.level || (entry.source.endsWith("error.log") ? "ERROR" : "INFO"),
      component: entry.component || entry.source,
      context: entry.context || "",
      message: existingMessage || displayLogText(entry.line),
    }
  }

  const match = entry.line.match(LOG_RECORD_PATTERN)
  if (match) {
    let component = match[4]
    let message = displayLogText(match[5])
    for (const stream of ["stdout", "stderr"]) {
      const prefix = `${stream}: `
      if (message.startsWith(prefix)) {
        component = stream
        message = message.slice(prefix.length)
        break
      }
    }
    return {
      source: entry.source,
      time: match[1],
      level: match[2],
      context: match[3],
      component,
      message,
    }
  }

  return {
    source: entry.source,
    time: "--",
    level: entry.source.endsWith("error.log") ? "ERROR" : "INFO",
    component: entry.source,
    context: "",
    message: displayLogText(entry.line),
  }
}

export function modelBlocksServiceStart(model: ModelStatus) {
  return !model.installed || ["missing", "installing", "error"].includes(model.state)
}

export function serviceNeedsInputPermissionRestart(status: StatusPayload) {
  const voiceMessage = status.voice.message.toLowerCase()
  return (
    status.service.running &&
    status.permissions.input.ok &&
    !status.voice.ready &&
    (status.overall.code === "input_blocked" ||
      voiceMessage.includes("accessibility permission"))
  )
}

export function modelActionMessage(payload: ModelEnvelope) {
  if (payload.message) {
    return payload.message
  }
  const label = payload.model.selected
  return `${label}: ${payload.model.message}`
}

export async function helperStatus() {
  const result = await invoke<HelperResult>("helper_status")
  return parseHelperJson<StatusEnvelope>(result)
}

export async function helperLogs(lines = LOG_LINES) {
  const result = await invoke<HelperResult>("helper_logs", { lines })
  return parseHelperJson<LogsEnvelope>(result)
}

export async function helperTelemetry() {
  const result = await invoke<HelperResult>("helper_telemetry")
  return parseHelperJson<TelemetryEnvelope>(result)
}

export async function invokeServiceAction(action: ServiceAction) {
  const result = await invoke<HelperResult>("service_action", { action })
  return parseHelperJson<ServiceEnvelope>(result)
}

export async function invokeModelAction(action: ModelAction, model: string) {
  const result = await invoke<HelperResult>("model_action", { action, model })
  return parseHelperJson<ModelEnvelope>(result)
}

export async function openPermissionPanel(kind: PermissionKind) {
  const result = await invoke<HelperResult>("open_permission", { kind })
  return parseHelperJson<ServiceEnvelope>(result)
}

export async function openLogsFolder() {
  await invoke("open_logs")
}
