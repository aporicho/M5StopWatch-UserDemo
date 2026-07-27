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
  type CommandHistoryItem,
  blankCommandEntry,
  commandAsMappingEntry,
  commandToolsEnvelope,
  commandWithMappingEntry,
  formatUnixTime,
  mappingActionLabel,
  mappingActionSummary,
  withMappingAction,
} from "@/lib/app-view-model"
import type { CommandEntry, CommandEnvelope } from "@/lib/helper-api"
import type { Translator } from "@/lib/i18n"

type CommandPageProps = {
  envelope: CommandEnvelope | null
  entries: CommandEntry[]
  history: CommandHistoryItem[]
  busyAction: string | null
  refreshing: boolean
  onRefresh: () => void
  onSaveEntries: (entries: CommandEntry[]) => Promise<boolean>
  onReset: () => void
  onClearHistory: () => void
  t: Translator
}

function cloneCommand(entry: CommandEntry): CommandEntry {
  return {
    ...entry,
    aliases: [...entry.aliases],
    flags: entry.flags ?? 0,
  }
}

function normalizedCommand(entry: CommandEntry): CommandEntry {
  return {
    ...entry,
    phrase: entry.phrase.trim(),
    aliases: entry.aliases.map((alias) => alias.trim()).filter(Boolean),
    flags: entry.flags ?? 0,
  }
}

