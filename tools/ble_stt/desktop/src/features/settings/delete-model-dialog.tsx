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
import { modelLabel } from "@/lib/app-view-model"

type DeleteModelDialogProps = {
  open: boolean
  activeModel: string
  onOpenChange: (open: boolean) => void
  onDelete: () => void
}

export function DeleteModelDialog({
  open,
  activeModel,
  onOpenChange,
  onDelete,
}: DeleteModelDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete model?</AlertDialogTitle>
          <AlertDialogDescription>
            This removes the local cache for {modelLabel(activeModel)}. Stop the service first if the model is in use.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={onDelete}>Delete model</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
