import { useMemo } from "react"

import { Badge } from "@/components/ui/badge"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Slider } from "@/components/ui/slider"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import type { MappingEntry, MappingEnvelope, MappingOption } from "@/lib/helper-api"
import {
  MODIFIER_TOGGLE_OPTIONS,
  WHEEL_DIRECTION_OPTIONS,
  localizedMappingOptionLabel,
  mappingOptionValue,
  modifierLabel,
} from "@/lib/app-view-model"
import type { Translator } from "@/lib/i18n"

function MappingSelectField({
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string
  value: number
  options: MappingOption[]
  disabled: boolean
  onChange: (value: number) => void
}) {
  const items = useMemo(
    () => options.map((option) => ({ label: option.label, value: String(option.value) })),
    [options]
  )

  return (
    <Field>
      <FieldLabel>{label}</FieldLabel>
      <Select
        items={items}
        value={mappingOptionValue(value)}
        onValueChange={(nextValue) => {
          if (nextValue == null) {
            return
          }
          onChange(Number(nextValue))
        }}
        disabled={disabled}
      >
        <SelectTrigger className="w-full">
          <SelectValue placeholder={label} />
        </SelectTrigger>
        <SelectContent alignItemWithTrigger={false}>
          <SelectGroup>
            {options.map((option) => (
              <SelectItem key={option.value} value={String(option.value)}>
                {option.label}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </Field>
  )
}

function MappingToggleField({
  label,
  value,
  options,
  disabled,
  onChange,
  t,
}: {
  label: string
  value: number
  options: MappingOption[]
  disabled: boolean
  onChange: (value: number) => void
  t: Translator
}) {
  return (
    <Field data-disabled={disabled ? true : undefined}>
      <FieldLabel>{label}</FieldLabel>
      <ToggleGroup
        aria-label={label}
        className="flex w-full flex-wrap"
        spacing={0}
        variant="outline"
        value={[String(value)]}
        onValueChange={(nextValues) => {
          const nextValue = nextValues[nextValues.length - 1]
          if (nextValue == null) {
            return
          }
          onChange(Number(nextValue))
        }}
      >
        {options.map((option) => (
          <ToggleGroupItem
            key={option.value}
            className="min-w-20 flex-1"
            disabled={disabled}
            value={String(option.value)}
          >
            {localizedMappingOptionLabel(option.label, t)}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </Field>
  )
}

function MappingModifierField({
  label,
  value,
  disabled,
  onChange,
  t,
}: {
  label: string
  value: number
  disabled: boolean
  onChange: (value: number) => void
  t: Translator
}) {
  return (
    <Field data-disabled={disabled ? true : undefined}>
      <FieldLabel>{label}</FieldLabel>
      <ToggleGroup
        aria-label={label}
        className="flex w-full flex-wrap"
        spacing={0}
        variant="outline"
        value={MODIFIER_TOGGLE_OPTIONS.filter((option) => (value & option.value) !== 0).map((option) => String(option.value))}
        onValueChange={(nextValues) => {
          const nextValue = nextValues.reduce((mask, item) => mask | Number(item), 0)
          onChange(nextValue)
        }}
        multiple
      >
        {MODIFIER_TOGGLE_OPTIONS.map((option) => (
          <ToggleGroupItem
            key={option.value}
            className="min-w-20 flex-1"
            disabled={disabled}
            value={String(option.value)}
          >
            {localizedMappingOptionLabel(option.label, t)}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <FieldDescription>{modifierLabel(value, t)}</FieldDescription>
    </Field>
  )
}

function MappingWheelSpeedField({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string
  value: number
  disabled: boolean
  onChange: (value: number) => void
}) {
  const safeValue = Math.min(4, Math.max(1, Math.round(value || 1)))

  return (
    <Field data-disabled={disabled ? true : undefined}>
      <div className="flex items-center justify-between gap-3">
        <FieldLabel>{label}</FieldLabel>
        <Badge variant="outline">{safeValue}x</Badge>
      </div>
      <Slider
        disabled={disabled}
        max={4}
        min={1}
        step={1}
        value={safeValue}
        onValueChange={(nextValue) => {
          const next = Array.isArray(nextValue) ? nextValue[0] : nextValue
          onChange(Math.min(4, Math.max(1, Math.round(next || 1))))
        }}
      />
      <div className="flex justify-between gap-2 text-xs text-muted-foreground">
        <span>1x</span>
        <span>4x</span>
      </div>
    </Field>
  )
}

export function MappingParameterEditor({
  entry,
  envelope,
  disabled,
  onChange,
  t,
}: {
  entry: MappingEntry
  envelope: MappingEnvelope
  disabled: boolean
  onChange: (entry: MappingEntry) => void
  t: Translator
}) {
  if (entry.locked) {
    return <p className="text-sm text-muted-foreground">{t("mapping.fixed_safety", "Fixed safety shortcut.")}</p>
  }

  if (entry.action === "hid.keyboard.tap") {
    return (
      <FieldGroup>
        <MappingSelectField
          label={t("mapping.key", "Key")}
          value={entry.param0}
          options={envelope.keyOptions}
          disabled={disabled}
          onChange={(value) => onChange({ ...entry, param0: value })}
        />
        <MappingModifierField
          label={t("mapping.modifier", "Modifier")}
          value={entry.param1}
          disabled={disabled}
          onChange={(value) => onChange({ ...entry, param1: value })}
          t={t}
        />
      </FieldGroup>
    )
  }

  if (entry.action === "hid.mouse.wheel") {
    return (
      <FieldGroup>
        <MappingWheelSpeedField
          label={t("mapping.speed", "Speed")}
          value={entry.param0}
          disabled={disabled}
          onChange={(value) => onChange({ ...entry, param0: value })}
        />
        <MappingToggleField
          label={t("mapping.direction", "Direction")}
          value={entry.param1}
          options={WHEEL_DIRECTION_OPTIONS}
          disabled={disabled}
          onChange={(value) => onChange({ ...entry, param1: value })}
          t={t}
        />
      </FieldGroup>
    )
  }

  if (entry.action === "hid.mouse.click") {
    return (
      <MappingToggleField
        label={t("mapping.button", "Button")}
        value={entry.param0}
        options={envelope.mouseButtons}
        disabled={disabled}
        onChange={(value) => onChange({ ...entry, param0: value })}
        t={t}
      />
    )
  }

  if (entry.action === "hid.media.control") {
    return (
      <MappingToggleField
        label={t("mapping.media_key", "Media key")}
        value={entry.param2}
        options={envelope.mediaControls}
        disabled={disabled}
        onChange={(value) => onChange({ ...entry, param2: value })}
        t={t}
      />
    )
  }

  return <p className="text-sm text-muted-foreground">{t("mapping.no_parameters", "No parameters.")}</p>
}
