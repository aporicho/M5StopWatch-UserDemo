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
import { toast } from "@/components/ui/toast"
import {
  formatBytes,
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
  resetMappings,
  saveMappings,
  serviceNeedsInputPermissionRestart,
  SERVICE_SETTLE_MS,
  sleep,
  structuredLogEntry,
  TELEMETRY_POLL_MS,
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

type PageKey = "home" | "map"

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
  { label: "4x", value: 4 },
]

const WHEEL_DIRECTION_OPTIONS: MappingOption[] = [
  { label: "Normal", value: 0 },
  { label: "Inverted", value: 1 },
]

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

function mappingOptionValue(value: number | null | undefined) {
  return String(value ?? 0)
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

function ReadinessTable({ status }: { status: StatusPayload | null }) {
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
      label: "Service",
      ok: status.service.running && !status.service.error,
      detail: status.service.running ? "running" : status.service.error || "stopped",
    },
    {
      label: "Watch",
      ok: status.watch.paired,
      detail: status.watch.paired ? "connected" : status.watch.label,
    },
    {
      label: "Voice",
      ok: status.voice.ready,
      detail: status.voice.message,
    },
    {
      label: "Model",
      ok: status.model.installed,
      detail: `${modelLabel(status.model.selected)} / ${status.model.state}`,
    },
  ]

  return (
    <Table>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.label}>
            <TableCell className="w-28 font-medium">{row.label}</TableCell>
            <TableCell className="w-24">
              <Badge variant={readinessVariant(row.ok)}>{row.ok ? "OK" : "Check"}</Badge>
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
}: {
  state: DailyState
  status: StatusPayload | null
  lastUpdated: Date | null
  busyAction: string | null
  onAction: () => void
  primaryActionLabel: Record<NonNullable<DailyState["action"]>, string>
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
        <ReadinessTable status={status} />
      </CardContent>
      <CardFooter className="text-sm text-muted-foreground">
        Updated {lastUpdated ? lastUpdated.toLocaleTimeString() : "never"}
      </CardFooter>
    </Card>
  )
}

function TranscriptCard({
  dictation,
  className,
}: {
  dictation: ReturnType<typeof latestDictation>
  className?: string
}) {
  return (
    <Card size="sm" className={cn("min-h-0", className)}>
      <CardHeader>
        <div>
          <CardTitle>Transcript</CardTitle>
        </div>
        <CardAction>
          <Badge variant={dictation?.final ? "default" : "outline"}>
            {dictation?.final ? "Final" : "Live"}
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
              <EmptyTitle>No text yet</EmptyTitle>
              <EmptyDescription>Hold the watch button and speak.</EmptyDescription>
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
}: {
  state: DailyState
  telemetry: RuntimeTelemetry | null
  className?: string
}) {
  const fresh = telemetryFresh(telemetry)
  const level = fresh ? telemetry?.audio.level : 0
  const peak = fresh ? telemetry?.audio.peak : 0
  const seconds = fresh ? telemetry?.audio.seconds ?? 0 : 0

  return (
    <Card size="sm" className={className}>
      <CardHeader>
        <div>
          <CardTitle>Runtime</CardTitle>
        </div>
        <CardAction>
          {state.key === "listening" || state.key === "recognizing" ? (
            <Spinner />
          ) : (
            <Badge variant={fresh ? "outline" : "secondary"}>{fresh ? "Live" : "Idle"}</Badge>
          )}
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <Progress value={progressValue(level)}>
          <ProgressLabel>Audio level</ProgressLabel>
          <ProgressValue>{() => percent(level)}</ProgressValue>
        </Progress>
        <Progress value={progressValue(peak)}>
          <ProgressLabel>Peak</ProgressLabel>
          <ProgressValue>{() => percent(peak)}</ProgressValue>
        </Progress>
      </CardContent>
      <CardFooter>
        <p className="text-sm text-muted-foreground">
          Stage {telemetry?.stage ?? "unknown"} · Audio {seconds.toFixed(1)}s · Age{" "}
          {telemetry?.age_seconds == null ? "unknown" : `${telemetry.age_seconds.toFixed(1)}s`}
          {telemetry?.stale ? " / stale" : ""}
        </p>
      </CardFooter>
    </Card>
  )
}

