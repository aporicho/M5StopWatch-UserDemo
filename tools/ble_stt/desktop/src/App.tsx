import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { AppShell } from "@/components/common/app-shell"
import { toast } from "@/components/ui/toast"
import { CommandPage } from "@/features/commands/command-page"
import { DiagnosticsSheet } from "@/features/diagnostics/diagnostics-sheet"
import { HomePage } from "@/features/home/home-page"
import { MappingPage } from "@/features/mapping/mapping-page"
import { DeleteModelDialog } from "@/features/settings/delete-model-dialog"
import { SettingsSheet } from "@/features/settings/settings-sheet"
import { useSystemTheme } from "@/hooks/use-system-theme"
import {
  MODEL_OPTIONS,
  type Notice,
  type PageKey,
  actionTitle,
  commandHistory,
  deriveDailyState,
  dictationHistory,
  errorMessage,
  localizedDailyState,
  modelDetail,
  modelDisplayLabel,
  recentActivity,
  telemetryRenderKey,
} from "@/lib/app-view-model"
import {
  formatBytes,
  clearPerformance,
  helperCommands,
  helperLogs,
  helperMappings,
  helperPerformance,
  helperStatus,
  helperTelemetry,
  invokeCorrectionModelAction,
  invokeModelAction,
  invokeServiceAction,
  LOG_LINES,
  MODEL_IDS,
  modelActionMessage,
  modelBlocksServiceStart,
  openLogsFolder,
  openPermissionPanel,
  POLL_MS,
  resetCommands,
  resetMappings,
  saveVoiceSettings,
  saveCommands,
  saveMappings,
  serviceNeedsInputPermissionRestart,
  SERVICE_SETTLE_MS,
  sleep,
  structuredLogEntry,
  TELEMETRY_POLL_MS,
  type CommandEntry,
  type CorrectionModelAction,
  type CommandEnvelope,
  type LogsEnvelope,
  type MappingEntry,
  type MappingEnvelope,
  type PerformanceSnapshot,
  type ModelAction,
  type PermissionKind,
  type ServiceAction,
  type StatusEnvelope,
  type TelemetryEnvelope,
  type VoicePreferences,
} from "@/lib/helper-api"
import {
  LANGUAGE_OPTIONS,
  createTranslator,
  detectInitialLanguage,
  persistLanguage,
  type LanguageCode,
} from "@/lib/i18n"

const DICTATION_HISTORY_CUTOFF_KEY = "m5stopwatch.history.dictation.clearedAt"
const COMMAND_HISTORY_CUTOFF_KEY = "m5stopwatch.history.command.clearedAt"

function historyCutoff(key: string) {
  const value = Number(window.localStorage.getItem(key) ?? 0)
  return Number.isFinite(value) ? value : 0
}

