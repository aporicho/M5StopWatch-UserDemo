import { describe, expect, it } from "vitest"

import { createTranslator, translations } from "@/lib/i18n"

describe("translations", () => {
  it("keeps English and Chinese keys in sync", () => {
    expect(Object.keys(translations["zh-CN"]).sort()).toEqual(Object.keys(translations.en).sort())
  })

  it("uses product language for the Chinese shell", () => {
    const t = createTranslator("zh-CN")
    expect(t("nav.map")).toBe("手势")
    expect(t("diagnostics.overview")).toBe("概览")
    expect(t("common.open_system_settings")).toBe("打开系统设置")
  })
})
