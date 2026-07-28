import { FileTextIcon, PlayIcon, SettingsIcon, Trash2Icon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { ModelOperationProgress } from "@/components/common/model-operation-progress"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Progress, ProgressLabel, ProgressValue } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table"
import {
  formatBytes,
  type ModelOperationProgress as ModelOperation,
  type RuntimeTelemetry,
  type StatusPayload,
} from "@/lib/helper-api"
import {
  type DailyState,
  type DictationHistoryItem,
  modelDisplayLabel,
  modelStateLabel,
  modelVariant,
  percent,
  progressValue,
  readinessVariant,
  telemetryFresh,
} from "@/lib/app-view-model"
import type { Translator } from "@/lib/i18n"
import { cn } from "@/lib/utils"

type PrimaryActionLabel = Record<NonNullable<DailyState["action"]>, string>

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
      detail: status.service.running ? t("status.running", "Running") : t("status.stopped", "Stopped"),
    },
    {
      label: t("home.watch", "Watch"),
      ok: status.watch.connected ?? false,
      detail: status.watch.connected
        ? t("status.connected", "connected")
        : status.watch.connection_state === "waiting_system_connection"
          ? t("status.waiting_system_connection", "waiting for system connection")
          : t("status.disconnected", "Disconnected"),
    },
    {
      label: t("home.voice", "Voice"),
      ok: status.voice.ready,
      detail: status.voice.ready ? t("status.ready", "Ready") : t("status.preparing", "Preparing"),
    },
    {
      label: t("home.text_input", "Text input"),
      ok: status.permissions.input.ok,
      detail: status.permissions.input.ok ? t("status.granted", "Granted") : t("status.required", "Required"),
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
  primaryActionLabel: PrimaryActionLabel
  t: Translator
}) {
  return (
    <Card size="sm" className="shrink-0">
      <CardHeader>
        <div>
          <CardTitle>{state.title}</CardTitle>
          <CardDescription>{state.description}</CardDescription>
        </div>
        {state.action && (
          <CardAction>
            <Button onClick={onAction} disabled={busyAction !== null}>
              <PlayIcon data-icon="inline-start" />
              {primaryActionLabel[state.action]}
            </Button>
          </CardAction>
        )}
      </CardHeader>
      <CardContent>
        <ReadinessTable status={status} t={t} />
      </CardContent>
      <CardFooter className="text-sm text-muted-foreground">
        {t("home.updated", "Updated")} {lastUpdated ? lastUpdated.toLocaleTimeString() : t("common.never", "never")}
      </CardFooter>
    </Card>
  )
}

