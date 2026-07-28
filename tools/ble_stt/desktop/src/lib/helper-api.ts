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

export type VoicePreferences = {
  correction: {
    enabled: boolean
    mode: "conservative"
    languages: string[]
    model: string
    repository: string
    filename: string
    glossary: string[]
    standard_lexicon_enabled: boolean
    lexicon_packs: string[]
    timeout_seconds: number
  }
  typing: {
    enabled: boolean
    characters_per_second: number
    auto_accelerate: boolean
    max_characters_per_second: number
  }
}

export type CorrectionModelStatus = {
  model: string
  repository: string
  filename: string
  display_name: string
  state: string
  installed: boolean
  ready: boolean
  disk_bytes: number
  expected_disk_bytes: number
  stale_disk_bytes: number
  path: string
  revision: string | null
  sha256: string | null
  runtime_available: boolean
  runtime_path: string | null
  message: string
}

export type CorrectionModelPreset = {
  id: string
  label: string
  description: string
  status: CorrectionModelStatus
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
    paused: boolean
    pause_reason: string | null
  }
  voice: {
    ready: boolean
    runtime_ok: boolean
    message: string
  }
  watch: {
    paired: boolean
    connected?: boolean
    connection_state?: "offline" | "waiting_system_connection" | "attaching" | "ready"
    id: string | null
    label: string
  }
  recognition: {
    engine: string
    model: string
  }
  model: ModelStatus
  preferences: VoicePreferences
  correction_model: CorrectionModelStatus
  correction_models: CorrectionModelPreset[]
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
  performance?: {
    revision: number
    current: {
      trace_id: string
      kind: string
      session_id: number | null
      mode: string | null
      phase: string
      elapsed_ms: number
    } | null
    latest: {
      trace_id: string
      kind: string
      session_id: number | null
      mode: string | null
      outcome: string
      duration_ms: number
      metrics: Record<string, number | string | null>
    } | null
  }
  last_text: {
    text: string
    raw_text?: string
    corrected_text?: string
    final: boolean
    time: number
    replacement?: string
    correction?: {
      state: string
      changed: boolean
      reason: string
      latency_ms: number
      model?: string | null
    }
  } | null
  last_command: {
    text: string
    matched: boolean
    phrase: string | null
    action: string | null
    score: number
    reason: string
    time: number
    error?: string
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

export type PerformanceSpan = {
  name: string
  lane: "device" | "ble" | "recognition" | "correction" | "output" | "command" | "host" | "lifecycle" | string
  category: "work" | "io" | "wait" | "intentional" | string
  start_ms: number | null
  duration_ms: number
  count?: number
  mean_ms?: number
  max_ms?: number
}

export type PerformanceRecord = {
  schema: number
  trace_id: string
  kind: "session" | "lifecycle"
  session_id: number | null
  mode: "dictation" | "command" | null
  outcome: string
  error_code: string | null
  configuration: Record<string, string | number | boolean | null>
  started_at: number
  completed_at: number
  duration_ms: number
  clock_sync: {
    rtt_ms: number
    uncertainty_ms: number
    merged: boolean
  } | null
  spans: PerformanceSpan[]
  metrics: Record<string, number | string | null>
}

export type PerformanceSnapshot = {
  schema: number
  revision: number
  updated_at: number | null
  sessions: PerformanceRecord[]
  lifecycles: PerformanceRecord[]
}

export type PerformanceEnvelope = {
  ok: boolean
  performance: PerformanceSnapshot
}

export type ServiceAction = "install" | "start" | "stop" | "restart"
export type ModelAction = "use" | "install" | "update" | "repair" | "delete"
export type CorrectionModelAction =
  | "use-model"
  | "install-model"
  | "update-model"
  | "repair-model"
  | "delete-model"
export type PermissionKind = "bluetooth" | "input"

export type MappingDefinition = {
  id: string
  code: number
  label: string
  locked?: boolean
}

export type MappingOption = {
  label: string
  value: number
}

export type MappingEntry = {
  event: string
  action: string
  param0: number
  param1: number
  param2: number
  flags?: number
  locked?: boolean
}

export type MappingPayload = {
  schema: number
  revision: number
  updated_at: number | null
  entries: MappingEntry[]
}

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

export type VoiceSettingsEnvelope = {
  ok: boolean
  action: string
  message?: string
  settings: VoicePreferences
  correction_model: CorrectionModelStatus
  correction_models: CorrectionModelPreset[]
}

export type MappingEnvelope = {
  ok: boolean
  schema: number
  mapping: MappingPayload
  events: MappingDefinition[]
  actions: MappingDefinition[]
  keyOptions: MappingOption[]
  modifierOptions: MappingOption[]
  mouseButtons: MappingOption[]
  mediaControls: MappingOption[]
}

export type CommandEntry = {
  id: string
  phrase: string
  aliases: string[]
  enabled: boolean
  action: string
  param0: number
  param1: number
  param2: number
  flags?: number
}

export type CommandPayload = {
  schema: number
  revision: number
  updated_at: number | null
  entries: CommandEntry[]
}

export type CommandEnvelope = {
  ok: boolean
  schema: number
  commands: CommandPayload
  actions: MappingDefinition[]
  keyOptions: MappingOption[]
  modifierOptions: MappingOption[]
  mouseButtons: MappingOption[]
  mediaControls: MappingOption[]
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

export async function helperPerformance() {
  const result = await invoke<HelperResult>("helper_performance")
  return parseHelperJson<PerformanceEnvelope>(result)
}

export async function clearPerformance() {
  const result = await invoke<HelperResult>("performance_clear")
  return parseHelperJson<PerformanceEnvelope>(result)
}

export async function helperMappings() {
  const result = await invoke<HelperResult>("mapping_status")
  return parseHelperJson<MappingEnvelope>(result)
}

export async function helperCommands() {
  const result = await invoke<HelperResult>("command_status")
  return parseHelperJson<CommandEnvelope>(result)
}

export async function saveMappings(entries: MappingEntry[]) {
  const result = await invoke<HelperResult>("mapping_save", {
    payload: JSON.stringify({ entries }),
  })
  return parseHelperJson<MappingEnvelope>(result)
}

export async function resetMappings() {
  const result = await invoke<HelperResult>("mapping_reset")
  return parseHelperJson<MappingEnvelope>(result)
}

export async function saveCommands(entries: CommandEntry[]) {
  const result = await invoke<HelperResult>("command_save", {
    payload: JSON.stringify({ entries }),
  })
  return parseHelperJson<CommandEnvelope>(result)
}

export async function resetCommands() {
  const result = await invoke<HelperResult>("command_reset")
  return parseHelperJson<CommandEnvelope>(result)
}

export async function invokeServiceAction(action: ServiceAction) {
  const result = await invoke<HelperResult>("service_action", { action })
  return parseHelperJson<ServiceEnvelope>(result)
}

export async function invokeModelAction(action: ModelAction, model: string) {
  const result = await invoke<HelperResult>("model_action", { action, model })
  return parseHelperJson<ModelEnvelope>(result)
}

export async function saveVoiceSettings(settings: VoicePreferences) {
  const result = await invoke<HelperResult>("voice_settings_save", {
    payload: JSON.stringify(settings),
  })
  return parseHelperJson<VoiceSettingsEnvelope>(result)
}

export async function invokeCorrectionModelAction(
  action: CorrectionModelAction,
  model: string
) {
  const result = await invoke<HelperResult>("correction_model_action", { action, model })
  return parseHelperJson<VoiceSettingsEnvelope>(result)
}

export async function openPermissionPanel(kind: PermissionKind) {
  const result = await invoke<HelperResult>("open_permission", { kind })
  return parseHelperJson<ServiceEnvelope>(result)
}

export async function openLogsFolder() {
  await invoke("open_logs")
}
