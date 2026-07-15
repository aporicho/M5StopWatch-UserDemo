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

constexpr uint8_t KeyboardReportId = 1;
constexpr uint8_t MouseReportId    = 2;

constexpr uint8_t SpeechProtocolVersion = 1;
constexpr uint8_t SpeechCodecImaAdpcm   = 1;
constexpr uint16_t SpeechSampleRate     = 16000;
constexpr uint16_t MinimumSpeechMtu     = 185;

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
const ble_uuid128_t SpeechStatusUuid =
    BLE_UUID128_INIT(0x01, 0x9a, 0x1f, 0x8b, 0x0d, 0x5e, 0xc0, 0xa7, 0x6d, 0x4c, 0x2e, 0x6b, 0x01, 0x10, 0x3a, 0x7f);
const ble_uuid128_t SpeechAudioUuid =
    BLE_UUID128_INIT(0x01, 0x9a, 0x1f, 0x8b, 0x0d, 0x5e, 0xc0, 0xa7, 0x6d, 0x4c, 0x2e, 0x6b, 0x02, 0x10, 0x3a, 0x7f);
const ble_uuid128_t HostStatusUuid =
    BLE_UUID128_INIT(0x01, 0x9a, 0x1f, 0x8b, 0x0d, 0x5e, 0xc0, 0xa7, 0x6d, 0x4c, 0x2e, 0x6b, 0x03, 0x10, 0x3a, 0x7f);

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

