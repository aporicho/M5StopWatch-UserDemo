import { useCallback, useEffect, useMemo, useRef, useState, type ComponentType, type SVGProps } from "react"
import {
  ActivityIcon,
  AlertCircleIcon,
  BluetoothIcon,
  BugIcon,
  CheckCircle2Icon,
  ClipboardIcon,
  DownloadIcon,
  FileTextIcon,
  FolderOpenIcon,
  HomeIcon,
  KeyboardIcon,
  MapIcon,
  PlusIcon,
  PlayIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  SaveIcon,
  SettingsIcon,
  SquareIcon,
  Trash2Icon,
  Undo2Icon,
  WrenchIcon,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ButtonGroup } from "@/components/ui/button-group"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldTitle,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Progress,
  ProgressLabel,
  ProgressValue,
} from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Slider } from "@/components/ui/slider"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { toast } from "@/components/ui/toast"
import {
  formatBytes,
  helperCommands,
  helperMappings,
  helperLogs,
  helperStatus,
  helperTelemetry,
  invokeModelAction,
  invokeServiceAction,
  LOG_LINES,
  MODEL_IDS,
  modelActionMessage,
  modelBlocksServiceStart,
  openLogsFolder,
  openPermissionPanel,
  POLL_MS,
  resetCommands,
  resetMappings,
  saveCommands,
  saveMappings,
  serviceNeedsInputPermissionRestart,
  SERVICE_SETTLE_MS,
  sleep,
  structuredLogEntry,
  TELEMETRY_POLL_MS,
  type CommandEntry,
  type CommandEnvelope,
  type LogsEnvelope,
  type MappingEntry,
  type MappingEnvelope,
  type MappingOption,
  type ModelAction,
  type PermissionKind,
  type RuntimeTelemetry,
  type ServiceAction,
  type StatusEnvelope,
  type StatusPayload,
  type StructuredLogEntry,
  type TelemetryEnvelope,
} from "@/lib/helper-api"
import {
  LANGUAGE_OPTIONS,
  createTranslator,
  detectInitialLanguage,
  persistLanguage,
  type LanguageCode,
  type Translator,
} from "@/lib/i18n"
import { cn } from "@/lib/utils"

type BadgeVariant = "default" | "secondary" | "destructive" | "outline"

type Notice = {
  level: "info" | "error"
  message: string
}

type DailyStateKey =
  | "loading"
  | "ready"
  | "listening"
  | "recognizing"
  | "inserted"
  | "waiting_watch"
  | "preparing_voice"
  | "service_paused"
  | "needs_attention"

type DailyState = {
  key: DailyStateKey
  label: string
  title: string
  description: string
  badgeVariant: BadgeVariant
  action?: "start" | "retry" | "install-model" | "request-bluetooth" | "request-input" | "diagnostics"
}

type ActivityItem = {
  key: string
  time: string
  label: string
  detail: string
  variant: BadgeVariant
}

type PageKey = "home" | "map" | "command"

