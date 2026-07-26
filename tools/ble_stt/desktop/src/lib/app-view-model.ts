import {
  modelBlocksServiceStart,
  type CommandEntry,
  type CommandEnvelope,
  type MappingEntry,
  type MappingEnvelope,
  type MappingOption,
  type RuntimeTelemetry,
  type StatusPayload,
  type StructuredLogEntry,
  type TelemetryEnvelope,
} from "@/lib/helper-api"
import type { Translator } from "@/lib/i18n"

export type BadgeVariant = "default" | "secondary" | "destructive" | "outline"

export type Notice = {
  level: "info" | "error"
  message: string
}

export type DailyStateKey =
  | "loading"
  | "ready"
  | "listening"
  | "recognizing"
  | "inserted"
  | "waiting_watch"
  | "preparing_voice"
  | "service_paused"
  | "needs_attention"

export type DailyState = {
  key: DailyStateKey
  label: string
  title: string
  description: string
  badgeVariant: BadgeVariant
  action?: "start" | "retry" | "install-model" | "request-bluetooth" | "request-input" | "diagnostics"
}

export type ActivityItem = {
  key: string
  time: string
  label: string
  detail: string
  variant: BadgeVariant
}

export type PageKey = "home" | "map" | "command"

export type DictationSnapshot = {
  text: string
  time: string
  final: boolean
} | null

export const MODEL_OPTIONS = [
  {
    value: "small",
    label: "Small",
    detail: "Fastest startup and lowest disk use.",
  },
  {
    value: "medium",
    label: "Medium",
    detail: "Balanced recognition quality for daily use.",
  },
  {
    value: "large",
    label: "Large",
    detail: "Higher accuracy with a larger download.",
  },
  {
    value: "turbo",
    label: "Turbo",
    detail: "Fast large-model variant when available.",
  },
] as const

export const WHEEL_MULTIPLIER_OPTIONS: MappingOption[] = [
  { label: "1x", value: 1 },
  { label: "2x", value: 2 },
  { label: "3x", value: 3 },
  { label: "4x", value: 4 },
]

export const WHEEL_DIRECTION_OPTIONS: MappingOption[] = [
  { label: "Normal", value: 0 },
  { label: "Inverted", value: 1 },
]

export const MODIFIER_TOGGLE_OPTIONS: MappingOption[] = [
  { label: "Ctrl", value: 1 },
  { label: "Shift", value: 2 },
  { label: "Alt", value: 4 },
  { label: "Cmd / Win", value: 8 },
]

export const COMMAND_ACTION_IDS = new Set([
  "none",
  "hid.keyboard.tap",
  "hid.mouse.wheel",
  "hid.mouse.click",
  "hid.media.control",
  "device.pair_new_computer",
])

const COMMON_MAPPING_EVENT_IDS = new Set([
  "button.left.tap",
  "button.left.hold",
  "button.left.release_after_hold",
  "button.right.tap",
  "button.right.hold",
  "button.right.release_after_hold",
  "touch.scroll_delta",
  "touch.triple_tap",
  "button.both.hold",
])

export const DEFAULT_DAILY_STATE: DailyState = {
  key: "loading",
  label: "Checking",
  title: "Checking voice input",
  description: "Reading watch, service, model, and telemetry state.",
  badgeVariant: "secondary",
}

export const DIAGNOSTIC_ROWS = [
  ["overall", "Status"],
  ["service", "Service"],
  ["watch", "Watch"],
  ["voice", "Voice"],
  ["model", "Model"],
  ["input", "Text input"],
  ["bluetooth", "Bluetooth"],
  ["logs", "Logs"],
] as const

export type DiagnosticKey = (typeof DIAGNOSTIC_ROWS)[number][0]

export function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

export function actionTitle(action: string) {
  return `${action.slice(0, 1).toUpperCase()}${action.slice(1)}`
}

