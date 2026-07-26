import type { ComponentType, SVGProps } from "react"

import { Spinner } from "@/components/ui/spinner"

type SpinnerOrIconProps = {
  busy: boolean
  icon: ComponentType<SVGProps<SVGSVGElement>>
}

export function SpinnerOrIcon({ busy, icon: Icon }: SpinnerOrIconProps) {
  if (busy) {
    return <Spinner data-icon="inline-start" />
  }

  return <Icon data-icon="inline-start" />
}
