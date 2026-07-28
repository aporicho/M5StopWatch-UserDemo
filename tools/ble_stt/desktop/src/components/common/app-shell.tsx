import { AlertCircleIcon, BugIcon, HomeIcon, KeyboardIcon, MapIcon, RefreshCwIcon, SettingsIcon } from "lucide-react"
import type { ReactNode } from "react"

import { SpinnerOrIcon } from "@/components/common/spinner-or-icon"
import { StatusBadge } from "@/components/common/status-badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import type { DailyState, Notice, PageKey } from "@/lib/app-view-model"
import type { Translator } from "@/lib/i18n"

type AppShellProps = {
  page: PageKey
  dailyState: DailyState
  notice: Notice | null
  busyAction: string | null
  refreshing: boolean
  onPageChange: (page: PageKey) => void
  onRefresh: () => void
  onOpenSettings: () => void
  onOpenDiagnostics: () => void
  t: Translator
  children: ReactNode
}

export function AppShell({
  page,
  dailyState,
  notice,
  busyAction,
  refreshing,
  onPageChange,
  onRefresh,
  onOpenSettings,
  onOpenDiagnostics,
  t,
  children,
}: AppShellProps) {
  return (
    <div className="min-h-screen bg-muted/30 text-foreground md:h-screen md:overflow-hidden">
      <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-3 p-4 sm:p-5 md:h-full md:min-h-0 md:overflow-hidden">
        <header className="flex shrink-0 flex-col gap-3 border-b bg-background/60 pb-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg border bg-card font-semibold">M5</div>
            <div>
              <p className="text-sm text-muted-foreground">{t("app.name", "M5StopWatch")}</p>
              <h1 className="text-2xl font-semibold tracking-tight">{t("app.title", "Speech Control")}</h1>
            </div>
            <StatusBadge state={dailyState} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Tabs value={page} onValueChange={(value) => onPageChange(value as PageKey)}>
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
            <Button variant="outline" onClick={onRefresh} disabled={busyAction !== null || refreshing}>
              <SpinnerOrIcon busy={busyAction === null && refreshing} icon={RefreshCwIcon} />
              {t("common.refresh", "Refresh")}
            </Button>
            <Button variant="outline" onClick={onOpenSettings}>
              <SettingsIcon data-icon="inline-start" />
              {t("common.settings", "Settings")}
            </Button>
            <Button variant="outline" onClick={onOpenDiagnostics}>
              <BugIcon data-icon="inline-start" />
              {t("common.diagnostics", "Diagnostics")}
            </Button>
          </div>
        </header>

        {notice && (
          <Alert className="shrink-0" variant="destructive">
            <AlertCircleIcon />
            <AlertTitle>{t("notice.needs_attention", "Needs attention")}</AlertTitle>
            <AlertDescription>{notice.message}</AlertDescription>
          </Alert>
        )}

        {children}
      </main>
    </div>
  )
}