export function CommandPage({
  envelope,
  entries,
  history,
  busyAction,
  refreshing,
  onRefresh,
  onSaveEntries,
  onReset,
  onClearHistory,
  t,
}: CommandPageProps) {
  const [draftCommand, setDraftCommand] = useState<CommandEntry | null>(null)
  const disabled = busyAction !== null || refreshing
  const saving = busyAction === "commands:save"
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
  const draftExists = Boolean(draftCommand && entries.some((entry) => entry.id === draftCommand.id))
  const draftInvalid = draftCommand ? !draftCommand.phrase.trim() : false

  const openEditor = (entry: CommandEntry) => {
    setDraftCommand(cloneCommand(entry))
  }

  const updateDraft = (updater: (entry: CommandEntry) => CommandEntry) => {
    setDraftCommand((current) => (current ? updater(current) : current))
  }

  const saveDraft = async () => {
    if (!draftCommand || draftInvalid) {
      return
    }

    const nextCommand = normalizedCommand(draftCommand)
    const exists = entries.some((entry) => entry.id === nextCommand.id)
    const nextEntries = exists
      ? entries.map((entry) => (entry.id === nextCommand.id ? nextCommand : entry))
      : [...entries, nextCommand]
    const saved = await onSaveEntries(nextEntries)
    if (saved) {
      setDraftCommand(null)
    }
  }

  const deleteDraft = async () => {
    if (!draftCommand) {
      return
    }
    const saved = await onSaveEntries(entries.filter((entry) => entry.id !== draftCommand.id))
    if (saved) {
      setDraftCommand(null)
    }
  }

  if (!envelope || !tools) {
    return (
      <section className="min-h-0 flex-1 p-px">
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
    <section className="grid min-h-0 flex-1 gap-3 overflow-hidden p-px md:grid-cols-[1fr_22rem]">
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
                  openEditor(entry)
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
                          <Button size="sm" variant="outline" onClick={() => openEditor(entry)}>
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
          <span>{t("commands.saved_hint", "Saved commands sync to the watch while connected")}</span>
        </CardFooter>
      </Card>

      <Card className="min-h-0 md:flex md:h-full md:flex-col">
        <CardHeader>
          <div>
            <CardTitle>{t("commands.last_result", "Command history")}</CardTitle>
            <CardDescription>{t("commands.last_result_description", "Recent command-mode recognition results.")}</CardDescription>
          </div>
          <CardAction>
            <Button size="sm" variant="ghost" onClick={onClearHistory} disabled={!history.length}>
              <Trash2Icon data-icon="inline-start" />
              {t("common.clear", "Clear")}
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent className="min-h-0 md:flex-1">
          {history.length ? (
            <ScrollArea className="h-[calc(100vh-21rem)] md:h-full">
              <Table>
                <TableBody>
                  {history.map((item) => (
                    <TableRow key={item.key}>
                      <TableCell className="align-top">
                        <div className="flex min-w-0 flex-col gap-1">
                          <span className="truncate font-medium">{item.text || "--"}</span>
                          <span className="text-sm text-muted-foreground">{item.time}</span>
                        </div>
                      </TableCell>
                      <TableCell className="w-28 align-top text-right">
                        <div className="flex flex-col items-end gap-1">
                          <Badge variant={item.matched ? "default" : "secondary"}>
                            {item.matched ? item.phrase : item.reason}
                          </Badge>
                          <span className="text-sm text-muted-foreground">
                            {Math.round(item.score * 100)}%
                          </span>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </ScrollArea>
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

      <Sheet open={Boolean(draftCommand)} onOpenChange={(open) => !open && setDraftCommand(null)}>
        <SheetContent className="w-[min(520px,calc(100vw-2rem))] sm:max-w-lg">
          <SheetHeader>
            <SheetTitle>{draftCommand?.phrase || t("commands.edit_title", "Edit command")}</SheetTitle>
            <SheetDescription>{t("commands.edit_description", "Choose what this spoken phrase does.")}</SheetDescription>
          </SheetHeader>

          {draftCommand && (
            <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
              <FieldGroup>
                <Field data-invalid={!draftCommand.phrase.trim() ? true : undefined}>
                  <FieldLabel>{t("commands.phrase", "Phrase")}</FieldLabel>
                  <Input
                    value={draftCommand.phrase}
                    onChange={(event) => updateDraft((entry) => ({ ...entry, phrase: event.target.value }))}
                    placeholder={t("commands.phrase_placeholder", "Clear")}
                    aria-invalid={!draftCommand.phrase.trim()}
                    disabled={disabled}
                  />
                  <FieldDescription>{t("commands.phrase_description", "Say this while holding the left button.")}</FieldDescription>
                </Field>
                <Field>
                  <FieldLabel>{t("commands.aliases", "Aliases")}</FieldLabel>
                  <Input
                    value={draftCommand.aliases.join(", ")}
                    onChange={(event) =>
                      updateDraft((entry) => ({
                        ...entry,
                        aliases: event.target.value
                          .split(",")
                          .map((value) => value.trim())
                          .filter(Boolean),
                      }))
                    }
                    placeholder={t("commands.aliases_placeholder", "Clear input, remove text")}
                    disabled={disabled}
                  />
                  <FieldDescription>{t("commands.aliases_description", "Separate alternatives with commas.")}</FieldDescription>
                </Field>
                <Field>
                  <FieldLabel>{t("commands.enabled", "Enabled")}</FieldLabel>
                  <ToggleGroup
                    aria-label={t("commands.enabled", "Enabled")}
                    spacing={0}
                    variant="outline"
                    value={[draftCommand.enabled ? "1" : "0"]}
                    onValueChange={(values) => {
                      const value = values[values.length - 1]
                      if (value != null) {
                        updateDraft((entry) => ({ ...entry, enabled: value === "1" }))
                      }
                    }}
                    disabled={disabled}
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
                    value={draftCommand.action}
                    onValueChange={(value) => {
                      if (value == null) {
                        return
                      }
                      updateDraft((entry) => {
                        const mapped = withMappingAction(commandAsMappingEntry(entry), value)
                        return commandWithMappingEntry(entry, mapped)
                      })
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
                    entry={commandAsMappingEntry(draftCommand)}
                    envelope={tools}
                    disabled={disabled}
                    onChange={(nextEntry) =>
                      updateDraft((entry) => commandWithMappingEntry(entry, nextEntry))
                    }
                    t={t}
                  />
                </Field>
              </FieldGroup>
            </div>
          )}

          <SheetFooter>
            {draftCommand && draftExists && (
              <Button variant="destructive" onClick={() => void deleteDraft()} disabled={disabled}>
                <Trash2Icon data-icon="inline-start" />
                {t("commands.delete", "Delete")}
              </Button>
            )}
            <Button onClick={() => void saveDraft()} disabled={disabled || draftInvalid}>
              <SpinnerOrIcon busy={saving} icon={SaveIcon} />
              {t("common.save", "Save")}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </section>
  )
}