function DictationHistoryCard({
  dictations,
  className,
  onClear,
  t,
}: {
  dictations: DictationHistoryItem[]
  className?: string
  onClear: () => void
  t: Translator
}) {
  const latest = dictations[0] ?? null

  return (
    <Card size="sm" className={cn("min-h-0 md:flex md:flex-col", className)}>
      <CardHeader>
        <CardTitle>{t("home.transcript", "Dictation history")}</CardTitle>
        <CardAction>
          <div className="flex items-center gap-2">
            {latest && !latest.final && <Badge variant="outline">{t("home.live", "Live")}</Badge>}
            <Button size="sm" variant="ghost" onClick={onClear} disabled={!dictations.length}>
              <Trash2Icon data-icon="inline-start" />
              {t("common.clear", "Clear")}
            </Button>
          </div>
        </CardAction>
      </CardHeader>
      <CardContent className="min-h-0 md:flex-1">
        {dictations.length ? (
          <ScrollArea className="h-full min-h-32">
            <Table>
              <TableBody>
                {dictations.map((item) => (
                  <TableRow key={item.key}>
                    <TableCell className="align-top">
                      <div className="flex min-w-0 flex-col gap-1">
                        <span className="text-lg leading-snug">{item.text}</span>
                        <span className="text-sm text-muted-foreground">{item.time}</span>
                      </div>
                    </TableCell>
                    {!item.final && (
                      <TableCell className="w-20 align-top text-right">
                        <Badge variant="outline">{t("home.live", "Live")}</Badge>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
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

export function RuntimeCard({
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
  const latestPerformance = telemetry?.performance?.latest
  const performanceMetrics = latestPerformance?.metrics ?? {}
  const formatLatency = (value: number | string | null | undefined) =>
    typeof value === "number" ? `${Math.round(value)} ms` : "—"

  return (
    <Card size="sm" className={className}>
      <CardHeader>
        <CardTitle>{t("home.runtime", "Runtime")}</CardTitle>
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
        {latestPerformance?.kind === "session" ? (
          <Table>
            <TableBody>
              <TableRow>
                <TableCell className="font-medium">{t("performance.first_character", "First character")}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatLatency(performanceMetrics.start_to_first_character_ms)}
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="font-medium">{t("performance.result_ready", "Release to result")}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatLatency(performanceMetrics.release_to_result_ready_ms ?? performanceMetrics.host_release_to_result_ready_ms)}
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="font-medium">{t("performance.typing_complete", "Release to typed")}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatLatency(performanceMetrics.release_to_typing_complete_ms ?? performanceMetrics.host_release_to_typing_complete_ms)}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        ) : null}
      </CardContent>
    </Card>
  )
}

function ModelCard({
  model,
  operation,
  onOpenSettings,
  onCancelModelOperation,
  t,
}: {
  model: StatusPayload["model"] | null
  operation: ModelOperation | null
  onOpenSettings: () => void
  onCancelModelOperation: () => void
  t: Translator
}) {
  return (
    <Card size="sm" className="shrink-0">
      <CardHeader>
        <CardTitle>{t("home.model", "Model")}</CardTitle>
        <CardAction>
          <Badge variant={modelVariant(model)}>{modelStateLabel(model?.state, t)}</Badge>
        </CardAction>
      </CardHeader>
      <CardContent>
        {model ? (
          <div className="flex flex-col gap-4">
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
            {operation && (
              <ModelOperationProgress
                operation={operation}
                onCancel={onCancelModelOperation}
                t={t}
              />
            )}
          </div>
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

type HomePageProps = {
  state: DailyState
  status: StatusPayload | null
  telemetry: RuntimeTelemetry | null
  dictations: DictationHistoryItem[]
  currentModel: StatusPayload["model"] | null
  modelOperation: ModelOperation | null
  lastUpdated: Date | null
  busyAction: string | null
  primaryActionLabel: PrimaryActionLabel
  onDailyAction: () => void
  onOpenSettings: () => void
  onCancelModelOperation: () => void
  onClearDictationHistory: () => void
  t: Translator
}

export function HomePage({
  state,
  status,
  telemetry,
  dictations,
  currentModel,
  modelOperation,
  lastUpdated,
  busyAction,
  primaryActionLabel,
  onDailyAction,
  onOpenSettings,
  onCancelModelOperation,
  onClearDictationHistory,
  t,
}: HomePageProps) {
  return (
    <section className="grid min-h-0 flex-1 gap-3 overflow-hidden p-px md:grid-cols-3">
      <div className="flex min-w-0 flex-col gap-3 overflow-visible md:col-span-2 md:min-h-0">
        <StatusCard
          state={state}
          status={status}
          lastUpdated={lastUpdated}
          busyAction={busyAction}
          onAction={onDailyAction}
          primaryActionLabel={primaryActionLabel}
          t={t}
        />
        <DictationHistoryCard dictations={dictations} className="md:flex-1" onClear={onClearDictationHistory} t={t} />
      </div>

      <ScrollArea className="min-h-0 md:h-full">
        <div className="flex min-w-0 flex-col gap-3 p-px pr-3">
          <ModelCard
            model={currentModel}
            operation={modelOperation}
            onOpenSettings={onOpenSettings}
            onCancelModelOperation={onCancelModelOperation}
            t={t}
          />
          <RuntimeCard state={state} telemetry={telemetry} t={t} />
        </div>
      </ScrollArea>
    </section>
  )
}
