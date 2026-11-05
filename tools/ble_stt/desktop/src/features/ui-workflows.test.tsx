import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { MappingPage } from "@/features/mapping/mapping-page"
import { ModelOperationProgress } from "@/components/common/model-operation-progress"
import { DeleteModelDialog } from "@/features/settings/delete-model-dialog"
import { PermissionPanel } from "@/features/settings/permission-panel"
import type {
  MappingEnvelope,
  ModelOperationProgress as ModelOperation,
  StatusPayload,
} from "@/lib/helper-api"
import { createTranslator } from "@/lib/i18n"

const en = createTranslator("en")
const zh = createTranslator("zh-CN")

afterEach(() => cleanup())

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

  it("shows real model download progress and allows cancellation", () => {
    const onCancel = vi.fn()
    const operation: ModelOperation = {
      schema: 1,
      id: "operation-1",
      kind: "speech",
      action: "install",
      model: "medium",
      phase: "downloading",
      component: "model",
      downloaded_bytes: 50 * 1024 * 1024,
      total_bytes: 100 * 1024 * 1024,
      percent: 50,
      cancellable: true,
      updated_at: 1,
    }

    render(<ModelOperationProgress operation={operation} onCancel={onCancel} t={zh} />)

    expect(screen.getByText("正在下载模型…")).toBeInTheDocument()
    expect(screen.getByText("50%")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "取消" }))
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it("does not offer cancellation while verifying", () => {
    const operation: ModelOperation = {
      schema: 1,
      id: "operation-1",
      kind: "correction",
      action: "repair",
      model: "lite",
      phase: "verifying",
      component: "model",
      downloaded_bytes: 100,
      total_bytes: 100,
      percent: 100,
      cancellable: false,
      updated_at: 1,
    }

    render(<ModelOperationProgress operation={operation} onCancel={vi.fn()} t={zh} />)

    expect(screen.getByText("正在校验文件…")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "取消" })).not.toBeInTheDocument()
  })
})