export function modelLabel(value: string | null | undefined) {
  if (!value) {
    return "Unknown"
  }
  return MODEL_OPTIONS.find((model) => model.value === value)?.label ?? value
}

export function modelDisplayLabel(value: string | null | undefined, t: Translator) {
  if (!value) {
    return t("common.unknown", "Unknown")
  }
  return t(`model.${value}.label`, modelLabel(value))
}

export function modelDetail(value: string, t: Translator) {
  return MODEL_OPTIONS.find((model) => model.value === value)
    ? t(`model.${value}.detail`)
    : t("settings.custom_model_detail", "Custom model selected by the helper.")
}

export function localizedDailyState(state: DailyState, t: Translator): DailyState {
  if (state.key === "needs_attention") {
    switch (state.action) {
      case "request-bluetooth":
        return {
          ...state,
          label: t("state.bluetooth_blocked.label"),
          title: t("state.bluetooth_blocked.title"),
          description: t("state.bluetooth_blocked.description"),
        }
      case "request-input":
        return {
          ...state,
          label: t("state.input_blocked.label"),
          title: t("state.input_blocked.title"),
          description: t("state.input_blocked.description"),
        }
      case "install-model":
        return {
          ...state,
          label: t("state.model_missing.label"),
          title: t("state.model_missing.title"),
          description: t("state.model_missing.description"),
        }
      case "diagnostics":
        return {
          ...state,
          label: t("state.service_error.label"),
          title: t("state.service_error.title"),
        }
    }
  }

  return {
    ...state,
    label: t(`state.${state.key}.label`, state.label),
    title: t(`state.${state.key}.title`, state.title),
    description: t(`state.${state.key}.description`, state.description),
  }
}

export function logLevelVariant(level: string): BadgeVariant {
  const normalized = level.toUpperCase()
  if (["ERROR", "CRITICAL", "FATAL"].includes(normalized)) {
    return "destructive"
  }
  if (["WARNING", "WARN"].includes(normalized)) {
    return "secondary"
  }
  if (["DEBUG", "TRACE"].includes(normalized)) {
    return "outline"
  }
  return "default"
}

export function compactTime(value: string) {
  if (!value || value === "--") {
    return "--"
  }
  const [, time] = value.split(" ")
  return time ? time.slice(0, 8) : value
}

export function formatUnixTime(value: number | null | undefined) {
  if (!value || !Number.isFinite(value)) {
    return "--"
  }
  return new Date(value * 1000).toLocaleTimeString()
}

export function ratio(value: number | null | undefined) {
  if (!Number.isFinite(value ?? NaN)) {
    return 0
  }
  return Math.max(0, Math.min(1, Number(value)))
}

export function percent(value: number | null | undefined) {
  return `${Math.round(ratio(value) * 100)}%`
}

export function mappingDefaults(action: string) {
  switch (action) {
    case "hid.keyboard.tap":
      return { param0: 0x29, param1: 0, param2: 0, flags: 0 }
    case "hid.mouse.wheel":
      return { param0: 1, param1: 0, param2: 0, flags: 0 }
    case "hid.mouse.click":
      return { param0: 1, param1: 0, param2: 0, flags: 0 }
    case "hid.media.control":
      return { param0: 0, param1: 0, param2: 0x00CD, flags: 0 }
    default:
      return { param0: 0, param1: 0, param2: 0, flags: 0 }
  }
}

export function blankMappingEntry(eventId: string, locked = false): MappingEntry {
  return {
    event: eventId,
    action: locked ? "device.go_home" : "none",
    ...mappingDefaults(locked ? "device.go_home" : "none"),
    locked,
  }
}

export function withMappingAction(entry: MappingEntry, action: string): MappingEntry {
  return {
    ...entry,
    action,
    ...mappingDefaults(action),
  }
}

export function blankCommandEntry(index: number): CommandEntry {
  return {
    id: `command-${Date.now()}-${index}`,
    phrase: "",
    aliases: [],
    enabled: true,
    action: "none",
    ...mappingDefaults("none"),
  }
}

