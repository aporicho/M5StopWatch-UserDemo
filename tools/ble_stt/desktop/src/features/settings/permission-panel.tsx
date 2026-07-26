import { BluetoothIcon, KeyboardIcon } from "lucide-react"

import { SpinnerOrIcon } from "@/components/common/spinner-or-icon"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldContent, FieldDescription, FieldGroup, FieldTitle } from "@/components/ui/field"
import type { PermissionKind, StatusPayload } from "@/lib/helper-api"
import type { Translator } from "@/lib/i18n"

type PermissionPanelProps = {
  status: StatusPayload | null
  busyAction: string | null
  requestPermission: (kind: PermissionKind) => void
  t: Translator
}

export function PermissionPanel({
  status,
  busyAction,
  requestPermission,
  t,
}: PermissionPanelProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.permissions", "Permissions")}</CardTitle>
        <CardDescription>{t("settings.permissions_description", "Required for Bluetooth audio and text insertion.")}</CardDescription>
      </CardHeader>
      <CardContent>
        <FieldGroup>
          <Field orientation="horizontal">
            <FieldContent>
              <FieldTitle>{t("settings.bluetooth", "Bluetooth")}</FieldTitle>
              <FieldDescription>{status?.permissions.bluetooth.message ?? t("common.unknown", "Unknown")}</FieldDescription>
            </FieldContent>
            <Button
              variant="outline"
              onClick={() => requestPermission("bluetooth")}
              disabled={busyAction !== null}
            >
              <SpinnerOrIcon busy={busyAction === "permission:bluetooth"} icon={BluetoothIcon} />
              {t("settings.request", "Request")}
            </Button>
          </Field>
          <Field orientation="horizontal">
            <FieldContent>
              <FieldTitle>{t("settings.text_input", "Text input")}</FieldTitle>
              <FieldDescription>{status?.permissions.input.message ?? t("common.unknown", "Unknown")}</FieldDescription>
            </FieldContent>
            <Button
              variant="outline"
              onClick={() => requestPermission("input")}
              disabled={busyAction !== null}
            >
              <SpinnerOrIcon busy={busyAction === "permission:input"} icon={KeyboardIcon} />
              {t("settings.request", "Request")}
            </Button>
          </Field>
        </FieldGroup>
      </CardContent>
    </Card>
  )
}
