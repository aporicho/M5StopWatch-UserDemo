import {
  AlertCircleIcon,
  BookOpenIcon,
  CheckCircle2Icon,
  DownloadIcon,
  PlayIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  SquareIcon,
  Trash2Icon,
  SaveIcon,
  SparklesIcon,
  KeyboardIcon,
  WrenchIcon,
} from "lucide-react"

import { SpinnerOrIcon } from "@/components/common/spinner-or-icon"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ButtonGroup } from "@/components/ui/button-group"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldTitle,
} from "@/components/ui/field"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Slider } from "@/components/ui/slider"
import { Textarea } from "@/components/ui/textarea"
import { Toggle } from "@/components/ui/toggle"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { PermissionPanel } from "@/features/settings/permission-panel"
import { modelDisplayLabel, readinessVariant } from "@/lib/app-view-model"
import {
  formatBytes,
  type CorrectionModelAction,
  type CorrectionModelStatus,
  type ModelAction,
  type PermissionKind,
  type ServiceAction,
  type StatusPayload,
  type VoicePreferences,
} from "@/lib/helper-api"
import type { LanguageCode, Translator } from "@/lib/i18n"

type SelectItemOption = {
  label: string
  value: string
}

type SettingsSheetProps = {
  open: boolean
  status: StatusPayload | null
  busyAction: string | null
  controlsDisabled: boolean
  currentModel: StatusPayload["model"] | null
  activeModel: string
  selectedModelDetail: string
  modelItems: SelectItemOption[]
  language: LanguageCode
  languageItems: SelectItemOption[]
  serviceModelBlocked: boolean
  installModelDisabled: boolean
  updateModelDisabled: boolean
  repairModelDisabled: boolean
  useModelDisabled: boolean
  deleteModelDisabled: boolean
  voicePreferences: VoicePreferences | null
  currentCorrectionModel: CorrectionModelStatus | null
  correctionModel: CorrectionModelStatus | null
  activeCorrectionModel: string
  correctionModelItems: SelectItemOption[]
  correctionModelSelectionTouched: boolean
  voiceSettingsTouched: boolean
  onOpenChange: (open: boolean) => void
  onLanguageChange: (language: LanguageCode) => void
  onModelChange: (model: string) => void
  onRunModelAction: (action: ModelAction) => void
  onRunServiceAction: (action: ServiceAction) => void
  onRequestPermission: (kind: PermissionKind) => void
  onRequestDeleteModel: () => void
  onVoicePreferencesChange: (preferences: VoicePreferences) => void
  onSaveVoiceSettings: () => void
  onCorrectionModelChange: (model: string) => void
  onRunCorrectionModelAction: (action: CorrectionModelAction) => void
  t: Translator
}