export function commandAsMappingEntry(command: CommandEntry): MappingEntry {
  return {
    event: "command.voice",
    action: command.action,
    param0: command.param0,
    param1: command.param1,
    param2: command.param2,
    flags: command.flags ?? 0,
  }
}

export function commandWithMappingEntry(command: CommandEntry, entry: MappingEntry): CommandEntry {
  return {
    ...command,
    action: entry.action,
    param0: entry.param0,
    param1: entry.param1,
    param2: entry.param2,
    flags: entry.flags ?? 0,
  }
}

export function commandToolsEnvelope(envelope: CommandEnvelope): MappingEnvelope {
  return {
    ok: envelope.ok,
    schema: envelope.schema,
    mapping: {
      schema: envelope.schema,
      revision: envelope.commands.revision,
      updated_at: envelope.commands.updated_at,
      entries: [],
    },
    events: [],
    actions: envelope.actions,
    keyOptions: envelope.keyOptions,
    modifierOptions: envelope.modifierOptions,
    mouseButtons: envelope.mouseButtons,
    mediaControls: envelope.mediaControls,
  }
}

export function mappingOptionValue(value: number | null | undefined) {
  return String(value ?? 0)
}

export function mappingEventLabel(eventId: string, fallback: string, t: Translator) {
  return t(`map.event.${eventId}`, fallback)
}

export function mappingActionLabel(actionId: string, fallback: string | undefined, t: Translator) {
  return t(`map.action.${actionId}`, fallback ?? actionId)
}

export function localizedMappingOptionLabel(label: string, t: Translator) {
  const normalized = label.toLowerCase()
  if (normalized === "none") {
    return t("map.option.none", label)
  }
  if (normalized === "ctrl") {
    return t("map.option.ctrl", label)
  }
  if (normalized === "shift") {
    return t("map.option.shift", label)
  }
  if (normalized === "alt") {
    return t("map.option.alt", label)
  }
  if (normalized === "cmd / win") {
    return t("map.option.cmd_win", label)
  }
  if (normalized === "normal") {
    return t("map.option.normal", label)
  }
  if (normalized === "inverted") {
    return t("map.option.inverted", label)
  }
  return label
}

export function findMappingOption(options: MappingOption[], value: number) {
  return options.find((option) => option.value === value)
}

export function mappingOptionLabel(options: MappingOption[], value: number, t: Translator) {
  const option = findMappingOption(options, value)
  return localizedMappingOptionLabel(option?.label ?? String(value), t)
}

export function modifierLabel(value: number, t: Translator) {
  const labels = MODIFIER_TOGGLE_OPTIONS
    .filter((option) => (value & option.value) !== 0)
    .map((option) => localizedMappingOptionLabel(option.label, t))
  return labels.length ? labels.join("+") : t("map.option.none", "None")
}

export function mappingActionSummary(entry: MappingEntry, envelope: MappingEnvelope, t: Translator) {
  if (entry.locked) {
    return t("mapping.locked_summary", "Fixed safety action")
  }

  const action = envelope.actions.find((item) => item.id === entry.action)

  switch (entry.action) {
    case "none":
      return t("mapping.none_summary", "No action")
    case "hid.keyboard.tap": {
      const key = mappingOptionLabel(envelope.keyOptions, entry.param0, t)
      const modifier = modifierLabel(entry.param1, t)
      return modifier === t("map.option.none", "None") ? key : `${modifier} + ${key}`
    }
    case "hid.mouse.wheel": {
      const speed = mappingOptionLabel(WHEEL_MULTIPLIER_OPTIONS, entry.param0, t)
      const direction = mappingOptionLabel(WHEEL_DIRECTION_OPTIONS, entry.param1, t)
      return `${speed} / ${direction}`
    }
    case "hid.mouse.click":
      return mappingOptionLabel(envelope.mouseButtons, entry.param0, t)
    case "hid.media.control":
      return mappingOptionLabel(envelope.mediaControls, entry.param2, t)
    default:
      return mappingActionLabel(entry.action, action?.label, t)
  }
}