function App() {
  useSystemTheme()

  const [statusEnvelope, setStatusEnvelope] = useState<StatusEnvelope | null>(null)
  const [logsEnvelope, setLogsEnvelope] = useState<LogsEnvelope | null>(null)
  const [telemetryEnvelope, setTelemetryEnvelope] = useState<TelemetryEnvelope | null>(null)
  const [performance, setPerformance] = useState<PerformanceSnapshot | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [selectedModel, setSelectedModel] = useState<string>("small")
  const [modelSelectionTouched, setModelSelectionTouched] = useState(false)
  const [selectedCorrectionModel, setSelectedCorrectionModel] = useState<string>("lite")
  const [correctionModelSelectionTouched, setCorrectionModelSelectionTouched] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [autoFollowLogs, setAutoFollowLogs] = useState(true)
  const [page, setPage] = useState<PageKey>("home")
  const [language, setLanguage] = useState<LanguageCode>(() => detectInitialLanguage())
  const [mappingEnvelope, setMappingEnvelope] = useState<MappingEnvelope | null>(null)
  const [mappingEntries, setMappingEntries] = useState<MappingEntry[]>([])
  const [mappingTouched, setMappingTouched] = useState(false)
  const [mappingRefreshing, setMappingRefreshing] = useState(false)
  const [commandEnvelope, setCommandEnvelope] = useState<CommandEnvelope | null>(null)
  const [commandEntries, setCommandEntries] = useState<CommandEntry[]>([])
  const [commandRefreshing, setCommandRefreshing] = useState(false)
  const [voicePreferences, setVoicePreferences] = useState<VoicePreferences | null>(null)
  const [voiceSettingsTouched, setVoiceSettingsTouched] = useState(false)
  const [dictationHistoryClearedAt, setDictationHistoryClearedAt] = useState(() =>
    historyCutoff(DICTATION_HISTORY_CUTOFF_KEY)
  )
  const [commandHistoryClearedAt, setCommandHistoryClearedAt] = useState(() =>
    historyCutoff(COMMAND_HISTORY_CUTOFF_KEY)
  )

  const latestStatusRef = useRef<StatusEnvelope | null>(null)
  const latestLogsRef = useRef<LogsEnvelope | null>(null)
  const latestTelemetryRef = useRef<TelemetryEnvelope | null>(null)
  const latestMappingRef = useRef<MappingEnvelope | null>(null)
  const latestCommandRef = useRef<CommandEnvelope | null>(null)
  const latestTelemetryRenderKeyRef = useRef("")
  const permissionRestartInFlight = useRef(false)
  const logEndRef = useRef<HTMLDivElement | null>(null)

  const status = statusEnvelope?.status ?? null
  const telemetry = telemetryEnvelope?.telemetry ?? null
  const currentModel = status?.model ?? null
  const currentCorrectionModel = status?.correction_model ?? null
  const controlsDisabled = busyAction !== null
  const activeModel = selectedModel || currentModel?.selected || "small"
  const activeCorrectionModel =
    selectedCorrectionModel || currentCorrectionModel?.model || "lite"
  const isCurrentModel = activeModel === currentModel?.selected
  const t = useMemo(() => createTranslator(language), [language])
  const languageItems = useMemo(
    () => LANGUAGE_OPTIONS.map((option) => ({ label: option.label, value: option.value })),
    []
  )

  const logEntries = useMemo(
    () => logsEnvelope?.logs.entries.map(structuredLogEntry) ?? [],
    [logsEnvelope]
  )

  const rawDailyState = useMemo(
    () => deriveDailyState(status, logEntries, telemetry),
    [status, logEntries, telemetry]
  )
  const dailyState = useMemo(() => localizedDailyState(rawDailyState, t), [rawDailyState, t])

  const dictations = useMemo(
    () => dictationHistory(logEntries, telemetry, dictationHistoryClearedAt),
    [dictationHistoryClearedAt, logEntries, telemetry]
  )
  const commands = useMemo(
    () => commandHistory(logEntries, telemetry, commandHistoryClearedAt),
    [commandHistoryClearedAt, logEntries, telemetry]
  )
  const activity = useMemo(() => recentActivity(logEntries), [logEntries])

  const modelItems = useMemo(() => {
    const items: Array<{ label: string; value: string }> = MODEL_OPTIONS.map((model) => ({
      label: modelDisplayLabel(model.value, t),
      value: model.value,
    }))
    const known = new Set<string>(MODEL_IDS)
    for (const value of [currentModel?.selected, selectedModel]) {
      if (value && !known.has(value)) {
        known.add(value)
        items.push({ label: modelDisplayLabel(value, t), value })
      }
    }
    return items
  }, [currentModel?.selected, selectedModel, t])

  const selectedModelDetail = useMemo(
    () => modelDetail(activeModel, t),
    [activeModel, t]
  )

  const correctionModelItems = useMemo(() => {
    const models = status?.correction_models ?? []
    if (models.length > 0) {
      return models.map((model) => ({
        label: `${model.label} · ${formatBytes(model.status.expected_disk_bytes)}`,
        value: model.id,
      }))
    }
    return currentCorrectionModel
      ? [{ label: currentCorrectionModel.display_name, value: currentCorrectionModel.model }]
      : [{ label: "Qwen3.5-0.8B Q4 · 537.0 MB", value: "lite" }]
  }, [currentCorrectionModel, status?.correction_models])

  const activeCorrectionModelStatus = useMemo(
    () =>
      status?.correction_models?.find((model) => model.id === activeCorrectionModel)
        ?.status ?? currentCorrectionModel,
    [activeCorrectionModel, currentCorrectionModel, status?.correction_models]
  )

  const applySnapshots = useCallback(
    (nextStatus: StatusEnvelope, nextLogs: LogsEnvelope, nextTelemetry?: TelemetryEnvelope | null) => {
      latestStatusRef.current = nextStatus
      latestLogsRef.current = nextLogs
      setStatusEnvelope(nextStatus)
      setLogsEnvelope(nextLogs)
      if (nextTelemetry) {
        latestTelemetryRef.current = nextTelemetry
        latestTelemetryRenderKeyRef.current = telemetryRenderKey(nextTelemetry)
        setTelemetryEnvelope(nextTelemetry)
      }
      setLastUpdated(new Date())
    },
    []
  )

  const applyMappingSnapshot = useCallback((nextMapping: MappingEnvelope) => {
    latestMappingRef.current = nextMapping
    setMappingEnvelope(nextMapping)
    setMappingEntries(nextMapping.mapping.entries)
    setMappingTouched(false)
  }, [])

  const applyCommandSnapshot = useCallback((nextCommands: CommandEnvelope) => {
    latestCommandRef.current = nextCommands
    setCommandEnvelope(nextCommands)
    setCommandEntries(nextCommands.commands.entries)
  }, [])

  const showNotice = useCallback(
    (
      message: string,
      level: Notice["level"] = "info",
      toastType?: "success" | "info" | "warning" | "error"
    ) => {
      setNotice({ level, message })
      if (toastType) {
        toast.add({
          title: level === "error" ? t("notice.action_failed", "Action failed") : "M5StopWatch",
          description: message,
          type: toastType,
        })
      }
    },
    [t]
  )

  const refreshMappings = useCallback(
    async ({ notifyErrors = false }: { notifyErrors?: boolean } = {}) => {
      setMappingRefreshing(true)
      try {
        const payload = await helperMappings()
        applyMappingSnapshot(payload)
      } catch (error) {
        showNotice(errorMessage(error), "error", notifyErrors ? "error" : undefined)
      } finally {
        setMappingRefreshing(false)
      }
    },
    [applyMappingSnapshot, showNotice]
  )

  const refreshCommands = useCallback(
    async ({ notifyErrors = false }: { notifyErrors?: boolean } = {}) => {
      setCommandRefreshing(true)
      try {
        const payload = await helperCommands()
        applyCommandSnapshot(payload)
      } catch (error) {
        showNotice(errorMessage(error), "error", notifyErrors ? "error" : undefined)
      } finally {
        setCommandRefreshing(false)
      }
    },
    [applyCommandSnapshot, showNotice]
  )

  const restartAfterInputPermissionGrant = useCallback(
    async (snapshot: StatusEnvelope) => {
      if (
        !serviceNeedsInputPermissionRestart(snapshot.status) ||
        permissionRestartInFlight.current
      ) {
        return false
      }

      permissionRestartInFlight.current = true
      try {
        showNotice("input permission granted; restarting service", "info")
        const payload = await invokeServiceAction("restart")
        showNotice(
          payload.message,
          payload.ok ? "info" : "error",
          payload.ok ? "success" : "error"
        )
        if (payload.ok) {
          await sleep(SERVICE_SETTLE_MS)
          const [nextStatus, nextLogs, nextTelemetry] = await Promise.all([
            helperStatus(),
            helperLogs(LOG_LINES),
            helperTelemetry().catch(() => null),
          ])
          applySnapshots(nextStatus, nextLogs, nextTelemetry)
        }
        return payload.ok
      } finally {
        permissionRestartInFlight.current = false
      }
    },
    [applySnapshots, showNotice]
  )

  const refreshAll = useCallback(
    async ({
      clearNotice = false,
      notifyErrors = false,
      showBusy = false,
    }: {
      clearNotice?: boolean
      notifyErrors?: boolean
      showBusy?: boolean
    } = {}) => {
      if (showBusy) {
        setRefreshing(true)
      }
      try {
        const [nextStatus, nextLogs, nextTelemetry] = await Promise.all([
          helperStatus(),
          helperLogs(LOG_LINES),
          helperTelemetry().catch(() => null),
        ])
        applySnapshots(nextStatus, nextLogs, nextTelemetry)
        const restarted = await restartAfterInputPermissionGrant(nextStatus)
        if (!restarted && clearNotice) {
          setNotice(null)
        }
      } catch (error) {
        showNotice(errorMessage(error), "error", notifyErrors ? "error" : undefined)
      } finally {
        if (showBusy) {
          setRefreshing(false)
        }
      }
    },
    [applySnapshots, restartAfterInputPermissionGrant, showNotice]
  )

  const refreshTelemetry = useCallback(async () => {
    try {
      const nextTelemetry = await helperTelemetry()
      const key = telemetryRenderKey(nextTelemetry)
      latestTelemetryRef.current = nextTelemetry
      if (key === latestTelemetryRenderKeyRef.current) {
        return
      }
      latestTelemetryRenderKeyRef.current = key
      setTelemetryEnvelope(nextTelemetry)
    } catch {
      // Telemetry is an enhancement; status/log polling remains authoritative.
    }
  }, [])

  const refreshPerformance = useCallback(async () => {
    try {
      const payload = await helperPerformance()
      setPerformance(payload.performance)
    } catch {
      // Performance history is diagnostic-only and must not affect voice operation.
    }
  }, [])

  const clearPerformanceHistory = useCallback(async () => {
    setBusyAction("performance-clear")
    try {
      const payload = await clearPerformance()
      setPerformance(payload.performance)
      showNotice(t("performance.cleared", "Performance history cleared."), "info", "success")
    } catch (error) {
      showNotice(errorMessage(error), "error", "error")
    } finally {
      setBusyAction(null)
    }
  }, [showNotice, t])

  useEffect(() => {
    void refreshAll({ notifyErrors: true })
    const timer = window.setInterval(() => {
      void refreshAll()
    }, POLL_MS)

    return () => window.clearInterval(timer)
  }, [refreshAll])

  useEffect(() => {
    void refreshMappings({ notifyErrors: true })
  }, [refreshMappings])

  useEffect(() => {
    void refreshCommands({ notifyErrors: true })
  }, [refreshCommands])

  useEffect(() => {
    void refreshTelemetry()
    const timer = window.setInterval(() => {
      void refreshTelemetry()
    }, TELEMETRY_POLL_MS)

    return () => window.clearInterval(timer)
  }, [refreshTelemetry])

  useEffect(() => {
    if (diagnosticsOpen) {
      void refreshPerformance()
    }
  }, [diagnosticsOpen, refreshPerformance, telemetry?.performance?.revision])

  useEffect(() => {
    const current = currentModel?.selected
    if (current && !modelSelectionTouched) {
      setSelectedModel(current)
    }
  }, [currentModel?.selected, modelSelectionTouched])

  useEffect(() => {
    const current = currentCorrectionModel?.model
    if (current && !correctionModelSelectionTouched) {
      setSelectedCorrectionModel(current)
    }
  }, [correctionModelSelectionTouched, currentCorrectionModel?.model])

  useEffect(() => {
    if (!voiceSettingsTouched && status?.preferences) {
      setVoicePreferences(status.preferences)
    }
  }, [status?.preferences, voiceSettingsTouched])

  useEffect(() => {
    persistLanguage(language)
  }, [language])

  useEffect(() => {
    if (!autoFollowLogs || !diagnosticsOpen) {
      return
    }
    window.requestAnimationFrame(() => {
      logEndRef.current?.scrollIntoView({ block: "end" })
    })
  }, [autoFollowLogs, diagnosticsOpen, logEntries.length, logsEnvelope])

  const runServiceAction = useCallback(
    async (action: ServiceAction) => {
      setBusyAction(`service:${action}`)
      try {
        const payload = await invokeServiceAction(action)
        showNotice(
          payload.message,
          payload.ok ? "info" : "error",
          payload.ok ? "success" : "error"
        )
        if (payload.ok && ["install", "start", "restart"].includes(action)) {
          await sleep(SERVICE_SETTLE_MS)
        }
        await refreshAll({ notifyErrors: true })
      } catch (error) {
        showNotice(errorMessage(error), "error", "error")
      } finally {
        setBusyAction(null)
      }
    },
    [refreshAll, showNotice]
  )

  const runModelAction = useCallback(
    async (action: ModelAction) => {
      const model = activeModel
      if (!model) {
        return
      }

      setBusyAction(`model:${action}`)
      try {
        const serviceWasRunning = Boolean(latestStatusRef.current?.status.service.running)
        const serviceWasInstalled = Boolean(latestStatusRef.current?.status.service.installed)

        showNotice(`${actionTitle(action)} ${model}`, "info")
        const payload = await invokeModelAction(action, model)
        showNotice(
          modelActionMessage(payload),
          payload.ok ? "info" : "error",
          payload.ok ? "success" : "error"
        )

        if (payload.ok && action === "use") {
          setModelSelectionTouched(false)
        }

        if (payload.ok && action === "use" && serviceWasInstalled) {
          showNotice("model changed; updating service", "info")
          const install = await invokeServiceAction("install")
          showNotice(
            install.message,
            install.ok ? "info" : "error",
            install.ok ? "success" : "error"
          )
          if (install.ok) {
            await sleep(SERVICE_SETTLE_MS)
            if (!serviceWasRunning) {
              const stop = await invokeServiceAction("stop")
              showNotice(
                stop.message,
                stop.ok ? "info" : "error",
                stop.ok ? "success" : "error"
              )
            }
          }
        } else if (
          payload.ok &&
          serviceWasRunning &&
          ["update", "repair"].includes(action)
        ) {
          showNotice("model changed; restarting service", "info")
          const restart = await invokeServiceAction("restart")
          showNotice(
            restart.message,
            restart.ok ? "info" : "error",
            restart.ok ? "success" : "error"
          )
          if (restart.ok) {
            await sleep(SERVICE_SETTLE_MS)
          }
        }

        await refreshAll({ notifyErrors: true })
      } catch (error) {
        showNotice(errorMessage(error), "error", "error")
      } finally {
        setBusyAction(null)
      }
    },
    [activeModel, refreshAll, showNotice]
  )

  const changeVoicePreferences = useCallback((preferences: VoicePreferences) => {
    setVoicePreferences(preferences)
    setVoiceSettingsTouched(true)
  }, [])

  const saveCurrentVoiceSettings = useCallback(async () => {
    if (!voicePreferences) return
    setBusyAction("voice-settings:save")
    try {
      const payload = await saveVoiceSettings(voicePreferences)
      if (!payload.ok) throw new Error(payload.message || "could not save voice settings")
      setVoicePreferences(payload.settings)
      setVoiceSettingsTouched(false)
      showNotice(
        t("settings.voice_settings_saved", "Voice settings saved. They apply to the next dictation."),
        "info",
        "success"
      )
      await refreshAll({ notifyErrors: true })
    } catch (error) {
      showNotice(errorMessage(error), "error", "error")
    } finally {
      setBusyAction(null)
    }
  }, [refreshAll, showNotice, t, voicePreferences])

  const runCorrectionModelAction = useCallback(
    async (action: CorrectionModelAction) => {
      const model = activeCorrectionModel
      if (!model) return
      setBusyAction(`correction-model:${action}`)
      const serviceWasRunning = Boolean(latestStatusRef.current?.status.service.running)
      try {
        if (serviceWasRunning) {
          const stop = await invokeServiceAction("stop")
          if (!stop.ok) throw new Error(stop.message)
        }
        const payload = await invokeCorrectionModelAction(action, model)
        if (!payload.ok) throw new Error(payload.message || payload.correction_model.message)
        setVoicePreferences(payload.settings)
        setVoiceSettingsTouched(false)
        if (action === "use-model") {
          setCorrectionModelSelectionTouched(false)
        }
        showNotice(payload.correction_model.message, "info", "success")
      } catch (error) {
        showNotice(errorMessage(error), "error", "error")
      } finally {
        if (serviceWasRunning) {
          try {
            await invokeServiceAction("start")
            await sleep(SERVICE_SETTLE_MS)
          } catch (error) {
            showNotice(errorMessage(error), "error", "error")
          }
        }
        await refreshAll({ notifyErrors: true })
        setBusyAction(null)
      }
    },
    [activeCorrectionModel, refreshAll, showNotice]
  )

  const requestPermission = useCallback(
    async (kind: PermissionKind) => {
      setBusyAction(`permission:${kind}`)
      try {
        const payload = await openPermissionPanel(kind)
        showNotice(
          payload.message,
          payload.ok ? "info" : "error",
          payload.ok ? "success" : "error"
        )
        if (
          payload.ok &&
          kind === "input" &&
          latestStatusRef.current?.status.service.running
        ) {
          showNotice("input permission granted; restarting service", "info")
          const restart = await invokeServiceAction("restart")
          showNotice(
            restart.message,
            restart.ok ? "info" : "error",
            restart.ok ? "success" : "error"
          )
          if (restart.ok) {
            await sleep(SERVICE_SETTLE_MS)
          }
        }
        await refreshAll({ notifyErrors: true })
      } catch (error) {
        showNotice(errorMessage(error), "error", "error")
      } finally {
        setBusyAction(null)
      }
    },
    [refreshAll, showNotice]
  )

  const updateMappingEntry = useCallback((entry: MappingEntry) => {
    setMappingEntries((currentEntries) => {
      const nextEntry = {
        ...entry,
        flags: entry.flags ?? 0,
      }
      const index = currentEntries.findIndex((item) => item.event === nextEntry.event)
      if (index === -1) {
        return [...currentEntries, nextEntry]
      }
      const nextEntries = [...currentEntries]
      nextEntries[index] = nextEntry
      return nextEntries
    })
    setMappingTouched(true)
  }, [])

  const saveEventMappings = useCallback(async () => {
    setBusyAction("mapping:save")
    try {
      const payload = await saveMappings(mappingEntries)
      applyMappingSnapshot(payload)
      showNotice("event map saved", "info", "success")
    } catch (error) {
      showNotice(errorMessage(error), "error", "error")
    } finally {
      setBusyAction(null)
    }
  }, [applyMappingSnapshot, mappingEntries, showNotice])

  const resetEventMappings = useCallback(async () => {
    setBusyAction("mapping:reset")
    try {
      const payload = await resetMappings()
      applyMappingSnapshot(payload)
      showNotice("event map reset", "info", "success")
    } catch (error) {
      showNotice(errorMessage(error), "error", "error")
    } finally {
      setBusyAction(null)
    }
  }, [applyMappingSnapshot, showNotice])

  const saveCommandMappings = useCallback(async (nextEntries: CommandEntry[]) => {
    setBusyAction("commands:save")
    try {
      const payload = await saveCommands(nextEntries)
      applyCommandSnapshot(payload)
      showNotice("commands saved", "info", "success")
      return true
    } catch (error) {
      showNotice(errorMessage(error), "error", "error")
      return false
    } finally {
      setBusyAction(null)
    }
  }, [applyCommandSnapshot, showNotice])

  const resetCommandMappings = useCallback(async () => {
    setBusyAction("commands:reset")
    try {
      const payload = await resetCommands()
      applyCommandSnapshot(payload)
      showNotice("commands reset", "info", "success")
    } catch (error) {
      showNotice(errorMessage(error), "error", "error")
    } finally {
      setBusyAction(null)
    }
  }, [applyCommandSnapshot, showNotice])

  const openLogs = useCallback(async () => {
    setBusyAction("logs")
    try {
      await openLogsFolder()
    } catch (error) {
      showNotice(errorMessage(error), "error", "error")
    } finally {
      setBusyAction(null)
    }
  }, [showNotice])

  const copyDiagnostics = useCallback(async () => {
    setBusyAction("diagnostics")
    try {
      const snapshotStatus = latestStatusRef.current ?? (await helperStatus())
      const snapshotLogs = latestLogsRef.current ?? (await helperLogs(LOG_LINES))
      const snapshotTelemetry =
        latestTelemetryRef.current ?? (await helperTelemetry().catch(() => null))
      const snapshotMapping =
        latestMappingRef.current ?? (await helperMappings().catch(() => null))
      const snapshotCommands =
        latestCommandRef.current ?? (await helperCommands().catch(() => null))
      const snapshotPerformance = performance ?? (await helperPerformance().then((value) => value.performance).catch(() => null))
      await navigator.clipboard.writeText(
        JSON.stringify(
          {
            generated_at: new Date().toISOString(),
            status: snapshotStatus,
            telemetry: snapshotTelemetry,
            mapping: snapshotMapping,
            commands: snapshotCommands,
            performance: snapshotPerformance,
            logs: snapshotLogs,
          },
          null,
          2
        )
      )
      showNotice("diagnostics copied", "info", "success")
    } catch (error) {
      showNotice(errorMessage(error), "error", "error")
    } finally {
      setBusyAction(null)
    }
  }, [performance, showNotice])

  const modelInstalled = Boolean(currentModel?.installed)
  const deleteModelDisabled =
    controlsDisabled ||
    !currentModel ||
    !isCurrentModel ||
    !modelInstalled ||
    currentModel.source === "bundled" ||
    Boolean(status?.service.running)
  const installModelDisabled =
    controlsDisabled || !activeModel || (isCurrentModel && modelInstalled)
  const updateModelDisabled =
    controlsDisabled ||
    !currentModel ||
    !isCurrentModel ||
    !currentModel.update_available
  const repairModelDisabled =
    controlsDisabled || !currentModel || !isCurrentModel || !modelInstalled
  const useModelDisabled = controlsDisabled || !activeModel || isCurrentModel
  const serviceModelBlocked = currentModel ? modelBlocksServiceStart(currentModel) : true

  const handleDailyAction = useCallback(() => {
    switch (dailyState.action) {
      case "start":
        void runServiceAction("start")
        break
      case "retry":
        void runServiceAction("restart")
        break
      case "install-model":
        void runModelAction("install")
        break
      case "request-bluetooth":
        void requestPermission("bluetooth")
        break
      case "request-input":
        void requestPermission("input")
        break
      case "diagnostics":
        setDiagnosticsOpen(true)
        break
    }
  }, [dailyState.action, requestPermission, runModelAction, runServiceAction])

  const clearDictationHistory = useCallback(() => {
    const cutoff = Date.now() / 1000
    window.localStorage.setItem(DICTATION_HISTORY_CUTOFF_KEY, String(cutoff))
    setDictationHistoryClearedAt(cutoff)
  }, [])

  const clearCommandHistory = useCallback(() => {
    const cutoff = Date.now() / 1000
    window.localStorage.setItem(COMMAND_HISTORY_CUTOFF_KEY, String(cutoff))
    setCommandHistoryClearedAt(cutoff)
  }, [])

  const primaryActionLabel: Record<NonNullable<typeof dailyState.action>, string> = {
    start: t("action.start_voice", "Start voice"),
    retry: t("action.retry_link", "Retry link"),
    "install-model": t("action.install_model", "Install model"),
    "request-bluetooth": t("action.allow_bluetooth", "Allow Bluetooth"),
    "request-input": t("action.allow_text_input", "Allow text input"),
    diagnostics: t("action.open_diagnostics", "Open diagnostics"),
  }

  return (
    <>
      <AppShell
        page={page}
        dailyState={dailyState}
        notice={notice}
        busyAction={busyAction}
        refreshing={refreshing}
        onPageChange={setPage}
        onRefresh={() => void refreshAll({ clearNotice: true, notifyErrors: true, showBusy: true })}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenDiagnostics={() => setDiagnosticsOpen(true)}
        t={t}
      >
        {page === "home" ? (
          <HomePage
            state={dailyState}
            status={status}
            telemetry={telemetry}
            dictations={dictations}
            currentModel={currentModel}
            lastUpdated={lastUpdated}
            busyAction={busyAction}
            primaryActionLabel={primaryActionLabel}
            onDailyAction={handleDailyAction}
            onOpenSettings={() => setSettingsOpen(true)}
            onClearDictationHistory={clearDictationHistory}
            t={t}
          />
        ) : page === "map" ? (
          <MappingPage
            envelope={mappingEnvelope}
            entries={mappingEntries}
            touched={mappingTouched}
            busyAction={busyAction}
            refreshing={mappingRefreshing}
            onRefresh={() => void refreshMappings({ notifyErrors: true })}
            onSave={() => void saveEventMappings()}
            onReset={() => void resetEventMappings()}
            onChange={updateMappingEntry}
            t={t}
          />
        ) : (
          <CommandPage
            envelope={commandEnvelope}
            entries={commandEntries}
            history={commands}
            busyAction={busyAction}
            refreshing={commandRefreshing}
            onRefresh={() => void refreshCommands({ notifyErrors: true })}
            onSaveEntries={saveCommandMappings}
            onReset={() => void resetCommandMappings()}
            onClearHistory={clearCommandHistory}
            t={t}
          />
        )}
      </AppShell>

      <SettingsSheet
        open={settingsOpen}
        status={status}
        busyAction={busyAction}
        controlsDisabled={controlsDisabled}
        currentModel={currentModel}
        activeModel={activeModel}
        selectedModelDetail={selectedModelDetail}
        modelItems={modelItems}
        language={language}
        languageItems={languageItems}
        serviceModelBlocked={serviceModelBlocked}
        installModelDisabled={installModelDisabled}
        updateModelDisabled={updateModelDisabled}
        repairModelDisabled={repairModelDisabled}
        useModelDisabled={useModelDisabled}
        deleteModelDisabled={deleteModelDisabled}
        voicePreferences={voicePreferences}
        currentCorrectionModel={currentCorrectionModel}
        correctionModel={activeCorrectionModelStatus}
        activeCorrectionModel={activeCorrectionModel}
        correctionModelItems={correctionModelItems}
        correctionModelSelectionTouched={correctionModelSelectionTouched}
        voiceSettingsTouched={voiceSettingsTouched}
        onOpenChange={setSettingsOpen}
        onLanguageChange={setLanguage}
        onModelChange={(model) => {
          setModelSelectionTouched(true)
          setSelectedModel(model)
        }}
        onRunModelAction={(action) => void runModelAction(action)}
        onRunServiceAction={(action) => void runServiceAction(action)}
        onRequestPermission={(kind) => void requestPermission(kind)}
        onRequestDeleteModel={() => setDeleteOpen(true)}
        onVoicePreferencesChange={changeVoicePreferences}
        onSaveVoiceSettings={() => void saveCurrentVoiceSettings()}
        onCorrectionModelChange={(model) => {
          setCorrectionModelSelectionTouched(model !== currentCorrectionModel?.model)
          setSelectedCorrectionModel(model)
        }}
        onRunCorrectionModelAction={(action) => void runCorrectionModelAction(action)}
        t={t}
      />

      <DiagnosticsSheet
        open={diagnosticsOpen}
        status={status}
        dailyState={dailyState}
        telemetry={telemetry}
        performance={performance}
        activity={activity}
        logEntries={logEntries}
        autoFollowLogs={autoFollowLogs}
        logEndRef={logEndRef}
        busyAction={busyAction}
        onOpenChange={setDiagnosticsOpen}
        onToggleAutoFollowLogs={() => setAutoFollowLogs((value) => !value)}
        onDisableAutoFollowLogs={() => {
          if (autoFollowLogs) {
            setAutoFollowLogs(false)
          }
        }}
        onOpenLogs={() => void openLogs()}
        onCopyDiagnostics={() => void copyDiagnostics()}
        onClearPerformance={() => void clearPerformanceHistory()}
        t={t}
      />

      <DeleteModelDialog
        open={deleteOpen}
        activeModel={activeModel}
        onOpenChange={setDeleteOpen}
        onDelete={() => {
          setDeleteOpen(false)
          void runModelAction("delete")
        }}
      />
    </>
  )
}

export default App
