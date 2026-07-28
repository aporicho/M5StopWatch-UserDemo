import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { MappingPage } from "@/features/mapping/mapping-page"
import { DeleteModelDialog } from "@/features/settings/delete-model-dialog"
import { PermissionPanel } from "@/features/settings/permission-panel"
import type { MappingEnvelope, StatusPayload } from "@/lib/helper-api"
import { createTranslator } from "@/lib/i18n"

const en = createTranslator("en")
const zh = createTranslator("zh-CN")

const mapping: MappingEnvelope = {
  ok: true,
  schema: 1,
  mapping: { schema: 1, revision: 1, updated_at: null, entries: [] },
  events: [{ id: "button.left.tap", code: 1, label: "Left tap" }],
  actions: [{ id: "none", code: 0, label: "None" }],
  keyOptions: [],
  modifierOptions: [],
  mouseButtons: [],
  mediaControls: [],
}

describe("desktop UI workflows", () => {
  it("saves a gesture from its editor sheet", async () => {
    const onSaveEntry = vi.fn().mockResolvedValue(true)
    render(
      <MappingPage
        envelope={mapping}
        entries={[]}
        busyAction={null}
        refreshing={false}
        onSaveEntry={onSaveEntry}
        onReset={vi.fn()}
        t={en}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: "Edit" }))
    fireEvent.click(screen.getByRole("button", { name: "Save" }))
    await waitFor(() => expect(onSaveEntry).toHaveBeenCalledOnce())
    expect(screen.getByRole("dialog")).toHaveAttribute("data-closed")
  })

  it("shows permission actions only when permission is missing", () => {
    const requestPermission = vi.fn()
    const status = {
      permissions: {
        bluetooth: { ok: true, message: "raw bluetooth status" },
        input: { ok: false, message: "kAXTrustedCheckOptionPrompt" },
      },
    } as StatusPayload

    render(
      <PermissionPanel
        status={status}
        busyAction={null}
        requestPermission={requestPermission}
        t={zh}
      />
    )

    expect(screen.getByText("已授权")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "打开系统设置" })).toBeInTheDocument()
    expect(screen.queryByText("kAXTrustedCheckOptionPrompt")).not.toBeInTheDocument()
  })

  it("localizes the model deletion confirmation", () => {
    render(
      <DeleteModelDialog
        open
        activeModel="small"
        onOpenChange={vi.fn()}
        onDelete={vi.fn()}
        t={zh}
      />
    )

    expect(screen.getByRole("heading", { name: "删除模型？" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "删除模型" })).toBeInTheDocument()
  })
})