function ModelCard({
  model,
  onOpenSettings,
}: {
  model: StatusPayload["model"] | null
  onOpenSettings: () => void
}) {
  return (
    <Card size="sm" className="shrink-0">
      <CardHeader>
        <div>
          <CardTitle>Model</CardTitle>
          <CardDescription>{model?.message ?? "Model status is loading."}</CardDescription>
        </div>
        <CardAction>
          <Badge variant={modelVariant(model)}>{model?.state ?? "Unknown"}</Badge>
        </CardAction>
      </CardHeader>
      <CardContent>
        {model ? (
          <Table>
            <TableBody>
              <TableRow>
                <TableCell className="font-medium">Selected</TableCell>
                <TableCell className="text-muted-foreground">{modelLabel(model.selected)}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="font-medium">Engine</TableCell>
                <TableCell className="text-muted-foreground">{model.engine}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="font-medium">Storage</TableCell>
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
          Manage model
        </Button>
      </CardFooter>
    </Card>
  )
}

function PermissionPanel({
  status,
  busyAction,
  requestPermission,
}: {
  status: StatusPayload | null
  busyAction: string | null
  requestPermission: (kind: PermissionKind) => void
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Permissions</CardTitle>
        <CardDescription>Required for Bluetooth audio and text insertion.</CardDescription>
      </CardHeader>
      <CardContent>
        <FieldGroup>
          <Field orientation="horizontal">
            <FieldContent>
              <FieldTitle>Bluetooth</FieldTitle>
              <FieldDescription>{status?.permissions.bluetooth.message ?? "Unknown"}</FieldDescription>
            </FieldContent>
            <Button
              variant="outline"
              onClick={() => requestPermission("bluetooth")}
              disabled={busyAction !== null}
            >
              <SpinnerOrIcon busy={busyAction === "permission:bluetooth"} icon={BluetoothIcon} />
              Request
            </Button>
          </Field>
          <Field orientation="horizontal">
            <FieldContent>
              <FieldTitle>Text input</FieldTitle>
              <FieldDescription>{status?.permissions.input.message ?? "Unknown"}</FieldDescription>
            </FieldContent>
            <Button
              variant="outline"
              onClick={() => requestPermission("input")}
              disabled={busyAction !== null}
            >
              <SpinnerOrIcon busy={busyAction === "permission:input"} icon={KeyboardIcon} />
              Request
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
  return (
    <Field>
      <FieldLabel>{label}</FieldLabel>
      <Select
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

function MappingParameterEditor({
  entry,
  envelope,
  disabled,
  onChange,
}: {
  entry: MappingEntry
  envelope: MappingEnvelope
  disabled: boolean
  onChange: (entry: MappingEntry) => void
}) {
  if (entry.locked) {
    return <p className="text-sm text-muted-foreground">Fixed safety shortcut.</p>
  }

  if (entry.action === "hid.keyboard.tap") {
    return (
      <FieldGroup className="grid gap-2 sm:grid-cols-2">
        <MappingSelectField
          label="Key"
          value={entry.param0}
          options={envelope.keyOptions}
          disabled={disabled}
          onChange={(value) => onChange({ ...entry, param0: value })}
        />
        <MappingSelectField
          label="Modifier"
          value={entry.param1}
          options={envelope.modifierOptions}
          disabled={disabled}
          onChange={(value) => onChange({ ...entry, param1: value })}
        />
      </FieldGroup>
    )
  }

  if (entry.action === "hid.mouse.wheel") {
    return (
      <FieldGroup className="grid gap-2 sm:grid-cols-2">
        <MappingSelectField
          label="Speed"
          value={entry.param0}
          options={WHEEL_MULTIPLIER_OPTIONS}
          disabled={disabled}
          onChange={(value) => onChange({ ...entry, param0: value })}
        />
        <MappingSelectField
          label="Direction"
          value={entry.param1}
          options={WHEEL_DIRECTION_OPTIONS}
          disabled={disabled}
          onChange={(value) => onChange({ ...entry, param1: value })}
        />
      </FieldGroup>
    )
  }

  if (entry.action === "hid.mouse.click") {
    return (
      <MappingSelectField
        label="Button"
        value={entry.param0}
        options={envelope.mouseButtons}
        disabled={disabled}
        onChange={(value) => onChange({ ...entry, param0: value })}
      />
    )
  }

  if (entry.action === "hid.media.control") {
    return (
      <MappingSelectField
        label="Media key"
        value={entry.param2}
        options={envelope.mediaControls}
        disabled={disabled}
        onChange={(value) => onChange({ ...entry, param2: value })}
      />
    )
  }

  return <p className="text-sm text-muted-foreground">No parameters.</p>
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
}) {
  const entriesByEvent = useMemo(
    () => new Map(entries.map((entry) => [entry.event, entry])),
    [entries]
  )
  const disabled = busyAction !== null || refreshing

  if (!envelope) {
    return (
      <section className="min-h-0 flex-1">
        <Card className="min-h-0">
          <CardHeader>
            <CardTitle>Event map</CardTitle>
            <CardDescription>Loading watch event configuration.</CardDescription>
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
    : "defaults"

  return (
    <section className="min-h-0 flex-1">
      <Card className="min-h-0 md:flex md:h-full md:flex-col">
        <CardHeader className="shrink-0">
          <div>
            <CardTitle>Event map</CardTitle>
            <CardDescription>Map watch gestures to keyboard, mouse, voice, and device actions.</CardDescription>
          </div>
          <CardAction>
            <ButtonGroup className="flex-wrap">
              <Button variant="outline" onClick={onRefresh} disabled={disabled}>
                <SpinnerOrIcon busy={refreshing} icon={RefreshCwIcon} />
                Refresh
              </Button>
              <Button variant="outline" onClick={onReset} disabled={disabled}>
                <SpinnerOrIcon busy={busyAction === "mapping:reset"} icon={Undo2Icon} />
                Reset
              </Button>
              <Button onClick={onSave} disabled={disabled || !touched}>
                <SpinnerOrIcon busy={busyAction === "mapping:save"} icon={SaveIcon} />
                Save
              </Button>
            </ButtonGroup>
          </CardAction>
        </CardHeader>
        <CardContent className="min-h-0 md:flex-1">
          <ScrollArea className="h-[calc(100vh-17rem)] rounded-md border md:h-full">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-48">Event</TableHead>
                  <TableHead className="w-64">Action</TableHead>
                  <TableHead>Parameters</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {envelope.events.map((event) => {
                  const locked = Boolean(event.locked)
                  const entry = entriesByEvent.get(event.id) ?? blankMappingEntry(event.id, locked)
                  const action = envelope.actions.find((item) => item.id === entry.action)
                  return (
                    <TableRow key={event.id}>
                      <TableCell className="align-top">
                        <div className="flex flex-col gap-2">
                          <span className="font-medium">{event.label}</span>
                          {locked && <Badge variant="outline">Locked</Badge>}
                        </div>
                      </TableCell>
                      <TableCell className="align-top">
                        <Select
                          value={entry.action}
                          onValueChange={(value) => {
                            if (value == null) {
                              return
                            }
                            onChange(withMappingAction({ ...entry, locked }, value))
                          }}
                          disabled={disabled || locked}
                        >
                          <SelectTrigger className="w-full">
                            <SelectValue placeholder="Action" />
                          </SelectTrigger>
                          <SelectContent alignItemWithTrigger={false}>
                            <SelectGroup>
                              <SelectLabel>Actions</SelectLabel>
                              {envelope.actions.map((item) => (
                                <SelectItem key={item.id} value={item.id}>
                                  {item.label}
                                </SelectItem>
                              ))}
                            </SelectGroup>
                          </SelectContent>
                        </Select>
                        <p className="mt-2 text-xs text-muted-foreground">
                          {action?.id ?? entry.action}
                        </p>
                      </TableCell>
                      <TableCell className="align-top">
                        <MappingParameterEditor
                          entry={{ ...entry, locked }}
                          envelope={envelope}
                          disabled={disabled}
                          onChange={(nextEntry) => onChange(nextEntry)}
                        />
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </ScrollArea>
        </CardContent>
        <CardFooter className="shrink-0 justify-between text-sm text-muted-foreground">
          <span>
            Revision {envelope.mapping.revision} · Updated {updatedAt}
          </span>
          <span>{touched ? "Unsaved changes" : "Saved changes sync to the watch while connected"}</span>
        </CardFooter>
      </Card>
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
  const [mappingEnvelope, setMappingEnvelope] = useState<MappingEnvelope | null>(null)
  const [mappingEntries, setMappingEntries] = useState<MappingEntry[]>([])
  const [mappingTouched, setMappingTouched] = useState(false)
  const [mappingRefreshing, setMappingRefreshing] = useState(false)

  const latestStatusRef = useRef<StatusEnvelope | null>(null)
  const latestLogsRef = useRef<LogsEnvelope | null>(null)
  const latestTelemetryRef = useRef<TelemetryEnvelope | null>(null)
  const latestMappingRef = useRef<MappingEnvelope | null>(null)
  const latestTelemetryRenderKeyRef = useRef("")
  const permissionRestartInFlight = useRef(false)
  const logEndRef = useRef<HTMLDivElement | null>(null)

  const status = statusEnvelope?.status ?? null
  const telemetry = telemetryEnvelope?.telemetry ?? null
  const currentModel = status?.model ?? null
  const controlsDisabled = busyAction !== null
  const activeModel = selectedModel || currentModel?.selected || "small"
  const isCurrentModel = activeModel === currentModel?.selected

  const logEntries = useMemo(
    () => logsEnvelope?.logs.entries.map(structuredLogEntry) ?? [],
    [logsEnvelope]
  )

  const dailyState = useMemo(
    () => deriveDailyState(status, logEntries, telemetry),
    [status, logEntries, telemetry]
  )

  const dictation = useMemo(() => latestDictation(logEntries, telemetry), [logEntries, telemetry])
  const activity = useMemo(() => recentActivity(logEntries), [logEntries])

  const modelItems = useMemo(() => {
    const items: Array<{ label: string; value: string }> = MODEL_OPTIONS.map((model) => ({
      label: model.label,
      value: model.value,
    }))
    const known = new Set<string>(MODEL_IDS)
    for (const value of [currentModel?.selected, selectedModel]) {
      if (value && !known.has(value)) {
        known.add(value)
        items.push({ label: value, value })
      }
    }
    return items
  }, [currentModel?.selected, selectedModel])

  const selectedModelDetail = useMemo(
    () =>
      MODEL_OPTIONS.find((model) => model.value === activeModel)?.detail ??
      "Custom model selected by the helper.",
    [activeModel]
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

  const showNotice = useCallback(
    (
      message: string,
      level: Notice["level"] = "info",
      toastType?: "success" | "info" | "warning" | "error"
    ) => {
      setNotice({ level, message })
      if (toastType) {
        toast.add({
          title: level === "error" ? "Action failed" : "M5StopWatch",
          description: message,
          type: toastType,
        })
      }
    },
    []
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
    }: {
      clearNotice?: boolean
      notifyErrors?: boolean
    } = {}) => {
      setRefreshing(true)
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
        setRefreshing(false)
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
      await navigator.clipboard.writeText(
        JSON.stringify(
          {
            generated_at: new Date().toISOString(),
            status: snapshotStatus,
            telemetry: snapshotTelemetry,
            mapping: snapshotMapping,
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
    start: "Start voice",
    retry: "Retry link",
    "install-model": "Install model",
    "request-bluetooth": "Allow Bluetooth",
    "request-input": "Allow text input",
    diagnostics: "Open diagnostics",
  }

  return (
    <div className="min-h-screen bg-background text-foreground md:h-screen md:overflow-hidden">
      <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-3 p-4 sm:p-5 md:h-full md:min-h-0 md:overflow-hidden">
        <header className="flex shrink-0 flex-col gap-3 border-b pb-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg border font-semibold">M5</div>
            <div>
              <p className="text-sm text-muted-foreground">M5StopWatch</p>
              <h1 className="text-2xl font-semibold tracking-tight">Speech Control</h1>
            </div>
            <StatusBadge state={dailyState} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Tabs value={page} onValueChange={(value) => setPage(value as PageKey)}>
              <TabsList>
                <TabsTrigger value="home">
                  <HomeIcon data-icon="inline-start" />
                  Home
                </TabsTrigger>
                <TabsTrigger value="map">
                  <MapIcon data-icon="inline-start" />
                  Map
                </TabsTrigger>
              </TabsList>
            </Tabs>
            <Button
              variant="outline"
              onClick={() => void refreshAll({ clearNotice: true, notifyErrors: true })}
              disabled={busyAction !== null || refreshing}
            >
              <SpinnerOrIcon busy={busyAction === null && refreshing} icon={RefreshCwIcon} />
              Refresh
            </Button>
            <Button variant="outline" onClick={() => setSettingsOpen(true)}>
              <SettingsIcon data-icon="inline-start" />
              Settings
            </Button>
            <Button variant="outline" onClick={() => setDiagnosticsOpen(true)}>
              <BugIcon data-icon="inline-start" />
              Diagnostics
            </Button>
          </div>
        </header>

        {notice && (
          <Alert className="shrink-0" variant={notice.level === "error" ? "destructive" : "default"}>
            {notice.level === "error" ? <AlertCircleIcon /> : <CheckCircle2Icon />}
            <AlertTitle>{notice.level === "error" ? "Needs attention" : "Notice"}</AlertTitle>
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
              />
              <TranscriptCard dictation={dictation} className="md:flex-1" />
            </div>

            <div className="flex min-w-0 flex-col gap-3 md:min-h-0">
              <ModelCard model={currentModel} onOpenSettings={() => setSettingsOpen(true)} />
              <RuntimeCard state={dailyState} telemetry={telemetry} className="md:min-h-0 md:flex-1" />
            </div>
          </section>
        ) : (
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
          />
        )}
      </main>

      <Sheet open={settingsOpen} onOpenChange={setSettingsOpen}>
        <SheetContent className="w-[min(760px,calc(100vw-2rem))] sm:max-w-2xl">
          <SheetHeader>
            <SheetTitle>Settings</SheetTitle>
            <SheetDescription>Model, permissions, and voice service controls.</SheetDescription>
          </SheetHeader>

          <div className="flex flex-col gap-4 overflow-y-auto px-4 py-4">
            <Card>
              <CardHeader>
                <CardTitle>Speech model</CardTitle>
                <CardDescription>{selectedModelDetail}</CardDescription>
              </CardHeader>
              <CardContent>
                <FieldGroup>
                  <Field>
                    <FieldLabel>Model</FieldLabel>
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
                        <SelectValue placeholder="Select model" />
                      </SelectTrigger>
                      <SelectContent alignItemWithTrigger={false}>
                        <SelectGroup>
                          <SelectLabel>Available models</SelectLabel>
                          {modelItems.map((item) => (
                            <SelectItem key={item.value} value={item.value}>
                              {item.label}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                    <FieldDescription>
                      Current: {modelLabel(currentModel?.selected)} / {currentModel?.message ?? "Unknown"}
                    </FieldDescription>
                  </Field>
                  <Field orientation="horizontal">
                    <FieldContent>
                      <FieldTitle>Storage</FieldTitle>
                      <FieldDescription>{formatBytes(currentModel?.disk_bytes ?? 0)}</FieldDescription>
                    </FieldContent>
                    <Badge variant={readinessVariant(Boolean(currentModel?.installed))}>
                      {currentModel?.state ?? "unknown"}
                    </Badge>
                  </Field>
                  <Field orientation="horizontal">
                    <FieldContent>
                      <FieldTitle>Update</FieldTitle>
                      <FieldDescription>
                        {currentModel?.update_available ? "An update is available." : "No update is available."}
                      </FieldDescription>
                    </FieldContent>
                    <Badge variant={currentModel?.update_available ? "secondary" : "outline"}>
                      {currentModel?.update_available ? "Available" : "Current"}
                    </Badge>
                  </Field>
                </FieldGroup>
              </CardContent>
              <CardFooter className="flex flex-wrap gap-2">
                <Button onClick={() => void runModelAction("use")} disabled={useModelDisabled}>
                  <SpinnerOrIcon busy={busyAction === "model:use"} icon={CheckCircle2Icon} />
                  Use
                </Button>
                <Button variant="outline" onClick={() => void runModelAction("install")} disabled={installModelDisabled}>
                  <SpinnerOrIcon busy={busyAction === "model:install"} icon={DownloadIcon} />
                  Install
                </Button>
                <Button variant="outline" onClick={() => void runModelAction("update")} disabled={updateModelDisabled}>
                  <SpinnerOrIcon busy={busyAction === "model:update"} icon={RefreshCwIcon} />
                  Update
                </Button>
                <Button variant="outline" onClick={() => void runModelAction("repair")} disabled={repairModelDisabled}>
                  <SpinnerOrIcon busy={busyAction === "model:repair"} icon={WrenchIcon} />
                  Repair
                </Button>
                <Button variant="destructive" onClick={() => setDeleteOpen(true)} disabled={deleteModelDisabled}>
                  <Trash2Icon data-icon="inline-start" />
                  Delete
                </Button>
              </CardFooter>
            </Card>

            <PermissionPanel
              status={status}
              busyAction={busyAction}
              requestPermission={(kind) => void requestPermission(kind)}
            />

            <Card>
              <CardHeader>
                <CardTitle>Voice service</CardTitle>
                <CardDescription>Advanced controls for the background process.</CardDescription>
              </CardHeader>
              <CardContent>
                <FieldGroup>
                  <Field orientation="horizontal">
                    <FieldContent>
                      <FieldTitle>Login service</FieldTitle>
                      <FieldDescription>
                        {status?.service.installed ? "installed" : "not installed"} /{" "}
                        {status?.service.running ? "running" : "stopped"}
                      </FieldDescription>
                    </FieldContent>
                    <Badge variant={readinessVariant(Boolean(status?.service.running))}>
                      {status?.service.running ? "Running" : "Stopped"}
                    </Badge>
                  </Field>
                  {serviceModelBlocked && (
                    <Alert>
                      <AlertCircleIcon />
                      <AlertTitle>Model required</AlertTitle>
                      <AlertDescription>Install a model before starting the voice service.</AlertDescription>
                    </Alert>
                  )}
                </FieldGroup>
              </CardContent>
              <CardFooter>
                <ButtonGroup className="flex-wrap">
                  <Button variant="outline" onClick={() => void runServiceAction("install")} disabled={controlsDisabled}>
                    <SpinnerOrIcon busy={busyAction === "service:install"} icon={DownloadIcon} />
                    Install
                  </Button>
                  <Button onClick={() => void runServiceAction("start")} disabled={controlsDisabled || serviceModelBlocked}>
                    <SpinnerOrIcon busy={busyAction === "service:start"} icon={PlayIcon} />
                    Start
                  </Button>
                  <Button variant="outline" onClick={() => void runServiceAction("stop")} disabled={controlsDisabled}>
                    <SpinnerOrIcon busy={busyAction === "service:stop"} icon={SquareIcon} />
                    Stop
                  </Button>
                  <Button variant="outline" onClick={() => void runServiceAction("restart")} disabled={controlsDisabled || serviceModelBlocked}>
                    <SpinnerOrIcon busy={busyAction === "service:restart"} icon={RotateCcwIcon} />
                    Restart
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
                  <RuntimeCard state={dailyState} telemetry={telemetry} />
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
