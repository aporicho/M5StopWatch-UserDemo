/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

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
    enum class State : uint8_t {
        Stopped,
        Starting,
        Advertising,
        Connected,
        Error,
    };

    enum class Key : uint8_t {
        Escape = 0x29,
        Enter  = 0x28,
    };

    enum class HostStatus : uint8_t {
        Waiting = 0,
        Preparing,
        Ready,
        Recognizing,
        PermissionError,
        ModelError,
        HostError,
    };

    BleHidRemote() = default;
    ~BleHidRemote();

    bool start();
    void stop();
    bool sendKeyTap(Key key);
    bool sendWheel(int8_t delta);
    bool pairNewComputer();
    bool startSpeech();
    void stopSpeech(bool abort = false);
    bool isSpeechReady() const;

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

    bool isConnected() const
    {
        return _state.load() == State::Connected;
    }

private:
    enum class CommandType : uint8_t {
        KeyTap,
        Wheel,
        Stop,
    };

    struct Command {
        CommandType type = CommandType::Stop;
        int8_t value     = 0;
    };

    static constexpr uint16_t InvalidConnectionHandle = 0xFFFF;

    std::atomic<State> _state{State::Stopped};
    std::atomic<int> _last_error{0};
    std::atomic<bool> _active{false};
    std::atomic<bool> _host_running{false};
    std::atomic<bool> _report_worker_running{false};
    std::atomic<bool> _speech_worker_running{false};
    std::atomic<bool> _speech_active{false};
    std::atomic<bool> _speech_abort_requested{false};
    std::atomic<bool> _speech_status_subscribed{false};
    std::atomic<bool> _speech_subscribed{false};
    std::atomic<bool> _pairing_replacement{false};
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
    uint16_t _speech_session         = 0;
    uint16_t _speech_sequence        = 0;
    std::array<std::array<uint8_t, 6>, 3> _replacement_peer_addresses{};
    std::array<uint8_t, 3> _replacement_peer_types{};
    uint8_t _replacement_peer_count = 0;
    std::array<uint8_t, 6> _last_peer_address{};
    uint8_t _last_peer_type      = 0;
    bool _last_peer_valid        = false;
    bool _controller_initialized = false;
    bool _controller_enabled     = false;
    bool _nimble_initialized     = false;

    bool initializeBluetooth();
    bool registerSpeechService();
    void cleanupBluetooth();
    bool startAdvertising();
    bool isAllowedPeer(uint16_t connectionHandle);
    void handleHidEvent(int32_t eventId, void* eventData);
    int handleGapEvent(struct ble_gap_event* event);
    void runReportWorker();
    void sendKeyboardReport(uint8_t keyCode);
    void sendMouseWheelReport(int8_t delta);
    void configureConnection(uint16_t connectionHandle);
    void runSpeechWorker();
    bool sendSpeechStatus(uint8_t event, uint16_t error = 0);
    bool sendSpeechAudio(const uint8_t* adpcm, std::size_t length);
    void waitForSpeechWorker();
    void setError(int error);

    static void hostTask(void* parameter);
    static void reportWorkerTask(void* parameter);
    static void speechWorkerTask(void* parameter);
    static void hidEventCallback(void* handlerArgs, const char* eventBase, int32_t eventId, void* eventData);
    static int gapEventCallback(struct ble_gap_event* event, void* argument);
    static int speechGattAccess(uint16_t connectionHandle, uint16_t attributeHandle,
                                struct ble_gatt_access_ctxt* context, void* argument);
};

const char* bleHidStateToString(BleHidRemote::State state);

}  // namespace model