export function mappingIsCommon(eventId: string, entry: MappingEntry) {
  return COMMON_MAPPING_EVENT_IDS.has(eventId) || entry.locked || entry.action !== "none"
}

export function progressValue(value: number | null | undefined) {
  return Math.round(ratio(value) * 100)
}

export function telemetryFresh(telemetry: RuntimeTelemetry | null) {
  return Boolean(telemetry && !telemetry.stale)
}

function isListeningEntry(entry: StructuredLogEntry) {
  const message = entry.message.toLowerCase()
  return message.includes("listening") || message.includes("speech session started")
}

function isRecognizingEntry(entry: StructuredLogEntry) {
  const message = entry.message.toLowerCase()
  return (
    message.includes("recognizing") ||
    message.includes("status=recognizing") ||
    message.includes("speech session ended")
  )
}

function isInsertedEntry(entry: StructuredLogEntry) {
  const message = entry.message.toLowerCase()
  return message.startsWith("[text final]") || message.includes("text_inserted=true")
}

function isPreparingEntry(entry: StructuredLogEntry) {
  const message = entry.message.toLowerCase()
  return (
    message.includes("status=preparing") ||
    message.includes("[model] loading") ||
    message.includes("model] loading")
  )
}

function isReadyEntry(entry: StructuredLogEntry) {
  const message = entry.message.toLowerCase()
  return (
    message.includes("status=ready") ||
    message.includes("speech input ready") ||
    message.includes("mlx ready")
  )
}

function latestRuntimeSignal(entries: StructuredLogEntry[]) {
  for (const entry of entries.slice().reverse()) {
    if (isListeningEntry(entry)) {
      return "listening" as const
    }
    if (isRecognizingEntry(entry)) {
      return "recognizing" as const
    }
    if (isInsertedEntry(entry)) {
      return "inserted" as const
    }
    if (isPreparingEntry(entry)) {
      return "preparing_voice" as const
    }
    if (isReadyEntry(entry)) {
      return "ready" as const
    }
  }

  return null
}

export function latestDictation(
  entries: StructuredLogEntry[],
  telemetry: RuntimeTelemetry | null
): DictationSnapshot {
  if (telemetry?.last_text?.text) {
    return {
      text: telemetry.last_text.text,
      time: formatUnixTime(telemetry.last_text.time),
      final: telemetry.last_text.final,
    }
  }

  for (const entry of entries.slice().reverse()) {
    const text = entry.message
      .replace(/^\[text final\]\s*/i, "")
      .replace(/^\[text\]\s*/i, "")
      .trim()

    if (text !== entry.message && text) {
      return {
        text,
        time: entry.time,
        final: entry.message.toLowerCase().startsWith("[text final]"),
      }
    }
  }

  return null
}

function telemetrySignal(telemetry: RuntimeTelemetry | null): DailyStateKey | null {
  if (!telemetry || telemetry.stale) {
    return null
  }
  if (telemetry.stage === "listening") {
    return "listening"
  }
  if (telemetry.stage === "recognizing") {
    return "recognizing"
  }
  if (telemetry.stage === "inserted") {
    return "inserted"
  }
  if (telemetry.stage === "ready") {
    return "ready"
  }
  if (telemetry.stage === "error") {
    return "needs_attention"
  }
  return null
}

