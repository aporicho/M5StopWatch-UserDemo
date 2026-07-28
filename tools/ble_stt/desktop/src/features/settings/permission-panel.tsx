import { BluetoothIcon, KeyboardIcon } from "lucide-react"

import { SpinnerOrIcon } from "@/components/common/spinner-or-icon"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldContent, FieldGroup, FieldTitle } from "@/components/ui/field"
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
      </CardHeader>
      <CardContent>
        <FieldGroup>
          <Field orientation="horizontal">
            <FieldContent>
              <FieldTitle>{t("settings.bluetooth", "Bluetooth")}</FieldTitle>
            </FieldContent>
            {status?.permissions.bluetooth.ok ? (
              <Badge variant="outline">{t("settings.permission_granted", "Granted")}</Badge>
            ) : (
              <Button variant="outline" onClick={() => requestPermission("bluetooth")} disabled={busyAction !== null}>
                <SpinnerOrIcon busy={busyAction === "permission:bluetooth"} icon={BluetoothIcon} />
                {t("common.open_system_settings", "Open System Settings")}
              </Button>
            )}
          </Field>
          <Field orientation="horizontal">
            <FieldContent>
              <FieldTitle>{t("settings.text_input", "Text input")}</FieldTitle>
            </FieldContent>
            {status?.permissions.input.ok ? (
              <Badge variant="outline">{t("settings.permission_granted", "Granted")}</Badge>
            ) : (
              <Button variant="outline" onClick={() => requestPermission("input")} disabled={busyAction !== null}>
                <SpinnerOrIcon busy={busyAction === "permission:input"} icon={KeyboardIcon} />
                {t("common.open_system_settings", "Open System Settings")}
              </Button>
            )}
          </Field>
        </FieldGroup>
      </CardContent>
    </Card>
  )
}
