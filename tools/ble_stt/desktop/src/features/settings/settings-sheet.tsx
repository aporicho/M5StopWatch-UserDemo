import {
  AlertCircleIcon,
  CheckCircle2Icon,
  DownloadIcon,
  PlayIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  SquareIcon,
  Trash2Icon,
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
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { PermissionPanel } from "@/features/settings/permission-panel"
import { modelDisplayLabel, readinessVariant } from "@/lib/app-view-model"
import { formatBytes, type ModelAction, type PermissionKind, type ServiceAction, type StatusPayload } from "@/lib/helper-api"
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
  onOpenChange: (open: boolean) => void
  onLanguageChange: (language: LanguageCode) => void
  onModelChange: (model: string) => void
  onRunModelAction: (action: ModelAction) => void
  onRunServiceAction: (action: ServiceAction) => void
  onRequestPermission: (kind: PermissionKind) => void
  onRequestDeleteModel: () => void
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
  onOpenChange,
  onLanguageChange,
  onModelChange,
  onRunModelAction,
  onRunServiceAction,
  onRequestPermission,
  onRequestDeleteModel,
  t,
}: SettingsSheetProps) {
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