export function telemetryRenderKey(envelope: TelemetryEnvelope | null) {
  const telemetry = envelope?.telemetry
  if (!telemetry) {
    return ""
  }
  return [
    telemetry.stage,
    telemetry.session_id ?? "",
    telemetry.audio.level.toFixed(3),
    telemetry.audio.peak.toFixed(3),
    telemetry.audio.seconds.toFixed(1),
    telemetry.audio.frames,
    telemetry.recognition.busy ? "busy" : "idle",
    telemetry.recognition.mode,
    telemetry.last_text?.text ?? "",
    telemetry.last_text?.final ? "final" : "live",
    telemetry.last_command?.text ?? "",
    telemetry.last_command?.phrase ?? "",
    telemetry.last_command?.matched ? "matched" : "unmatched",
    telemetry.last_command?.reason ?? "",
    telemetry.error ?? "",
    telemetry.stale ? "stale" : "fresh",
  ].join("|")
}

export function deriveDailyState(
  status: StatusPayload | null,
  entries: StructuredLogEntry[],
  telemetry: RuntimeTelemetry | null
): DailyState {
  if (!status) {
    return DEFAULT_DAILY_STATE
  }

  if (!status.permissions.bluetooth.ok) {
    return {
      key: "needs_attention",
      label: "Bluetooth blocked",
      title: "Bluetooth access is needed",
      description: "Allow Bluetooth so the app can stay connected to the watch.",
      badgeVariant: "destructive",
      action: "request-bluetooth",
    }
  }

  if (!status.permissions.input.ok) {
    return {
      key: "needs_attention",
      label: "Input blocked",
      title: "Text input access is needed",
      description: "Allow text input so recognized speech can be inserted into apps.",
      badgeVariant: "destructive",
      action: "request-input",
    }
  }

  if (modelBlocksServiceStart(status.model)) {
    return {
      key: "needs_attention",
      label: "Model missing",
      title: "Speech model is not ready",
      description: "Install the selected model before starting voice input.",
      badgeVariant: "destructive",
      action: "install-model",
    }
  }

  if (status.service.error) {
    return {
      key: "needs_attention",
      label: "Service error",
      title: "Voice service needs a restart",
      description: status.service.error,
      badgeVariant: "destructive",
      action: "diagnostics",
    }
  }

  if (!status.service.running) {
    return {
      key: "service_paused",
      label: "Stopped",
      title: "Voice input is paused",
      description: "Start voice input when you want the watch to send speech to this computer.",
      badgeVariant: "secondary",
      action: "start",
    }
  }

  if (!status.watch.paired) {
    return {
      key: "waiting_watch",
      label: "Waiting",
      title: "Waiting for watch",
      description: "Keep the watch nearby. M5StopWatch will reconnect automatically.",
      badgeVariant: "secondary",
      action: "retry",
    }
  }

  const signal = telemetrySignal(telemetry) ?? latestRuntimeSignal(entries)
  if (signal === "listening") {
    return {
      key: "listening",
      label: "Listening",
      title: "Listening from your watch",
      description: "Audio is streaming into the local speech model.",
      badgeVariant: "default",
    }
  }

  if (signal === "recognizing") {
    return {
      key: "recognizing",
      label: "Recognizing",
      title: "Model is decoding speech",
      description: "Audio is buffered. The model is producing text for insertion.",
      badgeVariant: "secondary",
    }
  }

  if (signal === "inserted") {
    return {
      key: "inserted",
      label: "Inserted",
      title: "Text inserted",
      description: "The last dictation was inserted into the active app.",
      badgeVariant: "default",
    }
  }

  if (!status.voice.ready || signal === "preparing_voice") {
    return {
      key: "preparing_voice",
      label: "Preparing",
      title: "Preparing voice",
      description: "The watch is connected. The speech model is getting ready.",
      badgeVariant: "secondary",
    }
  }

  return {
    key: "ready",
    label: "Ready",
    title: "Ready to dictate",
    description: "Hold the watch button and start speaking.",
    badgeVariant: "default",
  }
}

