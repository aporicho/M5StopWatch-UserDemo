import { afterEach, describe, expect, it, vi } from "vitest"

import { AutoSaveQueue, type AutoSaveState } from "@/lib/auto-save"

afterEach(() => vi.useRealTimers())

describe("AutoSaveQueue", () => {
  it("debounces edits and saves only the latest value", async () => {
    vi.useFakeTimers()
    let value = "first"
    const states: AutoSaveState[] = []
    const save = vi.fn(async (next: string) => next)
    const queue = new AutoSaveQueue({
      delayMs: 500,
      read: () => value,
      save,
      onSaved: (saved) => { value = saved },
      onStateChange: (state) => states.push(state),
      onError: vi.fn(),
    })

    queue.changed()
    value = "latest"
    queue.changed()
    await vi.advanceTimersByTimeAsync(499)
    expect(save).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(save).toHaveBeenCalledOnce()
    expect(save).toHaveBeenCalledWith("latest")
    expect(states).toContain("saving")
    expect(states).toContain("saved")
  })

  it("serializes an edit made while saving", async () => {
    let value = "one"
    let releaseFirst!: () => void
    const save = vi.fn((next: string) => new Promise<string>((resolve) => {
      if (next === "one") releaseFirst = () => resolve(next)
      else resolve(next)
    }))
    const queue = new AutoSaveQueue({
      delayMs: 500,
      read: () => value,
      save,
      onSaved: vi.fn(),
      onStateChange: vi.fn(),
      onError: vi.fn(),
    })

    queue.changed()
    const first = queue.flush()
    await Promise.resolve()
    expect(save).toHaveBeenCalledWith("one")
    value = "two"
    queue.changed()
    const second = queue.flush()
    releaseFirst()
    await expect(first).resolves.toBe(true)
    await expect(second).resolves.toBe(true)
    expect(save.mock.calls.map(([next]) => next)).toEqual(["one", "two"])
  })

  it("keeps changes retryable after a failure", async () => {
    const states: AutoSaveState[] = []
    const save = vi.fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce("value")
    const queue = new AutoSaveQueue({
      delayMs: 500,
      read: () => "value",
      save,
      onSaved: vi.fn(),
      onStateChange: (state) => states.push(state),
      onError: vi.fn(),
    })

    queue.changed()
    await expect(queue.flush()).resolves.toBe(false)
    await expect(queue.flush()).resolves.toBe(true)
    expect(states).toContain("error")
    expect(save).toHaveBeenCalledTimes(2)
  })
})
