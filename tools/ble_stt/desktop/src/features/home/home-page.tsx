import { AlertCircleIcon, CheckCircle2Icon, FileTextIcon, PlayIcon, SettingsIcon } from "lucide-react"

import { StatusBadge } from "@/components/common/status-badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
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
import { formatBytes, type RuntimeTelemetry, type StatusPayload } from "@/lib/helper-api"
import {
  type DailyState,
  type DictationSnapshot,
  modelDisplayLabel,
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
  dictation: DictationSnapshot
  className?: string
  t: Translator
}) {
  return (
    <Card size="sm" className={cn("min-h-0", className)}>
      <CardHeader>
        <CardTitle>{t("home.transcript", "Transcript")}</CardTitle>
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
  const seconds = fresh ? telemetry?.audio.seconds ?? 0 : 0

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

type HomePageProps = {
  state: DailyState
  status: StatusPayload | null
  telemetry: RuntimeTelemetry | null
  dictation: DictationSnapshot
  currentModel: StatusPayload["model"] | null
  lastUpdated: Date | null
  busyAction: string | null
  primaryActionLabel: PrimaryActionLabel
  onDailyAction: () => void
  onOpenSettings: () => void
  t: Translator
}

export function HomePage({
  state,
  status,
  telemetry,
  dictation,
  currentModel,
  lastUpdated,
  busyAction,
  primaryActionLabel,
  onDailyAction,
  onOpenSettings,
  t,
}: HomePageProps) {
  return (
    <section className="grid gap-3 md:min-h-0 md:flex-1 md:grid-cols-3 md:overflow-hidden">
      <div className="flex min-w-0 flex-col gap-3 md:col-span-2 md:min-h-0">
        <StatusCard
          state={state}
          status={status}
          lastUpdated={lastUpdated}
          busyAction={busyAction}
          onAction={onDailyAction}
          primaryActionLabel={primaryActionLabel}
          t={t}
        />
        <TranscriptCard dictation={dictation} className="md:flex-1" t={t} />
      </div>

      <div className="flex min-w-0 flex-col gap-3 md:min-h-0">
        <ModelCard model={currentModel} onOpenSettings={onOpenSettings} t={t} />
        <RuntimeCard state={state} telemetry={telemetry} className="md:min-h-0 md:flex-1" t={t} />
      </div>
    </section>
  )
}
