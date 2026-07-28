/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include "ble_connection_policy.h"
#include "user_event_mapping.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>

struct esp_hidd_dev_s;
typedef struct esp_hidd_dev_s esp_hidd_dev_t;
struct ble_gap_event;
struct ble_gatt_access_ctxt;

namespace model {

class BleHidRemote {
public:
    using State           = BleConnectionState;
    using AdvertisingMode = BleAdvertisingMode;

    enum class HostStatus : uint8_t {
        Waiting = 0,
        Preparing,
        Ready,
        Recognizing,
        PermissionError,
        ModelError,
        HostError,
    };

    enum class SpeechServiceState : uint8_t {
        Disconnected,
        BluetoothConnected,
        Connecting,
        Preparing,
        Ready,
        Listening,
        Recognizing,
        PermissionError,
        ModelError,
        HostError,
        MtuTooSmall,
    };

    struct SpeechTimingSeed {
        uint64_t buttonDownUs    = 0;
        uint64_t holdTriggeredUs = 0;
        uint64_t scheduledUs     = 0;
    };

    BleHidRemote() = default;
    ~BleHidRemote();

    bool start();
    void stop();
    bool sendKeyboardShortcut(uint8_t keyCode, uint8_t modifiers);
    bool sendWheel(int8_t delta);
    bool sendMouseClick(uint8_t buttons);
    bool sendMediaControl(uint16_t usage);
    bool pairNewComputer();
    bool reconnect();
    bool cancelPairing();
    void poll();
    bool startSpeech();
    bool startSpeech(const SpeechTimingSeed& timing);
    void stopSpeech(bool abort = false);
    void noteSpeechRelease(uint64_t releasedAtUs);
    bool isSpeechReady() const;
    SpeechServiceState speechServiceState() const;
    UserActionMapping mappingFor(UserEvent event) const;
    bool notifyUserEvent(UserEvent event, UserActionType action, int8_t value, bool handled);

    HostStatus hostStatus() const
    {
        return _host_status.load();
    }

    uint16_t hostError() const
    {
        return _host_error.load();
    }

    bool isSpeechActive() const
    {
        return _speech_active.load();
    }

    State state() const
    {
        return _state.load();
    }

    int lastError() const
    {
        return _last_error.load();
    }

    const char* lastErrorStage() const
    {
        return _last_error_stage.load();
    }

    bool isConnected() const
    {
        return _state.load() == State::Connected;
    }

    AdvertisingMode advertisingMode() const
    {
        return _advertising_mode.load();
    }

    bool pairingOpen() const
    {
        return _pairing_open.load();
    }

    uint8_t bondCount() const
    {
        return _bond_count.load();
    }

    uint32_t rejectedPeerCount() const
    {
        return _rejected_peer_count.load();
    }

    uint8_t lastDisconnectReason() const
    {
        return _last_disconnect_reason.load();
    }

    uint32_t advertisingRemainingMs() const;

private:
    enum class CommandType : uint8_t {
        KeyTap,
        Wheel,
        MouseClick,
        Stop,
    };

    struct Command {
        CommandType type = CommandType::Stop;
        int16_t value    = 0;
        uint8_t modifier = 0;
    };

    static constexpr uint16_t InvalidConnectionHandle = 0xFFFF;

    std::atomic<State> _state{State::Stopped};
    std::atomic<int> _last_error{0};
    std::atomic<const char*> _last_error_stage{"none"};
    std::atomic<bool> _active{false};
    std::atomic<bool> _host_running{false};
    std::atomic<bool> _report_worker_running{false};
    std::atomic<bool> _speech_worker_running{false};
    std::atomic<bool> _speech_active{false};
    std::atomic<bool> _speech_abort_requested{false};
    std::atomic<bool> _speech_status_subscribed{false};
    std::atomic<bool> _speech_subscribed{false};
    std::atomic<bool> _user_event_subscribed{false};
    std::atomic<bool> _performance_subscribed{false};
    std::atomic<bool> _pairing_open{false};
    std::atomic<AdvertisingMode> _advertising_mode{AdvertisingMode::None};
    std::atomic<uint8_t> _bond_count{0};
    std::atomic<uint8_t> _last_disconnect_reason{0};
    std::atomic<uint32_t> _rejected_peer_count{0};
    std::atomic<HostStatus> _host_status{HostStatus::Waiting};
    std::atomic<uint16_t> _host_error{0};
    std::atomic<uint16_t> _connection_handle{InvalidConnectionHandle};

    esp_hidd_dev_t* _hid_device      = nullptr;
    QueueHandle_t _command_queue     = nullptr;
    TaskHandle_t _report_worker_task = nullptr;
    TaskHandle_t _speech_worker_task = nullptr;
    uint16_t _speech_status_handle   = 0;
    uint16_t _speech_audio_handle    = 0;
    uint16_t _host_status_handle     = 0;
    uint16_t _mapping_config_handle  = 0;
    uint16_t _user_event_handle      = 0;
    uint16_t _action_exec_handle     = 0;
    uint16_t _performance_handle     = 0;
    uint16_t _speech_session         = 0;
    uint16_t _speech_sequence        = 0;
    uint16_t _user_event_sequence    = 0;
    BleConnectionPolicy _policy;
    uint32_t _advertising_started_at = 0;
    int32_t _advertising_duration_ms = 0;
    uint32_t _last_battery_poll_at   = 0;
    uint32_t _connected_at           = 0;
    uint8_t _last_battery_level      = 0xFF;
    bool _pairing_after_disconnect   = false;
    bool _controller_initialized     = false;
    bool _controller_enabled         = false;
    bool _nimble_initialized         = false;

