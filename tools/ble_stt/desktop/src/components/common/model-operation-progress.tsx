import { XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Progress, ProgressLabel, ProgressValue } from "@/components/ui/progress"
import { Spinner } from "@/components/ui/spinner"
import {
  formatBytes,
  type ModelOperationProgress as ModelOperation,
} from "@/lib/helper-api"
import type { Translator } from "@/lib/i18n"

function bytes(value: number) {
  return value === 0 ? "0 B" : formatBytes(value)
}

export function modelOperationLabel(operation: ModelOperation, t: Translator) {
  switch (operation.phase) {
    case "preparing":
      return t("model_operation.preparing", "Preparing download…")
    case "downloading":
      return operation.component === "runtime"
        ? t("model_operation.downloading_runtime", "Downloading runtime…")
        : operation.kind === "correction"
          ? t("model_operation.downloading_correction", "Downloading correction model…")
        : t("model_operation.downloading", "Downloading model…")
    case "verifying":
      return t("model_operation.verifying", "Verifying files…")
    case "installing":
      return t("model_operation.installing", "Installing…")
    case "cancelling":
      return t("model_operation.cancelling", "Cancelling…")
    default:
      return ""
  }
}

export function ModelOperationProgress({
  operation,
  onCancel,
  t,
}: {
  operation: ModelOperation
  onCancel?: () => void
  t: Translator
}) {
  const label = modelOperationLabel(operation, t)
  const hasProgress =
    operation.phase === "downloading" &&
    operation.total_bytes !== null &&
    operation.total_bytes > 0 &&
    operation.percent !== null

  return (
    <div className="flex w-full flex-col gap-3" aria-live="polite">
      {hasProgress ? (
        <Progress value={Math.min(100, Math.max(0, operation.percent ?? 0))}>
          <ProgressLabel>{label}</ProgressLabel>
          <ProgressValue>
            {() => `${Math.round(operation.percent ?? 0)}%`}
          </ProgressValue>
        </Progress>
      ) : (
        <div className="flex items-center gap-2 text-sm font-medium">
          <Spinner />
          <span>{label}</span>
        </div>
      )}
      {operation.phase === "downloading" && (
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-muted-foreground tabular-nums">
            {bytes(operation.downloaded_bytes)}
            {operation.total_bytes ? ` / ${bytes(operation.total_bytes)}` : ""}
          </span>
          {operation.cancellable && onCancel && (
            <Button size="sm" variant="outline" onClick={onCancel}>
              <XIcon data-icon="inline-start" />
              {t("common.cancel", "Cancel")}
            </Button>
          )}
        </div>
      )}
      {operation.phase === "preparing" && operation.cancellable && onCancel && (
        <Button className="self-start" size="sm" variant="outline" onClick={onCancel}>
          <XIcon data-icon="inline-start" />
          {t("common.cancel", "Cancel")}
        </Button>
      )}
    </div>
  )
}