bool sameAddress(const ble_addr_t& left, const ble_addr_t& right)
{
    return ble_addr_cmp(&left, &right) == 0;
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

    _state                    = State::Starting;
    _last_error               = ESP_OK;
    _active                   = true;
    _speech_active            = false;
    _speech_abort_requested   = false;
    _speech_subscribed        = false;
    _speech_status_subscribed = false;
    _host_status              = HostStatus::Waiting;
    _host_error               = 0;

    _command_queue = xQueueCreate(16, sizeof(Command));
    if (_command_queue == nullptr) {
        setError(ESP_ERR_NO_MEM);
        _active = false;
        return false;
    }

    _report_worker_running = true;
    if (xTaskCreate(reportWorkerTask, "ble_hid_reports", 4 * 1024, this, 2, &_report_worker_task) != pdPASS) {
        _report_worker_running = false;
        vQueueDelete(_command_queue);
        _command_queue = nullptr;
        setError(ESP_ERR_NO_MEM);
        _active = false;
        return false;
    }

    if (!initializeBluetooth()) {
        const int error = _last_error.load();
        stop();
        setError(error);
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
    _connection_handle = InvalidConnectionHandle;
    _state             = State::Stopped;
    ESP_LOGI(Tag, "BLE HID stopped");
}

bool BleHidRemote::sendKeyTap(Key key)
{
    if (!isConnected() || _command_queue == nullptr) {
        return false;
    }

    const Command command{
        .type  = CommandType::KeyTap,
        .value = static_cast<int8_t>(key),
    };
    return xQueueSend(_command_queue, &command, 0) == pdTRUE;
}

bool BleHidRemote::sendWheel(int8_t delta)
{
    if (!isConnected() || delta == 0 || _command_queue == nullptr) {
        return false;
    }

    const Command command{
        .type  = CommandType::Wheel,
        .value = delta,
    };
    return xQueueSend(_command_queue, &command, 0) == pdTRUE;
}

bool BleHidRemote::isSpeechReady() const
{
    const uint16_t handle       = _connection_handle.load();
    const HostStatus hostStatus = _host_status.load();
    const bool hostReady        = hostStatus == HostStatus::Waiting || hostStatus == HostStatus::Ready;
    return isConnected() && handle != InvalidConnectionHandle && _speech_subscribed.load() &&
           _speech_status_subscribed.load() && hostReady && ble_att_mtu(handle) >= MinimumSpeechMtu;
}

bool BleHidRemote::startSpeech()
{
    if (_speech_active.load() || _speech_worker_running.load() || !isSpeechReady()) {
        return false;
    }

    ++_speech_session;
    if (_speech_session == 0) {
        ++_speech_session;
    }
    _speech_sequence        = 0;
    _speech_abort_requested = false;
    _speech_active          = true;

    if (!sendSpeechStatus(SpeechStart)) {
        _speech_active = false;
        return false;
    }

    _speech_worker_running = true;
    if (xTaskCreate(speechWorkerTask, "ble_speech", 5 * 1024, this, 4, &_speech_worker_task) != pdPASS) {
        _speech_worker_running = false;
        _speech_active         = false;
        sendSpeechStatus(SpeechError, ESP_ERR_NO_MEM);
        return false;
    }

    ESP_LOGI(Tag, "speech session %u started", _speech_session);
    return true;
}

void BleHidRemote::stopSpeech(bool abort)
{
    if (abort) {
        _speech_abort_requested = true;
    }
    _speech_active = false;
}

bool BleHidRemote::forgetBond()
{
    if (!_active.load() || !_nimble_initialized) {
        return false;
    }

    const uint16_t handle     = _connection_handle.load();
    bool waitingForDisconnect = false;
    if (handle != InvalidConnectionHandle) {
        const int terminateResult = ble_gap_terminate(handle, BLE_ERR_REM_USER_CONN_TERM);
        if (terminateResult == 0) {
            waitingForDisconnect = true;
        } else if (terminateResult != BLE_HS_ENOTCONN) {
            ESP_LOGE(Tag, "failed to disconnect before clearing bond: %d", terminateResult);
            setError(terminateResult);
            return false;
        }
    }

    const int result = ble_store_clear();
    if (result != 0) {
        ESP_LOGE(Tag, "failed to clear BLE bonds: %d", result);
        setError(result);
        return false;
    }

    ESP_LOGI(Tag, "BLE bonds cleared");
    _state = State::Advertising;
    if (waitingForDisconnect) {
        return true;
    }

    _connection_handle = InvalidConnectionHandle;
    if (ble_gap_adv_active()) {
        ble_gap_adv_stop();
    }
    return startAdvertising();
}

bool BleHidRemote::initializeBluetooth()
{
    ActiveInstance = this;

    esp_bt_controller_config_t controller_config = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    esp_err_t result                             = esp_bt_controller_init(&controller_config);
    if (result != ESP_OK) {
        setError(result);
        return false;
    }
    _controller_initialized = true;

    result = esp_bt_controller_enable(ESP_BT_MODE_BLE);
    if (result != ESP_OK) {
        setError(result);
        return false;
    }
    _controller_enabled = true;

    result = esp_nimble_init();
    if (result != ESP_OK) {
        setError(result);
        return false;
    }
    _nimble_initialized = true;

    const int mtuResult = ble_att_set_preferred_mtu(247);
    if (mtuResult != 0) {
        setError(mtuResult);
        return false;
    }

    ble_hs_cfg.sm_io_cap         = BLE_SM_IO_CAP_DISP_ONLY;
    ble_hs_cfg.sm_bonding        = 1;
    ble_hs_cfg.sm_mitm           = 1;
    ble_hs_cfg.sm_sc             = 1;
    ble_hs_cfg.sm_our_key_dist   = BLE_SM_PAIR_KEY_DIST_ID | BLE_SM_PAIR_KEY_DIST_ENC;
    ble_hs_cfg.sm_their_key_dist = BLE_SM_PAIR_KEY_DIST_ID | BLE_SM_PAIR_KEY_DIST_ENC;

    ble_store_config_init();
    ble_hs_cfg.store_status_cb = ble_store_util_status_rr;

    result = esp_hidd_dev_init(&HidConfig, ESP_HID_TRANSPORT_BLE,
                               reinterpret_cast<esp_event_handler_t>(hidEventCallback), &_hid_device);
    if (result != ESP_OK) {
        setError(result);
        return false;
    }

    if (!registerSpeechService()) {
        return false;
    }

    const int nameResult = ble_svc_gap_device_name_set(DeviceName);
    if (nameResult != 0) {
        setError(nameResult);
        return false;
    }

    _host_running = true;
    result        = esp_nimble_enable(reinterpret_cast<void*>(hostTask));
    if (result != ESP_OK) {
        _host_running = false;
        setError(result);
        return false;
    }

    return true;
}

bool BleHidRemote::registerSpeechService()
{
    static ble_gatt_chr_def characteristics[4]{};
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
    }

    int result = ble_gatts_count_cfg(services);
    if (result == 0) {
        result = ble_gatts_add_svcs(services);
    }
    if (result != 0) {
        ESP_LOGE(Tag, "failed to register speech GATT service: %d", result);
        setError(result);
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
    if (ble_gap_adv_active()) {
        return true;
    }

    ble_uuid16_t hid_uuid = BLE_UUID16_INIT(0x1812);
    ble_hs_adv_fields fields{};
    fields.flags                 = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.appearance            = ESP_HID_APPEARANCE_GENERIC;
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
        setError(result);
        return false;
    }

    ble_gap_adv_params parameters{};
    parameters.conn_mode = BLE_GAP_CONN_MODE_UND;
    parameters.disc_mode = BLE_GAP_DISC_MODE_GEN;
    parameters.itvl_min  = BLE_GAP_ADV_ITVL_MS(30);
    parameters.itvl_max  = BLE_GAP_ADV_ITVL_MS(50);

    result = ble_gap_adv_start(BLE_OWN_ADDR_PUBLIC, nullptr, BLE_HS_FOREVER, &parameters, gapEventCallback, this);
    if (result != 0 && result != BLE_HS_EALREADY) {
        ESP_LOGE(Tag, "failed to start advertising: %d", result);
        setError(result);
        return false;
    }

    _state = State::Advertising;
    return true;
}

