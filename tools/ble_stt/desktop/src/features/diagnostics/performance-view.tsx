import { GaugeIcon, Trash2Icon } from "lucide-react"
import { useMemo, useState } from "react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import type { PerformanceRecord, PerformanceSnapshot, PerformanceSpan } from "@/lib/helper-api"
import type { Translator } from "@/lib/i18n"
import { cn } from "@/lib/utils"

type TimelineMode = "full" | "processing"

const METRICS = [
  ["start_to_first_character_ms", null, "performance.first_character", "首字延迟"],
  ["release_to_result_ready_ms", "host_release_to_result_ready_ms", "performance.result_ready", "松手到结果"],
  ["release_to_typing_complete_ms", "host_release_to_typing_complete_ms", "performance.typing_complete", "松手到输入完成"],
  ["command_release_to_action_ms", null, "performance.command_action", "松手到指令执行"],
] as const

function nearestRank(values: number[], fraction: number) {
  if (!values.length) return null
  const ordered = [...values].sort((left, right) => left - right)
  return ordered[Math.max(0, Math.ceil(ordered.length * fraction) - 1)]
}

function milliseconds(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "—"
  if (value < 10) return `${value.toFixed(2)} ms`
  return `${Math.round(value)} ms`
}

function configurationKey(record: PerformanceRecord) {
  const configuration = Object.entries(record.configuration)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}:${String(value)}`)
    .join("|")
  return `${record.mode ?? "none"}|${configuration}`
}

function visibleTimelineSpans(record: PerformanceRecord, mode: TimelineMode) {
  return record.spans.filter(
    (span) =>
      span.start_ms != null &&
      (mode === "full" || !["wait", "intentional"].includes(span.category))
  )
}

function Waterfall({ record, mode }: { record: PerformanceRecord; mode: TimelineMode }) {
  const spans = visibleTimelineSpans(record, mode)
  if (!spans.length) return null
  const start = Math.min(...spans.map((span) => span.start_ms ?? 0))
  const end = Math.max(...spans.map((span) => (span.start_ms ?? 0) + span.duration_ms))
  const range = Math.max(1, end - start)

  return (
    <TooltipProvider>
      <div className="flex flex-col gap-2">
        {spans.map((span, index) => {
          const left = (((span.start_ms ?? start) - start) / range) * 100
          const width = Math.max(0.8, (span.duration_ms / range) * 100)
          return (
            <div key={`${span.name}-${span.lane}-${index}`} className="grid grid-cols-[9rem_1fr_5rem] items-center gap-3 text-xs">
              <span className="truncate text-muted-foreground">{span.lane} · {span.name}</span>
              <div className="relative h-5 overflow-hidden rounded-md bg-muted">
                <Tooltip>
                  <TooltipTrigger
                    aria-label={`${span.name} ${milliseconds(span.duration_ms)}`}
                    className={cn(
                      "absolute top-0 h-full rounded-md",
                      span.category === "wait" || span.category === "intentional" ? "bg-secondary" : "bg-primary"
                    )}
                    style={{ left: `${left}%`, width: `${width}%` }}
                  />
                  <TooltipContent>
                    {span.name} · {span.category} · {milliseconds(span.duration_ms)}
                  </TooltipContent>
                </Tooltip>
              </div>
              <span className="text-right tabular-nums">{milliseconds(span.duration_ms)}</span>
            </div>
          )
        })}
      </div>
    </TooltipProvider>
  )
}

function SpanTable({ spans, t }: { spans: PerformanceSpan[]; t: Translator }) {
  const values = [...spans].sort((left, right) => right.duration_ms - left.duration_ms)
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("performance.stage", "阶段")}</TableHead>
          <TableHead>{t("performance.lane", "泳道")}</TableHead>
          <TableHead>{t("performance.category", "类型")}</TableHead>
          <TableHead className="text-right">{t("performance.current", "本次")}</TableHead>
          <TableHead className="text-right">{t("performance.count", "次数")}</TableHead>
          <TableHead className="text-right">{t("performance.mean_max", "平均/最大")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {values.map((span, index) => (
          <TableRow key={`${span.name}-${span.lane}-${index}`}>
            <TableCell className="font-medium">{span.name}</TableCell>
            <TableCell>{span.lane}</TableCell>
            <TableCell><Badge variant="outline">{span.category}</Badge></TableCell>
            <TableCell className="text-right tabular-nums">{milliseconds(span.duration_ms)}</TableCell>
            <TableCell className="text-right tabular-nums">{span.count ?? 1}</TableCell>
            <TableCell className="text-right tabular-nums">
              {span.mean_ms == null ? "—" : `${milliseconds(span.mean_ms)} / ${milliseconds(span.max_ms)}`}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

export function PerformanceView({
  snapshot,
  busy,
  onClear,
  t,
}: {
  snapshot: PerformanceSnapshot | null
  busy: boolean
  onClear: () => void
  t: Translator
}) {
  const [timelineMode, setTimelineMode] = useState<TimelineMode>("processing")
  const sessions = snapshot?.sessions ?? []
  const latest = sessions.length ? sessions[sessions.length - 1] : null
  const lifecycles = snapshot?.lifecycles ?? []
  const latestLifecycle = lifecycles.length ? lifecycles[lifecycles.length - 1] : null
  const cohort = useMemo(() => {
    if (!latest || !snapshot) return []
    const key = configurationKey(latest)
    return snapshot.sessions.filter((record) => configurationKey(record) === key)
  }, [latest, snapshot])
  const bottleneck = latest?.spans
    .filter((span) => !["wait", "intentional"].includes(span.category))
    .sort((left, right) => right.duration_ms - left.duration_ms)[0]

  if (!snapshot || (!latest && !latestLifecycle)) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon"><GaugeIcon /></EmptyMedia>
          <EmptyTitle>{t("performance.empty", "暂无性能样本")}</EmptyTitle>
          <EmptyDescription>{t("performance.empty_description", "完成一次语音输入后，这里会显示完整链路耗时。")}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-px py-4">
      {latest ? <Card>
        <CardHeader>
          <div>
            <CardTitle>{t("performance.latest", "最近一次链路")}</CardTitle>
            <CardDescription>
              {latest.mode} · {latest.configuration.stt_model ?? "unknown"} · {latest.outcome} · {milliseconds(latest.duration_ms)}
            </CardDescription>
          </div>
          <CardAction>
            {bottleneck ? <Badge variant="secondary">{t("performance.longest", "最长处理")}：{bottleneck.name}</Badge> : null}
          </CardAction>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <ToggleGroup
            aria-label={t("performance.timeline_mode", "时间线模式")}
            spacing={0}
            variant="outline"
            value={[timelineMode]}
            onValueChange={(values) => {
              const value = values[values.length - 1] as TimelineMode | undefined
              if (value) setTimelineMode(value)
            }}
          >
            <ToggleGroupItem value="processing">{t("performance.processing", "处理路径")}</ToggleGroupItem>
            <ToggleGroupItem value="full">{t("performance.full", "完整链路")}</ToggleGroupItem>
          </ToggleGroup>
          <Waterfall record={latest} mode={timelineMode} />
        </CardContent>
      </Card> : null}

      {latest ? <Card>
        <CardHeader>
          <div>
            <CardTitle>{t("performance.baseline", "同配置基线")}</CardTitle>
            <CardDescription>
              {t("performance.baseline_description", "只比较模式、识别模型、纠错模型和打字设置相同的样本。")}
            </CardDescription>
          </div>
          <CardAction>
            <Badge variant={cohort.length < 20 ? "secondary" : "outline"}>
              {cohort.length < 20
                ? `${t("performance.insufficient", "样本不足")} · ${cohort.length}`
                : `${cohort.length} ${t("performance.samples", "个样本")}`}
            </Badge>
          </CardAction>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("performance.metric", "指标")}</TableHead>
                <TableHead className="text-right">{t("performance.current", "本次")}</TableHead>
                <TableHead className="text-right">p50</TableHead>
                <TableHead className="text-right">p95</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {METRICS.map(([key, fallbackKey, labelKey, label]) => {
                const values = cohort
                  .map((record) => record.metrics[key] ?? (fallbackKey ? record.metrics[fallbackKey] : null))
                  .filter((value): value is number => typeof value === "number")
                const current = latest.metrics[key] ?? (fallbackKey ? latest.metrics[fallbackKey] : null)
                if (typeof current !== "number" && !values.length) return null
                return (
                  <TableRow key={key}>
                    <TableCell className="font-medium">{t(labelKey, label)}</TableCell>
                    <TableCell className="text-right tabular-nums">{milliseconds(typeof current === "number" ? current : null)}</TableCell>
                    <TableCell className="text-right tabular-nums">{milliseconds(nearestRank(values, 0.5))}</TableCell>
                    <TableCell className="text-right tabular-nums">{milliseconds(nearestRank(values, 0.95))}</TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card> : null}

      {latest ? <Card>
        <CardHeader>
          <div>
            <CardTitle>{t("performance.stage_details", "阶段明细")}</CardTitle>
            <CardDescription>
              {latest.clock_sync?.merged
                ? `${t("performance.clock_aligned", "固件与电脑时间线已对齐，误差约")} ±${latest.clock_sync.uncertainty_ms.toFixed(2)} ms。`
                : t("performance.clock_unaligned", "固件时钟未可靠对齐时，不计算虚假的单向 BLE 延迟。")}
            </CardDescription>
          </div>
          <CardAction>
            <AlertDialog>
              <AlertDialogTrigger render={<Button variant="outline" disabled={busy} />}>
                <Trash2Icon data-icon="inline-start" />
                {t("performance.clear", "清空性能历史")}
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>{t("performance.clear_title", "清空全部性能样本？")}</AlertDialogTitle>
                  <AlertDialogDescription>
                    {t("performance.clear_description", "这会删除最近 200 次会话和生命周期统计，不影响转写历史、模型或设置。")}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>{t("common.cancel", "取消")}</AlertDialogCancel>
                  <AlertDialogAction onClick={onClear}>{t("common.clear", "清空")}</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </CardAction>
        </CardHeader>
        <CardContent><SpanTable spans={latest.spans} t={t} /></CardContent>
      </Card> : null}

      {latestLifecycle ? (
        <Card>
          <CardHeader>
            <div>
              <CardTitle>{t("performance.lifecycle", "最近一次服务准备")}</CardTitle>
              <CardDescription>
                {latestLifecycle.outcome} · {milliseconds(latestLifecycle.duration_ms)}
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <Waterfall record={latestLifecycle} mode="full" />
            <SpanTable spans={latestLifecycle.spans} t={t} />
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}
