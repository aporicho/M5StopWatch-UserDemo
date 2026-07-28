import { ActivityIcon, ClipboardIcon, FileTextIcon, FolderOpenIcon } from "lucide-react"
import type { RefObject } from "react"

import { SpinnerOrIcon } from "@/components/common/spinner-or-icon"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { PerformanceView } from "@/features/diagnostics/performance-view"
import {
  type ActivityItem,
  DIAGNOSTIC_ROWS,
  compactTime,
  diagnosticDetail,
  diagnosticLabel,
  diagnosticOk,
  logLevelVariant,
  percent,
  performanceValueLabel,
  readinessVariant,
} from "@/lib/app-view-model"
import type { PerformanceSnapshot, RuntimeTelemetry, StatusPayload, StructuredLogEntry } from "@/lib/helper-api"
import type { Translator } from "@/lib/i18n"
import { cn } from "@/lib/utils"

type DiagnosticsSheetProps = {
  open: boolean
  status: StatusPayload | null
  telemetry: RuntimeTelemetry | null
  performance: PerformanceSnapshot | null
  activity: ActivityItem[]
  logEntries: StructuredLogEntry[]
  autoFollowLogs: boolean
  logEndRef: RefObject<HTMLDivElement | null>
  busyAction: string | null
  onOpenChange: (open: boolean) => void
  onToggleAutoFollowLogs: () => void
  onDisableAutoFollowLogs: () => void
  onOpenLogs: () => void
  onCopyDiagnostics: () => void
  onClearPerformance: () => void
  t: Translator
}

