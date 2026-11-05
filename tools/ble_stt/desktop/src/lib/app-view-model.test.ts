import { describe, expect, it } from "vitest"

import {
  commandReasonLabel,
  diagnosticDetail,
  modelStateLabel,
  performanceValueLabel,
  recentActivity,
} from "@/lib/app-view-model"
import type { StatusPayload, StructuredLogEntry } from "@/lib/helper-api"
import { createTranslator } from "@/lib/i18n"

const zh = createTranslator("zh-CN")

const status = {
  overall: { code: "ready", label: "ready", ready: true },
  service: { installed: true, running: true, error: null, paused: false, pause_reason: null },
  voice: { ready: false, runtime_ok: true, message: "waiting for voice service" },
  watch: { paired: true, connected: false, id: "watch-id", label: "M5StopWatch" },
  model: { selected: "small", state: "ready", installed: true },
  permissions: {
    input: { ok: true, message: "kAXTrustedCheckOptionPrompt" },
    bluetooth: { ok: false, message: "CBManagerAuthorizationDenied" },
  },
  logs: { directory: "/tmp/m5stopwatch", latest_event: null },
} as StatusPayload

describe("localized presentation", () => {
  it("maps internal model and command states", () => {
    expect(modelStateLabel("ready", zh)).toBe("已就绪")
    expect(commandReasonLabel("score_too_low", zh)).toBe("相似度不足")
    expect(commandReasonLabel("no_match", zh)).toBe("未匹配")
  })

  it("does not expose raw helper messages in diagnostic summaries", () => {
    expect(diagnosticDetail(status, "voice", zh)).toBe("准备中")
    expect(diagnosticDetail(status, "input", zh)).toBe("已授权")
    expect(diagnosticDetail(status, "bluetooth", zh)).toBe("需要授权")
  })

  it("localizes performance identifiers", () => {
    expect(performanceValueLabel("lane", "recognition", zh)).toBe("识别")
    expect(performanceValueLabel("stage", "final_stt", zh)).toBe("最终识别")
    expect(performanceValueLabel("category", "intentional", zh)).toBe("设定延迟")
  })

  it("localizes recent activity derived from raw logs", () => {
    const entries: StructuredLogEntry[] = [
      {
        source: "service.log",
        time: "2026-07-28 12:00:00.000",
        level: "INFO",
        component: "ble",
        context: "main",
        message: "[BLE] connected mtu=247",
      },
    ]
    expect(recentActivity(entries, zh)[0]).toMatchObject({
      label: "已连接",
      detail: "手表已连接。",
    })
  })
})
