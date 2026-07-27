import { RefreshCwIcon, SaveIcon, SettingsIcon, Undo2Icon, MapIcon } from "lucide-react"
import { useMemo, useState } from "react"

import { SpinnerOrIcon } from "@/components/common/spinner-or-icon"
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
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldTitle,
} from "@/components/ui/field"
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { MappingParameterEditor } from "@/features/mapping/mapping-parameter-editor"
import {
  blankMappingEntry,
  formatUnixTime,
  mappingActionLabel,
  mappingActionSummary,
  mappingEventLabel,
  mappingIsCommon,
  withMappingAction,
} from "@/lib/app-view-model"
import type { MappingEntry, MappingEnvelope } from "@/lib/helper-api"
import type { Translator } from "@/lib/i18n"

type MappingPageProps = {
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
}

export function MappingPage({
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
}: MappingPageProps) {
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
      <section className="min-h-0 flex-1 p-px">
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
    <section className="min-h-0 flex-1 p-px">
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
                  <ScrollArea className="h-[calc(100vh-21rem)] rounded-md border bg-background md:h-full">
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
                  <Empty className="rounded-md border bg-background">
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
