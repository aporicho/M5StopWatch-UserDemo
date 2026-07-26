import { Badge } from "@/components/ui/badge"
import type { DailyState } from "@/lib/app-view-model"

export function StatusBadge({ state }: { state: DailyState }) {
  return <Badge variant={state.badgeVariant}>{state.label}</Badge>
}
