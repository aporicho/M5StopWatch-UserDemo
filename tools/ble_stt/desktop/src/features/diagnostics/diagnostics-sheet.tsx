import { ActivityIcon, ClipboardIcon, FileTextIcon, FolderOpenIcon } from "lucide-react"
import type { RefObject } from "react"

import { SpinnerOrIcon } from "@/components/common/spinner-or-icon"
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
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { RuntimeCard } from "@/features/home/home-page"
import {
  type ActivityItem,
  type DailyState,
  DIAGNOSTIC_ROWS,
  compactTime,
  diagnosticDetail,
  diagnosticOk,
  logLevelVariant,
  percent,
  readinessVariant,
} from "@/lib/app-view-model"
import type { RuntimeTelemetry, StatusPayload, StructuredLogEntry } from "@/lib/helper-api"
import type { Translator } from "@/lib/i18n"
import { cn } from "@/lib/utils"

type DiagnosticsSheetProps = {
  open: boolean
  status: StatusPayload | null
  dailyState: DailyState
  telemetry: RuntimeTelemetry | null
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
  t: Translator
}

export function DiagnosticsSheet({
  open,
  status,
  dailyState,
  telemetry,
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
  t,
}: DiagnosticsSheetProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
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
                      onClick={onToggleAutoFollowLogs}
                    >
                      {autoFollowLogs ? "Following" : "Follow latest"}
                    </Button>
                  </CardAction>
                </CardHeader>
                <CardContent className="min-h-0">
                  <ScrollArea
                    className="h-[calc(100vh-18rem)] rounded-md border bg-background"
                    onWheel={onDisableAutoFollowLogs}
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
          <Button variant="outline" onClick={onOpenLogs} disabled={busyAction !== null}>
            <SpinnerOrIcon busy={busyAction === "logs"} icon={FolderOpenIcon} />
            Open logs
          </Button>
          <Button onClick={onCopyDiagnostics} disabled={busyAction !== null}>
            <SpinnerOrIcon busy={busyAction === "diagnostics"} icon={ClipboardIcon} />
            Copy diagnostics
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