const MODEL_OPTIONS = [
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

const WHEEL_MULTIPLIER_OPTIONS: MappingOption[] = [
  { label: "1x", value: 1 },
  { label: "2x", value: 2 },
  { label: "3x", value: 3 },
  { label: "4x", value: 4 },
]

const WHEEL_DIRECTION_OPTIONS: MappingOption[] = [
  { label: "Normal", value: 0 },
  { label: "Inverted", value: 1 },
]

const MODIFIER_TOGGLE_OPTIONS: MappingOption[] = [
  { label: "Ctrl", value: 1 },
  { label: "Shift", value: 2 },
  { label: "Alt", value: 4 },
  { label: "Cmd / Win", value: 8 },
]

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

const COMMAND_ACTION_IDS = new Set([
  "none",
  "hid.keyboard.tap",
  "hid.mouse.wheel",
  "hid.mouse.click",
  "hid.media.control",
  "device.pair_new_computer",
])

const DEFAULT_DAILY_STATE: DailyState = {
  key: "loading",
  label: "Checking",
  title: "Checking voice input",
  description: "Reading watch, service, model, and telemetry state.",
  badgeVariant: "secondary",
}

const DIAGNOSTIC_ROWS = [
  ["overall", "Status"],
  ["service", "Service"],
  ["watch", "Watch"],
  ["voice", "Voice"],
  ["model", "Model"],
  ["input", "Text input"],
  ["bluetooth", "Bluetooth"],
  ["logs", "Logs"],
] as const

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

function actionTitle(action: string) {
  return `${action.slice(0, 1).toUpperCase()}${action.slice(1)}`
}

function modelLabel(value: string | null | undefined) {
  if (!value) {
    return "Unknown"
  }
  return MODEL_OPTIONS.find((model) => model.value === value)?.label ?? value
}

function modelDisplayLabel(value: string | null | undefined, t: Translator) {
  if (!value) {
    return t("common.unknown", "Unknown")
  }
  return t(`model.${value}.label`, modelLabel(value))
}

function modelDetail(value: string, t: Translator) {
  return (
    MODEL_OPTIONS.find((model) => model.value === value)
      ? t(`model.${value}.detail`)
      : t("settings.custom_model_detail", "Custom model selected by the helper.")
  )
}

function localizedDailyState(state: DailyState, t: Translator): DailyState {
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

function logLevelVariant(level: string): BadgeVariant {
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

function compactTime(value: string) {
  if (!value || value === "--") {
    return "--"
  }
  const [, time] = value.split(" ")
  return time ? time.slice(0, 8) : value
}

function formatUnixTime(value: number | null | undefined) {
  if (!value || !Number.isFinite(value)) {
    return "--"
  }
  return new Date(value * 1000).toLocaleTimeString()
}

function ratio(value: number | null | undefined) {
  if (!Number.isFinite(value ?? NaN)) {
    return 0
  }
  return Math.max(0, Math.min(1, Number(value)))
}

function percent(value: number | null | undefined) {
  return `${Math.round(ratio(value) * 100)}%`
}

function mappingDefaults(action: string) {
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

function blankMappingEntry(eventId: string, locked = false): MappingEntry {
  return {
    event: eventId,
    action: locked ? "device.go_home" : "none",
    ...mappingDefaults(locked ? "device.go_home" : "none"),
    locked,
  }
}

function withMappingAction(entry: MappingEntry, action: string): MappingEntry {
  return {
    ...entry,
    action,
    ...mappingDefaults(action),
  }
}

function blankCommandEntry(index: number): CommandEntry {
  return {
    id: `command-${Date.now()}-${index}`,
    phrase: "",
    aliases: [],
    enabled: true,
    action: "none",
    ...mappingDefaults("none"),
  }
}

function commandAsMappingEntry(command: CommandEntry): MappingEntry {
  return {
    event: "command.voice",
    action: command.action,
    param0: command.param0,
    param1: command.param1,
    param2: command.param2,
    flags: command.flags ?? 0,
  }
}

function commandWithMappingEntry(command: CommandEntry, entry: MappingEntry): CommandEntry {
  return {
    ...command,
    action: entry.action,
    param0: entry.param0,
    param1: entry.param1,
    param2: entry.param2,
    flags: entry.flags ?? 0,
  }
}

function commandToolsEnvelope(envelope: CommandEnvelope): MappingEnvelope {
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

function mappingOptionValue(value: number | null | undefined) {
  return String(value ?? 0)
}

function mappingEventLabel(eventId: string, fallback: string, t: Translator) {
  return t(`map.event.${eventId}`, fallback)
}

function mappingActionLabel(actionId: string, fallback: string | undefined, t: Translator) {
  return t(`map.action.${actionId}`, fallback ?? actionId)
}

function localizedMappingOptionLabel(label: string, t: Translator) {
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

function findMappingOption(options: MappingOption[], value: number) {
  return options.find((option) => option.value === value)
}

function mappingOptionLabel(options: MappingOption[], value: number, t: Translator) {
  const option = findMappingOption(options, value)
  return localizedMappingOptionLabel(option?.label ?? String(value), t)
}

function modifierLabel(value: number, t: Translator) {
  const labels = MODIFIER_TOGGLE_OPTIONS
    .filter((option) => (value & option.value) !== 0)
    .map((option) => localizedMappingOptionLabel(option.label, t))
  return labels.length ? labels.join("+") : t("map.option.none", "None")
}

function mappingActionSummary(entry: MappingEntry, envelope: MappingEnvelope, t: Translator) {
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

function mappingIsCommon(eventId: string, entry: MappingEntry) {
  return COMMON_MAPPING_EVENT_IDS.has(eventId) || entry.locked || entry.action !== "none"
}

function progressValue(value: number | null | undefined) {
  return Math.round(ratio(value) * 100)
}

function telemetryFresh(telemetry: RuntimeTelemetry | null) {
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

function latestDictation(entries: StructuredLogEntry[], telemetry: RuntimeTelemetry | null) {
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

function telemetryRenderKey(envelope: TelemetryEnvelope | null) {
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

function deriveDailyState(
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

function recentActivity(entries: StructuredLogEntry[]) {
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

function diagnosticDetail(status: StatusPayload | null, key: (typeof DIAGNOSTIC_ROWS)[number][0]) {
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

function diagnosticOk(status: StatusPayload | null, key: (typeof DIAGNOSTIC_ROWS)[number][0]) {
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

function readinessVariant(ok: boolean): BadgeVariant {
  return ok ? "default" : "destructive"
}

function modelVariant(model: StatusPayload["model"] | null): BadgeVariant {
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

function SpinnerOrIcon({
  busy,
  icon: Icon,
}: {
  busy: boolean
  icon: ComponentType<SVGProps<SVGSVGElement>>
}) {
  if (busy) {
    return <Spinner data-icon="inline-start" />
  }

  return <Icon data-icon="inline-start" />
}

function useSystemTheme() {
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)")
    const syncTheme = () => {
      document.documentElement.classList.toggle("dark", media.matches)
    }

    syncTheme()
    media.addEventListener("change", syncTheme)
    return () => media.removeEventListener("change", syncTheme)
  }, [])
}

function StatusBadge({ state }: { state: DailyState }) {
  return <Badge variant={state.badgeVariant}>{state.label}</Badge>
}

function ReadinessTable({ status, t }: { status: StatusPayload | null; t: Translator }) {
  if (!status) {
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-5/6" />
        <Skeleton className="h-8 w-2/3" />
      </div>
    )
  }

  const rows = [
    {
      label: t("home.service", "Service"),
      ok: status.service.running && !status.service.error,
      detail: status.service.running ? t("settings.running", "running") : status.service.error || t("settings.stopped", "stopped"),
    },
    {
      label: t("home.watch", "Watch"),
      ok: status.watch.paired,
      detail: status.watch.paired ? t("status.connected", "connected") : status.watch.label,
    },
    {
      label: t("home.voice", "Voice"),
      ok: status.voice.ready,
      detail: status.voice.message,
    },
    {
      label: t("home.model", "Model"),
      ok: status.model.installed,
      detail: `${modelDisplayLabel(status.model.selected, t)} / ${status.model.state}`,
    },
  ]

  return (
    <Table>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.label}>
            <TableCell className="w-28 font-medium">{row.label}</TableCell>
            <TableCell className="w-24">
              <Badge variant={readinessVariant(row.ok)}>
                {row.ok ? t("common.ok", "OK") : t("common.check", "Check")}
              </Badge>
            </TableCell>
            <TableCell className="whitespace-normal text-muted-foreground">{row.detail}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function StatusCard({
  state,
  status,
  lastUpdated,
  busyAction,
  onAction,
  primaryActionLabel,
  t,
}: {
  state: DailyState
  status: StatusPayload | null
  lastUpdated: Date | null
  busyAction: string | null
  onAction: () => void
  primaryActionLabel: Record<NonNullable<DailyState["action"]>, string>
  t: Translator
}) {
  return (
    <Card size="sm" className="shrink-0">
      <CardHeader>
        <div>
          <CardTitle>{state.title}</CardTitle>
          <CardDescription>{state.description}</CardDescription>
        </div>
        <CardAction>
          <StatusBadge state={state} />
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {state.action && (
          <Alert variant={state.badgeVariant === "destructive" ? "destructive" : "default"}>
            {state.badgeVariant === "destructive" ? <AlertCircleIcon /> : <CheckCircle2Icon />}
            <AlertTitle>{state.label}</AlertTitle>
            <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <span>{state.description}</span>
              <Button onClick={onAction} disabled={busyAction !== null}>
                <PlayIcon data-icon="inline-start" />
                {primaryActionLabel[state.action]}
              </Button>
            </AlertDescription>
          </Alert>
        )}
        <ReadinessTable status={status} t={t} />
      </CardContent>
      <CardFooter className="text-sm text-muted-foreground">
        {t("home.updated", "Updated")} {lastUpdated ? lastUpdated.toLocaleTimeString() : t("common.never", "never")}
      </CardFooter>
    </Card>
  )
}

function TranscriptCard({
  dictation,
  className,
  t,
}: {
  dictation: ReturnType<typeof latestDictation>
  className?: string
  t: Translator
}) {
  return (
    <Card size="sm" className={cn("min-h-0", className)}>
      <CardHeader>
        <div>
          <CardTitle>{t("home.transcript", "Transcript")}</CardTitle>
        </div>
        <CardAction>
          <Badge variant={dictation?.final ? "default" : "outline"}>
            {dictation?.final ? t("home.final", "Final") : t("home.live", "Live")}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="min-h-0 flex-1">
        {dictation ? (
          <ScrollArea className="h-full min-h-24">
            <div className="flex flex-col gap-3 pr-3">
              <p className="text-xl leading-snug">{dictation.text}</p>
              <p className="text-sm text-muted-foreground">{dictation.time}</p>
            </div>
          </ScrollArea>
        ) : (
          <Empty className="min-h-24">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <FileTextIcon />
              </EmptyMedia>
              <EmptyTitle>{t("home.no_text", "No text yet")}</EmptyTitle>
              <EmptyDescription>{t("home.no_text_description", "Hold the watch button and speak.")}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
      </CardContent>
    </Card>
  )
}

function RuntimeCard({
  state,
  telemetry,
  className,
  t,
}: {
  state: DailyState
  telemetry: RuntimeTelemetry | null
  className?: string
  t: Translator
}) {
  const fresh = telemetryFresh(telemetry)
  const level = fresh ? telemetry?.audio.level : 0
  const peak = fresh ? telemetry?.audio.peak : 0
  const seconds = fresh ? telemetry?.audio.seconds ?? 0 : 0

  return (
    <Card size="sm" className={className}>
      <CardHeader>
        <div>
          <CardTitle>{t("home.runtime", "Runtime")}</CardTitle>
        </div>
        <CardAction>
          {state.key === "listening" || state.key === "recognizing" ? (
            <Spinner />
          ) : (
            <Badge variant={fresh ? "outline" : "secondary"}>
              {fresh ? t("home.live", "Live") : t("home.idle", "Idle")}
            </Badge>
          )}
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <Progress value={progressValue(level)}>
          <ProgressLabel>{t("home.audio_level", "Audio level")}</ProgressLabel>
          <ProgressValue>{() => percent(level)}</ProgressValue>
        </Progress>
        <Progress value={progressValue(peak)}>
          <ProgressLabel>{t("home.peak", "Peak")}</ProgressLabel>
          <ProgressValue>{() => percent(peak)}</ProgressValue>
        </Progress>
      </CardContent>
      <CardFooter>
        <p className="text-sm text-muted-foreground">
          {t("home.stage", "Stage")} {telemetry?.stage ?? t("common.unknown", "unknown")} · {t("home.audio", "Audio")} {seconds.toFixed(1)}s · {t("home.age", "Age")}{" "}
          {telemetry?.age_seconds == null ? t("common.unknown", "unknown") : `${telemetry.age_seconds.toFixed(1)}s`}
          {telemetry?.stale ? ` / ${t("home.stale", "stale")}` : ""}
        </p>
      </CardFooter>
    </Card>
  )
}

function ModelCard({
  model,
  onOpenSettings,
  t,
}: {
  model: StatusPayload["model"] | null
  onOpenSettings: () => void
  t: Translator
}) {
  return (
    <Card size="sm" className="shrink-0">
      <CardHeader>
        <div>
          <CardTitle>{t("home.model", "Model")}</CardTitle>
          <CardDescription>{model?.message ?? t("home.model_loading", "Model status is loading.")}</CardDescription>
        </div>
        <CardAction>
          <Badge variant={modelVariant(model)}>{model?.state ?? t("common.unknown", "Unknown")}</Badge>
        </CardAction>
      </CardHeader>
      <CardContent>
        {model ? (
          <Table>
            <TableBody>
              <TableRow>
                <TableCell className="font-medium">{t("home.selected", "Selected")}</TableCell>
                <TableCell className="text-muted-foreground">{modelDisplayLabel(model.selected, t)}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="font-medium">{t("home.engine", "Engine")}</TableCell>
                <TableCell className="text-muted-foreground">{model.engine}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="font-medium">{t("home.storage", "Storage")}</TableCell>
                <TableCell className="text-muted-foreground">{formatBytes(model.disk_bytes)}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        ) : (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-4/5" />
          </div>
        )}
      </CardContent>
      <CardFooter>
        <Button variant="outline" onClick={onOpenSettings}>
          <SettingsIcon data-icon="inline-start" />
          {t("home.manage_model", "Manage model")}
        </Button>
      </CardFooter>
    </Card>
  )
}

function PermissionPanel({
  status,
  busyAction,
  requestPermission,
  t,
}: {
  status: StatusPayload | null
  busyAction: string | null
  requestPermission: (kind: PermissionKind) => void
  t: Translator
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.permissions", "Permissions")}</CardTitle>
        <CardDescription>{t("settings.permissions_description", "Required for Bluetooth audio and text insertion.")}</CardDescription>
      </CardHeader>
      <CardContent>
        <FieldGroup>
          <Field orientation="horizontal">
            <FieldContent>
              <FieldTitle>{t("settings.bluetooth", "Bluetooth")}</FieldTitle>
              <FieldDescription>{status?.permissions.bluetooth.message ?? t("common.unknown", "Unknown")}</FieldDescription>
            </FieldContent>
            <Button
              variant="outline"
              onClick={() => requestPermission("bluetooth")}
              disabled={busyAction !== null}
            >
              <SpinnerOrIcon busy={busyAction === "permission:bluetooth"} icon={BluetoothIcon} />
              {t("settings.request", "Request")}
            </Button>
          </Field>
          <Field orientation="horizontal">
            <FieldContent>
              <FieldTitle>{t("settings.text_input", "Text input")}</FieldTitle>
              <FieldDescription>{status?.permissions.input.message ?? t("common.unknown", "Unknown")}</FieldDescription>
            </FieldContent>
            <Button
              variant="outline"
              onClick={() => requestPermission("input")}
              disabled={busyAction !== null}
            >
              <SpinnerOrIcon busy={busyAction === "permission:input"} icon={KeyboardIcon} />
              {t("settings.request", "Request")}
            </Button>
          </Field>
        </FieldGroup>
      </CardContent>
    </Card>
  )
}

function MappingSelectField({
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string
  value: number
  options: MappingOption[]
  disabled: boolean
  onChange: (value: number) => void
}) {
  const items = useMemo(
    () => options.map((option) => ({ label: option.label, value: String(option.value) })),
    [options]
  )

  return (
    <Field>
      <FieldLabel>{label}</FieldLabel>
      <Select
        items={items}
        value={mappingOptionValue(value)}
        onValueChange={(nextValue) => {
          if (nextValue == null) {
            return
          }
          onChange(Number(nextValue))
        }}
        disabled={disabled}
      >
        <SelectTrigger className="w-full">
          <SelectValue placeholder={label} />
        </SelectTrigger>
        <SelectContent alignItemWithTrigger={false}>
          <SelectGroup>
            {options.map((option) => (
              <SelectItem key={option.value} value={String(option.value)}>
                {option.label}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </Field>
  )
}

function MappingToggleField({
  label,
  value,
  options,
  disabled,
  onChange,
  t,
}: {
  label: string
  value: number
  options: MappingOption[]
  disabled: boolean
  onChange: (value: number) => void
  t: Translator
}) {
  return (
    <Field data-disabled={disabled ? true : undefined}>
      <FieldLabel>{label}</FieldLabel>
      <ToggleGroup
        aria-label={label}
        className="flex w-full flex-wrap"
        spacing={0}
        variant="outline"
        value={[String(value)]}
        onValueChange={(nextValues) => {
          const nextValue = nextValues[nextValues.length - 1]
          if (nextValue == null) {
            return
          }
          onChange(Number(nextValue))
        }}
      >
        {options.map((option) => (
          <ToggleGroupItem
            key={option.value}
            className="min-w-20 flex-1"
            disabled={disabled}
            value={String(option.value)}
          >
            {localizedMappingOptionLabel(option.label, t)}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </Field>
  )
}

function MappingModifierField({
  label,
  value,
  disabled,
  onChange,
  t,
}: {
  label: string
  value: number
  disabled: boolean
  onChange: (value: number) => void
  t: Translator
}) {
  return (
    <Field data-disabled={disabled ? true : undefined}>
      <FieldLabel>{label}</FieldLabel>
      <ToggleGroup
        aria-label={label}
        className="flex w-full flex-wrap"
        spacing={0}
        variant="outline"
        value={MODIFIER_TOGGLE_OPTIONS.filter((option) => (value & option.value) !== 0).map((option) => String(option.value))}
        onValueChange={(nextValues) => {
          const nextValue = nextValues.reduce((mask, item) => mask | Number(item), 0)
          onChange(nextValue)
        }}
      >
        {MODIFIER_TOGGLE_OPTIONS.map((option) => (
          <ToggleGroupItem
            key={option.value}
            className="min-w-20 flex-1"
            disabled={disabled}
            value={String(option.value)}
          >
            {localizedMappingOptionLabel(option.label, t)}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <FieldDescription>{modifierLabel(value, t)}</FieldDescription>
    </Field>
  )
}

function MappingWheelSpeedField({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string
  value: number
  disabled: boolean
  onChange: (value: number) => void
}) {
  const safeValue = Math.min(4, Math.max(1, Math.round(value || 1)))

  return (
    <Field data-disabled={disabled ? true : undefined}>
      <div className="flex items-center justify-between gap-3">
        <FieldLabel>{label}</FieldLabel>
        <Badge variant="outline">{safeValue}x</Badge>
      </div>
      <Slider
        disabled={disabled}
        max={4}
        min={1}
        step={1}
        value={[safeValue]}
        onValueChange={(nextValue) => {
          const next = Array.isArray(nextValue) ? nextValue[0] : nextValue
          onChange(Math.min(4, Math.max(1, Math.round(next || 1))))
        }}
      />
      <div className="flex justify-between gap-2 text-xs text-muted-foreground">
        <span>1x</span>
        <span>4x</span>
      </div>
    </Field>
  )
}

function MappingParameterEditor({
  entry,
  envelope,
  disabled,
  onChange,
  t,
}: {
  entry: MappingEntry
  envelope: MappingEnvelope
  disabled: boolean
  onChange: (entry: MappingEntry) => void
  t: Translator
}) {
  if (entry.locked) {
    return <p className="text-sm text-muted-foreground">{t("mapping.fixed_safety", "Fixed safety shortcut.")}</p>
  }

  if (entry.action === "hid.keyboard.tap") {
    return (
      <FieldGroup>
        <MappingSelectField
          label={t("mapping.key", "Key")}
          value={entry.param0}
          options={envelope.keyOptions}
          disabled={disabled}
          onChange={(value) => onChange({ ...entry, param0: value })}
        />
        <MappingModifierField
          label={t("mapping.modifier", "Modifier")}
          value={entry.param1}
          disabled={disabled}
          onChange={(value) => onChange({ ...entry, param1: value })}
          t={t}
        />
      </FieldGroup>
    )
  }

  if (entry.action === "hid.mouse.wheel") {
    return (
      <FieldGroup>
        <MappingWheelSpeedField
          label={t("mapping.speed", "Speed")}
          value={entry.param0}
          disabled={disabled}
          onChange={(value) => onChange({ ...entry, param0: value })}
        />
        <MappingToggleField
          label={t("mapping.direction", "Direction")}
          value={entry.param1}
          options={WHEEL_DIRECTION_OPTIONS}
          disabled={disabled}
          onChange={(value) => onChange({ ...entry, param1: value })}
          t={t}
        />
      </FieldGroup>
    )
  }

  if (entry.action === "hid.mouse.click") {
    return (
      <MappingToggleField
        label={t("mapping.button", "Button")}
        value={entry.param0}
        options={envelope.mouseButtons}
        disabled={disabled}
        onChange={(value) => onChange({ ...entry, param0: value })}
        t={t}
      />
    )
  }

  if (entry.action === "hid.media.control") {
    return (
      <MappingToggleField
        label={t("mapping.media_key", "Media key")}
        value={entry.param2}
        options={envelope.mediaControls}
        disabled={disabled}
        onChange={(value) => onChange({ ...entry, param2: value })}
        t={t}
      />
    )
  }

  return <p className="text-sm text-muted-foreground">{t("mapping.no_parameters", "No parameters.")}</p>
}

function MappingPage({
  envelope,
  entries,
  touched,
  busyAction,
  refreshing,
  onRefresh,
  onSave,
  onReset,
  onChange,
  t,
}: {
  envelope: MappingEnvelope | null
  entries: MappingEntry[]
  touched: boolean
  busyAction: string | null
  refreshing: boolean
  onRefresh: () => void
  onSave: () => void
  onReset: () => void
  onChange: (entry: MappingEntry) => void
  t: Translator
}) {
  const [mapView, setMapView] = useState<"common" | "all">("common")
  const [editingEventId, setEditingEventId] = useState<string | null>(null)
  const entriesByEvent = useMemo(
    () => new Map(entries.map((entry) => [entry.event, entry])),
    [entries]
  )
  const disabled = busyAction !== null || refreshing
  const actionItems = useMemo(
    () =>
      envelope?.actions.map((action) => ({
        label: mappingActionLabel(action.id, action.label, t),
        value: action.id,
      })) ?? [],
    [envelope, t]
  )
  const rows = useMemo(() => {
    if (!envelope) {
      return []
    }
    return envelope.events.map((event) => {
      const entry = entriesByEvent.get(event.id) ?? blankMappingEntry(event.id, Boolean(event.locked))
      const locked = Boolean(event.locked || entry.locked)
      const normalizedEntry = { ...entry, locked }
      const action = envelope.actions.find((item) => item.id === normalizedEntry.action)
      return {
        event,
        entry: normalizedEntry,
        locked,
        eventLabel: mappingEventLabel(event.id, event.label, t),
        actionLabel: mappingActionLabel(normalizedEntry.action, action?.label, t),
        summary: mappingActionSummary(normalizedEntry, envelope, t),
      }
    })
  }, [entriesByEvent, envelope, t])
  const visibleRows = useMemo(
    () => (mapView === "common" ? rows.filter((row) => mappingIsCommon(row.event.id, row.entry)) : rows),
    [mapView, rows]
  )
  const selectedRow = useMemo(
    () => rows.find((row) => row.event.id === editingEventId) ?? null,
    [editingEventId, rows]
  )

  if (!envelope) {
    return (
      <section className="min-h-0 flex-1">
        <Card className="min-h-0">
          <CardHeader>
            <CardTitle>{t("mapping.title", "Event map")}</CardTitle>
            <CardDescription>{t("mapping.loading_description", "Loading watch event configuration.")}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-4/5" />
            <Skeleton className="h-10 w-3/5" />
          </CardContent>
        </Card>
      </section>
    )
  }

  const updatedAt = envelope.mapping.updated_at
    ? formatUnixTime(envelope.mapping.updated_at)
    : t("mapping.defaults", "defaults")

  return (
    <section className="min-h-0 flex-1">
      <Card className="min-h-0 md:flex md:h-full md:flex-col">
        <CardHeader className="shrink-0">
          <div>
            <CardTitle>{t("mapping.title", "Event map")}</CardTitle>
            <CardDescription>{t("mapping.description", "Choose common watch gestures first. Open an event for details.")}</CardDescription>
          </div>
          <CardAction>
            <ButtonGroup className="flex-wrap">
              <Button variant="outline" onClick={onRefresh} disabled={disabled}>
                <SpinnerOrIcon busy={refreshing} icon={RefreshCwIcon} />
                {t("common.refresh", "Refresh")}
              </Button>
              <Button variant="outline" onClick={onReset} disabled={disabled}>
                <SpinnerOrIcon busy={busyAction === "mapping:reset"} icon={Undo2Icon} />
                {t("common.reset", "Reset")}
              </Button>
              <Button onClick={onSave} disabled={disabled || !touched}>
                <SpinnerOrIcon busy={busyAction === "mapping:save"} icon={SaveIcon} />
                {t("common.save", "Save")}
              </Button>
            </ButtonGroup>
          </CardAction>
        </CardHeader>
        <CardContent className="min-h-0 md:flex-1">
          <Tabs
            value={mapView}
            onValueChange={(value) => setMapView(value as "common" | "all")}
            className="flex min-h-0 flex-col gap-3 md:h-full"
          >
            <TabsList>
              <TabsTrigger value="common">{t("mapping.common", "Common")}</TabsTrigger>
              <TabsTrigger value="all">{t("mapping.all_events", "All events")}</TabsTrigger>
            </TabsList>

            {(["common", "all"] as const).map((view) => (
              <TabsContent key={view} value={view} className="min-h-0 md:flex-1">
                {visibleRows.length ? (
                  <ScrollArea className="h-[calc(100vh-21rem)] rounded-md border md:h-full">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-[32%]">{t("mapping.event", "Event")}</TableHead>
                          <TableHead>{t("mapping.result", "Result")}</TableHead>
                          <TableHead className="w-32 text-right">{t("mapping.action", "Action")}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {visibleRows.map((row) => (
                          <TableRow key={row.event.id}>
                            <TableCell className="align-middle">
                              <div className="flex min-w-0 items-center gap-2">
                                <span className="truncate font-medium">{row.eventLabel}</span>
                                {row.locked && <Badge variant="outline">{t("common.locked", "Locked")}</Badge>}
                              </div>
                            </TableCell>
                            <TableCell className="align-middle">
                              <div className="flex min-w-0 flex-col gap-1">
                                <span className="truncate">{row.actionLabel}</span>
                                <span className="truncate text-sm text-muted-foreground">{row.summary}</span>
                              </div>
                            </TableCell>
                            <TableCell className="align-middle text-right">
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => setEditingEventId(row.event.id)}
                              >
                                <SettingsIcon data-icon="inline-start" />
                                {t("mapping.open_editor", "Open editor")}
                              </Button>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </ScrollArea>
                ) : (
                  <Empty className="rounded-md border">
                    <EmptyHeader>
                      <EmptyMedia variant="icon">
                        <MapIcon />
                      </EmptyMedia>
                      <EmptyTitle>{t("mapping.empty_title", "No common mappings")}</EmptyTitle>
                      <EmptyDescription>{t("mapping.empty_description", "Open All events to configure a watch gesture.")}</EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                )}
              </TabsContent>
            ))}
          </Tabs>
        </CardContent>
        <CardFooter className="shrink-0 justify-between text-sm text-muted-foreground">
          <span>
            {t("mapping.revision", "Revision")} {envelope.mapping.revision} · {t("mapping.updated", "Updated")} {updatedAt}
          </span>
          <span>{touched ? t("mapping.unsaved_hint", "Unsaved changes") : t("mapping.saved_hint", "Saved changes sync to the watch while connected")}</span>
        </CardFooter>
      </Card>

      <Sheet open={Boolean(selectedRow)} onOpenChange={(open) => !open && setEditingEventId(null)}>
        <SheetContent className="w-[min(520px,calc(100vw-2rem))] sm:max-w-lg">
          <SheetHeader>
            <SheetTitle>{selectedRow?.eventLabel ?? t("mapping.edit_title", "Edit event")}</SheetTitle>
            <SheetDescription>{t("mapping.edit_description", "Choose what this watch event does on this computer.")}</SheetDescription>
          </SheetHeader>

          {selectedRow && (
            <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
              <FieldGroup>
                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldTitle>{t("mapping.event", "Event")}</FieldTitle>
                    <FieldDescription>{selectedRow.eventLabel}</FieldDescription>
                  </FieldContent>
                  {selectedRow.locked && <Badge variant="outline">{t("common.locked", "Locked")}</Badge>}
                </Field>
                <Field data-disabled={selectedRow.locked || disabled ? true : undefined}>
                  <FieldLabel>{t("mapping.action", "Action")}</FieldLabel>
                  <Select
                    items={actionItems}
                    value={selectedRow.entry.action}
                    onValueChange={(value) => {
                      if (value == null) {
                        return
                      }
                      onChange(withMappingAction(selectedRow.entry, value))
                    }}
                    disabled={selectedRow.locked || disabled}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder={t("mapping.action", "Action")} />
                    </SelectTrigger>
                    <SelectContent alignItemWithTrigger={false}>
                      <SelectGroup>
                        <SelectLabel>{t("mapping.actions", "Actions")}</SelectLabel>
                        {actionItems.map((item) => (
                          <SelectItem key={item.value} value={item.value}>
                            {item.label}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  <FieldDescription>{selectedRow.summary}</FieldDescription>
                </Field>
                <Field>
                  <FieldTitle>{t("mapping.parameters", "Parameters")}</FieldTitle>
                  <MappingParameterEditor
                    entry={selectedRow.entry}
                    envelope={envelope}
                    disabled={disabled || selectedRow.locked}
                    onChange={(nextEntry) => onChange(nextEntry)}
                    t={t}
                  />
                </Field>
              </FieldGroup>
            </div>
          )}

          <SheetFooter>
            <Button variant="outline" onClick={() => setEditingEventId(null)}>
              {t("common.done", "Done")}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </section>
  )
}

function CommandPage({
  envelope,
  entries,
  telemetry,
  touched,
  busyAction,
  refreshing,
  onRefresh,
  onSave,
  onReset,
  onChange,
  onDelete,
  t,
}: {
  envelope: CommandEnvelope | null
  entries: CommandEntry[]
  telemetry: RuntimeTelemetry | null
  touched: boolean
  busyAction: string | null
  refreshing: boolean
  onRefresh: () => void
  onSave: () => void
  onReset: () => void
  onChange: (entry: CommandEntry) => void
  onDelete: (id: string) => void
  t: Translator
}) {
  const [editingCommandId, setEditingCommandId] = useState<string | null>(null)
  const disabled = busyAction !== null || refreshing
  const tools = useMemo(() => (envelope ? commandToolsEnvelope(envelope) : null), [envelope])
  const actionItems = useMemo(
    () =>
      envelope?.actions
        .filter((action) => COMMAND_ACTION_IDS.has(action.id))
        .map((action) => ({
          label: mappingActionLabel(action.id, action.label, t),
          value: action.id,
        })) ?? [],
    [envelope, t]
  )
  const selectedCommand = useMemo(
    () => entries.find((entry) => entry.id === editingCommandId) ?? null,
    [editingCommandId, entries]
  )
  const lastCommand = telemetry?.last_command ?? null
  const hasBlankPhrase = entries.some((entry) => !entry.phrase.trim())

  if (!envelope || !tools) {
    return (
      <section className="min-h-0 flex-1">
        <Card className="min-h-0">
          <CardHeader>
            <CardTitle>{t("commands.title", "Commands")}</CardTitle>
            <CardDescription>{t("commands.loading_description", "Loading speech command configuration.")}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-4/5" />
            <Skeleton className="h-10 w-3/5" />
          </CardContent>
        </Card>
      </section>
    )
  }

  const updatedAt = envelope.commands.updated_at
    ? formatUnixTime(envelope.commands.updated_at)
    : t("mapping.defaults", "defaults")

  return (
    <section className="grid min-h-0 flex-1 gap-3 md:grid-cols-[1fr_22rem] md:overflow-hidden">
      <Card className="min-h-0 md:flex md:h-full md:flex-col">
        <CardHeader className="shrink-0">
          <div>
            <CardTitle>{t("commands.title", "Commands")}</CardTitle>
            <CardDescription>{t("commands.description", "Map short spoken phrases to watch actions.")}</CardDescription>
          </div>
          <CardAction>
            <ButtonGroup className="flex-wrap">
              <Button
                variant="outline"
                onClick={() => {
                  const entry = blankCommandEntry(entries.length + 1)
                  onChange(entry)
                  setEditingCommandId(entry.id)
                }}
                disabled={disabled}
              >
                <PlusIcon data-icon="inline-start" />
                {t("commands.add", "Add")}
              </Button>
              <Button variant="outline" onClick={onRefresh} disabled={disabled}>
                <SpinnerOrIcon busy={refreshing} icon={RefreshCwIcon} />
                {t("common.refresh", "Refresh")}
              </Button>
              <Button variant="outline" onClick={onReset} disabled={disabled}>
                <SpinnerOrIcon busy={busyAction === "commands:reset"} icon={Undo2Icon} />
                {t("common.reset", "Reset")}
              </Button>
              <Button onClick={onSave} disabled={disabled || !touched || hasBlankPhrase}>
                <SpinnerOrIcon busy={busyAction === "commands:save"} icon={SaveIcon} />
                {t("common.save", "Save")}
              </Button>
            </ButtonGroup>
          </CardAction>
        </CardHeader>
        <CardContent className="min-h-0 md:flex-1">
          {entries.length ? (
            <ScrollArea className="h-[calc(100vh-21rem)] rounded-md border md:h-full">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[36%]">{t("commands.phrase", "Phrase")}</TableHead>
                    <TableHead>{t("mapping.result", "Result")}</TableHead>
                    <TableHead className="w-32 text-right">{t("mapping.action", "Action")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {entries.map((entry) => {
                    const mapped = commandAsMappingEntry(entry)
                    const action = envelope.actions.find((item) => item.id === entry.action)
                    return (
                      <TableRow key={entry.id}>
                        <TableCell className="align-middle">
                          <div className="flex min-w-0 items-center gap-2">
                            <span className="truncate font-medium">
                              {entry.phrase || t("commands.untitled", "Untitled")}
                            </span>
                            <Badge variant={entry.enabled ? "default" : "secondary"}>
                              {entry.enabled ? t("commands.enabled", "Enabled") : t("commands.disabled", "Disabled")}
                            </Badge>
                          </div>
                        </TableCell>
                        <TableCell className="align-middle">
                          <div className="flex min-w-0 flex-col gap-1">
                            <span className="truncate">{mappingActionLabel(entry.action, action?.label, t)}</span>
                            <span className="truncate text-sm text-muted-foreground">
                              {mappingActionSummary(mapped, tools, t)}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell className="align-middle text-right">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setEditingCommandId(entry.id)}
                          >
                            <SettingsIcon data-icon="inline-start" />
                            {t("mapping.open_editor", "Open editor")}
                          </Button>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </ScrollArea>
          ) : (
            <Empty className="rounded-md border">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <KeyboardIcon />
                </EmptyMedia>
                <EmptyTitle>{t("commands.empty_title", "No commands")}</EmptyTitle>
                <EmptyDescription>{t("commands.empty_description", "Add a spoken phrase and map it to an action.")}</EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
        </CardContent>
        <CardFooter className="shrink-0 justify-between text-sm text-muted-foreground">
          <span>
            {t("mapping.revision", "Revision")} {envelope.commands.revision} · {t("mapping.updated", "Updated")} {updatedAt}
          </span>
          <span>{touched ? t("mapping.unsaved_hint", "Unsaved changes") : t("mapping.saved_hint", "Saved changes sync to the watch while connected")}</span>
        </CardFooter>
      </Card>

      <Card className="md:h-full">
        <CardHeader>
          <CardTitle>{t("commands.last_result", "Last command")}</CardTitle>
          <CardDescription>{t("commands.last_result_description", "Latest command-mode recognition result.")}</CardDescription>
        </CardHeader>
        <CardContent>
          {lastCommand ? (
            <Table>
              <TableBody>
                <TableRow>
                  <TableCell className="font-medium">{t("commands.heard", "Heard")}</TableCell>
                  <TableCell className="text-muted-foreground">{lastCommand.text || "--"}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell className="font-medium">{t("commands.match", "Match")}</TableCell>
                  <TableCell>
                    <Badge variant={lastCommand.matched ? "default" : "secondary"}>
                      {lastCommand.matched ? lastCommand.phrase : lastCommand.reason}
                    </Badge>
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell className="font-medium">{t("commands.score", "Score")}</TableCell>
                  <TableCell className="text-muted-foreground">{Math.round(lastCommand.score * 100)}%</TableCell>
                </TableRow>
                {lastCommand.error && (
                  <TableRow>
                    <TableCell className="font-medium">{t("commands.error", "Error")}</TableCell>
                    <TableCell className="text-muted-foreground">{lastCommand.error}</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          ) : (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <KeyboardIcon />
                </EmptyMedia>
                <EmptyTitle>{t("commands.no_result", "No command yet")}</EmptyTitle>
                <EmptyDescription>{t("commands.no_result_description", "Hold the left button and speak a command.")}</EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
        </CardContent>
      </Card>

      <Sheet open={Boolean(selectedCommand)} onOpenChange={(open) => !open && setEditingCommandId(null)}>
        <SheetContent className="w-[min(520px,calc(100vw-2rem))] sm:max-w-lg">
          <SheetHeader>
            <SheetTitle>{selectedCommand?.phrase || t("commands.edit_title", "Edit command")}</SheetTitle>
            <SheetDescription>{t("commands.edit_description", "Choose what this spoken phrase does.")}</SheetDescription>
          </SheetHeader>

          {selectedCommand && (
            <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
              <FieldGroup>
                <Field data-invalid={!selectedCommand.phrase.trim() ? true : undefined}>
                  <FieldLabel>{t("commands.phrase", "Phrase")}</FieldLabel>
                  <Input
                    value={selectedCommand.phrase}
                    onChange={(event) => onChange({ ...selectedCommand, phrase: event.target.value })}
                    placeholder={t("commands.phrase_placeholder", "Clear")}
                    aria-invalid={!selectedCommand.phrase.trim()}
                  />
                  <FieldDescription>{t("commands.phrase_description", "Say this while holding the left button.")}</FieldDescription>
                </Field>
                <Field>
                  <FieldLabel>{t("commands.aliases", "Aliases")}</FieldLabel>
                  <Input
                    value={selectedCommand.aliases.join(", ")}
                    onChange={(event) =>
                      onChange({
                        ...selectedCommand,
                        aliases: event.target.value
                          .split(",")
                          .map((value) => value.trim())
                          .filter(Boolean),
                      })
                    }
                    placeholder={t("commands.aliases_placeholder", "Clear input, remove text")}
                  />
                  <FieldDescription>{t("commands.aliases_description", "Separate alternatives with commas.")}</FieldDescription>
                </Field>
                <Field>
                  <FieldLabel>{t("commands.enabled", "Enabled")}</FieldLabel>
                  <ToggleGroup
                    aria-label={t("commands.enabled", "Enabled")}
                    spacing={0}
                    variant="outline"
                    value={[selectedCommand.enabled ? "1" : "0"]}
                    onValueChange={(values) => {
                      const value = values[values.length - 1]
                      if (value != null) {
                        onChange({ ...selectedCommand, enabled: value === "1" })
                      }
                    }}
                  >
                    <ToggleGroupItem className="flex-1" value="1">
                      {t("commands.enabled", "Enabled")}
                    </ToggleGroupItem>
                    <ToggleGroupItem className="flex-1" value="0">
                      {t("commands.disabled", "Disabled")}
                    </ToggleGroupItem>
                  </ToggleGroup>
                </Field>
                <Field>
                  <FieldLabel>{t("mapping.action", "Action")}</FieldLabel>
                  <Select
                    items={actionItems}
                    value={selectedCommand.action}
                    onValueChange={(value) => {
                      if (value == null) {
                        return
                      }
                      const mapped = withMappingAction(commandAsMappingEntry(selectedCommand), value)
                      onChange(commandWithMappingEntry(selectedCommand, mapped))
                    }}
                    disabled={disabled}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder={t("mapping.action", "Action")} />
                    </SelectTrigger>
                    <SelectContent alignItemWithTrigger={false}>
                      <SelectGroup>
                        <SelectLabel>{t("mapping.actions", "Actions")}</SelectLabel>
                        {actionItems.map((item) => (
                          <SelectItem key={item.value} value={item.value}>
                            {item.label}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                </Field>
                <Field>
                  <FieldTitle>{t("mapping.parameters", "Parameters")}</FieldTitle>
                  <MappingParameterEditor
                    entry={commandAsMappingEntry(selectedCommand)}
                    envelope={tools}
                    disabled={disabled}
                    onChange={(nextEntry) => onChange(commandWithMappingEntry(selectedCommand, nextEntry))}
                    t={t}
                  />
                </Field>
              </FieldGroup>
            </div>
          )}

          <SheetFooter>
            {selectedCommand && (
              <Button variant="destructive" onClick={() => onDelete(selectedCommand.id)} disabled={disabled}>
                <Trash2Icon data-icon="inline-start" />
                {t("commands.delete", "Delete")}
              </Button>
            )}
            <Button variant="outline" onClick={() => setEditingCommandId(null)}>
              {t("common.done", "Done")}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </section>
  )
}

function App() {
  useSystemTheme()

  const [statusEnvelope, setStatusEnvelope] = useState<StatusEnvelope | null>(null)
  const [logsEnvelope, setLogsEnvelope] = useState<LogsEnvelope | null>(null)
  const [telemetryEnvelope, setTelemetryEnvelope] = useState<TelemetryEnvelope | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [selectedModel, setSelectedModel] = useState<string>("small")
  const [modelSelectionTouched, setModelSelectionTouched] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [autoFollowLogs, setAutoFollowLogs] = useState(true)
  const [page, setPage] = useState<PageKey>("home")
  const [language, setLanguage] = useState<LanguageCode>(() => detectInitialLanguage())
  const [mappingEnvelope, setMappingEnvelope] = useState<MappingEnvelope | null>(null)
  const [mappingEntries, setMappingEntries] = useState<MappingEntry[]>([])
  const [mappingTouched, setMappingTouched] = useState(false)
  const [mappingRefreshing, setMappingRefreshing] = useState(false)
  const [commandEnvelope, setCommandEnvelope] = useState<CommandEnvelope | null>(null)
  const [commandEntries, setCommandEntries] = useState<CommandEntry[]>([])
  const [commandTouched, setCommandTouched] = useState(false)
  const [commandRefreshing, setCommandRefreshing] = useState(false)

  const latestStatusRef = useRef<StatusEnvelope | null>(null)
  const latestLogsRef = useRef<LogsEnvelope | null>(null)
  const latestTelemetryRef = useRef<TelemetryEnvelope | null>(null)
  const latestMappingRef = useRef<MappingEnvelope | null>(null)
  const latestCommandRef = useRef<CommandEnvelope | null>(null)
  const latestTelemetryRenderKeyRef = useRef("")
  const permissionRestartInFlight = useRef(false)
  const logEndRef = useRef<HTMLDivElement | null>(null)

  const status = statusEnvelope?.status ?? null
  const telemetry = telemetryEnvelope?.telemetry ?? null
  const currentModel = status?.model ?? null
  const controlsDisabled = busyAction !== null
  const activeModel = selectedModel || currentModel?.selected || "small"
  const isCurrentModel = activeModel === currentModel?.selected
  const t = useMemo(() => createTranslator(language), [language])
  const languageItems = useMemo(
    () => LANGUAGE_OPTIONS.map((option) => ({ label: option.label, value: option.value })),
    []
  )

  const logEntries = useMemo(
    () => logsEnvelope?.logs.entries.map(structuredLogEntry) ?? [],
    [logsEnvelope]
  )

  const rawDailyState = useMemo(
    () => deriveDailyState(status, logEntries, telemetry),
    [status, logEntries, telemetry]
  )
  const dailyState = useMemo(() => localizedDailyState(rawDailyState, t), [rawDailyState, t])

  const dictation = useMemo(() => latestDictation(logEntries, telemetry), [logEntries, telemetry])
  const activity = useMemo(() => recentActivity(logEntries), [logEntries])

  const modelItems = useMemo(() => {
    const items: Array<{ label: string; value: string }> = MODEL_OPTIONS.map((model) => ({
      label: modelDisplayLabel(model.value, t),
      value: model.value,
    }))
    const known = new Set<string>(MODEL_IDS)
    for (const value of [currentModel?.selected, selectedModel]) {
      if (value && !known.has(value)) {
        known.add(value)
        items.push({ label: modelDisplayLabel(value, t), value })
      }
    }
    return items
  }, [currentModel?.selected, selectedModel, t])

  const selectedModelDetail = useMemo(
    () => modelDetail(activeModel, t),
    [activeModel, t]
  )

  const applySnapshots = useCallback(
    (nextStatus: StatusEnvelope, nextLogs: LogsEnvelope, nextTelemetry?: TelemetryEnvelope | null) => {
      latestStatusRef.current = nextStatus
      latestLogsRef.current = nextLogs
      setStatusEnvelope(nextStatus)
      setLogsEnvelope(nextLogs)
      if (nextTelemetry) {
        latestTelemetryRef.current = nextTelemetry
        latestTelemetryRenderKeyRef.current = telemetryRenderKey(nextTelemetry)
        setTelemetryEnvelope(nextTelemetry)
      }
      setLastUpdated(new Date())
    },
    []
  )

  const applyMappingSnapshot = useCallback((nextMapping: MappingEnvelope) => {
    latestMappingRef.current = nextMapping
    setMappingEnvelope(nextMapping)
    setMappingEntries(nextMapping.mapping.entries)
    setMappingTouched(false)
  }, [])

  const applyCommandSnapshot = useCallback((nextCommands: CommandEnvelope) => {
    latestCommandRef.current = nextCommands
    setCommandEnvelope(nextCommands)
    setCommandEntries(nextCommands.commands.entries)
    setCommandTouched(false)
  }, [])

  const showNotice = useCallback(
    (
      message: string,
      level: Notice["level"] = "info",
      toastType?: "success" | "info" | "warning" | "error"
    ) => {
      setNotice({ level, message })
      if (toastType) {
        toast.add({
          title: level === "error" ? t("notice.action_failed", "Action failed") : "M5StopWatch",
          description: message,
          type: toastType,
        })
      }
    },
    [t]
  )

  const refreshMappings = useCallback(
    async ({ notifyErrors = false }: { notifyErrors?: boolean } = {}) => {
      setMappingRefreshing(true)
      try {
        const payload = await helperMappings()
        applyMappingSnapshot(payload)
      } catch (error) {
        showNotice(errorMessage(error), "error", notifyErrors ? "error" : undefined)
      } finally {
        setMappingRefreshing(false)
      }
    },
    [applyMappingSnapshot, showNotice]
  )

  const refreshCommands = useCallback(
    async ({ notifyErrors = false }: { notifyErrors?: boolean } = {}) => {
      setCommandRefreshing(true)
      try {
        const payload = await helperCommands()
        applyCommandSnapshot(payload)
      } catch (error) {
        showNotice(errorMessage(error), "error", notifyErrors ? "error" : undefined)
      } finally {
        setCommandRefreshing(false)
      }
    },
    [applyCommandSnapshot, showNotice]
  )

  const restartAfterInputPermissionGrant = useCallback(
    async (snapshot: StatusEnvelope) => {
      if (
        !serviceNeedsInputPermissionRestart(snapshot.status) ||
        permissionRestartInFlight.current
      ) {
        return false
      }

      permissionRestartInFlight.current = true
      try {
        showNotice("input permission granted; restarting service", "info")
        const payload = await invokeServiceAction("restart")
        showNotice(
          payload.message,
          payload.ok ? "info" : "error",
          payload.ok ? "success" : "error"
        )
        if (payload.ok) {
          await sleep(SERVICE_SETTLE_MS)
          const [nextStatus, nextLogs, nextTelemetry] = await Promise.all([
            helperStatus(),
            helperLogs(LOG_LINES),
            helperTelemetry().catch(() => null),
          ])
          applySnapshots(nextStatus, nextLogs, nextTelemetry)
        }
        return payload.ok
      } finally {
        permissionRestartInFlight.current = false
      }
    },
    [applySnapshots, showNotice]
  )

  const refreshAll = useCallback(
    async ({
      clearNotice = false,
      notifyErrors = false,
      showBusy = false,
    }: {
      clearNotice?: boolean
      notifyErrors?: boolean
      showBusy?: boolean
    } = {}) => {
      if (showBusy) {
        setRefreshing(true)
      }
      try {
        const [nextStatus, nextLogs, nextTelemetry] = await Promise.all([
          helperStatus(),
          helperLogs(LOG_LINES),
          helperTelemetry().catch(() => null),
        ])
        applySnapshots(nextStatus, nextLogs, nextTelemetry)
        const restarted = await restartAfterInputPermissionGrant(nextStatus)
        if (!restarted && clearNotice) {
          setNotice(null)
        }
      } catch (error) {
        showNotice(errorMessage(error), "error", notifyErrors ? "error" : undefined)
      } finally {
        if (showBusy) {
          setRefreshing(false)
        }
      }
    },
    [applySnapshots, restartAfterInputPermissionGrant, showNotice]
  )

  const refreshTelemetry = useCallback(async () => {
    try {
      const nextTelemetry = await helperTelemetry()
      const key = telemetryRenderKey(nextTelemetry)
      latestTelemetryRef.current = nextTelemetry
      if (key === latestTelemetryRenderKeyRef.current) {
        return
      }
      latestTelemetryRenderKeyRef.current = key
      setTelemetryEnvelope(nextTelemetry)
    } catch {
      // Telemetry is an enhancement; status/log polling remains authoritative.
    }
  }, [])

  useEffect(() => {
    void refreshAll({ notifyErrors: true })
    const timer = window.setInterval(() => {
      void refreshAll()
    }, POLL_MS)

    return () => window.clearInterval(timer)
  }, [refreshAll])

  useEffect(() => {
    void refreshMappings({ notifyErrors: true })
  }, [refreshMappings])

  useEffect(() => {
    void refreshCommands({ notifyErrors: true })
  }, [refreshCommands])

  useEffect(() => {
    void refreshTelemetry()
    const timer = window.setInterval(() => {
      void refreshTelemetry()
    }, TELEMETRY_POLL_MS)

    return () => window.clearInterval(timer)
  }, [refreshTelemetry])

  useEffect(() => {
    const current = currentModel?.selected
    if (current && !modelSelectionTouched) {
      setSelectedModel(current)
    }
  }, [currentModel?.selected, modelSelectionTouched])

  useEffect(() => {
    persistLanguage(language)
  }, [language])

  useEffect(() => {
    if (!autoFollowLogs || !diagnosticsOpen) {
      return
    }
    window.requestAnimationFrame(() => {
      logEndRef.current?.scrollIntoView({ block: "end" })
    })
  }, [autoFollowLogs, diagnosticsOpen, logEntries.length, logsEnvelope])

  const runServiceAction = useCallback(
    async (action: ServiceAction) => {
      setBusyAction(`service:${action}`)
      try {
        const payload = await invokeServiceAction(action)
        showNotice(
          payload.message,
          payload.ok ? "info" : "error",
          payload.ok ? "success" : "error"
        )
        if (payload.ok && ["install", "start", "restart"].includes(action)) {
          await sleep(SERVICE_SETTLE_MS)
        }
        await refreshAll({ notifyErrors: true })
      } catch (error) {
        showNotice(errorMessage(error), "error", "error")
      } finally {
        setBusyAction(null)
      }
    },
    [refreshAll, showNotice]
  )

  const runModelAction = useCallback(
    async (action: ModelAction) => {
      const model = activeModel
      if (!model) {
        return
      }

      setBusyAction(`model:${action}`)
      try {
        const serviceWasRunning = Boolean(latestStatusRef.current?.status.service.running)
        const serviceWasInstalled = Boolean(latestStatusRef.current?.status.service.installed)

        showNotice(`${actionTitle(action)} ${model}`, "info")
        const payload = await invokeModelAction(action, model)
        showNotice(
          modelActionMessage(payload),
          payload.ok ? "info" : "error",
          payload.ok ? "success" : "error"
        )

        if (payload.ok && action === "use") {
          setModelSelectionTouched(false)
        }

        if (payload.ok && action === "use" && serviceWasInstalled) {
          showNotice("model changed; updating service", "info")
          const install = await invokeServiceAction("install")
          showNotice(
            install.message,
            install.ok ? "info" : "error",
            install.ok ? "success" : "error"
          )
          if (install.ok) {
            await sleep(SERVICE_SETTLE_MS)
            if (!serviceWasRunning) {
              const stop = await invokeServiceAction("stop")
              showNotice(
                stop.message,
                stop.ok ? "info" : "error",
                stop.ok ? "success" : "error"
              )
            }
          }
        } else if (
          payload.ok &&
          serviceWasRunning &&
          ["update", "repair"].includes(action)
        ) {
          showNotice("model changed; restarting service", "info")
          const restart = await invokeServiceAction("restart")
          showNotice(
            restart.message,
            restart.ok ? "info" : "error",
            restart.ok ? "success" : "error"
          )
          if (restart.ok) {
            await sleep(SERVICE_SETTLE_MS)
          }
        }

        await refreshAll({ notifyErrors: true })
      } catch (error) {
        showNotice(errorMessage(error), "error", "error")
      } finally {
        setBusyAction(null)
      }
    },
    [activeModel, refreshAll, showNotice]
  )

  const requestPermission = useCallback(
    async (kind: PermissionKind) => {
      setBusyAction(`permission:${kind}`)
      try {
        const payload = await openPermissionPanel(kind)
        showNotice(
          payload.message,
          payload.ok ? "info" : "error",
          payload.ok ? "success" : "error"
        )
        if (
          payload.ok &&
          kind === "input" &&
          latestStatusRef.current?.status.service.running
        ) {
          showNotice("input permission granted; restarting service", "info")
          const restart = await invokeServiceAction("restart")
          showNotice(
            restart.message,
            restart.ok ? "info" : "error",
            restart.ok ? "success" : "error"
          )
          if (restart.ok) {
            await sleep(SERVICE_SETTLE_MS)
          }
        }
        await refreshAll({ notifyErrors: true })
      } catch (error) {
        showNotice(errorMessage(error), "error", "error")
      } finally {
        setBusyAction(null)
      }
    },
    [refreshAll, showNotice]
  )

  const updateMappingEntry = useCallback((entry: MappingEntry) => {
    setMappingEntries((currentEntries) => {
      const nextEntry = {
        ...entry,
        flags: entry.flags ?? 0,
      }
      const index = currentEntries.findIndex((item) => item.event === nextEntry.event)
      if (index === -1) {
        return [...currentEntries, nextEntry]
      }
      const nextEntries = [...currentEntries]
      nextEntries[index] = nextEntry
      return nextEntries
    })
    setMappingTouched(true)
  }, [])

  const saveEventMappings = useCallback(async () => {
    setBusyAction("mapping:save")
    try {
      const payload = await saveMappings(mappingEntries)
      applyMappingSnapshot(payload)
      showNotice("event map saved", "info", "success")
    } catch (error) {
      showNotice(errorMessage(error), "error", "error")
    } finally {
      setBusyAction(null)
    }
  }, [applyMappingSnapshot, mappingEntries, showNotice])

  const resetEventMappings = useCallback(async () => {
    setBusyAction("mapping:reset")
    try {
      const payload = await resetMappings()
      applyMappingSnapshot(payload)
      showNotice("event map reset", "info", "success")
    } catch (error) {
      showNotice(errorMessage(error), "error", "error")
    } finally {
      setBusyAction(null)
    }
  }, [applyMappingSnapshot, showNotice])

  const updateCommandEntry = useCallback((entry: CommandEntry) => {
    setCommandEntries((currentEntries) => {
      const nextEntry = {
        ...entry,
        flags: entry.flags ?? 0,
      }
      const index = currentEntries.findIndex((item) => item.id === nextEntry.id)
      if (index === -1) {
        return [...currentEntries, nextEntry]
      }
      const nextEntries = [...currentEntries]
      nextEntries[index] = nextEntry
      return nextEntries
    })
    setCommandTouched(true)
  }, [])

  const deleteCommandEntry = useCallback((id: string) => {
    setCommandEntries((currentEntries) => currentEntries.filter((entry) => entry.id !== id))
    setCommandTouched(true)
  }, [])

  const saveCommandMappings = useCallback(async () => {
    setBusyAction("commands:save")
    try {
      const payload = await saveCommands(commandEntries)
      applyCommandSnapshot(payload)
      showNotice("commands saved", "info", "success")
    } catch (error) {
      showNotice(errorMessage(error), "error", "error")
    } finally {
      setBusyAction(null)
    }
  }, [applyCommandSnapshot, commandEntries, showNotice])

  const resetCommandMappings = useCallback(async () => {
    setBusyAction("commands:reset")
    try {
      const payload = await resetCommands()
      applyCommandSnapshot(payload)
      showNotice("commands reset", "info", "success")
    } catch (error) {
      showNotice(errorMessage(error), "error", "error")
    } finally {
      setBusyAction(null)
    }
  }, [applyCommandSnapshot, showNotice])

  const openLogs = useCallback(async () => {
    setBusyAction("logs")
    try {
      await openLogsFolder()
    } catch (error) {
      showNotice(errorMessage(error), "error", "error")
    } finally {
      setBusyAction(null)
    }
  }, [showNotice])

  const copyDiagnostics = useCallback(async () => {
    setBusyAction("diagnostics")
    try {
      const snapshotStatus = latestStatusRef.current ?? (await helperStatus())
      const snapshotLogs = latestLogsRef.current ?? (await helperLogs(LOG_LINES))
      const snapshotTelemetry =
        latestTelemetryRef.current ?? (await helperTelemetry().catch(() => null))
      const snapshotMapping =
        latestMappingRef.current ?? (await helperMappings().catch(() => null))
      const snapshotCommands =
        latestCommandRef.current ?? (await helperCommands().catch(() => null))
      await navigator.clipboard.writeText(
        JSON.stringify(
          {
            generated_at: new Date().toISOString(),
            status: snapshotStatus,
            telemetry: snapshotTelemetry,
            mapping: snapshotMapping,
            commands: snapshotCommands,
            logs: snapshotLogs,
          },
          null,
          2
        )
      )
      showNotice("diagnostics copied", "info", "success")
    } catch (error) {
      showNotice(errorMessage(error), "error", "error")
    } finally {
      setBusyAction(null)
    }
  }, [showNotice])

  const modelInstalled = Boolean(currentModel?.installed)
  const deleteModelDisabled =
    controlsDisabled ||
    !currentModel ||
    !isCurrentModel ||
    !modelInstalled ||
    currentModel.source === "bundled" ||
    Boolean(status?.service.running)
  const installModelDisabled =
    controlsDisabled || !activeModel || (isCurrentModel && modelInstalled)
  const updateModelDisabled =
    controlsDisabled ||
    !currentModel ||
    !isCurrentModel ||
    !currentModel.update_available
  const repairModelDisabled =
    controlsDisabled || !currentModel || !isCurrentModel || !modelInstalled
  const useModelDisabled = controlsDisabled || !activeModel || isCurrentModel
  const serviceModelBlocked = currentModel ? modelBlocksServiceStart(currentModel) : true

  const handleDailyAction = useCallback(() => {
    switch (dailyState.action) {
      case "start":
        void runServiceAction("start")
        break
      case "retry":
        void runServiceAction("restart")
        break
      case "install-model":
        void runModelAction("install")
        break
      case "request-bluetooth":
        void requestPermission("bluetooth")
        break
      case "request-input":
        void requestPermission("input")
        break
      case "diagnostics":
        setDiagnosticsOpen(true)
        break
    }
  }, [dailyState.action, requestPermission, runModelAction, runServiceAction])

  const primaryActionLabel: Record<NonNullable<DailyState["action"]>, string> = {
    start: t("action.start_voice", "Start voice"),
    retry: t("action.retry_link", "Retry link"),
    "install-model": t("action.install_model", "Install model"),
    "request-bluetooth": t("action.allow_bluetooth", "Allow Bluetooth"),
    "request-input": t("action.allow_text_input", "Allow text input"),
    diagnostics: t("action.open_diagnostics", "Open diagnostics"),
  }

  return (
    <div className="min-h-screen bg-background text-foreground md:h-screen md:overflow-hidden">
      <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-3 p-4 sm:p-5 md:h-full md:min-h-0 md:overflow-hidden">
        <header className="flex shrink-0 flex-col gap-3 border-b pb-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg border font-semibold">M5</div>
            <div>
              <p className="text-sm text-muted-foreground">{t("app.name", "M5StopWatch")}</p>
              <h1 className="text-2xl font-semibold tracking-tight">{t("app.title", "Speech Control")}</h1>
            </div>
            <StatusBadge state={dailyState} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Tabs value={page} onValueChange={(value) => setPage(value as PageKey)}>
              <TabsList>
                <TabsTrigger value="home">
                  <HomeIcon data-icon="inline-start" />
                  {t("nav.home", "Home")}
                </TabsTrigger>
                <TabsTrigger value="map">
                  <MapIcon data-icon="inline-start" />
                  {t("nav.map", "Map")}
                </TabsTrigger>
                <TabsTrigger value="command">
                  <KeyboardIcon data-icon="inline-start" />
                  {t("nav.command", "Command")}
                </TabsTrigger>
              </TabsList>
            </Tabs>
            <Button
              variant="outline"
              onClick={() => void refreshAll({ clearNotice: true, notifyErrors: true, showBusy: true })}
              disabled={busyAction !== null || refreshing}
            >
              <SpinnerOrIcon busy={busyAction === null && refreshing} icon={RefreshCwIcon} />
              {t("common.refresh", "Refresh")}
            </Button>
            <Button variant="outline" onClick={() => setSettingsOpen(true)}>
              <SettingsIcon data-icon="inline-start" />
              {t("common.settings", "Settings")}
            </Button>
            <Button variant="outline" onClick={() => setDiagnosticsOpen(true)}>
              <BugIcon data-icon="inline-start" />
              {t("common.diagnostics", "Diagnostics")}
            </Button>
          </div>
        </header>

        {notice && (
          <Alert className="shrink-0" variant={notice.level === "error" ? "destructive" : "default"}>
            {notice.level === "error" ? <AlertCircleIcon /> : <CheckCircle2Icon />}
            <AlertTitle>{notice.level === "error" ? t("notice.needs_attention", "Needs attention") : t("notice.notice", "Notice")}</AlertTitle>
            <AlertDescription>{notice.message}</AlertDescription>
          </Alert>
        )}

        {page === "home" ? (
          <section className="grid gap-3 md:min-h-0 md:flex-1 md:grid-cols-3 md:overflow-hidden">
            <div className="flex min-w-0 flex-col gap-3 md:col-span-2 md:min-h-0">
              <StatusCard
                state={dailyState}
                status={status}
                lastUpdated={lastUpdated}
                busyAction={busyAction}
                onAction={handleDailyAction}
                primaryActionLabel={primaryActionLabel}
                t={t}
              />
              <TranscriptCard dictation={dictation} className="md:flex-1" t={t} />
            </div>

            <div className="flex min-w-0 flex-col gap-3 md:min-h-0">
              <ModelCard model={currentModel} onOpenSettings={() => setSettingsOpen(true)} t={t} />
              <RuntimeCard state={dailyState} telemetry={telemetry} className="md:min-h-0 md:flex-1" t={t} />
            </div>
          </section>
        ) : page === "map" ? (
          <MappingPage
            envelope={mappingEnvelope}
            entries={mappingEntries}
            touched={mappingTouched}
            busyAction={busyAction}
            refreshing={mappingRefreshing}
            onRefresh={() => void refreshMappings({ notifyErrors: true })}
            onSave={() => void saveEventMappings()}
            onReset={() => void resetEventMappings()}
            onChange={updateMappingEntry}
            t={t}
          />
        ) : (
          <CommandPage
            envelope={commandEnvelope}
            entries={commandEntries}
            telemetry={telemetry}
            touched={commandTouched}
            busyAction={busyAction}
            refreshing={commandRefreshing}
            onRefresh={() => void refreshCommands({ notifyErrors: true })}
            onSave={() => void saveCommandMappings()}
            onReset={() => void resetCommandMappings()}
            onChange={updateCommandEntry}
            onDelete={deleteCommandEntry}
            t={t}
          />
        )}
      </main>

      <Sheet open={settingsOpen} onOpenChange={setSettingsOpen}>
        <SheetContent className="w-[min(760px,calc(100vw-2rem))] sm:max-w-2xl">
          <SheetHeader>
            <SheetTitle>{t("settings.title", "Settings")}</SheetTitle>
            <SheetDescription>{t("settings.description", "Model, permissions, and voice service controls.")}</SheetDescription>
          </SheetHeader>

          <div className="flex flex-col gap-4 overflow-y-auto px-4 py-4">
            <Card>
              <CardHeader>
                <CardTitle>{t("settings.general", "General")}</CardTitle>
                <CardDescription>{t("settings.general_description", "App preferences for this computer.")}</CardDescription>
              </CardHeader>
              <CardContent>
                <FieldGroup>
                  <Field orientation="horizontal">
                    <FieldContent>
                      <FieldTitle>{t("settings.language", "Language")}</FieldTitle>
                      <FieldDescription>{t("settings.language_description", "Changes apply immediately.")}</FieldDescription>
                    </FieldContent>
                    <Select
                      items={languageItems}
                      value={language}
                      onValueChange={(value) => {
                        if (value == null) {
                          return
                        }
                        setLanguage(value as LanguageCode)
                      }}
                    >
                      <SelectTrigger className="w-40">
                        <SelectValue placeholder={t("settings.language", "Language")} />
                      </SelectTrigger>
                      <SelectContent alignItemWithTrigger={false}>
                        <SelectGroup>
                          {languageItems.map((item) => (
                            <SelectItem key={item.value} value={item.value}>
                              {item.label}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </Field>
                </FieldGroup>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>{t("settings.speech_model", "Speech model")}</CardTitle>
                <CardDescription>{selectedModelDetail}</CardDescription>
              </CardHeader>
              <CardContent>
                <FieldGroup>
                  <Field>
                    <FieldLabel>{t("settings.model", "Model")}</FieldLabel>
                    <Select
                      items={modelItems}
                      value={activeModel}
                      onValueChange={(value) => {
                        if (!value) {
                          return
                        }
                        setModelSelectionTouched(true)
                        setSelectedModel(value)
                      }}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder={t("settings.select_model", "Select model")} />
                      </SelectTrigger>
                      <SelectContent alignItemWithTrigger={false}>
                        <SelectGroup>
                          <SelectLabel>{t("settings.available_models", "Available models")}</SelectLabel>
                          {modelItems.map((item) => (
                            <SelectItem key={item.value} value={item.value}>
                              {item.label}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                    <FieldDescription>
                      {t("settings.current_model", "Current")}: {modelDisplayLabel(currentModel?.selected, t)} / {currentModel?.message ?? t("common.unknown", "Unknown")}
                    </FieldDescription>
                  </Field>
                  <Field orientation="horizontal">
                    <FieldContent>
                      <FieldTitle>{t("home.storage", "Storage")}</FieldTitle>
                      <FieldDescription>{formatBytes(currentModel?.disk_bytes ?? 0)}</FieldDescription>
                    </FieldContent>
                    <Badge variant={readinessVariant(Boolean(currentModel?.installed))}>
                      {currentModel?.state ?? "unknown"}
                    </Badge>
                  </Field>
                  <Field orientation="horizontal">
                    <FieldContent>
                      <FieldTitle>{t("settings.update", "Update")}</FieldTitle>
                      <FieldDescription>
                        {currentModel?.update_available ? t("settings.update_available", "An update is available.") : t("settings.no_update", "No update is available.")}
                      </FieldDescription>
                    </FieldContent>
                    <Badge variant={currentModel?.update_available ? "secondary" : "outline"}>
                      {currentModel?.update_available ? t("settings.available", "Available") : t("settings.current", "Current")}
                    </Badge>
                  </Field>
                </FieldGroup>
              </CardContent>
              <CardFooter className="flex flex-wrap gap-2">
                <Button onClick={() => void runModelAction("use")} disabled={useModelDisabled}>
                  <SpinnerOrIcon busy={busyAction === "model:use"} icon={CheckCircle2Icon} />
                  {t("settings.use", "Use")}
                </Button>
                <Button variant="outline" onClick={() => void runModelAction("install")} disabled={installModelDisabled}>
                  <SpinnerOrIcon busy={busyAction === "model:install"} icon={DownloadIcon} />
                  {t("settings.install", "Install")}
                </Button>
                <Button variant="outline" onClick={() => void runModelAction("update")} disabled={updateModelDisabled}>
                  <SpinnerOrIcon busy={busyAction === "model:update"} icon={RefreshCwIcon} />
                  {t("settings.update", "Update")}
                </Button>
                <Button variant="outline" onClick={() => void runModelAction("repair")} disabled={repairModelDisabled}>
                  <SpinnerOrIcon busy={busyAction === "model:repair"} icon={WrenchIcon} />
                  {t("settings.repair", "Repair")}
                </Button>
                <Button variant="destructive" onClick={() => setDeleteOpen(true)} disabled={deleteModelDisabled}>
                  <Trash2Icon data-icon="inline-start" />
                  {t("settings.delete", "Delete")}
                </Button>
              </CardFooter>
            </Card>

            <PermissionPanel
              status={status}
              busyAction={busyAction}
              requestPermission={(kind) => void requestPermission(kind)}
              t={t}
            />

            <Card>
              <CardHeader>
                <CardTitle>{t("settings.voice_service", "Voice service")}</CardTitle>
                <CardDescription>{t("settings.voice_service_description", "Advanced controls for the background process.")}</CardDescription>
              </CardHeader>
              <CardContent>
                <FieldGroup>
                  <Field orientation="horizontal">
                    <FieldContent>
                      <FieldTitle>{t("settings.login_service", "Login service")}</FieldTitle>
                      <FieldDescription>
                        {status?.service.installed ? t("settings.installed", "installed") : t("settings.not_installed", "not installed")} /{" "}
                        {status?.service.running ? t("settings.running", "running") : t("settings.stopped", "stopped")}
                      </FieldDescription>
                    </FieldContent>
                    <Badge variant={readinessVariant(Boolean(status?.service.running))}>
                      {status?.service.running ? t("settings.running_badge", "Running") : t("settings.stopped_badge", "Stopped")}
                    </Badge>
                  </Field>
                  {serviceModelBlocked && (
                    <Alert>
                      <AlertCircleIcon />
                      <AlertTitle>{t("settings.model_required", "Model required")}</AlertTitle>
                      <AlertDescription>{t("settings.model_required_description", "Install a model before starting the voice service.")}</AlertDescription>
                    </Alert>
                  )}
                </FieldGroup>
              </CardContent>
              <CardFooter>
                <ButtonGroup className="flex-wrap">
                  <Button variant="outline" onClick={() => void runServiceAction("install")} disabled={controlsDisabled}>
                    <SpinnerOrIcon busy={busyAction === "service:install"} icon={DownloadIcon} />
                    {t("settings.install", "Install")}
                  </Button>
                  <Button onClick={() => void runServiceAction("start")} disabled={controlsDisabled || serviceModelBlocked}>
                    <SpinnerOrIcon busy={busyAction === "service:start"} icon={PlayIcon} />
                    {t("settings.start", "Start")}
                  </Button>
                  <Button variant="outline" onClick={() => void runServiceAction("stop")} disabled={controlsDisabled}>
                    <SpinnerOrIcon busy={busyAction === "service:stop"} icon={SquareIcon} />
                    {t("settings.stop", "Stop")}
                  </Button>
                  <Button variant="outline" onClick={() => void runServiceAction("restart")} disabled={controlsDisabled || serviceModelBlocked}>
                    <SpinnerOrIcon busy={busyAction === "service:restart"} icon={RotateCcwIcon} />
                    {t("settings.restart", "Restart")}
                  </Button>
                </ButtonGroup>
              </CardFooter>
            </Card>
          </div>
        </SheetContent>
      </Sheet>

      <Sheet open={diagnosticsOpen} onOpenChange={setDiagnosticsOpen}>
        <SheetContent className="w-[min(1040px,calc(100vw-2rem))] sm:max-w-5xl">
          <SheetHeader>
            <SheetTitle>Diagnostics</SheetTitle>
            <SheetDescription>Technical state and logs for troubleshooting.</SheetDescription>
          </SheetHeader>

          <Tabs defaultValue="overview" className="min-h-0 flex-1 px-4 pb-4">
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="runtime">Runtime</TabsTrigger>
              <TabsTrigger value="logs">Logs</TabsTrigger>
            </TabsList>

            <TabsContent value="overview" className="min-h-0">
              <ScrollArea className="h-[calc(100vh-9rem)] pr-3">
                <div className="flex flex-col gap-4 py-4">
                  <Card>
                    <CardHeader>
                      <CardTitle>Status details</CardTitle>
                      <CardDescription>Raw readiness checks from the helper.</CardDescription>
                    </CardHeader>
                    <CardContent>
                      {status ? (
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Check</TableHead>
                              <TableHead>State</TableHead>
                              <TableHead>Detail</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {DIAGNOSTIC_ROWS.map(([key, label]) => {
                              const ok = diagnosticOk(status, key)
                              return (
                                <TableRow key={key}>
                                  <TableCell className="font-medium">{label}</TableCell>
                                  <TableCell>
                                    <Badge variant={readinessVariant(ok)}>{ok ? "OK" : "Check"}</Badge>
                                  </TableCell>
                                  <TableCell className="whitespace-normal text-muted-foreground">
                                    {diagnosticDetail(status, key)}
                                  </TableCell>
                                </TableRow>
                              )
                            })}
                          </TableBody>
                        </Table>
                      ) : (
                        <div className="flex flex-col gap-3">
                          <Skeleton className="h-8 w-full" />
                          <Skeleton className="h-8 w-4/5" />
                          <Skeleton className="h-8 w-3/5" />
                        </div>
                      )}
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader>
                      <CardTitle>Recent activity</CardTitle>
                      <CardDescription>User-facing events derived from logs.</CardDescription>
                    </CardHeader>
                    <CardContent>
                      {activity.length ? (
                        <Table>
                          <TableBody>
                            {activity.map((item) => (
                              <TableRow key={item.key}>
                                <TableCell className="w-28 text-xs tabular-nums">{compactTime(item.time)}</TableCell>
                                <TableCell className="w-40">
                                  <Badge variant={item.variant}>{item.label}</Badge>
                                </TableCell>
                                <TableCell className="whitespace-normal text-muted-foreground">{item.detail}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      ) : (
                        <Empty>
                          <EmptyHeader>
                            <EmptyMedia variant="icon">
                              <ActivityIcon />
                            </EmptyMedia>
                            <EmptyTitle>No events yet</EmptyTitle>
                            <EmptyDescription>Events appear after the service starts.</EmptyDescription>
                          </EmptyHeader>
                        </Empty>
                      )}
                    </CardContent>
                  </Card>
                </div>
              </ScrollArea>
            </TabsContent>

            <TabsContent value="runtime" className="min-h-0">
              <ScrollArea className="h-[calc(100vh-9rem)] pr-3">
                <div className="flex flex-col gap-4 py-4">
                  <RuntimeCard state={dailyState} telemetry={telemetry} t={t} />
                  <Card>
                    <CardHeader>
                      <CardTitle>Runtime telemetry</CardTitle>
                      <CardDescription>Live data produced by the speech helper.</CardDescription>
                    </CardHeader>
                    <CardContent>
                      <Table>
                        <TableBody>
                          <TableRow>
                            <TableCell className="font-medium">Stage</TableCell>
                            <TableCell>{telemetry?.stage ?? "unknown"}</TableCell>
                          </TableRow>
                          <TableRow>
                            <TableCell className="font-medium">Session</TableCell>
                            <TableCell>{telemetry?.session_id ?? "none"}</TableCell>
                          </TableRow>
                          <TableRow>
                            <TableCell className="font-medium">Audio level</TableCell>
                            <TableCell>{percent(telemetry?.audio.level)}</TableCell>
                          </TableRow>
                          <TableRow>
                            <TableCell className="font-medium">Peak</TableCell>
                            <TableCell>{percent(telemetry?.audio.peak)}</TableCell>
                          </TableRow>
                          <TableRow>
                            <TableCell className="font-medium">Mode</TableCell>
                            <TableCell>{telemetry?.recognition.mode ?? "unknown"}</TableCell>
                          </TableRow>
                          <TableRow>
                            <TableCell className="font-medium">Age</TableCell>
                            <TableCell>
                              {telemetry?.age_seconds == null ? "unknown" : `${telemetry.age_seconds.toFixed(2)}s`}
                              {telemetry?.stale ? " / stale" : ""}
                            </TableCell>
                          </TableRow>
                        </TableBody>
                      </Table>
                    </CardContent>
                  </Card>
                </div>
              </ScrollArea>
            </TabsContent>

            <TabsContent value="logs" className="min-h-0">
              <div className="flex h-[calc(100vh-9rem)] flex-col gap-4 py-4">
                <Card className="min-h-0 flex-1">
                  <CardHeader>
                    <div>
                      <CardTitle>Logs</CardTitle>
                      <CardDescription>Structured helper events from the local log directory.</CardDescription>
                    </div>
                    <CardAction>
                      <Button
                        variant={autoFollowLogs ? "secondary" : "outline"}
                        onClick={() => setAutoFollowLogs((value) => !value)}
                      >
                        {autoFollowLogs ? "Following" : "Follow latest"}
                      </Button>
                    </CardAction>
                  </CardHeader>
                  <CardContent className="min-h-0">
                    <ScrollArea
                      className="h-[calc(100vh-18rem)] rounded-md border"
                      onWheel={() => {
                        if (autoFollowLogs) {
                          setAutoFollowLogs(false)
                        }
                      }}
                    >
                      {logEntries.length ? (
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="w-44">Time</TableHead>
                              <TableHead className="w-24">Level</TableHead>
                              <TableHead className="w-36">Component</TableHead>
                              <TableHead>Message</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {logEntries.map((entry, index) => (
                              <TableRow key={`${entry.source}-${entry.time}-${index}`}>
                                <TableCell className="text-xs tabular-nums">{entry.time || "--"}</TableCell>
                                <TableCell>
                                  <Badge variant={logLevelVariant(entry.level)}>{entry.level}</Badge>
                                </TableCell>
                                <TableCell className="text-xs">{entry.component}</TableCell>
                                <TableCell
                                  className={cn(
                                    "max-w-[46rem] whitespace-normal text-muted-foreground",
                                    entry.level === "ERROR" && "text-destructive"
                                  )}
                                >
                                  {entry.message}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      ) : (
                        <Empty>
                          <EmptyHeader>
                            <EmptyMedia variant="icon">
                              <FileTextIcon />
                            </EmptyMedia>
                            <EmptyTitle>No logs yet</EmptyTitle>
                            <EmptyDescription>Logs appear once the helper has started.</EmptyDescription>
                          </EmptyHeader>
                        </Empty>
                      )}
                      <div ref={logEndRef} />
                    </ScrollArea>
                  </CardContent>
                </Card>
              </div>
            </TabsContent>
          </Tabs>

          <SheetFooter>
            <Button variant="outline" onClick={() => void openLogs()} disabled={busyAction !== null}>
              <SpinnerOrIcon busy={busyAction === "logs"} icon={FolderOpenIcon} />
              Open logs
            </Button>
            <Button onClick={() => void copyDiagnostics()} disabled={busyAction !== null}>
              <SpinnerOrIcon busy={busyAction === "diagnostics"} icon={ClipboardIcon} />
              Copy diagnostics
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete model?</AlertDialogTitle>
            <AlertDialogDescription>
              This removes the local cache for {modelLabel(activeModel)}. Stop the service first if the model is in use.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setDeleteOpen(false)
                void runModelAction("delete")
              }}
            >
              Delete model
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

export default App