export function SettingsSheet({
  open,
  status,
  busyAction,
  controlsDisabled,
  currentModel,
  activeModel,
  selectedModelDetail,
  modelItems,
  language,
  languageItems,
  serviceModelBlocked,
  installModelDisabled,
  updateModelDisabled,
  repairModelDisabled,
  useModelDisabled,
  deleteModelDisabled,
  voicePreferences,
  currentCorrectionModel,
  correctionModel,
  activeCorrectionModel,
  correctionModelItems,
  correctionModelSelectionTouched,
  voiceSettingsTouched,
  onOpenChange,
  onLanguageChange,
  onModelChange,
  onRunModelAction,
  onRunServiceAction,
  onRequestPermission,
  onRequestDeleteModel,
  onVoicePreferencesChange,
  onSaveVoiceSettings,
  onCorrectionModelChange,
  onRunCorrectionModelAction,
  t,
}: SettingsSheetProps) {
  const correctionModelDetail =
    activeCorrectionModel === "balanced"
      ? t(
          "settings.correction_balanced_detail",
          "Improved context correction while remaining below 1 GB."
        )
      : t(
          "settings.correction_lite_detail",
          "Smallest recommended option; good enough for everyday conservative correction."
        )

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[min(760px,calc(100vw-2rem))] sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>{t("settings.title", "Settings")}</SheetTitle>
          <SheetDescription>{t("settings.description", "Model, permissions, and voice service controls.")}</SheetDescription>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          <div className="flex flex-col gap-4 p-px">
            <Card>
              <CardHeader>
                <CardTitle>{t("settings.general", "General")}</CardTitle>
                <CardDescription>{t("settings.general_description", "App preferences for this computer.")}</CardDescription>
              </CardHeader>
              <CardContent>
                <FieldGroup>
                  <Field orientation="horizontal">
                    <FieldContent>
                      <FieldTitle>{t("settings.language", "Language")}</FieldTitle>
                      <FieldDescription>{t("settings.language_description", "Changes apply immediately.")}</FieldDescription>
                    </FieldContent>
                    <Select
                      items={languageItems}
                      value={language}
                      onValueChange={(value) => {
                        if (value == null) {
                          return
                        }
                        onLanguageChange(value as LanguageCode)
                      }}
                    >
                      <SelectTrigger className="w-40">
                        <SelectValue placeholder={t("settings.language", "Language")} />
                      </SelectTrigger>
                      <SelectContent alignItemWithTrigger={false}>
                        <SelectGroup>
                          {languageItems.map((item) => (
                            <SelectItem key={item.value} value={item.value}>
                              {item.label}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </Field>
                </FieldGroup>
              </CardContent>
            </Card>

            {voicePreferences && (
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <SparklesIcon className="size-4" />
                    {t("settings.smart_correction", "Smart correction")}
                  </CardTitle>
                  <CardDescription>
                    {t(
                      "settings.smart_correction_description",
                      "Conservative local correction for Simplified Chinese and English."
                    )}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <FieldGroup>
                    <Field orientation="horizontal">
                      <FieldContent>
                        <FieldTitle>{t("settings.enable_correction", "Enable smart correction")}</FieldTitle>
                        <FieldDescription>
                          {t("settings.enable_correction_description", "Runs locally after recognition and keeps numbers, English, and personal terms unchanged.")}
                        </FieldDescription>
                      </FieldContent>
                      <Toggle
                        variant="outline"
                        pressed={voicePreferences.correction.enabled}
                        onPressedChange={(pressed) =>
                          onVoicePreferencesChange({
                            ...voicePreferences,
                            correction: { ...voicePreferences.correction, enabled: pressed },
                          })
                        }
                      >
                        {voicePreferences.correction.enabled ? t("common.on", "On") : t("common.off", "Off")}
                      </Toggle>
                    </Field>

                    <Field orientation="horizontal">
                      <FieldContent>
                        <FieldTitle className="flex items-center gap-2">
                          <BookOpenIcon className="size-4" />
                          {t("settings.standard_lexicon", "Built-in word packs")}
                        </FieldTitle>
                        <FieldDescription>
                          {t("settings.standard_lexicon_description", "Bias recognition toward common computing and M5StopWatch terms without forcing replacements.")}
                        </FieldDescription>
                      </FieldContent>
                      <Toggle
                        variant="outline"
                        pressed={voicePreferences.correction.standard_lexicon_enabled}
                        onPressedChange={(pressed) =>
                          onVoicePreferencesChange({
                            ...voicePreferences,
                            correction: {
                              ...voicePreferences.correction,
                              standard_lexicon_enabled: pressed,
                            },
                          })
                        }
                      >
                        {voicePreferences.correction.standard_lexicon_enabled ? t("common.on", "On") : t("common.off", "Off")}
                      </Toggle>
                    </Field>

                    <Field>
                      <FieldLabel htmlFor="personal-glossary">
                        {t("settings.personal_glossary", "Personal glossary")}
                      </FieldLabel>
                      <Textarea
                        id="personal-glossary"
                        rows={4}
                        value={voicePreferences.correction.glossary.join("\n")}
                        placeholder={t("settings.personal_glossary_placeholder", "One name or term per line")}
                        onChange={(event) =>
                          onVoicePreferencesChange({
                            ...voicePreferences,
                            correction: {
                              ...voicePreferences.correction,
                              glossary: event.currentTarget.value.split(/\r?\n/),
                            },
                          })
                        }
                      />
                      <FieldDescription>
                        {t("settings.personal_glossary_description", "Personal terms take priority and are protected during correction. Up to 128 terms.")}
                      </FieldDescription>
                    </Field>

                    <Field>
                      <FieldLabel>{t("settings.correction_model", "Correction model")}</FieldLabel>
                      <Select
                        items={correctionModelItems}
                        value={activeCorrectionModel}
                        onValueChange={(value) => {
                          if (value) onCorrectionModelChange(value)
                        }}
                      >
                        <SelectTrigger className="w-full">
                          <SelectValue
                            placeholder={t("settings.select_correction_model", "Select correction model")}
                          />
                        </SelectTrigger>
                        <SelectContent alignItemWithTrigger={false}>
                          <SelectGroup>
                            <SelectLabel>
                              {t("settings.available_models", "Available models")}
                            </SelectLabel>
                            {correctionModelItems.map((item) => (
                              <SelectItem key={item.value} value={item.value}>
                                {item.label}
                              </SelectItem>
                            ))}
                          </SelectGroup>
                        </SelectContent>
                      </Select>
                      <FieldDescription>
                        {correctionModel ? (
                          <>
                            {correctionModel.installed
                              ? t("settings.correction_installed_size", "Installed")
                              : t("settings.correction_download_size", "Download")} {formatBytes(
                              correctionModel.installed
                                ? correctionModel.disk_bytes
                                : correctionModel.expected_disk_bytes,
                            )} · {correctionModelDetail}
                            {correctionModel.stale_disk_bytes > 0 && (
                              <> · {t("settings.correction_legacy_size", "Legacy model")} {formatBytes(correctionModel.stale_disk_bytes)}</>
                            )}
                          </>
                        ) : t("common.loading", "Loading")}
                      </FieldDescription>
                      <FieldDescription>
                        {t("settings.current_model", "Current")}: {currentCorrectionModel?.display_name ?? t("common.unknown", "Unknown")}
                      </FieldDescription>
                      <Badge variant={correctionModel?.state === "legacy" ? "secondary" : readinessVariant(Boolean(correctionModel?.ready))}>
                        {correctionModel?.state ?? "unknown"}
                      </Badge>
                    </Field>

                    {correctionModel && correctionModel.stale_disk_bytes > 0 && (
                      <Alert>
                        <AlertCircleIcon />
                        <AlertTitle>{t("settings.correction_legacy_title", "Legacy 4B model found")}</AlertTitle>
                        <AlertDescription>
                          {t(
                            "settings.correction_legacy_description",
                            "The old model stays untouched until the selected model is downloaded and verified, then this space is reclaimed automatically.",
                          )}
                        </AlertDescription>
                      </Alert>
                    )}

                    {correctionModel && !correctionModel.runtime_available && (
                      <Alert>
                        <AlertCircleIcon />
                        <AlertTitle>{t("settings.correction_runtime_missing", "Correction runtime missing")}</AlertTitle>
                        <AlertDescription>
                          {t("settings.correction_runtime_missing_description", "This build does not include llama-server, so recognition will safely fall back to uncorrected text.")}
                        </AlertDescription>
                      </Alert>
                    )}
                  </FieldGroup>
                </CardContent>
                <CardFooter className="flex flex-wrap gap-2">
                  <Button
                    onClick={() => onRunCorrectionModelAction("use-model")}
                    disabled={controlsDisabled || !correctionModelSelectionTouched}
                  >
                    <SpinnerOrIcon busy={busyAction === "correction-model:use-model"} icon={CheckCircle2Icon} />
                    {t("settings.use", "Use")}
                  </Button>
                  <Button onClick={onSaveVoiceSettings} disabled={controlsDisabled || !voiceSettingsTouched}>
                    <SpinnerOrIcon busy={busyAction === "voice-settings:save"} icon={SaveIcon} />
                    {t("common.save", "Save")}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => onRunCorrectionModelAction("install-model")}
                    disabled={controlsDisabled || Boolean(correctionModel?.installed)}
                  >
                    <SpinnerOrIcon busy={busyAction === "correction-model:install-model"} icon={DownloadIcon} />
                    {correctionModel && correctionModel.stale_disk_bytes > 0
                      ? t("settings.replace_model", "Replace legacy model")
                      : t("settings.install_model", "Install model")}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => onRunCorrectionModelAction("update-model")}
                    disabled={controlsDisabled || !correctionModel?.installed}
                  >
                    <SpinnerOrIcon busy={busyAction === "correction-model:update-model"} icon={RefreshCwIcon} />
                    {t("settings.update", "Update")}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => onRunCorrectionModelAction("repair-model")}
                    disabled={controlsDisabled || !(correctionModel?.disk_bytes ?? 0)}
                  >
                    <SpinnerOrIcon busy={busyAction === "correction-model:repair-model"} icon={WrenchIcon} />
                    {t("settings.repair", "Repair")}
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={() => onRunCorrectionModelAction("delete-model")}
                    disabled={controlsDisabled || (!correctionModel?.disk_bytes && !((correctionModel?.stale_disk_bytes ?? 0) > 0))}
                  >
                    <Trash2Icon data-icon="inline-start" />
                    {t("settings.delete", "Delete")}
                  </Button>
                </CardFooter>
              </Card>
            )}

            {voicePreferences && (
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <KeyboardIcon className="size-4" />
                    {t("settings.typing_effect", "Typing effect")}
                  </CardTitle>
                  <CardDescription>
                    {t("settings.typing_effect_description", "Show live recognition as a natural typing animation in the target app.")}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <FieldGroup>
                    <Field orientation="horizontal">
                      <FieldContent>
                        <FieldTitle>{t("settings.enable_typing_effect", "Animate inserted text")}</FieldTitle>
                        <FieldDescription>{t("settings.enable_typing_effect_description", "Disable to insert each recognized chunk immediately.")}</FieldDescription>
                      </FieldContent>
                      <Toggle
                        variant="outline"
                        pressed={voicePreferences.typing.enabled}
                        onPressedChange={(pressed) =>
                          onVoicePreferencesChange({
                            ...voicePreferences,
                            typing: { ...voicePreferences.typing, enabled: pressed },
                          })
                        }
                      >
                        {voicePreferences.typing.enabled ? t("common.on", "On") : t("common.off", "Off")}
                      </Toggle>
                    </Field>
                    <Field>
                      <div className="flex items-center justify-between gap-4">
                        <FieldLabel>{t("settings.typing_speed", "Typing speed")}</FieldLabel>
                        <Badge variant="outline">{voicePreferences.typing.characters_per_second} {t("settings.characters_per_second", "chars/s")}</Badge>
                      </div>
                      <Slider
                        min={10}
                        max={100}
                        step={5}
                        value={[voicePreferences.typing.characters_per_second]}
                        disabled={!voicePreferences.typing.enabled}
                        onValueChange={(value) => {
                          const speed = Array.isArray(value) ? value[0] : value
                          if (typeof speed !== "number") return
                          onVoicePreferencesChange({
                            ...voicePreferences,
                            typing: { ...voicePreferences.typing, characters_per_second: speed },
                          })
                        }}
                      />
                    </Field>
                    <Field orientation="horizontal">
                      <FieldContent>
                        <FieldTitle>{t("settings.auto_accelerate", "Auto accelerate")}</FieldTitle>
                        <FieldDescription>{t("settings.auto_accelerate_description", "Speed up smoothly when recognized text is waiting, up to 120 chars/s.")}</FieldDescription>
                      </FieldContent>
                      <Toggle
                        variant="outline"
                        pressed={voicePreferences.typing.auto_accelerate}
                        disabled={!voicePreferences.typing.enabled}
                        onPressedChange={(pressed) =>
                          onVoicePreferencesChange({
                            ...voicePreferences,
                            typing: { ...voicePreferences.typing, auto_accelerate: pressed },
                          })
                        }
                      >
                        {voicePreferences.typing.auto_accelerate ? t("common.on", "On") : t("common.off", "Off")}
                      </Toggle>
                    </Field>
                  </FieldGroup>
                </CardContent>
                <CardFooter>
                  <Button onClick={onSaveVoiceSettings} disabled={controlsDisabled || !voiceSettingsTouched}>
                    <SpinnerOrIcon busy={busyAction === "voice-settings:save"} icon={SaveIcon} />
                    {t("common.save", "Save")}
                  </Button>
                </CardFooter>
              </Card>
            )}

          <Card>
            <CardHeader>
              <CardTitle>{t("settings.speech_model", "Speech model")}</CardTitle>
              <CardDescription>{selectedModelDetail}</CardDescription>
            </CardHeader>
            <CardContent>
              <FieldGroup>
                <Field>
                  <FieldLabel>{t("settings.model", "Model")}</FieldLabel>
                  <Select
                    items={modelItems}
                    value={activeModel}
                    onValueChange={(value) => {
                      if (!value) {
                        return
                      }
                      onModelChange(value)
                    }}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder={t("settings.select_model", "Select model")} />
                    </SelectTrigger>
                    <SelectContent alignItemWithTrigger={false}>
                      <SelectGroup>
                        <SelectLabel>{t("settings.available_models", "Available models")}</SelectLabel>
                        {modelItems.map((item) => (
                          <SelectItem key={item.value} value={item.value}>
                            {item.label}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  <FieldDescription>
                    {t("settings.current_model", "Current")}: {modelDisplayLabel(currentModel?.selected, t)} / {currentModel?.message ?? t("common.unknown", "Unknown")}
                  </FieldDescription>
                </Field>
                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldTitle>{t("home.storage", "Storage")}</FieldTitle>
                    <FieldDescription>{formatBytes(currentModel?.disk_bytes ?? 0)}</FieldDescription>
                  </FieldContent>
                  <Badge variant={readinessVariant(Boolean(currentModel?.installed))}>
                    {currentModel?.state ?? "unknown"}
                  </Badge>
                </Field>
                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldTitle>{t("settings.update", "Update")}</FieldTitle>
                    <FieldDescription>
                      {currentModel?.update_available ? t("settings.update_available", "An update is available.") : t("settings.no_update", "No update is available.")}
                    </FieldDescription>
                  </FieldContent>
                  <Badge variant={currentModel?.update_available ? "secondary" : "outline"}>
                    {currentModel?.update_available ? t("settings.available", "Available") : t("settings.current", "Current")}
                  </Badge>
                </Field>
              </FieldGroup>
            </CardContent>
            <CardFooter className="flex flex-wrap gap-2">
              <Button onClick={() => onRunModelAction("use")} disabled={useModelDisabled}>
                <SpinnerOrIcon busy={busyAction === "model:use"} icon={CheckCircle2Icon} />
                {t("settings.use", "Use")}
              </Button>
              <Button variant="outline" onClick={() => onRunModelAction("install")} disabled={installModelDisabled}>
                <SpinnerOrIcon busy={busyAction === "model:install"} icon={DownloadIcon} />
                {t("settings.install", "Install")}
              </Button>
              <Button variant="outline" onClick={() => onRunModelAction("update")} disabled={updateModelDisabled}>
                <SpinnerOrIcon busy={busyAction === "model:update"} icon={RefreshCwIcon} />
                {t("settings.update", "Update")}
              </Button>
              <Button variant="outline" onClick={() => onRunModelAction("repair")} disabled={repairModelDisabled}>
                <SpinnerOrIcon busy={busyAction === "model:repair"} icon={WrenchIcon} />
                {t("settings.repair", "Repair")}
              </Button>
              <Button variant="destructive" onClick={onRequestDeleteModel} disabled={deleteModelDisabled}>
                <Trash2Icon data-icon="inline-start" />
                {t("settings.delete", "Delete")}
              </Button>
            </CardFooter>
          </Card>

          <PermissionPanel
            status={status}
            busyAction={busyAction}
            requestPermission={onRequestPermission}
            t={t}
          />

          <Card>
            <CardHeader>
              <CardTitle>{t("settings.voice_service", "Voice service")}</CardTitle>
              <CardDescription>{t("settings.voice_service_description", "Advanced controls for the background process.")}</CardDescription>
            </CardHeader>
            <CardContent>
              <FieldGroup>
                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldTitle>{t("settings.login_service", "Login service")}</FieldTitle>
                    <FieldDescription>
                      {status?.service.installed ? t("settings.installed", "installed") : t("settings.not_installed", "not installed")} /{" "}
                      {status?.service.running ? t("settings.running", "running") : t("settings.stopped", "stopped")}
                    </FieldDescription>
                  </FieldContent>
                  <Badge variant={readinessVariant(Boolean(status?.service.running))}>
                    {status?.service.running ? t("settings.running_badge", "Running") : t("settings.stopped_badge", "Stopped")}
                  </Badge>
                </Field>
                {serviceModelBlocked && (
                  <Alert>
                    <AlertCircleIcon />
                    <AlertTitle>{t("settings.model_required", "Model required")}</AlertTitle>
                    <AlertDescription>{t("settings.model_required_description", "Install a model before starting the voice service.")}</AlertDescription>
                  </Alert>
                )}
              </FieldGroup>
            </CardContent>
            <CardFooter>
              <ButtonGroup className="flex-wrap">
                <Button variant="outline" onClick={() => onRunServiceAction("install")} disabled={controlsDisabled}>
                  <SpinnerOrIcon busy={busyAction === "service:install"} icon={DownloadIcon} />
                  {t("settings.install", "Install")}
                </Button>
                <Button onClick={() => onRunServiceAction("start")} disabled={controlsDisabled || serviceModelBlocked}>
                  <SpinnerOrIcon busy={busyAction === "service:start"} icon={PlayIcon} />
                  {t("settings.start", "Start")}
                </Button>
                <Button variant="outline" onClick={() => onRunServiceAction("stop")} disabled={controlsDisabled}>
                  <SpinnerOrIcon busy={busyAction === "service:stop"} icon={SquareIcon} />
                  {t("settings.stop", "Stop")}
                </Button>
                <Button variant="outline" onClick={() => onRunServiceAction("restart")} disabled={controlsDisabled || serviceModelBlocked}>
                  <SpinnerOrIcon busy={busyAction === "service:restart"} icon={RotateCcwIcon} />
                  {t("settings.restart", "Restart")}
                </Button>
              </ButtonGroup>
            </CardFooter>
          </Card>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}
