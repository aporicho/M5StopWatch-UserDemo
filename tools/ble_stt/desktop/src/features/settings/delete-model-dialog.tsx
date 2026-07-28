import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { modelDisplayLabel } from "@/lib/app-view-model"
import type { Translator } from "@/lib/i18n"

type DeleteModelDialogProps = {
  open: boolean
  activeModel: string
  onOpenChange: (open: boolean) => void
  onDelete: () => void
  t: Translator
}

export function DeleteModelDialog({
  open,
  activeModel,
  onOpenChange,
  onDelete,
  t,
}: DeleteModelDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("settings.delete_model_title", "Delete model?")}</AlertDialogTitle>
          <AlertDialogDescription>
            {t(
              "settings.delete_model_description",
              "The downloaded {model} files will be removed from this computer."
            ).replace("{model}", modelDisplayLabel(activeModel, t))}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t("common.cancel", "Cancel")}</AlertDialogCancel>
          <AlertDialogAction onClick={onDelete}>
            {t("settings.delete_model_action", "Delete model")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