    enum SpeechTimingIndex : uint8_t {
        TimingButtonDown = 0,
        TimingHoldTriggered,
        TimingSpeechScheduled,
        TimingSpeechStartCall,
        TimingStatusStartSent,
        TimingWorkerStarted,
        TimingFirstCaptureDone,
        TimingFirstResampleDone,
        TimingFirstEncodeDone,
        TimingFirstAudioSent,
        TimingReleaseDetected,
        TimingStopRequested,
        TimingWorkerExited,
        TimingStatusEndSent,
        SpeechTimingCount,
    };

    enum ConnectionTimingIndex : uint8_t {
        ConnectionRemoteStarted = 0,
        ConnectionAdvertisingStarted,
        ConnectionLinkConnected,
        ConnectionEncryptionReady,
        ConnectionMtuReady,
        ConnectionStatusSubscribed,
        ConnectionAudioSubscribed,
        ConnectionPerformanceSubscribed,
        ConnectionTimingCount,
    };

    struct TimingAggregate {
        uint64_t totalUs = 0;
        uint32_t maxUs   = 0;
        void observe(uint64_t durationUs)
        {
            totalUs += durationUs;
            maxUs = durationUs > UINT32_MAX ? UINT32_MAX : std::max(maxUs, static_cast<uint32_t>(durationUs));
        }
    };

    struct SpeechTiming {
        std::array<uint64_t, SpeechTimingCount> timestampUs{};
        TimingAggregate capture;
        TimingAggregate resample;
        TimingAggregate encode;
        TimingAggregate notify;
        uint16_t frameCount     = 0;
        uint16_t notifyFailures = 0;
    };

    portMUX_TYPE _timing_mux = portMUX_INITIALIZER_UNLOCKED;
    SpeechTiming _speech_timing;
    std::array<uint64_t, ConnectionTimingCount> _connection_timing{};

    bool initializeBluetooth();
    bool registerSpeechService();
    bool registerControlService();
    void cleanupBluetooth();
    bool startAdvertising();
    bool startPolicyAdvertising();
    bool startPairingWindow();
    bool eraseAllBonds();
    bool refreshSingleBond();
    bool isAllowedPeer(uint16_t connectionHandle);
    bool commitConnectedPeer(uint16_t connectionHandle);
    void enterState(State state);
    void enterIdleState();
    void handleDisconnected(uint8_t reason);
    void updateBatteryLevel(bool force = false);
    void handleHidEvent(int32_t eventId, void* eventData);
    int handleGapEvent(struct ble_gap_event* event);
    void runReportWorker();
    void sendKeyboardReport(uint8_t keyCode, uint8_t modifiers = 0);
    void sendMouseWheelReport(int8_t delta);
    void sendMouseClickReport(uint8_t buttons);
    void configureConnection(uint16_t connectionHandle);
    void requestLowLatencyConnection(uint16_t connectionHandle);
    void runSpeechWorker();
    std::array<uint8_t, 12> buildSpeechStatusPacket(uint8_t event, uint16_t error = 0) const;
    bool sendSpeechStatus(uint8_t event, uint16_t error = 0);
    bool sendSpeechAudio(const uint8_t* adpcm, std::size_t length);
    bool sendPerformanceCapabilities();
    bool sendSpeechTimingSummary();
    bool sendConnectionTimingSummary();
    bool sendPerformancePacket(const uint8_t* data, std::size_t length);
    void recordSpeechTiming(SpeechTimingIndex index, uint64_t timestampUs);
    void recordConnectionTiming(ConnectionTimingIndex index, uint64_t timestampUs);
    int readPerformance(struct ble_gatt_access_ctxt* context);
    int writePerformance(struct ble_gatt_access_ctxt* context);
    void waitForSpeechWorker();
    int readSpeechStatus(struct ble_gatt_access_ctxt* context);
    int readMappingConfig(struct ble_gatt_access_ctxt* context);
    int writeMappingConfig(struct ble_gatt_access_ctxt* context);
    int readUserEvent(struct ble_gatt_access_ctxt* context);
    int writeHostStatus(struct ble_gatt_access_ctxt* context);
    int writeActionExecute(struct ble_gatt_access_ctxt* context);
    void setError(int error, const char* stage);

    UserEventMapper _mapping;

    static void hostTask(void* parameter);
    static void reportWorkerTask(void* parameter);
    static void speechWorkerTask(void* parameter);
    static void hidEventCallback(void* handlerArgs, const char* eventBase, int32_t eventId, void* eventData);
    static int gapEventCallback(struct ble_gap_event* event, void* argument);
    static int speechGattAccess(uint16_t connectionHandle, uint16_t attributeHandle,
                                struct ble_gatt_access_ctxt* context, void* argument);
    static int controlGattAccess(uint16_t connectionHandle, uint16_t attributeHandle,
                                 struct ble_gatt_access_ctxt* context, void* argument);
};

const char* bleHidStateToString(BleHidRemote::State state);
const char* speechServiceStateToString(BleHidRemote::SpeechServiceState state);

}  // namespace model
