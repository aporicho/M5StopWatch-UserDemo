export type AutoSaveState = "idle" | "pending" | "saving" | "saved" | "error"

type TimerHandle = ReturnType<typeof setTimeout>

type AutoSaveQueueOptions<T> = {
  delayMs: number
  savedStateMs?: number
  read: () => T | null
  save: (value: T) => Promise<T>
  onSaved: (value: T) => void
  onStateChange: (state: AutoSaveState) => void
  onError: (error: unknown) => void
}

export class AutoSaveQueue<T> {
  private revision = 0
  private savedRevision = 0
  private timer: TimerHandle | null = null
  private savedStateTimer: TimerHandle | null = null
  private chain: Promise<void> = Promise.resolve()

  constructor(private readonly options: AutoSaveQueueOptions<T>) {}

  changed() {
    this.revision += 1
    this.options.onStateChange("pending")
    this.clearTimer()
    this.timer = setTimeout(() => {
      this.timer = null
      void this.flush()
    }, this.options.delayMs)
  }

  flush() {
    this.clearTimer()
    const run = async () => {
      const value = this.options.read()
      const revision = this.revision
      if (!value || this.savedRevision >= revision) return true

      this.options.onStateChange("saving")
      try {
        const saved = await this.options.save(value)
        this.savedRevision = revision
        if (this.revision === revision) {
          this.options.onSaved(saved)
          this.options.onStateChange("saved")
          this.clearSavedStateTimer()
          this.savedStateTimer = setTimeout(() => {
            this.savedStateTimer = null
            this.options.onStateChange("idle")
          }, this.options.savedStateMs ?? 1200)
        } else {
          this.options.onStateChange("pending")
        }
        return true
      } catch (error) {
        this.options.onStateChange("error")
        this.options.onError(error)
        return false
      }
    }

    const queued = this.chain.then(run, run)
    this.chain = queued.then(() => undefined)
    return queued
  }

  synchronize() {
    this.savedRevision = this.revision
    this.clearTimer()
    this.clearSavedStateTimer()
    this.options.onStateChange("idle")
  }

  dispose() {
    this.clearTimer()
    this.clearSavedStateTimer()
  }

  private clearTimer() {
    if (this.timer !== null) {
      clearTimeout(this.timer)
      this.timer = null
    }
  }

  private clearSavedStateTimer() {
    if (this.savedStateTimer !== null) {
      clearTimeout(this.savedStateTimer)
      this.savedStateTimer = null
    }
  }
}