function activityFromEntry(entry: StructuredLogEntry): ActivityItem | null {
  const message = entry.message
  const lower = message.toLowerCase()

  if (lower.includes("[ble] connected") || lower.includes("connected mtu")) {
    return {
      key: `connected-${entry.time}`,
      time: entry.time,
      label: "Connected",
      detail: "Watch connection is active.",
      variant: "default",
    }
  }

  if (isListeningEntry(entry)) {
    return {
      key: `listening-${entry.time}`,
      time: entry.time,
      label: "Listening",
      detail: "Speech capture started from the watch.",
      variant: "default",
    }
  }

  if (isRecognizingEntry(entry)) {
    return {
      key: `recognizing-${entry.time}`,
      time: entry.time,
      label: "Recognizing",
      detail: "Speech is being converted to text.",
      variant: "secondary",
    }
  }

  if (isInsertedEntry(entry)) {
    return {
      key: `inserted-${entry.time}`,
      time: entry.time,
      label: "Inserted text",
      detail: "Dictation was sent to the active app.",
      variant: "default",
    }
  }

  if (lower.includes("speech input ready") || lower.includes("mlx ready")) {
    return {
      key: `ready-${entry.time}`,
      time: entry.time,
      label: "Voice ready",
      detail: "Hold the watch button to talk.",
      variant: "outline",
    }
  }

  if (lower.includes("connecting to")) {
    return {
      key: `connecting-${entry.time}`,
      time: entry.time,
      label: "Connecting",
      detail: "Trying to reach the watch.",
      variant: "secondary",
    }
  }

  if (lower.includes("disconnect")) {
    return {
      key: `reconnecting-${entry.time}`,
      time: entry.time,
      label: "Reconnecting",
      detail: "The watch connection changed.",
      variant: "secondary",
    }
  }

  if (isPreparingEntry(entry)) {
    return {
      key: `preparing-${entry.time}`,
      time: entry.time,
      label: "Preparing",
      detail: "Speech model is loading.",
      variant: "secondary",
    }
  }

  return null
}

export function recentActivity(entries: StructuredLogEntry[]) {
  const result: ActivityItem[] = []
  const seen = new Set<string>()

  for (const entry of entries.slice().reverse()) {
    const item = activityFromEntry(entry)
    if (!item || seen.has(item.label)) {
      continue
    }

    seen.add(item.label)
    result.push(item)
    if (result.length >= 8) {
      break
    }
  }

  return result
}

export function diagnosticDetail(status: StatusPayload | null, key: DiagnosticKey) {
  if (!status) {
    return "Unknown"
  }
  switch (key) {
    case "overall":
      return `${status.overall.label} (${status.overall.code})`
    case "service":
      return status.service.running ? "running" : status.service.error || "stopped"
    case "watch":
      return status.watch.paired ? `paired as ${status.watch.id}` : status.watch.label
    case "voice":
      return status.voice.message
    case "model":
      return `${modelLabel(status.model.selected)} / ${status.model.message}`
    case "input":
      return status.permissions.input.message
    case "bluetooth":
      return status.permissions.bluetooth.message
    case "logs":
      return status.logs.directory
  }
}

export function diagnosticOk(status: StatusPayload | null, key: DiagnosticKey) {
  if (!status) {
    return false
  }
  switch (key) {
    case "overall":
      return status.overall.ready
    case "service":
      return status.service.running && !status.service.error
    case "watch":
      return status.watch.paired
    case "voice":
      return status.voice.ready
    case "model":
      return status.model.installed
    case "input":
      return status.permissions.input.ok
    case "bluetooth":
      return status.permissions.bluetooth.ok
    case "logs":
      return Boolean(status.logs.directory)
  }
}

export function readinessVariant(ok: boolean): BadgeVariant {
  return ok ? "default" : "destructive"
}

export function modelVariant(model: StatusPayload["model"] | null): BadgeVariant {
  if (!model) {
    return "secondary"
  }
  if (!model.installed || model.state === "error") {
    return "destructive"
  }
  if (model.update_available) {
    return "secondary"
  }
  return "default"
}