export function DiagnosticsSheet({
  open,
  status,
  telemetry,
  performance,
  activity,
  logEntries,
  autoFollowLogs,
  logEndRef,
  busyAction,
  onOpenChange,
  onToggleAutoFollowLogs,
  onDisableAutoFollowLogs,
  onOpenLogs,
  onCopyDiagnostics,
  onClearPerformance,
  t,
}: DiagnosticsSheetProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[min(1040px,calc(100vw-2rem))] sm:max-w-5xl">
        <SheetHeader>
          <SheetTitle>{t("diagnostics.title", "Diagnostics")}</SheetTitle>
        </SheetHeader>

        <Tabs defaultValue="overview" className="min-h-0 flex-1 px-4">
          <TabsList className="shrink-0">
            <TabsTrigger value="overview">{t("diagnostics.overview", "Overview")}</TabsTrigger>
            <TabsTrigger value="runtime">{t("diagnostics.runtime", "Runtime")}</TabsTrigger>
            <TabsTrigger value="performance">{t("diagnostics.performance", "Performance")}</TabsTrigger>
            <TabsTrigger value="logs">{t("diagnostics.logs", "Logs")}</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="min-h-0">
            <ScrollArea className="h-full pr-3">
              <div className="flex flex-col gap-4 p-px py-4">
                <Card>
                  <CardHeader><CardTitle>{t("diagnostics.status", "Health checks")}</CardTitle></CardHeader>
                  <CardContent>
                    {status ? (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>{t("diagnostics.check", "Check")}</TableHead>
                            <TableHead>{t("diagnostics.state", "State")}</TableHead>
                            <TableHead>{t("diagnostics.detail", "Detail")}</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {DIAGNOSTIC_ROWS.map(([key]) => {
                            const ok = diagnosticOk(status, key)
                            return (
                              <TableRow key={key}>
                                <TableCell className="font-medium">{diagnosticLabel(key, t)}</TableCell>
                                <TableCell>
                                  <Badge variant={readinessVariant(ok)}>
                                    {ok ? t("common.ok", "OK") : t("common.check", "Check")}
                                  </Badge>
                                </TableCell>
                                <TableCell className="whitespace-normal text-muted-foreground">
                                  {diagnosticDetail(status, key, t)}
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
                  <CardHeader><CardTitle>{t("diagnostics.activity", "Recent activity")}</CardTitle></CardHeader>
                  <CardContent>
                    {activity.length ? (
                      <Table>
                        <TableBody>
                          {activity.map((item) => (
                            <TableRow key={item.key}>
                              <TableCell className="w-28 text-xs tabular-nums">{compactTime(item.time)}</TableCell>
                              <TableCell className="w-40"><Badge variant={item.variant}>{item.label}</Badge></TableCell>
                              <TableCell className="whitespace-normal text-muted-foreground">{item.detail}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    ) : (
                      <Empty>
                        <EmptyHeader>
                          <EmptyMedia variant="icon"><ActivityIcon /></EmptyMedia>
                          <EmptyTitle>{t("diagnostics.no_events", "No activity yet")}</EmptyTitle>
                          <EmptyDescription>{t("diagnostics.no_events_description", "Activity appears after the voice service starts.")}</EmptyDescription>
                        </EmptyHeader>
                      </Empty>
                    )}
                  </CardContent>
                </Card>
              </div>
            </ScrollArea>
          </TabsContent>

          <TabsContent value="runtime" className="min-h-0">
            <ScrollArea className="h-full pr-3">
              <div className="p-px py-4">
                <Card>
                  <CardHeader><CardTitle>{t("diagnostics.runtime", "Runtime")}</CardTitle></CardHeader>
                  <CardContent>
                    <Table>
                      <TableBody>
                        <TableRow>
                          <TableCell className="font-medium">{t("performance.stage", "Stage")}</TableCell>
                          <TableCell>{performanceValueLabel("stage", telemetry?.stage, t)}</TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell className="font-medium">{t("diagnostics.mode", "Mode")}</TableCell>
                          <TableCell>{performanceValueLabel("mode", telemetry?.recognition.mode, t)}</TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell className="font-medium">{t("home.audio_level", "Audio level")}</TableCell>
                          <TableCell>{percent(telemetry?.audio.level)}</TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell className="font-medium">{t("home.peak", "Peak")}</TableCell>
                          <TableCell>{percent(telemetry?.audio.peak)}</TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell className="font-medium">{t("diagnostics.age", "Updated")}</TableCell>
                          <TableCell>
                            {telemetry?.age_seconds == null ? "—" : `${telemetry.age_seconds.toFixed(2)}s`}
                          </TableCell>
                        </TableRow>
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              </div>
            </ScrollArea>
          </TabsContent>

          <TabsContent value="performance" className="min-h-0">
            <ScrollArea className="h-full pr-3">
              <PerformanceView snapshot={performance} busy={busyAction !== null} onClear={onClearPerformance} t={t} />
            </ScrollArea>
          </TabsContent>

          <TabsContent value="logs" className="min-h-0">
            <div className="flex h-full min-h-0 flex-col gap-4 p-px py-4">
              <Card className="min-h-0 flex-1">
                <CardHeader>
                  <CardTitle>{t("diagnostics.logs", "Logs")}</CardTitle>
                  <CardAction>
                    <Button variant={autoFollowLogs ? "secondary" : "outline"} onClick={onToggleAutoFollowLogs}>
                      {autoFollowLogs
                        ? t("diagnostics.following", "Following")
                        : t("diagnostics.follow_latest", "Follow latest")}
                    </Button>
                  </CardAction>
                </CardHeader>
                <CardContent className="min-h-0">
                  <ScrollArea className="h-full rounded-md border bg-background" onWheel={onDisableAutoFollowLogs}>
                    {logEntries.length ? (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead className="w-44">{t("diagnostics.time", "Time")}</TableHead>
                            <TableHead className="w-24">{t("diagnostics.level", "Level")}</TableHead>
                            <TableHead className="w-36">{t("diagnostics.component", "Component")}</TableHead>
                            <TableHead>{t("diagnostics.message", "Message")}</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {logEntries.map((entry, index) => (
                            <TableRow key={`${entry.source}-${entry.time}-${index}`}>
                              <TableCell className="text-xs tabular-nums">{entry.time || "--"}</TableCell>
                              <TableCell><Badge variant={logLevelVariant(entry.level)}>{entry.level}</Badge></TableCell>
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
                          <EmptyMedia variant="icon"><FileTextIcon /></EmptyMedia>
                          <EmptyTitle>{t("diagnostics.no_logs", "No logs yet")}</EmptyTitle>
                          <EmptyDescription>{t("diagnostics.no_logs_description", "Logs appear after the voice service starts.")}</EmptyDescription>
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
          <Button variant="outline" onClick={onOpenLogs} disabled={busyAction !== null}>
            <SpinnerOrIcon busy={busyAction === "logs"} icon={FolderOpenIcon} />
            {t("diagnostics.open_logs", "Open logs")}
          </Button>
          <Button onClick={onCopyDiagnostics} disabled={busyAction !== null}>
            <SpinnerOrIcon busy={busyAction === "diagnostics"} icon={ClipboardIcon} />
            {t("diagnostics.copy", "Copy diagnostics")}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
