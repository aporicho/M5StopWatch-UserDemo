import { EyeIcon, MapIcon, SaveIcon, SettingsIcon, Undo2Icon } from "lucide-react"
import { useMemo, useState } from "react"

import { SpinnerOrIcon } from "@/components/common/spinner-or-icon"
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
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldTitle } from "@/components/ui/field"
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
import { Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { MappingParameterEditor } from "@/features/mapping/mapping-parameter-editor"
import {
  blankMappingEntry,
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
  busyAction: string | null
  refreshing: boolean
  onSaveEntry: (entry: MappingEntry) => Promise<boolean>
  onReset: () => void
  t: Translator
}

export function MappingPage({
  envelope,
  entries,
  busyAction,
  refreshing,
  onSaveEntry,
  onReset,
  t,
}: MappingPageProps) {
  const [mapView, setMapView] = useState<"common" | "all">("common")
  const [draft, setDraft] = useState<MappingEntry | null>(null)
  const entriesByEvent = useMemo(() => new Map(entries.map((entry) => [entry.event, entry])), [entries])
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
    if (!envelope) return []
    return envelope.events.map((event) => {
      const entry = entriesByEvent.get(event.id) ?? blankMappingEntry(event.id, Boolean(event.locked))
      const locked = Boolean(event.locked || entry.locked)
      const normalizedEntry = { ...entry, flags: entry.flags ?? 0, locked }
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
  const selectedRow = draft ? rows.find((row) => row.event.id === draft.event) ?? null : null
  const draftSummary = draft && envelope ? mappingActionSummary(draft, envelope, t) : ""

  const saveDraft = async () => {
    if (!draft || draft.locked) return
    if (await onSaveEntry(draft)) setDraft(null)
  }

  if (!envelope) {
    return (
      <section className="min-h-0 flex-1 p-px">
        <Card className="min-h-0">
          <CardHeader>
            <CardTitle>{t("mapping.title", "Gestures")}</CardTitle>
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

  return (
    <section className="min-h-0 flex-1 p-px">
      <Card className="min-h-0 md:flex md:h-full md:flex-col">
        <CardHeader className="shrink-0">
          <CardTitle>{t("mapping.title", "Gestures")}</CardTitle>
          <CardAction>
            <AlertDialog>
              <AlertDialogTrigger render={<Button variant="outline" disabled={disabled} />}>
                <SpinnerOrIcon busy={busyAction === "mapping:reset"} icon={Undo2Icon} />
                {t("common.reset", "Reset")}
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>{t("mapping.reset_title", "Reset all gestures?")}</AlertDialogTitle>
                  <AlertDialogDescription>
                    {t("mapping.reset_description", "Your custom gesture actions will be replaced with the defaults.")}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>{t("common.cancel", "Cancel")}</AlertDialogCancel>
                  <AlertDialogAction onClick={onReset}>{t("common.reset", "Reset")}</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
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
                  <ScrollArea className="h-[calc(100vh-17rem)] rounded-md border bg-background md:h-full">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-[32%]">{t("mapping.event", "Event")}</TableHead>
                          <TableHead>{t("mapping.result", "Result")}</TableHead>
                          <TableHead className="w-28 text-right">{t("mapping.action", "Action")}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {visibleRows.map((row) => (
                          <TableRow key={row.event.id}>
                            <TableCell>
                              <div className="flex min-w-0 items-center gap-2">
                                <span className="truncate font-medium">{row.eventLabel}</span>
                                {row.locked && <Badge variant="outline">{t("common.locked", "Locked")}</Badge>}
                              </div>
                            </TableCell>
                            <TableCell>
                              <div className="flex min-w-0 flex-col gap-1">
                                <span className="truncate">{row.actionLabel}</span>
                                <span className="truncate text-sm text-muted-foreground">{row.summary}</span>
                              </div>
                            </TableCell>
                            <TableCell className="text-right">
                              <Button size="sm" variant="outline" onClick={() => setDraft({ ...row.entry })}>
                                {row.locked ? <EyeIcon data-icon="inline-start" /> : <SettingsIcon data-icon="inline-start" />}
                                {row.locked ? t("common.view", "View") : t("common.edit", "Edit")}
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
                      <EmptyMedia variant="icon"><MapIcon /></EmptyMedia>
                      <EmptyTitle>{t("mapping.empty_title", "No common mappings")}</EmptyTitle>
                      <EmptyDescription>{t("mapping.empty_description", "Open All events to configure a watch gesture.")}</EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                )}
              </TabsContent>
            ))}
          </Tabs>
        </CardContent>
      </Card>

      <Sheet open={Boolean(draft && selectedRow)} onOpenChange={(open) => !open && setDraft(null)}>
        <SheetContent className="w-[min(520px,calc(100vw-2rem))] sm:max-w-lg">
          <SheetHeader>
            <SheetTitle>{selectedRow?.eventLabel ?? t("mapping.edit_title", "Edit event")}</SheetTitle>
          </SheetHeader>
          {draft && selectedRow && (
            <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
              <FieldGroup>
                {selectedRow.locked && <Badge variant="outline">{t("common.locked", "Locked")}</Badge>}
                <Field data-disabled={selectedRow.locked || disabled ? true : undefined}>
                  <FieldLabel>{t("mapping.action", "Action")}</FieldLabel>
                  <Select
                    items={actionItems}
                    value={draft.action}
                    onValueChange={(value) => value && setDraft(withMappingAction(draft, value))}
                    disabled={selectedRow.locked || disabled}
                  >
                    <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent alignItemWithTrigger={false}>
                      <SelectGroup>
                        <SelectLabel>{t("mapping.actions", "Actions")}</SelectLabel>
                        {actionItems.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  <FieldDescription>{draftSummary}</FieldDescription>
                </Field>
                <Field data-disabled={selectedRow.locked || disabled ? true : undefined}>
                  <FieldTitle>{t("mapping.parameters", "Parameters")}</FieldTitle>
                  <MappingParameterEditor
                    entry={draft}
                    envelope={envelope}
                    disabled={disabled || selectedRow.locked}
                    onChange={setDraft}
                    t={t}
                  />
                </Field>
              </FieldGroup>
            </div>
          )}
          <SheetFooter>
            <Button variant="outline" onClick={() => setDraft(null)}>
              {selectedRow?.locked ? t("common.close", "Close") : t("common.cancel", "Cancel")}
            </Button>
            {!selectedRow?.locked && (
              <Button onClick={() => void saveDraft()} disabled={disabled}>
                <SpinnerOrIcon busy={busyAction === "mapping:save"} icon={SaveIcon} />
                {t("common.save", "Save")}
              </Button>
            )}
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </section>
  )
}
