import { KeyboardIcon, PlusIcon, RefreshCwIcon, SaveIcon, SettingsIcon, Trash2Icon, Undo2Icon } from "lucide-react"
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
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldTitle,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { MappingParameterEditor } from "@/features/mapping/mapping-parameter-editor"
import {
  COMMAND_ACTION_IDS,
  blankCommandEntry,
  commandAsMappingEntry,
  commandToolsEnvelope,
  commandWithMappingEntry,
  formatUnixTime,
  mappingActionLabel,
  mappingActionSummary,
  withMappingAction,
} from "@/lib/app-view-model"
import type { CommandEntry, CommandEnvelope, RuntimeTelemetry } from "@/lib/helper-api"
import type { Translator } from "@/lib/i18n"

type CommandPageProps = {
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
}

export function CommandPage({
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
}: CommandPageProps) {
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
            <ScrollArea className="h-[calc(100vh-21rem)] rounded-md border bg-background md:h-full">
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
                          <Button size="sm" variant="outline" onClick={() => setEditingCommandId(entry.id)}>
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
            <Empty className="rounded-md border bg-background">
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
