/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#include "ble_hid_remote.h"
#include "speech_codec.h"

#include <algorithm>
#include <array>
#include <cstring>

#include <esp_bt.h>
#include <esp_err.h>
#include <esp_hid_common.h>
#include <esp_hidd.h>
#include <esp_log.h>
#include <esp_timer.h>
#include <hal/hal.h>
#include <host/ble_att.h>
#include <host/ble_gap.h>
#include <host/ble_gatt.h>
#include <host/ble_hs.h>
#include <host/ble_sm.h>
#include <host/ble_store.h>
#include <nimble/ble.h>
#include <nimble/nimble_port.h>
#include <nimble/nimble_port_freertos.h>
#include <services/gap/ble_svc_gap.h>
#include <services/gatt/ble_svc_gatt.h>
#include <store/config/ble_store_config.h>

extern "C" void ble_store_config_init(void);

namespace model {
namespace {

constexpr char Tag[]        = "BLE-HID";
constexpr char DeviceName[] = "M5StopWatch HID";

constexpr uint8_t KeyboardReportId            = 1;
constexpr uint8_t MouseReportId               = 2;
constexpr size_t BondScanCapacity             = 8;
constexpr uint32_t BatteryPollMs              = 60000;
constexpr uint32_t ConnectionParameterDelayMs = 5000;

constexpr uint8_t SpeechProtocolVersion     = 1;
constexpr uint8_t SpeechCodecImaAdpcm       = 1;
constexpr uint16_t SpeechSampleRate         = 16000;
constexpr uint16_t MinimumSpeechMtu         = 185;
constexpr uint32_t SpeechWorkerStackBytes   = 12 * 1024;
constexpr uint8_t PerformanceWireVersion    = 1;
constexpr uint8_t PerformanceCapabilities   = 0;
constexpr uint8_t PerformanceSyncRequest    = 1;
constexpr uint8_t PerformanceSyncResponse   = 2;
constexpr uint8_t PerformanceSession        = 3;
constexpr uint8_t PerformanceConnection     = 4;
constexpr size_t PerformanceSessionBytes    = 154;
constexpr size_t PerformanceConnectionBytes = 68;

enum SpeechEvent : uint8_t {
    SpeechReady = 0,
    SpeechStart = 1,
    SpeechEnd   = 2,
    SpeechAbort = 3,
    SpeechError = 4,
};

// NimBLE stores 128-bit UUIDs least-significant byte first.
const ble_uuid128_t SpeechServiceUuid =
    BLE_UUID128_INIT(0x01, 0x9a, 0x1f, 0x8b, 0x0d, 0x5e, 0xc0, 0xa7, 0x6d, 0x4c, 0x2e, 0x6b, 0x00, 0x10, 0x3a, 0x7f);
const ble_uuid128_t ControlServiceUuid =
    BLE_UUID128_INIT(0x01, 0x9a, 0x1f, 0x8b, 0x0d, 0x5e, 0xc0, 0xa7, 0x6d, 0x4c, 0x2e, 0x6b, 0x00, 0x11, 0x3a, 0x7f);
const ble_uuid128_t SpeechStatusUuid =
    BLE_UUID128_INIT(0x01, 0x9a, 0x1f, 0x8b, 0x0d, 0x5e, 0xc0, 0xa7, 0x6d, 0x4c, 0x2e, 0x6b, 0x01, 0x10, 0x3a, 0x7f);
const ble_uuid128_t SpeechAudioUuid =
    BLE_UUID128_INIT(0x01, 0x9a, 0x1f, 0x8b, 0x0d, 0x5e, 0xc0, 0xa7, 0x6d, 0x4c, 0x2e, 0x6b, 0x02, 0x10, 0x3a, 0x7f);
const ble_uuid128_t HostStatusUuid =
    BLE_UUID128_INIT(0x01, 0x9a, 0x1f, 0x8b, 0x0d, 0x5e, 0xc0, 0xa7, 0x6d, 0x4c, 0x2e, 0x6b, 0x03, 0x10, 0x3a, 0x7f);
const ble_uuid128_t MappingConfigUuid =
    BLE_UUID128_INIT(0x01, 0x9a, 0x1f, 0x8b, 0x0d, 0x5e, 0xc0, 0xa7, 0x6d, 0x4c, 0x2e, 0x6b, 0x04, 0x10, 0x3a, 0x7f);
const ble_uuid128_t UserEventUuid =
    BLE_UUID128_INIT(0x01, 0x9a, 0x1f, 0x8b, 0x0d, 0x5e, 0xc0, 0xa7, 0x6d, 0x4c, 0x2e, 0x6b, 0x05, 0x10, 0x3a, 0x7f);
const ble_uuid128_t ActionExecUuid =
    BLE_UUID128_INIT(0x01, 0x9a, 0x1f, 0x8b, 0x0d, 0x5e, 0xc0, 0xa7, 0x6d, 0x4c, 0x2e, 0x6b, 0x06, 0x10, 0x3a, 0x7f);
const ble_uuid128_t PerformanceUuid =
    BLE_UUID128_INIT(0x01, 0x9a, 0x1f, 0x8b, 0x0d, 0x5e, 0xc0, 0xa7, 0x6d, 0x4c, 0x2e, 0x6b, 0x07, 0x10, 0x3a, 0x7f);

uint64_t monotonicUs()
{
    return static_cast<uint64_t>(esp_timer_get_time());
}

template <size_t Size>
void put16(std::array<uint8_t, Size>& packet, size_t& offset, uint16_t value)
{
    packet[offset++] = static_cast<uint8_t>(value & 0xFF);
    packet[offset++] = static_cast<uint8_t>(value >> 8);
}

template <size_t Size>
void put32(std::array<uint8_t, Size>& packet, size_t& offset, uint32_t value)
{
    for (int shift = 0; shift < 32; shift += 8) {
        packet[offset++] = static_cast<uint8_t>(value >> shift);
    }
}

template <size_t Size>
void put64(std::array<uint8_t, Size>& packet, size_t& offset, uint64_t value)
{
    for (int shift = 0; shift < 64; shift += 8) {
        packet[offset++] = static_cast<uint8_t>(value >> shift);
    }
}

constexpr uint8_t HidReportMap[] = {
    // Keyboard, report ID 1.
    0x05,
    0x01,  // Usage Page (Generic Desktop)
    0x09,
    0x06,  // Usage (Keyboard)
    0xA1,
    0x01,  // Collection (Application)
    0x85,
    KeyboardReportId,
    0x05,
    0x07,  // Usage Page (Keyboard)
    0x19,
    0xE0,  // Usage Minimum (Left Control)
    0x29,
    0xE7,  // Usage Maximum (Right GUI)
    0x15,
    0x00,
    0x25,
    0x01,
    0x75,
    0x01,
    0x95,
    0x08,
    0x81,
    0x02,  // Input (Data, Variable, Absolute)
    0x95,
    0x01,
    0x75,
    0x08,
    0x81,
    0x03,  // Input (Constant)
    0x95,
    0x05,
    0x75,
    0x01,
    0x05,
    0x08,  // Usage Page (LEDs)
    0x19,
    0x01,
    0x29,
    0x05,
    0x91,
    0x02,  // Output (Data, Variable, Absolute)
    0x95,
    0x01,
    0x75,
    0x03,
    0x91,
    0x03,  // Output (Constant)
    0x95,
    0x06,
    0x75,
    0x08,
    0x15,
    0x00,
    0x25,
    0x65,
    0x05,
    0x07,
    0x19,
    0x00,
    0x29,
    0x65,
    0x81,
    0x00,  // Input (Data, Array)
    0xC0,

    // Mouse wheel, report ID 2.
    0x05,
    0x01,  // Usage Page (Generic Desktop)
    0x09,
    0x02,  // Usage (Mouse)
    0xA1,
    0x01,  // Collection (Application)
    0x85,
    MouseReportId,
    0x09,
    0x01,  // Usage (Pointer)
    0xA1,
    0x00,  // Collection (Physical)
    0x05,
    0x09,  // Usage Page (Button)
    0x19,
    0x01,
    0x29,
    0x03,
    0x15,
    0x00,
    0x25,
    0x01,
    0x95,
    0x03,
    0x75,
    0x01,
    0x81,
    0x02,
    0x95,
    0x01,
    0x75,
    0x05,
    0x81,
    0x03,
    0x05,
    0x01,
    0x09,
    0x30,  // Usage (X)
    0x09,
    0x31,  // Usage (Y)
    0x09,
    0x38,  // Usage (Wheel)
    0x15,
    0x81,  // Logical Minimum (-127)
    0x25,
    0x7F,  // Logical Maximum (127)
    0x75,
    0x08,
    0x95,
    0x03,
    0x81,
    0x06,  // Input (Data, Variable, Relative)
    0xC0,
    0xC0,
};

esp_hid_raw_report_map_t ReportMaps[] = {
    {
        .data = HidReportMap,
        .len  = sizeof(HidReportMap),
    },
};

esp_hid_device_config_t HidConfig = {
    .vendor_id         = 0x303A,
    .product_id        = 0x4001,
    .version           = 0x0100,
    .device_name       = DeviceName,
    .manufacturer_name = "M5Stack",
    .serial_number     = "M5StopWatch-HID",
    .report_maps       = ReportMaps,
    .report_maps_len   = 1,
};

void logPeerAddress(const char* message, const ble_addr_t& address)
{
    ESP_LOGI(Tag, "%s type=%u addr=%02x:%02x:%02x:%02x:%02x:%02x", message, address.type, address.val[5],
             address.val[4], address.val[3], address.val[2], address.val[1], address.val[0]);
}

ble_addr_t controllerAddress(ble_addr_t address)
{
    address.type &= 0x01U;
    return address;
}

bool samePeerAddress(const ble_addr_t& left, const ble_addr_t& right)
{
    return (left.type & 0x01U) == (right.type & 0x01U) && std::memcmp(left.val, right.val, sizeof(left.val)) == 0;
}

int bondStoreStatus(struct ble_store_status_event* event, void*)
{
    ESP_LOGE(Tag, "BLE bond store full (event=%d); Pair New must erase the existing bond first",
             event == nullptr ? -1 : event->event_code);
    return BLE_HS_ENOMEM;
}

BleHidRemote* ActiveInstance = nullptr;

}  // namespace

BleHidRemote::~BleHidRemote()
{
    stop();
}

bool BleHidRemote::start()
{
    if (_active.load()) {
        return true;
    }

    _connection_timing.fill(0);
    recordConnectionTiming(ConnectionRemoteStarted, monotonicUs());
    _speech_timing            = {};
    _state                    = State::Starting;
    _last_error               = ESP_OK;
    _last_error_stage         = "none";
    _active                   = true;
    _speech_active            = false;
    _speech_abort_requested   = false;
    _speech_subscribed        = false;
    _speech_status_subscribed = false;
    _pairing_open             = false;
    _advertising_mode         = AdvertisingMode::None;
    _rejected_peer_count      = 0;
    _bond_count               = 0;
    _last_disconnect_reason   = 0;
    _pairing_after_disconnect = false;
    _advertising_started_at   = 0;
    _advertising_duration_ms  = 0;
    _last_battery_poll_at     = 0;
    _connected_at             = 0;
    _last_battery_level       = 0xFF;
    _host_status              = HostStatus::Waiting;
    _host_error               = 0;
    _user_event_subscribed    = false;
    _performance_subscribed   = false;
    _mapping.load();

    _command_queue = xQueueCreate(16, sizeof(Command));
    if (_command_queue == nullptr) {
        setError(ESP_ERR_NO_MEM, "command_queue");
        _active = false;
        return false;
    }

    _report_worker_running = true;
    if (xTaskCreate(reportWorkerTask, "ble_hid_reports", 4 * 1024, this, 2, &_report_worker_task) != pdPASS) {
        _report_worker_running = false;
        vQueueDelete(_command_queue);
        _command_queue = nullptr;
        setError(ESP_ERR_NO_MEM, "report_worker_task");
        _active = false;
        return false;
    }

    if (!initializeBluetooth()) {
        const int error        = _last_error.load();
        const char* errorStage = _last_error_stage.load();
        stop();
        setError(error, errorStage);
        return false;
    }

    ESP_LOGI(Tag, "BLE HID started");
    return true;
}

void BleHidRemote::stop()
{
    if (!_active.exchange(false) && _state.load() == State::Stopped) {
        return;
    }

    stopSpeech(true);
    waitForSpeechWorker();

    if (_command_queue != nullptr) {
        xQueueReset(_command_queue);
        const Command command{.type = CommandType::Stop};
        xQueueSend(_command_queue, &command, 0);
        for (int i = 0; i < 40 && _report_worker_running.load(); ++i) {
            vTaskDelay(pdMS_TO_TICKS(5));
        }
        if (_report_worker_running.load() && _report_worker_task != nullptr) {
            vTaskDelete(_report_worker_task);
            _report_worker_running = false;
        }
        _report_worker_task = nullptr;
        vQueueDelete(_command_queue);
        _command_queue = nullptr;
    }

    cleanupBluetooth();
    _connection_handle      = InvalidConnectionHandle;
    _advertising_mode       = AdvertisingMode::None;
    _pairing_open           = false;
    _performance_subscribed = false;
    enterState(_policy.stop());
    ESP_LOGI(Tag, "BLE HID stopped");
}

bool BleHidRemote::sendKeyboardShortcut(uint8_t keyCode, uint8_t modifiers)
{
    if (!isConnected() || _command_queue == nullptr) {
        return false;
    }

    const Command command{
        .type     = CommandType::KeyTap,
        .value    = static_cast<int16_t>(keyCode),
        .modifier = modifiers,
    };
    return xQueueSend(_command_queue, &command, 0) == pdTRUE;
}

bool BleHidRemote::sendWheel(int8_t delta)
{
    if (!isConnected() || delta == 0 || _command_queue == nullptr) {
        return false;
    }

    const Command command{
        .type     = CommandType::Wheel,
        .value    = delta,
        .modifier = 0,
    };
    return xQueueSend(_command_queue, &command, 0) == pdTRUE;
}

bool BleHidRemote::sendMouseClick(uint8_t buttons)
{
    if (!isConnected() || buttons == 0 || _command_queue == nullptr) {
        return false;
    }

    const Command command{
        .type     = CommandType::MouseClick,
        .value    = buttons,
        .modifier = 0,
    };
    return xQueueSend(_command_queue, &command, 0) == pdTRUE;
}

bool BleHidRemote::sendMediaControl(uint16_t usage)
{
    (void)usage;
    return false;
}

UserActionMapping BleHidRemote::mappingFor(UserEvent event) const
{
    return _mapping.actionFor(event);
}

bool BleHidRemote::notifyUserEvent(UserEvent event, UserActionType action, int8_t value, bool handled)
{
    if (!_user_event_subscribed.load()) {
        return false;
    }
    const uint16_t connectionHandle = _connection_handle.load();
    if (connectionHandle == InvalidConnectionHandle || _user_event_handle == 0) {
        return false;
    }

    ++_user_event_sequence;
    std::array<uint8_t, 8> packet{};
    packet[0] = UserEventMapper::MappingVersion;
    packet[1] = static_cast<uint8_t>(event);
    packet[2] = static_cast<uint8_t>(action);
    packet[3] = handled ? 1 : 0;
    packet[4] = static_cast<uint8_t>(value);
    packet[5] = static_cast<uint8_t>(_user_event_sequence & 0xFF);
    packet[6] = static_cast<uint8_t>(_user_event_sequence >> 8);
    packet[7] = 0;

    os_mbuf* buffer = ble_hs_mbuf_from_flat(packet.data(), packet.size());
    if (buffer == nullptr) {
        return false;
    }
    return ble_gatts_notify_custom(connectionHandle, _user_event_handle, buffer) == 0;
}

bool BleHidRemote::isSpeechReady() const
{
    return speechServiceState() == SpeechServiceState::Ready;
}

BleHidRemote::SpeechServiceState BleHidRemote::speechServiceState() const
{
    if (!isConnected()) {
        return SpeechServiceState::Disconnected;
    }
    if (_speech_active.load()) {
        return SpeechServiceState::Listening;
    }

    const HostStatus hostStatus = _host_status.load();
    switch (hostStatus) {
        case HostStatus::Preparing:
            return SpeechServiceState::Preparing;
        case HostStatus::Recognizing:
            return SpeechServiceState::Recognizing;
        case HostStatus::PermissionError:
            return SpeechServiceState::PermissionError;
        case HostStatus::ModelError:
            return SpeechServiceState::ModelError;
        case HostStatus::HostError:
            return SpeechServiceState::HostError;
        case HostStatus::Ready:
            break;
        case HostStatus::Waiting:
        default:
            if (_speech_status_subscribed.load() || _speech_subscribed.load()) {
                return SpeechServiceState::Connecting;
            }
            return SpeechServiceState::BluetoothConnected;
    }

    const uint16_t handle = _connection_handle.load();
    if (handle == InvalidConnectionHandle || !_speech_status_subscribed.load() || !_speech_subscribed.load()) {
        return SpeechServiceState::Connecting;
    }
    if (ble_att_mtu(handle) < MinimumSpeechMtu) {
        return SpeechServiceState::MtuTooSmall;
    }
    return SpeechServiceState::Ready;
}

bool BleHidRemote::startSpeech()
{
    return startSpeech(SpeechTimingSeed{});
}

bool BleHidRemote::startSpeech(const SpeechTimingSeed& timing)
{
    if (_speech_active.load() || _speech_worker_running.load() || !isSpeechReady()) {
        return false;
    }

    taskENTER_CRITICAL(&_timing_mux);
    _speech_timing                                    = {};
    _speech_timing.timestampUs[TimingButtonDown]      = timing.buttonDownUs;
    _speech_timing.timestampUs[TimingHoldTriggered]   = timing.holdTriggeredUs;
    _speech_timing.timestampUs[TimingSpeechScheduled] = timing.scheduledUs;
    _speech_timing.timestampUs[TimingSpeechStartCall] = monotonicUs();
    taskEXIT_CRITICAL(&_timing_mux);

    ++_speech_session;
    if (_speech_session == 0) {
        ++_speech_session;
    }
    _speech_sequence        = 0;
    _speech_abort_requested = false;
    _speech_active          = true;

    requestLowLatencyConnection(_connection_handle.load());
    updateBatteryLevel();

    if (!sendSpeechStatus(SpeechStart)) {
        _speech_active = false;
        return false;
    }
    recordSpeechTiming(TimingStatusStartSent, monotonicUs());

    _speech_worker_running = true;
    if (xTaskCreate(speechWorkerTask, "ble_speech", SpeechWorkerStackBytes, this, 4, &_speech_worker_task) != pdPASS) {
        _speech_worker_running = false;
        _speech_active         = false;
        sendSpeechStatus(SpeechError, ESP_ERR_NO_MEM);
        return false;
    }

    ESP_LOGI(Tag, "speech session %u started, stack=%u bytes", _speech_session,
             static_cast<unsigned>(SpeechWorkerStackBytes));
    return true;
}

void BleHidRemote::stopSpeech(bool abort)
{
    if (abort) {
        _speech_abort_requested = true;
    }
    if (_speech_active.load()) {
        recordSpeechTiming(TimingStopRequested, monotonicUs());
    }
    _speech_active = false;
}

void BleHidRemote::noteSpeechRelease(uint64_t releasedAtUs)
{
    if (_speech_active.load()) {
        recordSpeechTiming(TimingReleaseDetected, releasedAtUs == 0 ? monotonicUs() : releasedAtUs);
    }
}

bool BleHidRemote::pairNewComputer()
{
    if (!_active.load() || !_nimble_initialized) {
        return false;
    }

    if (_pairing_open.load()) {
        ESP_LOGI(Tag, "pair-new-computer mode is already active");
        return true;
    }

    stopSpeech(true);
    _pairing_after_disconnect = false;
    if (ble_gap_adv_active()) {
        ble_gap_adv_stop();
    }

    const uint16_t handle = _connection_handle.load();
    if (handle != InvalidConnectionHandle) {
        const int terminateResult = ble_gap_terminate(handle, BLE_ERR_REM_USER_CONN_TERM);
        if (terminateResult == 0) {
            _pairing_after_disconnect = true;
            ESP_LOGI(Tag, "Pair New requested; waiting for the existing link to close");
            return true;
        } else if (terminateResult != BLE_HS_ENOTCONN) {
            setError(terminateResult, "pair_disconnect");
            return false;
        }
    }
    _connection_handle = InvalidConnectionHandle;
    return startPairingWindow();
}

bool BleHidRemote::reconnect()
{
    if (!_active.load() || !_nimble_initialized || _connection_handle.load() != InvalidConnectionHandle) {
        return false;
    }
    if (!refreshSingleBond() || _bond_count.load() == 0) {
        enterState(_policy.pairingCancelled(false));
        return false;
    }
    if (ble_gap_adv_active()) {
        ble_gap_adv_stop();
    }
    _pairing_open = false;
    enterState(_policy.requestReconnect(true));
    return startPolicyAdvertising();
}

bool BleHidRemote::cancelPairing()
{
    if (!_pairing_open.load()) {
        return false;
    }
    if (ble_gap_adv_active()) {
        ble_gap_adv_stop();
    }
    _pairing_open = false;
    refreshSingleBond();
    enterState(_policy.pairingCancelled(_bond_count.load() != 0));
    return true;
}

void BleHidRemote::poll()
{
    if (!isConnected()) {
        return;
    }
    const uint32_t now = GetHAL().millis();
    if (_last_battery_poll_at == 0 || now - _last_battery_poll_at >= BatteryPollMs) {
        updateBatteryLevel();
        _last_battery_poll_at = now;
    }
}

bool BleHidRemote::initializeBluetooth()
{
    ActiveInstance = this;

    esp_bt_controller_config_t controller_config = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    esp_err_t result                             = esp_bt_controller_init(&controller_config);
    if (result != ESP_OK) {
        setError(result, "controller_init");
        return false;
    }
    _controller_initialized = true;

    result = esp_bt_controller_enable(ESP_BT_MODE_BLE);
    if (result != ESP_OK) {
        setError(result, "controller_enable");
        return false;
    }
    _controller_enabled = true;

    result = esp_nimble_init();
    if (result != ESP_OK) {
        setError(result, "nimble_init");
        return false;
    }
    _nimble_initialized = true;

    const int mtuResult = ble_att_set_preferred_mtu(247);
    if (mtuResult != 0) {
        setError(mtuResult, "preferred_mtu");
        return false;
    }

    // CoreBluetooth does not reliably present a passkey sheet for pairing
    // initiated by an application.  These characteristics require encrypted,
    // bonded access but not MITM authentication, so Secure Connections Just
    // Works gives macOS, Linux, and Windows one automatic pairing flow.
    ble_hs_cfg.sm_io_cap         = BLE_SM_IO_CAP_NO_IO;
    ble_hs_cfg.sm_bonding        = 1;
    ble_hs_cfg.sm_mitm           = 0;
    ble_hs_cfg.sm_sc             = 1;
    ble_hs_cfg.sm_our_key_dist   = BLE_SM_PAIR_KEY_DIST_ID | BLE_SM_PAIR_KEY_DIST_ENC;
    ble_hs_cfg.sm_their_key_dist = BLE_SM_PAIR_KEY_DIST_ID | BLE_SM_PAIR_KEY_DIST_ENC;

    ble_store_config_init();
    ble_hs_cfg.store_status_cb = bondStoreStatus;

    result = esp_hidd_dev_init(&HidConfig, ESP_HID_TRANSPORT_BLE,
                               reinterpret_cast<esp_event_handler_t>(hidEventCallback), &_hid_device);
    if (result != ESP_OK) {
        setError(result, "hid_init");
        return false;
    }

    if (!registerSpeechService()) {
        return false;
    }

    if (!registerControlService()) {
        return false;
    }

    const int nameResult = ble_svc_gap_device_name_set(DeviceName);
    if (nameResult != 0) {
        setError(nameResult, "device_name");
        return false;
    }
    const int appearanceResult = ble_svc_gap_device_appearance_set(ESP_HID_APPEARANCE_MOUSE);
    if (appearanceResult != 0) {
        setError(appearanceResult, "device_appearance");
        return false;
    }

    _host_running = true;
    result        = esp_nimble_enable(reinterpret_cast<void*>(hostTask));
    if (result != ESP_OK) {
        _host_running = false;
        setError(result, "nimble_enable");
        return false;
    }

    return true;
}

bool BleHidRemote::registerSpeechService()
{
    static ble_gatt_chr_def characteristics[5]{};
    static ble_gatt_svc_def services[2]{};
    static bool initialized = false;

    if (!initialized) {
        characteristics[0].uuid       = &SpeechStatusUuid.u;
        characteristics[0].access_cb  = speechGattAccess;
        characteristics[0].flags      = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_READ_ENC | BLE_GATT_CHR_F_NOTIFY;
        characteristics[0].val_handle = &_speech_status_handle;

        characteristics[1].uuid       = &SpeechAudioUuid.u;
        characteristics[1].access_cb  = speechGattAccess;
        characteristics[1].flags      = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_READ_ENC | BLE_GATT_CHR_F_NOTIFY;
        characteristics[1].val_handle = &_speech_audio_handle;

        characteristics[2].uuid       = &HostStatusUuid.u;
        characteristics[2].access_cb  = speechGattAccess;
        characteristics[2].flags      = BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_ENC;
        characteristics[2].val_handle = &_host_status_handle;

        characteristics[3].uuid       = &PerformanceUuid.u;
        characteristics[3].access_cb  = speechGattAccess;
        characteristics[3].flags      = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_READ_ENC | BLE_GATT_CHR_F_WRITE |
                                        BLE_GATT_CHR_F_WRITE_ENC | BLE_GATT_CHR_F_NOTIFY;
        characteristics[3].val_handle = &_performance_handle;

        services[0].type            = BLE_GATT_SVC_TYPE_PRIMARY;
        services[0].uuid            = &SpeechServiceUuid.u;
        services[0].characteristics = characteristics;
        initialized                 = true;
    } else {
        // The definitions are process-static, but value handles belong to the
        // current app instance and must be written into this instance.
        characteristics[0].val_handle = &_speech_status_handle;
        characteristics[1].val_handle = &_speech_audio_handle;
        characteristics[2].val_handle = &_host_status_handle;
        characteristics[3].val_handle = &_performance_handle;
    }

    int result = ble_gatts_count_cfg(services);
    if (result == 0) {
        result = ble_gatts_add_svcs(services);
    }
    if (result != 0) {
        ESP_LOGE(Tag, "failed to register speech GATT service: %d", result);
        setError(result, result == BLE_HS_EBUSY ? "speech_gatt_busy" : "speech_gatt_register");
        return false;
    }
    return true;
}

bool BleHidRemote::registerControlService()
{
    static ble_gatt_chr_def characteristics[4]{};
    static ble_gatt_svc_def services[2]{};
    static bool initialized = false;

    if (!initialized) {
        characteristics[0].uuid      = &MappingConfigUuid.u;
        characteristics[0].access_cb = controlGattAccess;
        characteristics[0].flags =
            BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_READ_ENC | BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_ENC;
        characteristics[0].val_handle = &_mapping_config_handle;

        characteristics[1].uuid       = &UserEventUuid.u;
        characteristics[1].access_cb  = controlGattAccess;
        characteristics[1].flags      = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_READ_ENC | BLE_GATT_CHR_F_NOTIFY;
        characteristics[1].val_handle = &_user_event_handle;

        characteristics[2].uuid       = &ActionExecUuid.u;
        characteristics[2].access_cb  = controlGattAccess;
        characteristics[2].flags      = BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_ENC;
        characteristics[2].val_handle = &_action_exec_handle;

        services[0].type            = BLE_GATT_SVC_TYPE_PRIMARY;
        services[0].uuid            = &ControlServiceUuid.u;
        services[0].characteristics = characteristics;
        initialized                 = true;
    } else {
        characteristics[0].val_handle = &_mapping_config_handle;
        characteristics[1].val_handle = &_user_event_handle;
        characteristics[2].val_handle = &_action_exec_handle;
    }

    int result = ble_gatts_count_cfg(services);
    if (result == 0) {
        result = ble_gatts_add_svcs(services);
    }
    if (result != 0) {
        ESP_LOGE(Tag, "failed to register control GATT service: %d", result);
        setError(result, result == BLE_HS_EBUSY ? "control_gatt_busy" : "control_gatt_register");
        return false;
    }
    return true;
}

void BleHidRemote::cleanupBluetooth()
{
    stopSpeech(true);
    waitForSpeechWorker();
    _speech_subscribed        = false;
    _speech_status_subscribed = false;
    _user_event_subscribed    = false;
    _performance_subscribed   = false;
    _host_status              = HostStatus::Waiting;
    _host_error               = 0;

    if (_nimble_initialized && ble_gap_adv_active()) {
        ble_gap_adv_stop();
    }

    const uint16_t handle = _connection_handle.load();
    if (_nimble_initialized && handle != InvalidConnectionHandle) {
        ble_gap_terminate(handle, BLE_ERR_REM_USER_CONN_TERM);
        for (int i = 0; i < 30 && _connection_handle.load() != InvalidConnectionHandle; ++i) {
            vTaskDelay(pdMS_TO_TICKS(10));
        }
    }

    if (_hid_device != nullptr) {
        esp_hidd_dev_deinit(_hid_device);
        _hid_device = nullptr;
    }

    if (_nimble_initialized && _host_running.load()) {
        const int result = nimble_port_stop();
        if (result != 0 && result != BLE_HS_EALREADY) {
            ESP_LOGW(Tag, "nimble_port_stop failed: %d", result);
        }
        for (int i = 0; i < 100 && _host_running.load(); ++i) {
            vTaskDelay(pdMS_TO_TICKS(10));
        }
    }

    if (_nimble_initialized) {
        const esp_err_t result = esp_nimble_deinit();
        if (result != ESP_OK) {
            ESP_LOGW(Tag, "esp_nimble_deinit failed: %d", result);
        }
        _nimble_initialized = false;
    }

    if (_controller_enabled) {
        const esp_err_t result = esp_bt_controller_disable();
        if (result != ESP_OK) {
            ESP_LOGW(Tag, "esp_bt_controller_disable failed: %d", result);
        }
        _controller_enabled = false;
    }

    if (_controller_initialized) {
        const esp_err_t result = esp_bt_controller_deinit();
        if (result != ESP_OK) {
            ESP_LOGW(Tag, "esp_bt_controller_deinit failed: %d", result);
        }
        _controller_initialized = false;
    }

    if (ActiveInstance == this) {
        ActiveInstance = nullptr;
    }
}

bool BleHidRemote::startAdvertising()
{
    if (!_active.load() || !_nimble_initialized) {
        return false;
    }
    if (_connection_handle.load() != InvalidConnectionHandle) {
        return true;
    }
    if (!refreshSingleBond()) {
        setError(ESP_FAIL, "read_bonds");
        return false;
    }
    const bool hasBond = _bond_count.load() != 0;
    _pairing_open      = !hasBond;
    enterState(_policy.start(hasBond));
    return startPolicyAdvertising();
}

bool BleHidRemote::startPolicyAdvertising()
{
    if (!_active.load() || !_nimble_initialized || _connection_handle.load() != InvalidConnectionHandle) {
        return false;
    }
    if (ble_gap_adv_active()) {
        return true;
    }

    const AdvertisingMode mode = _policy.advertisingMode();
    if (mode == AdvertisingMode::None) {
        enterIdleState();
        return true;
    }

    std::array<ble_addr_t, BondScanCapacity> bondedPeers{};
    int bondedCount = 0;
    if (mode != AdvertisingMode::PairingLimited) {
        const int storeResult =
            ble_store_util_bonded_peers(bondedPeers.data(), &bondedCount, static_cast<int>(bondedPeers.size()));
        if (storeResult != 0 || bondedCount != 1) {
            ESP_LOGE(Tag, "reconnect requires exactly one bond: result=%d count=%d", storeResult, bondedCount);
            setError(storeResult == 0 ? BLE_HS_ENOENT : storeResult, "reconnect_bond");
            return false;
        }
    }

    ble_uuid16_t hid_uuid = BLE_UUID16_INIT(0x1812);
    ble_hs_adv_fields fields{};
    fields.flags = BLE_HS_ADV_F_BREDR_UNSUP;
    if (mode == AdvertisingMode::PairingLimited) {
        fields.flags |= BLE_HS_ADV_F_DISC_LTD;
    }
    // Advertise the primary HID role before service discovery.  The report
    // map remains a keyboard/mouse composite device after connection.
    fields.appearance            = ESP_HID_APPEARANCE_MOUSE;
    fields.appearance_is_present = 1;
    fields.tx_pwr_lvl            = BLE_HS_ADV_TX_PWR_LVL_AUTO;
    fields.tx_pwr_lvl_is_present = 1;
    fields.name                  = reinterpret_cast<const uint8_t*>(DeviceName);
    fields.name_len              = std::strlen(DeviceName);
    fields.name_is_complete      = 1;
    fields.uuids16               = &hid_uuid;
    fields.num_uuids16           = 1;
    fields.uuids16_is_complete   = 1;

    int result = ble_gap_adv_set_fields(&fields);
    if (result != 0) {
        ESP_LOGE(Tag, "failed to set advertisement fields: %d", result);
        setError(result, "adv_fields");
        return false;
    }

    ble_hs_adv_fields response{};
    response.uuids128             = &SpeechServiceUuid;
    response.num_uuids128         = 1;
    response.uuids128_is_complete = 1;

    result = ble_gap_adv_rsp_set_fields(&response);
    if (result != 0) {
        ESP_LOGE(Tag, "failed to set scan response fields: %d", result);
        setError(result, "scan_response");
        return false;
    }

    ble_gap_adv_params parameters{};
    const ble_addr_t* directAddressPointer = nullptr;
    const int32_t duration                 = _policy.advertisingDurationMs();
    ble_addr_t allowedPeer{};

    if (mode == AdvertisingMode::ReconnectDirected) {
        allowedPeer                = controllerAddress(bondedPeers[0]);
        directAddressPointer       = &allowedPeer;
        parameters.conn_mode       = BLE_GAP_CONN_MODE_DIR;
        parameters.disc_mode       = BLE_GAP_DISC_MODE_NON;
        parameters.high_duty_cycle = 1;
    } else {
        parameters.conn_mode = BLE_GAP_CONN_MODE_UND;
        parameters.disc_mode = mode == AdvertisingMode::PairingLimited ? BLE_GAP_DISC_MODE_LTD : BLE_GAP_DISC_MODE_NON;
        parameters.itvl_min  = BLE_GAP_ADV_ITVL_MS(30);
        parameters.itvl_max  = BLE_GAP_ADV_ITVL_MS(60);
        if (mode == AdvertisingMode::ReconnectFiltered) {
            allowedPeer               = controllerAddress(bondedPeers[0]);
            const int whitelistResult = ble_gap_wl_set(&allowedPeer, 1);
            if (whitelistResult != 0) {
                ESP_LOGE(Tag, "failed to configure reconnect accept-list: %d", whitelistResult);
                setError(whitelistResult, "accept_list");
                return false;
            }
            parameters.filter_policy = BLE_HCI_ADV_FILT_CONN;
        }
    }

    result = ble_gap_adv_start(BLE_OWN_ADDR_RPA_PUBLIC_DEFAULT, directAddressPointer, duration, &parameters,
                               gapEventCallback, this);
    if (result != 0 && result != BLE_HS_EALREADY) {
        ESP_LOGE(Tag, "failed to start advertising: %d", result);
        _advertising_mode = AdvertisingMode::None;
        setError(result, "adv_start");
        return false;
    }

    _advertising_mode        = mode;
    _advertising_started_at  = GetHAL().millis();
    _advertising_duration_ms = duration;
    recordConnectionTiming(ConnectionAdvertisingStarted, monotonicUs());
    if (mode == AdvertisingMode::ReconnectDirected) {
        logPeerAddress("bounded high-duty directed reconnect", allowedPeer);
    } else {
        ESP_LOGI(Tag, "bounded undirected advertising as %s mode=%s duration=%ldms", DeviceName,
                 bleAdvertisingModeToString(mode), static_cast<long>(duration));
    }
    return true;
}

bool BleHidRemote::startPairingWindow()
{
    if (ble_gap_adv_active()) {
        ble_gap_adv_stop();
    }
    if (!eraseAllBonds()) {
        setError(ESP_FAIL, "erase_bonds");
        return false;
    }
    _pairing_after_disconnect = false;
    _pairing_open             = true;
    enterState(_policy.beginPairing());
    ESP_LOGI(Tag, "limited pairing window opened; previous bond and privacy identity were cleared");
    return startPolicyAdvertising();
}

bool BleHidRemote::eraseAllBonds()
{
    std::array<ble_addr_t, BondScanCapacity> bondedPeers{};
    int bondedCount = 0;
    const int storeResult =
        ble_store_util_bonded_peers(bondedPeers.data(), &bondedCount, static_cast<int>(bondedPeers.size()));
    if (storeResult != 0) {
        ESP_LOGE(Tag, "failed to enumerate bonds for deletion: %d", storeResult);
        return false;
    }
    for (int index = 0; index < bondedCount; ++index) {
        logPeerAddress("unpairing previous computer", bondedPeers[index]);
        const int result = ble_gap_unpair(&bondedPeers[index]);
        if (result != 0 && result != BLE_HS_ENOENT) {
            ESP_LOGE(Tag, "failed to unpair previous computer: %d", result);
            return false;
        }
    }
    ble_gap_wl_set(nullptr, 0);
    _bond_count = 0;
    return true;
}

bool BleHidRemote::refreshSingleBond()
{
    std::array<ble_addr_t, BondScanCapacity> bondedPeers{};
    int bondedCount = 0;
    const int storeResult =
        ble_store_util_bonded_peers(bondedPeers.data(), &bondedCount, static_cast<int>(bondedPeers.size()));
    if (storeResult != 0) {
        ESP_LOGW(Tag, "failed to inspect BLE bonds: %d", storeResult);
        return false;
    }
    if (bondedCount > 1) {
        ESP_LOGW(Tag, "legacy firmware left %d bonds; clearing all to restore the single-host invariant", bondedCount);
        return eraseAllBonds();
    }
    _bond_count = static_cast<uint8_t>(bondedCount);
    return true;
}

bool BleHidRemote::isAllowedPeer(uint16_t connectionHandle)
{
    std::array<ble_addr_t, BondScanCapacity> bondedPeers{};
    int bondedCount = 0;
    const int storeResult =
        ble_store_util_bonded_peers(bondedPeers.data(), &bondedCount, static_cast<int>(bondedPeers.size()));
    if (storeResult != 0) {
        return false;
    }

    ble_gap_conn_desc description{};
    if (ble_gap_conn_find(connectionHandle, &description) != 0) {
        return false;
    }

    logPeerAddress("incoming peer", description.peer_id_addr);
    if (_pairing_open.load()) {
        if (bondedCount != 0) {
            ++_rejected_peer_count;
            ESP_LOGW(Tag, "pairing connection rejected because an old bond still exists");
            return false;
        }
        ESP_LOGI(Tag, "limited pairing window is open; allowing one unbonded central");
        return true;
    }
    if (bondedCount == 1 && (samePeerAddress(description.peer_id_addr, bondedPeers[0]) ||
                             samePeerAddress(description.peer_ota_addr, bondedPeers[0]))) {
        ESP_LOGI(Tag, "sole bonded peer accepted");
        return true;
    }
    ++_rejected_peer_count;
    ESP_LOGW(Tag, "unbonded peer rejected outside the explicit pairing window");
    return false;
}

bool BleHidRemote::commitConnectedPeer(uint16_t connectionHandle)
{
    ble_gap_conn_desc description{};
    if (ble_gap_conn_find(connectionHandle, &description) != 0 || description.sec_state.encrypted == 0 ||
        description.sec_state.bonded == 0) {
        ESP_LOGW(Tag, "cannot commit peer before an encrypted bonded connection exists");
        return false;
    }

    if (!refreshSingleBond() || _bond_count.load() != 1) {
        ESP_LOGE(Tag, "secured connection did not produce exactly one persisted bond");
        return false;
    }
    _pairing_open = false;
    logPeerAddress("committed sole bonded peer", description.peer_id_addr);
    return true;
}

void BleHidRemote::enterState(State state)
{
    _state            = state;
    _advertising_mode = _policy.advertisingMode();
}

void BleHidRemote::enterIdleState()
{
    _advertising_mode        = AdvertisingMode::None;
    _advertising_started_at  = 0;
    _advertising_duration_ms = 0;
}

uint32_t BleHidRemote::advertisingRemainingMs() const
{
    const int32_t duration = _advertising_duration_ms;
    if (duration <= 0 || _advertising_mode.load() == AdvertisingMode::None) {
        return 0;
    }
    const uint32_t elapsed = GetHAL().millis() - _advertising_started_at;
    return elapsed >= static_cast<uint32_t>(duration) ? 0 : static_cast<uint32_t>(duration) - elapsed;
}

void BleHidRemote::handleHidEvent(int32_t eventId, void* eventData)
{
    const auto event = static_cast<esp_hidd_event_t>(eventId);
    switch (event) {
        case ESP_HIDD_START_EVENT:
            startAdvertising();
            break;
        case ESP_HIDD_CONNECT_EVENT:
            break;
        case ESP_HIDD_DISCONNECT_EVENT:
            // GAP is the single source of truth for disconnect reasons and
            // reconnect policy.  The HIDD event intentionally has no policy.
            break;
        case ESP_HIDD_STOP_EVENT:
            break;
        default:
            break;
    }
    (void)eventData;
}

void BleHidRemote::handleDisconnected(uint8_t reason)
{
    stopSpeech(true);
    _speech_subscribed        = false;
    _speech_status_subscribed = false;
    _user_event_subscribed    = false;
    _performance_subscribed   = false;
    _host_status              = HostStatus::Waiting;
    _host_error               = 0;
    _connection_handle        = InvalidConnectionHandle;
    _last_disconnect_reason   = reason;
    enterIdleState();

    if (!_active.load()) {
        return;
    }
    taskENTER_CRITICAL(&_timing_mux);
    _connection_timing.fill(0);
    _connection_timing[ConnectionRemoteStarted] = monotonicUs();
    taskEXIT_CRITICAL(&_timing_mux);
    if (_pairing_after_disconnect || _pairing_open.load()) {
        startPairingWindow();
        return;
    }
    if (!refreshSingleBond()) {
        setError(ESP_FAIL, "disconnect_bonds");
        return;
    }

    enterState(_policy.disconnected(reason, _bond_count.load() != 0, false));
    if (_policy.advertisingMode() != AdvertisingMode::None) {
        startPolicyAdvertising();
    } else {
        ESP_LOGI(Tag, "graceful disconnect; radio remains off until an explicit Reconnect action");
    }
}

int BleHidRemote::handleGapEvent(ble_gap_event* event)
{
    if (event == nullptr) {
        return 0;
    }

    switch (event->type) {
        case BLE_GAP_EVENT_CONNECT: {
            if (event->connect.status != 0) {
                ESP_LOGW(Tag, "connection failed: %d", event->connect.status);
                enterIdleState();
                if (_active.load() && _policy.advertisingMode() != AdvertisingMode::None) {
                    enterState(_policy.advertisingComplete());
                    startPolicyAdvertising();
                }
                break;
            }

            ESP_LOGI(Tag, "computer connected; checking peer before encrypted HID session");
            _connection_handle = event->connect.conn_handle;
            recordConnectionTiming(ConnectionLinkConnected, monotonicUs());
            enterIdleState();
            ble_gap_conn_desc connectedPeer{};
            const bool hasDescription = ble_gap_conn_find(event->connect.conn_handle, &connectedPeer) == 0;
            if (hasDescription) {
                logPeerAddress("connected peer id", connectedPeer.peer_id_addr);
                ESP_LOGI(Tag, "connected peer security encrypted=%u authenticated=%u bonded=%u key_size=%u",
                         connectedPeer.sec_state.encrypted, connectedPeer.sec_state.authenticated,
                         connectedPeer.sec_state.bonded, connectedPeer.sec_state.key_size);
            }
            if (!isAllowedPeer(event->connect.conn_handle)) {
                ESP_LOGW(Tag, "rejecting connection from an unpaired computer");
                ble_gap_terminate(event->connect.conn_handle, BLE_ERR_AUTH_FAIL);
                break;
            }
            if (hasDescription && connectedPeer.sec_state.encrypted != 0 && connectedPeer.sec_state.bonded != 0) {
                recordConnectionTiming(ConnectionEncryptionReady, monotonicUs());
                if (!commitConnectedPeer(event->connect.conn_handle)) {
                    ble_gap_terminate(event->connect.conn_handle, BLE_ERR_AUTH_FAIL);
                    break;
                }
                ESP_LOGI(Tag, "computer connected with encrypted bond");
                enterState(_policy.linkConnected(true));
                configureConnection(event->connect.conn_handle);
            } else {
                ESP_LOGI(Tag, "computer connected; waiting for the central to request pairing");
                enterState(_policy.linkConnected(false));
            }
            break;
        }
        case BLE_GAP_EVENT_ENC_CHANGE:
            if (event->enc_change.status == 0 && _active.load()) {
                ESP_LOGI(Tag, "pairing complete; encrypted connection ready");
                recordConnectionTiming(ConnectionEncryptionReady, monotonicUs());
                if (!commitConnectedPeer(event->enc_change.conn_handle)) {
                    const int result = ble_gap_terminate(event->enc_change.conn_handle, BLE_ERR_AUTH_FAIL);
                    if (result != 0 && result != BLE_HS_ENOTCONN) {
                        ESP_LOGW(Tag, "failed to disconnect uncommitted peer: %d", result);
                    }
                    break;
                }
                enterState(_policy.secured(true));
                configureConnection(event->enc_change.conn_handle);
            } else {
                ESP_LOGW(Tag, "pairing/encryption failed: %d", event->enc_change.status);
                const int result = ble_gap_terminate(event->enc_change.conn_handle, BLE_ERR_AUTH_FAIL);
                if (result != 0 && result != BLE_HS_ENOTCONN) {
                    ESP_LOGW(Tag, "failed to disconnect after pairing error: %d", result);
                }
            }
            break;
        case BLE_GAP_EVENT_DISCONNECT:
            ESP_LOGI(Tag, "computer disconnected: reason=%d", event->disconnect.reason);
            handleDisconnected(static_cast<uint8_t>(event->disconnect.reason));
            break;
        case BLE_GAP_EVENT_SUBSCRIBE:
            if (event->subscribe.attr_handle == _speech_audio_handle) {
                _speech_subscribed = event->subscribe.cur_notify != 0;
                if (_speech_subscribed.load()) {
                    recordConnectionTiming(ConnectionAudioSubscribed, monotonicUs());
                }
                ESP_LOGI(Tag, "speech audio subscription: %s", _speech_subscribed.load() ? "on" : "off");
            } else if (event->subscribe.attr_handle == _speech_status_handle) {
                _speech_status_subscribed = event->subscribe.cur_notify != 0;
                if (_speech_status_subscribed.load()) {
                    recordConnectionTiming(ConnectionStatusSubscribed, monotonicUs());
                }
                ESP_LOGI(Tag, "speech status subscription: %s", _speech_status_subscribed.load() ? "on" : "off");
            } else if (event->subscribe.attr_handle == _user_event_handle) {
                _user_event_subscribed = event->subscribe.cur_notify != 0;
                ESP_LOGI(Tag, "user event subscription: %s", _user_event_subscribed.load() ? "on" : "off");
            } else if (event->subscribe.attr_handle == _performance_handle) {
                _performance_subscribed = event->subscribe.cur_notify != 0;
                ESP_LOGI(Tag, "performance subscription: %s", _performance_subscribed.load() ? "on" : "off");
                if (_performance_subscribed.load()) {
                    recordConnectionTiming(ConnectionPerformanceSubscribed, monotonicUs());
                    sendPerformanceCapabilities();
                    sendConnectionTimingSummary();
                }
            }
            if (isSpeechReady()) {
                sendSpeechStatus(SpeechReady);
            }
            break;
        case BLE_GAP_EVENT_MTU:
            ESP_LOGI(Tag, "ATT MTU updated: %u", event->mtu.value);
            recordConnectionTiming(ConnectionMtuReady, monotonicUs());
            if (isSpeechReady()) {
                sendSpeechStatus(SpeechReady);
            }
            break;
        case BLE_GAP_EVENT_ADV_COMPLETE:
            ESP_LOGI(Tag, "advertising complete: reason=%d", event->adv_complete.reason);
            if (_advertising_mode.load() == AdvertisingMode::None) {
                break;
            }
            enterIdleState();
            enterState(_policy.advertisingComplete());
            if (_policy.advertisingMode() != AdvertisingMode::None && _active.load()) {
                startPolicyAdvertising();
            } else if (_state.load() == State::UnpairedIdle) {
                _pairing_open = false;
                ESP_LOGI(Tag, "limited pairing window expired; radio is off");
            } else {
                ESP_LOGI(Tag, "bounded reconnect window expired; radio is off");
            }
            break;
        case BLE_GAP_EVENT_REPEAT_PAIRING:
            ESP_LOGW(Tag, "repeat pairing ignored; use the destructive Pair New action instead");
            return BLE_GAP_REPEAT_PAIRING_IGNORE;
        default:
            break;
    }
    return 0;
}

void BleHidRemote::runReportWorker()
{
    while (true) {
        Command command;
        if (xQueueReceive(_command_queue, &command, portMAX_DELAY) != pdTRUE) {
            continue;
        }

        if (command.type == CommandType::Stop) {
            break;
        }
        if (!isConnected() || _hid_device == nullptr) {
            continue;
        }

        if (command.type == CommandType::KeyTap) {
            sendKeyboardReport(static_cast<uint8_t>(command.value), command.modifier);
        } else if (command.type == CommandType::Wheel) {
            sendMouseWheelReport(static_cast<int8_t>(command.value));
        } else if (command.type == CommandType::MouseClick) {
            sendMouseClickReport(static_cast<uint8_t>(command.value));
        }
    }

    _report_worker_running = false;
}

void BleHidRemote::sendKeyboardReport(uint8_t keyCode, uint8_t modifiers)
{
    std::array<uint8_t, 8> report{};
    report[0] = modifiers;
    report[2] = keyCode;
    esp_hidd_dev_input_set(_hid_device, 0, KeyboardReportId, report.data(), report.size());
    vTaskDelay(pdMS_TO_TICKS(12));
    report.fill(0);
    if (_hid_device != nullptr) {
        esp_hidd_dev_input_set(_hid_device, 0, KeyboardReportId, report.data(), report.size());
    }
}

void BleHidRemote::sendMouseWheelReport(int8_t delta)
{
    std::array<uint8_t, 4> report{};
    report[3] = static_cast<uint8_t>(delta);
    esp_hidd_dev_input_set(_hid_device, 0, MouseReportId, report.data(), report.size());
}

void BleHidRemote::sendMouseClickReport(uint8_t buttons)
{
    std::array<uint8_t, 4> report{};
    report[0] = buttons;
    esp_hidd_dev_input_set(_hid_device, 0, MouseReportId, report.data(), report.size());
    vTaskDelay(pdMS_TO_TICKS(20));
    report.fill(0);
    if (_hid_device != nullptr) {
        esp_hidd_dev_input_set(_hid_device, 0, MouseReportId, report.data(), report.size());
    }
}

void BleHidRemote::configureConnection(uint16_t connectionHandle)
{
    // GAP recommends that a Peripheral wait at least five seconds before it
    // requests a connection-parameter update.  We therefore leave the
    // Central-selected parameters alone here and request low latency only
    // later, when the user explicitly starts a speech session.
    _connected_at = GetHAL().millis();
    int result    = ble_gap_set_data_len(connectionHandle, 251, 2120);
    if (result != 0) {
        ESP_LOGW(Tag, "data length update failed: %d", result);
    }
    result = ble_gap_set_prefered_le_phy(connectionHandle, BLE_GAP_LE_PHY_2M_MASK, BLE_GAP_LE_PHY_2M_MASK,
                                         BLE_GAP_LE_PHY_CODED_ANY);
    if (result != 0) {
        ESP_LOGW(Tag, "2M PHY request failed; continuing on 1M PHY: %d", result);
    }
    updateBatteryLevel(true);
}

void BleHidRemote::requestLowLatencyConnection(uint16_t connectionHandle)
{
    if (connectionHandle == InvalidConnectionHandle) {
        return;
    }
    if (GetHAL().millis() - _connected_at < ConnectionParameterDelayMs) {
        ESP_LOGI(Tag, "keeping Central-selected parameters during the first five seconds");
        return;
    }
    ble_gap_upd_params parameters{};
    parameters.itvl_min            = 12;  // 15 ms
    parameters.itvl_max            = 24;  // 30 ms
    parameters.latency             = 0;
    parameters.supervision_timeout = 400;  // 4 seconds
    parameters.min_ce_len          = 0;
    parameters.max_ce_len          = 0;
    const int result               = ble_gap_update_params(connectionHandle, &parameters);
    if (result != 0 && result != BLE_HS_EALREADY) {
        ESP_LOGW(Tag, "speech connection parameter update failed: %d", result);
    }
}

void BleHidRemote::updateBatteryLevel(bool force)
{
    if (!isConnected() || _hid_device == nullptr) {
        return;
    }
    const uint8_t level = std::min<uint8_t>(GetHAL().getBatteryLevel(), 100);
    if (!force && level == _last_battery_level) {
        return;
    }
    const esp_err_t result = esp_hidd_dev_battery_set(_hid_device, level);
    if (result == ESP_OK) {
        _last_battery_level = level;
    } else {
        ESP_LOGW(Tag, "battery service update failed: %s", esp_err_to_name(result));
    }
}

std::array<uint8_t, 12> BleHidRemote::buildSpeechStatusPacket(uint8_t event, uint16_t error) const
{
    std::array<uint8_t, 12> packet{};
    packet[0]  = SpeechProtocolVersion;
    packet[1]  = event;
    packet[2]  = static_cast<uint8_t>(_speech_session & 0xFF);
    packet[3]  = static_cast<uint8_t>(_speech_session >> 8);
    packet[4]  = static_cast<uint8_t>(SpeechSampleRate & 0xFF);
    packet[5]  = static_cast<uint8_t>(SpeechSampleRate >> 8);
    packet[6]  = static_cast<uint8_t>(speech::OutputSamplesPerFrame & 0xFF);
    packet[7]  = static_cast<uint8_t>(speech::OutputSamplesPerFrame >> 8);
    packet[8]  = SpeechCodecImaAdpcm;
    packet[9]  = _speech_active.load() ? 1 : 0;
    packet[10] = static_cast<uint8_t>(error & 0xFF);
    packet[11] = static_cast<uint8_t>(error >> 8);
    return packet;
}

bool BleHidRemote::sendSpeechStatus(uint8_t event, uint16_t error)
{
    if (!_speech_status_subscribed.load()) {
        return false;
    }
    const uint16_t connectionHandle = _connection_handle.load();
    if (connectionHandle == InvalidConnectionHandle || _speech_status_handle == 0) {
        return false;
    }

    const auto packet = buildSpeechStatusPacket(event, error);

    os_mbuf* buffer = ble_hs_mbuf_from_flat(packet.data(), packet.size());
    if (buffer == nullptr) {
        return false;
    }
    return ble_gatts_notify_custom(connectionHandle, _speech_status_handle, buffer) == 0;
}

bool BleHidRemote::sendSpeechAudio(const uint8_t* adpcm, std::size_t length)
{
    if (!_speech_subscribed.load() || adpcm == nullptr || length != speech::AdpcmBlockBytes) {
        return false;
    }
    const uint16_t connectionHandle = _connection_handle.load();
    if (connectionHandle == InvalidConnectionHandle || ble_att_mtu(connectionHandle) < MinimumSpeechMtu) {
        return false;
    }

    std::array<uint8_t, 8 + speech::AdpcmBlockBytes> packet{};
    packet[0] = SpeechProtocolVersion;
    packet[1] = 1;  // Audio frame.
    packet[2] = static_cast<uint8_t>(_speech_session & 0xFF);
    packet[3] = static_cast<uint8_t>(_speech_session >> 8);
    packet[4] = static_cast<uint8_t>(_speech_sequence & 0xFF);
    packet[5] = static_cast<uint8_t>(_speech_sequence >> 8);
    packet[6] = static_cast<uint8_t>(speech::OutputSamplesPerFrame & 0xFF);
    packet[7] = static_cast<uint8_t>(speech::OutputSamplesPerFrame >> 8);
    std::memcpy(packet.data() + 8, adpcm, length);

    os_mbuf* buffer = ble_hs_mbuf_from_flat(packet.data(), packet.size());
    if (buffer == nullptr) {
        return false;
    }
    const int result = ble_gatts_notify_custom(connectionHandle, _speech_audio_handle, buffer);
    if (result == 0) {
        ++_speech_sequence;
        return true;
    }
    ESP_LOGW(Tag, "speech notification failed: %d", result);
    return false;
}

void BleHidRemote::recordSpeechTiming(SpeechTimingIndex index, uint64_t timestampUs)
{
    taskENTER_CRITICAL(&_timing_mux);
    _speech_timing.timestampUs[index] = timestampUs;
    taskEXIT_CRITICAL(&_timing_mux);
}

void BleHidRemote::recordConnectionTiming(ConnectionTimingIndex index, uint64_t timestampUs)
{
    taskENTER_CRITICAL(&_timing_mux);
    _connection_timing[index] = timestampUs;
    taskEXIT_CRITICAL(&_timing_mux);
}

bool BleHidRemote::sendPerformancePacket(const uint8_t* data, std::size_t length)
{
    if (!_performance_subscribed.load() || data == nullptr || length == 0) {
        return false;
    }
    const uint16_t connectionHandle = _connection_handle.load();
    if (connectionHandle == InvalidConnectionHandle || _performance_handle == 0) {
        return false;
    }
    os_mbuf* buffer = ble_hs_mbuf_from_flat(data, length);
    return buffer != nullptr && ble_gatts_notify_custom(connectionHandle, _performance_handle, buffer) == 0;
}

bool BleHidRemote::sendPerformanceCapabilities()
{
    std::array<uint8_t, 4> packet{PerformanceWireVersion, PerformanceCapabilities, 0x03, 0x00};
    return sendPerformancePacket(packet.data(), packet.size());
}

bool BleHidRemote::sendSpeechTimingSummary()
{
    SpeechTiming timing{};
    taskENTER_CRITICAL(&_timing_mux);
    timing = _speech_timing;
    taskEXIT_CRITICAL(&_timing_mux);

    std::array<uint8_t, PerformanceSessionBytes> packet{};
    size_t offset    = 0;
    packet[offset++] = PerformanceWireVersion;
    packet[offset++] = PerformanceSession;
    put16(packet, offset, _speech_session);
    uint16_t flags = 0;
    for (size_t index = 0; index < timing.timestampUs.size(); ++index) {
        if (timing.timestampUs[index] != 0) {
            flags |= static_cast<uint16_t>(1U << index);
        }
    }
    put16(packet, offset, flags);
    put16(packet, offset, timing.frameCount);
    put16(packet, offset, timing.notifyFailures);
    for (const uint64_t timestamp : timing.timestampUs) {
        put64(packet, offset, timestamp);
    }
    const std::array<TimingAggregate, 4> aggregates{
        timing.capture,
        timing.resample,
        timing.encode,
        timing.notify,
    };
    for (const auto& aggregate : aggregates) {
        put32(packet, offset, aggregate.totalUs > UINT32_MAX ? UINT32_MAX : static_cast<uint32_t>(aggregate.totalUs));
        put32(packet, offset, aggregate.maxUs);
    }
    return offset == packet.size() && sendPerformancePacket(packet.data(), packet.size());
}

bool BleHidRemote::sendConnectionTimingSummary()
{
    std::array<uint64_t, ConnectionTimingCount> timing{};
    taskENTER_CRITICAL(&_timing_mux);
    timing = _connection_timing;
    taskEXIT_CRITICAL(&_timing_mux);

    std::array<uint8_t, PerformanceConnectionBytes> packet{};
    size_t offset    = 0;
    packet[offset++] = PerformanceWireVersion;
    packet[offset++] = PerformanceConnection;
    uint16_t flags   = 0;
    for (size_t index = 0; index < timing.size(); ++index) {
        if (timing[index] != 0) {
            flags |= static_cast<uint16_t>(1U << index);
        }
    }
    put16(packet, offset, flags);
    for (const uint64_t timestamp : timing) {
        put64(packet, offset, timestamp);
    }
    return offset == packet.size() && sendPerformancePacket(packet.data(), packet.size());
}

int BleHidRemote::readPerformance(ble_gatt_access_ctxt* context)
{
    const std::array<uint8_t, 4> packet{PerformanceWireVersion, PerformanceCapabilities, 0x03, 0x00};
    return os_mbuf_append(context->om, packet.data(), packet.size()) == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}

int BleHidRemote::writePerformance(ble_gatt_access_ctxt* context)
{
    if (OS_MBUF_PKTLEN(context->om) != 4) {
        return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    }
    std::array<uint8_t, 4> request{};
    const uint64_t receivedAt = monotonicUs();
    if (os_mbuf_copydata(context->om, 0, request.size(), request.data()) != 0 || request[0] != PerformanceWireVersion ||
        request[1] != PerformanceSyncRequest) {
        return BLE_ATT_ERR_UNLIKELY;
    }
    const uint16_t sequence = static_cast<uint16_t>(request[2] | (static_cast<uint16_t>(request[3]) << 8));
    std::array<uint8_t, 20> response{};
    size_t offset      = 0;
    response[offset++] = PerformanceWireVersion;
    response[offset++] = PerformanceSyncResponse;
    put16(response, offset, sequence);
    put64(response, offset, receivedAt);
    put64(response, offset, monotonicUs());
    return sendPerformancePacket(response.data(), response.size()) ? 0 : BLE_ATT_ERR_UNLIKELY;
}

void BleHidRemote::runSpeechWorker()
{
    std::array<int16_t, speech::InputSamplesPerFrame> input{};
    std::array<int16_t, speech::OutputSamplesPerFrame> resampled{};
    std::array<uint8_t, speech::AdpcmBlockBytes> encoded{};
    int stepIndex      = 0;
    uint16_t errorCode = 0;

    recordSpeechTiming(TimingWorkerStarted, monotonicUs());
    while (_speech_active.load()) {
        const uint64_t captureStarted = monotonicUs();
        if (!GetHAL().audioReadSamples(input.data(), input.size(), 30.0f)) {
            errorCode = static_cast<uint16_t>(ESP_FAIL);
            break;
        }
        const uint64_t captureDone     = monotonicUs();
        const uint64_t resampleStarted = captureDone;
        speech::resample44k1To16k(input.data(), resampled);
        const uint64_t resampleDone  = monotonicUs();
        const uint64_t encodeStarted = resampleDone;
        speech::encodeImaAdpcm(resampled, encoded, stepIndex);
        const uint64_t encodeDone    = monotonicUs();
        const uint64_t notifyStarted = encodeDone;
        const bool sent              = sendSpeechAudio(encoded.data(), encoded.size());
        const uint64_t notifyDone    = monotonicUs();
        taskENTER_CRITICAL(&_timing_mux);
        _speech_timing.capture.observe(captureDone - captureStarted);
        _speech_timing.resample.observe(resampleDone - resampleStarted);
        _speech_timing.encode.observe(encodeDone - encodeStarted);
        _speech_timing.notify.observe(notifyDone - notifyStarted);
        _speech_timing.frameCount = _speech_sequence;
        if (_speech_timing.timestampUs[TimingFirstCaptureDone] == 0) {
            _speech_timing.timestampUs[TimingFirstCaptureDone]  = captureDone;
            _speech_timing.timestampUs[TimingFirstResampleDone] = resampleDone;
            _speech_timing.timestampUs[TimingFirstEncodeDone]   = encodeDone;
            if (sent) {
                _speech_timing.timestampUs[TimingFirstAudioSent] = notifyDone;
            }
        }
        if (!sent && _speech_timing.notifyFailures != UINT16_MAX) {
            ++_speech_timing.notifyFailures;
        }
        taskEXIT_CRITICAL(&_timing_mux);
        if (!sent) {
            errorCode = static_cast<uint16_t>(ESP_FAIL);
            break;
        }
    }

    recordSpeechTiming(TimingWorkerExited, monotonicUs());
    const bool aborted = _speech_abort_requested.load() || errorCode != 0;
    _speech_active     = false;
    if (errorCode != 0) {
        sendSpeechStatus(SpeechError, errorCode);
    } else {
        sendSpeechStatus(aborted ? SpeechAbort : SpeechEnd);
    }
    recordSpeechTiming(TimingStatusEndSent, monotonicUs());
    sendSpeechTimingSummary();
    const UBaseType_t stackFree = uxTaskGetStackHighWaterMark(nullptr);
    ESP_LOGI(Tag, "speech session %u %s after %u frames, min free stack=%u bytes", _speech_session,
             aborted ? "aborted" : "ended", _speech_sequence, static_cast<unsigned>(stackFree));
    _speech_worker_running = false;
    _speech_worker_task    = nullptr;
}

void BleHidRemote::waitForSpeechWorker()
{
    _speech_active = false;
    for (int attempt = 0; attempt < 100 && _speech_worker_running.load(); ++attempt) {
        vTaskDelay(pdMS_TO_TICKS(5));
    }
    if (_speech_worker_running.load() && _speech_worker_task != nullptr) {
        vTaskDelete(_speech_worker_task);
        _speech_worker_running = false;
        _speech_worker_task    = nullptr;
    }
}

int BleHidRemote::readSpeechStatus(ble_gatt_access_ctxt* context)
{
    const uint8_t event = _speech_active.load() ? SpeechStart : SpeechReady;
    const auto packet   = buildSpeechStatusPacket(event);
    return os_mbuf_append(context->om, packet.data(), packet.size()) == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}

int BleHidRemote::readMappingConfig(ble_gatt_access_ctxt* context)
{
    std::array<uint8_t, UserEventMapper::WireHeaderSize + UserEventMapper::MaxRecords * UserEventMapper::WireRecordSize>
        packet{};
    const std::size_t length = _mapping.writeWire(packet.data(), packet.size());
    if (length == 0) {
        return BLE_ATT_ERR_UNLIKELY;
    }
    return os_mbuf_append(context->om, packet.data(), length) == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}

int BleHidRemote::writeMappingConfig(ble_gatt_access_ctxt* context)
{
    const uint16_t length = OS_MBUF_PKTLEN(context->om);
    if (length < UserEventMapper::WireHeaderSize ||
        length > UserEventMapper::WireHeaderSize + UserEventMapper::MaxRecords * UserEventMapper::WireRecordSize) {
        return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    }

    std::array<uint8_t, UserEventMapper::WireHeaderSize + UserEventMapper::MaxRecords * UserEventMapper::WireRecordSize>
        packet{};
    if (os_mbuf_copydata(context->om, 0, length, packet.data()) != 0) {
        return BLE_ATT_ERR_UNLIKELY;
    }
    if (!_mapping.updateFromWire(packet.data(), length)) {
        ESP_LOGW(Tag, "invalid mapping config write length=%u", length);
        return BLE_ATT_ERR_UNLIKELY;
    }
    if (!_mapping.save()) {
        return BLE_ATT_ERR_UNLIKELY;
    }
    ESP_LOGI(Tag, "mapping config updated over BLE");
    return 0;
}

int BleHidRemote::readUserEvent(ble_gatt_access_ctxt* context)
{
    std::array<uint8_t, 8> packet{};
    packet[0] = UserEventMapper::MappingVersion;
    packet[5] = static_cast<uint8_t>(_user_event_sequence & 0xFF);
    packet[6] = static_cast<uint8_t>(_user_event_sequence >> 8);
    return os_mbuf_append(context->om, packet.data(), packet.size()) == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}

int BleHidRemote::writeHostStatus(ble_gatt_access_ctxt* context)
{
    if (OS_MBUF_PKTLEN(context->om) != 4) {
        return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    }
    std::array<uint8_t, 4> packet{};
    if (os_mbuf_copydata(context->om, 0, packet.size(), packet.data()) != 0) {
        return BLE_ATT_ERR_UNLIKELY;
    }
    if (packet[0] != SpeechProtocolVersion || packet[1] > static_cast<uint8_t>(HostStatus::HostError)) {
        return BLE_ATT_ERR_UNLIKELY;
    }
    _host_status = static_cast<HostStatus>(packet[1]);
    _host_error  = static_cast<uint16_t>(packet[2] | (packet[3] << 8));
    ESP_LOGI(Tag, "desktop helper status: %u, error: %u", packet[1], _host_error.load());
    if (isSpeechReady()) {
        sendSpeechStatus(SpeechReady);
    }
    return 0;
}

int BleHidRemote::writeActionExecute(ble_gatt_access_ctxt* context)
{
    if (OS_MBUF_PKTLEN(context->om) != 8) {
        return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    }
    std::array<uint8_t, 8> packet{};
    if (os_mbuf_copydata(context->om, 0, packet.size(), packet.data()) != 0) {
        return BLE_ATT_ERR_UNLIKELY;
    }
    if (packet[0] != UserEventMapper::MappingVersion) {
        return BLE_ATT_ERR_UNLIKELY;
    }

    const auto action    = static_cast<UserActionType>(packet[1]);
    const uint8_t param0 = packet[2];
    const uint8_t param1 = packet[3];
    const int16_t param2 = static_cast<int16_t>(packet[4] | (packet[5] << 8));
    bool handled         = false;

    switch (action) {
        case UserActionType::None:
            handled = true;
            break;
        case UserActionType::HidKeyboardTap:
            handled = sendKeyboardShortcut(param0, param1);
            break;
        case UserActionType::HidMouseWheel: {
            int delta = param2 == 0 ? 1 : param2;
            delta *= param0 == 0 ? 1 : param0;
            if (param1 != 0) {
                delta = -delta;
            }
            delta   = std::clamp(delta, -127, 127);
            handled = sendWheel(static_cast<int8_t>(delta));
            break;
        }
        case UserActionType::HidMouseClick:
            handled = sendMouseClick(param0 == 0 ? 1 : param0);
            break;
        case UserActionType::HidMediaControl:
            handled = sendMediaControl(static_cast<uint16_t>(param2));
            break;
        case UserActionType::DevicePairNewComputer:
            handled = pairNewComputer();
            break;
        default:
            handled = false;
            break;
    }

    ESP_LOGI(Tag, "host action execute action=%u handled=%d", static_cast<unsigned>(packet[1]), handled ? 1 : 0);
    return handled ? 0 : BLE_ATT_ERR_UNLIKELY;
}

int BleHidRemote::speechGattAccess(uint16_t connectionHandle, uint16_t attributeHandle, ble_gatt_access_ctxt* context,
                                   void* argument)
{
    (void)connectionHandle;
    (void)argument;
    if (ActiveInstance == nullptr || context == nullptr) {
        return BLE_ATT_ERR_UNLIKELY;
    }

    auto* instance = ActiveInstance;
    if (context->op == BLE_GATT_ACCESS_OP_READ_CHR && attributeHandle == instance->_speech_status_handle) {
        return instance->readSpeechStatus(context);
    }
    if (context->op == BLE_GATT_ACCESS_OP_READ_CHR && attributeHandle == instance->_speech_audio_handle) {
        return 0;
    }
    if (context->op == BLE_GATT_ACCESS_OP_WRITE_CHR && attributeHandle == instance->_host_status_handle) {
        return instance->writeHostStatus(context);
    }
    if (attributeHandle == instance->_performance_handle) {
        if (context->op == BLE_GATT_ACCESS_OP_READ_CHR) {
            return instance->readPerformance(context);
        }
        if (context->op == BLE_GATT_ACCESS_OP_WRITE_CHR) {
            return instance->writePerformance(context);
        }
    }
    return BLE_ATT_ERR_UNLIKELY;
}

int BleHidRemote::controlGattAccess(uint16_t connectionHandle, uint16_t attributeHandle, ble_gatt_access_ctxt* context,
                                    void* argument)
{
    (void)connectionHandle;
    (void)argument;
    if (ActiveInstance == nullptr || context == nullptr) {
        return BLE_ATT_ERR_UNLIKELY;
    }

    auto* instance = ActiveInstance;
    if (attributeHandle == instance->_mapping_config_handle) {
        if (context->op == BLE_GATT_ACCESS_OP_READ_CHR) {
            return instance->readMappingConfig(context);
        }
        if (context->op == BLE_GATT_ACCESS_OP_WRITE_CHR) {
            return instance->writeMappingConfig(context);
        }
    }
    if (context->op == BLE_GATT_ACCESS_OP_READ_CHR && attributeHandle == instance->_user_event_handle) {
        return instance->readUserEvent(context);
    }
    if (context->op == BLE_GATT_ACCESS_OP_WRITE_CHR && attributeHandle == instance->_action_exec_handle) {
        return instance->writeActionExecute(context);
    }
    return BLE_ATT_ERR_UNLIKELY;
}

void BleHidRemote::setError(int error, const char* stage)
{
    _last_error       = error;
    _last_error_stage = stage == nullptr ? "unknown" : stage;
    enterState(_policy.fail());
    ESP_LOGE(Tag, "BLE error stage=%s code=%d", _last_error_stage.load(), error);
}

void BleHidRemote::hostTask(void* parameter)
{
    (void)parameter;
    auto* self = ActiveInstance;

    nimble_port_run();
    if (self != nullptr) {
        self->_host_running = false;
    }
    nimble_port_freertos_deinit();
}

void BleHidRemote::reportWorkerTask(void* parameter)
{
    auto* self = static_cast<BleHidRemote*>(parameter);
    if (self != nullptr) {
        self->runReportWorker();
    }
    vTaskDelete(nullptr);
}

void BleHidRemote::speechWorkerTask(void* parameter)
{
    auto* self = static_cast<BleHidRemote*>(parameter);
    if (self != nullptr) {
        self->runSpeechWorker();
    }
    vTaskDelete(nullptr);
}

void BleHidRemote::hidEventCallback(void* handlerArgs, const char* eventBase, int32_t eventId, void* eventData)
{
    (void)handlerArgs;
    (void)eventBase;

    // esp_hidd does not preserve an application callback argument.
    if (ActiveInstance != nullptr) {
        ActiveInstance->handleHidEvent(eventId, eventData);
    }
}

int BleHidRemote::gapEventCallback(ble_gap_event* event, void* argument)
{
    auto* self = static_cast<BleHidRemote*>(argument);
    return self != nullptr ? self->handleGapEvent(event) : 0;
}

const char* bleHidStateToString(BleHidRemote::State state)
{
    return bleConnectionStateToString(state);
}

const char* speechServiceStateToString(BleHidRemote::SpeechServiceState state)
{
    switch (state) {
        case BleHidRemote::SpeechServiceState::Disconnected:
            return "Disconnected";
        case BleHidRemote::SpeechServiceState::BluetoothConnected:
            return "Bluetooth connected";
        case BleHidRemote::SpeechServiceState::Connecting:
            return "Speech service connecting";
        case BleHidRemote::SpeechServiceState::Preparing:
            return "Speech service preparing";
        case BleHidRemote::SpeechServiceState::Ready:
            return "Speech service ready";
        case BleHidRemote::SpeechServiceState::Listening:
            return "Listening";
        case BleHidRemote::SpeechServiceState::Recognizing:
            return "Recognizing";
        case BleHidRemote::SpeechServiceState::PermissionError:
            return "Permission error";
        case BleHidRemote::SpeechServiceState::ModelError:
            return "Model error";
        case BleHidRemote::SpeechServiceState::HostError:
            return "Host error";
        case BleHidRemote::SpeechServiceState::MtuTooSmall:
            return "MTU too small";
        default:
            return "Unknown";
    }
}

}  // namespace model