bool BleHidRemote::isAllowedPeer(uint16_t connectionHandle)
{
    std::array<ble_addr_t, 1> bonded_peers{};
    int bonded_count = 0;
    if (ble_store_util_bonded_peers(bonded_peers.data(), &bonded_count, static_cast<int>(bonded_peers.size())) != 0 ||
        bonded_count == 0) {
        return true;
    }

    ble_gap_conn_desc description{};
    if (ble_gap_conn_find(connectionHandle, &description) != 0) {
        return false;
    }

    return sameAddress(description.peer_id_addr, bonded_peers[0]) ||
           sameAddress(description.peer_ota_addr, bonded_peers[0]);
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
            _connection_handle = InvalidConnectionHandle;
            if (_active.load()) {
                _state = State::Advertising;
                startAdvertising();
            }
            break;
        case ESP_HIDD_STOP_EVENT:
            break;
        default:
            break;
    }
    (void)eventData;
}

int BleHidRemote::handleGapEvent(ble_gap_event* event)
{
    if (event == nullptr) {
        return 0;
    }

    switch (event->type) {
        case BLE_GAP_EVENT_CONNECT:
            if (event->connect.status != 0) {
                ESP_LOGW(Tag, "connection failed: %d", event->connect.status);
                if (_active.load()) {
                    startAdvertising();
                }
                break;
            }

            ESP_LOGI(Tag, "computer connected, starting authenticated pairing");
            _connection_handle = event->connect.conn_handle;
            if (!isAllowedPeer(event->connect.conn_handle)) {
                ESP_LOGW(Tag, "rejecting connection from an unpaired computer");
                ble_gap_terminate(event->connect.conn_handle, BLE_ERR_AUTH_FAIL);
                break;
            }

            {
                const int result = ble_gap_security_initiate(event->connect.conn_handle);
                if (result != 0 && result != BLE_HS_EALREADY) {
                    ESP_LOGW(Tag, "failed to initiate security: %d", result);
                }
            }
            break;
        case BLE_GAP_EVENT_ENC_CHANGE:
            if (event->enc_change.status == 0 && _active.load()) {
                ESP_LOGI(Tag, "pairing complete; encrypted connection ready");
                _state = State::Connected;
                configureConnection(event->enc_change.conn_handle);
                ble_svc_gatt_changed(0x0001, 0xFFFF);
            } else {
                ESP_LOGW(Tag, "pairing/encryption failed: %d", event->enc_change.status);
            }
            break;
        case BLE_GAP_EVENT_DISCONNECT:
            ESP_LOGI(Tag, "computer disconnected: reason=%d", event->disconnect.reason);
            stopSpeech(true);
            _speech_subscribed        = false;
            _speech_status_subscribed = false;
            _host_status              = HostStatus::Waiting;
            _host_error               = 0;
            _connection_handle        = InvalidConnectionHandle;
            if (_active.load()) {
                _state = State::Advertising;
                startAdvertising();
            }
            break;
        case BLE_GAP_EVENT_SUBSCRIBE:
            if (event->subscribe.attr_handle == _speech_audio_handle) {
                _speech_subscribed = event->subscribe.cur_notify != 0;
                ESP_LOGI(Tag, "speech audio subscription: %s", _speech_subscribed.load() ? "on" : "off");
            } else if (event->subscribe.attr_handle == _speech_status_handle) {
                _speech_status_subscribed = event->subscribe.cur_notify != 0;
                ESP_LOGI(Tag, "speech status subscription: %s", _speech_status_subscribed.load() ? "on" : "off");
            }
            if (isSpeechReady()) {
                sendSpeechStatus(SpeechReady);
            }
            break;
        case BLE_GAP_EVENT_MTU:
            ESP_LOGI(Tag, "ATT MTU updated: %u", event->mtu.value);
            if (isSpeechReady()) {
                sendSpeechStatus(SpeechReady);
            }
            break;
        case BLE_GAP_EVENT_ADV_COMPLETE:
            if (_active.load()) {
                startAdvertising();
            }
            break;
        case BLE_GAP_EVENT_REPEAT_PAIRING: {
            ESP_LOGI(Tag, "replacing stale bond for repeat pairing");
            ble_gap_conn_desc description{};
            if (ble_gap_conn_find(event->repeat_pairing.conn_handle, &description) == 0) {
                ble_store_util_delete_peer(&description.peer_id_addr);
                return BLE_GAP_REPEAT_PAIRING_RETRY;
            }
            break;
        }
        case BLE_GAP_EVENT_PASSKEY_ACTION: {
            ESP_LOGI(Tag, "pairing passkey requested: action=%u", event->passkey.params.action);
            if (event->passkey.params.action != BLE_SM_IOACT_DISP) {
                ESP_LOGW(Tag, "unsupported pairing action: %u", event->passkey.params.action);
                break;
            }

            ble_sm_io response{};
            response.action  = BLE_SM_IOACT_DISP;
            response.passkey = PairingPasskey;
            const int result = ble_sm_inject_io(event->passkey.conn_handle, &response);
            if (result != 0) {
                ESP_LOGW(Tag, "failed to provide pairing passkey: %d", result);
            }
            break;
        }
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
            sendKeyboardReport(static_cast<uint8_t>(command.value));
        } else if (command.type == CommandType::Wheel) {
            sendMouseWheelReport(command.value);
        }
    }

    _report_worker_running = false;
}

void BleHidRemote::sendKeyboardReport(uint8_t keyCode)
{
    std::array<uint8_t, 8> report{};
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

void BleHidRemote::configureConnection(uint16_t connectionHandle)
{
    ble_gap_upd_params parameters{};
    parameters.itvl_min            = 12;  // 15 ms
    parameters.itvl_max            = 24;  // 30 ms
    parameters.latency             = 0;
    parameters.supervision_timeout = 400;  // 4 seconds
    parameters.min_ce_len          = 0;
    parameters.max_ce_len          = 0;

    int result = ble_gap_update_params(connectionHandle, &parameters);
    if (result != 0 && result != BLE_HS_EALREADY) {
        ESP_LOGW(Tag, "connection parameter update failed: %d", result);
    }
    result = ble_gap_set_data_len(connectionHandle, 251, 2120);
    if (result != 0) {
        ESP_LOGW(Tag, "data length update failed: %d", result);
    }
    result = ble_gap_set_prefered_le_phy(connectionHandle, BLE_GAP_LE_PHY_2M_MASK, BLE_GAP_LE_PHY_2M_MASK,
                                         BLE_GAP_LE_PHY_CODED_ANY);
    if (result != 0) {
        ESP_LOGW(Tag, "2M PHY request failed; continuing on 1M PHY: %d", result);
    }
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

void BleHidRemote::runSpeechWorker()
{
    std::array<int16_t, speech::InputSamplesPerFrame> input{};
    std::array<int16_t, speech::OutputSamplesPerFrame> resampled{};
    std::array<uint8_t, speech::AdpcmBlockBytes> encoded{};
    int stepIndex      = 0;
    uint16_t errorCode = 0;

    while (_speech_active.load()) {
        if (!GetHAL().audioReadSamples(input.data(), input.size(), 30.0f)) {
            errorCode = static_cast<uint16_t>(ESP_FAIL);
            break;
        }
        speech::resample44k1To16k(input.data(), resampled);
        speech::encodeImaAdpcm(resampled, encoded, stepIndex);
        if (!sendSpeechAudio(encoded.data(), encoded.size())) {
            errorCode = static_cast<uint16_t>(ESP_FAIL);
            break;
        }
    }

    const bool aborted = _speech_abort_requested.load() || errorCode != 0;
    _speech_active     = false;
    if (errorCode != 0) {
        sendSpeechStatus(SpeechError, errorCode);
    } else {
        sendSpeechStatus(aborted ? SpeechAbort : SpeechEnd);
    }
    ESP_LOGI(Tag, "speech session %u %s after %u frames", _speech_session, aborted ? "aborted" : "ended",
             _speech_sequence);
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

int BleHidRemote::speechGattAccess(uint16_t connectionHandle, uint16_t attributeHandle, ble_gatt_access_ctxt* context,
                                   void* argument)
{
    (void)connectionHandle;
    (void)argument;
    if (ActiveInstance == nullptr || context == nullptr) {
        return BLE_ATT_ERR_UNLIKELY;
    }

    if (context->op == BLE_GATT_ACCESS_OP_READ_CHR && attributeHandle == ActiveInstance->_speech_status_handle) {
        std::array<uint8_t, 12> packet{};
        packet[0] = SpeechProtocolVersion;
        packet[1] = ActiveInstance->_speech_active.load() ? SpeechStart : SpeechReady;
        packet[2] = static_cast<uint8_t>(ActiveInstance->_speech_session & 0xFF);
        packet[3] = static_cast<uint8_t>(ActiveInstance->_speech_session >> 8);
        packet[4] = static_cast<uint8_t>(SpeechSampleRate & 0xFF);
        packet[5] = static_cast<uint8_t>(SpeechSampleRate >> 8);
        packet[6] = static_cast<uint8_t>(speech::OutputSamplesPerFrame & 0xFF);
        packet[7] = static_cast<uint8_t>(speech::OutputSamplesPerFrame >> 8);
        packet[8] = SpeechCodecImaAdpcm;
        packet[9] = ActiveInstance->_speech_active.load() ? 1 : 0;
        return os_mbuf_append(context->om, packet.data(), packet.size()) == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
    }
    if (context->op == BLE_GATT_ACCESS_OP_READ_CHR && attributeHandle == ActiveInstance->_speech_audio_handle) {
        return 0;
    }
    if (context->op == BLE_GATT_ACCESS_OP_WRITE_CHR && attributeHandle == ActiveInstance->_host_status_handle) {
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
        ActiveInstance->_host_status = static_cast<HostStatus>(packet[1]);
        ActiveInstance->_host_error  = static_cast<uint16_t>(packet[2] | (packet[3] << 8));
        ESP_LOGI(Tag, "desktop helper status: %u, error: %u", packet[1], ActiveInstance->_host_error.load());
        if (ActiveInstance->isSpeechReady()) {
            ActiveInstance->sendSpeechStatus(SpeechReady);
        }
        return 0;
    }
    return BLE_ATT_ERR_UNLIKELY;
}

void BleHidRemote::setError(int error)
{
    _last_error = error;
    _state      = State::Error;
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
    switch (state) {
        case BleHidRemote::State::Stopped:
            return "Stopped";
        case BleHidRemote::State::Starting:
            return "Starting Bluetooth...";
        case BleHidRemote::State::Advertising:
            return "Waiting for computer";
        case BleHidRemote::State::Connected:
            return "Connected";
        case BleHidRemote::State::Error:
            return "Bluetooth error";
        default:
            return "Unknown";
    }
}

}  // namespace model
