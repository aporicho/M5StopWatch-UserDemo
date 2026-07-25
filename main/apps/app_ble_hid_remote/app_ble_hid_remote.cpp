/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#include "app_ble_hid_remote.h"

#include <assets/assets.h>
#include <esp_log.h>
#include <esp_system.h>
#include <hal/hal.h>
#include <hal/utils/wear_levelling/wear_levelling.h>
#include <mooncake_log.h>
#include <smooth_lvgl.hpp>

#include <cstdarg>
#include <cstdio>
#include <sys/stat.h>

AppBleHidRemote::AppBleHidRemote()
{
    setAppInfo().name = "BLE Remote";
    setAppInfo().icon = (void*)&icon_ble_hid;
}

namespace {

constexpr const char* LogTag      = "BLE-REMOTE-APP";
constexpr const char* LogFileName = "ble_remote.log";
constexpr size_t MaxLogBytes      = 48 * 1024;

const char* hostStatusToString(model::BleHidRemote::HostStatus status)
{
    switch (status) {
        case model::BleHidRemote::HostStatus::Waiting:
            return "Waiting";
        case model::BleHidRemote::HostStatus::Preparing:
            return "Preparing";
        case model::BleHidRemote::HostStatus::Ready:
            return "Ready";
        case model::BleHidRemote::HostStatus::Recognizing:
            return "Recognizing";
        case model::BleHidRemote::HostStatus::PermissionError:
            return "PermissionError";
        case model::BleHidRemote::HostStatus::ModelError:
            return "ModelError";
        case model::BleHidRemote::HostStatus::HostError:
            return "HostError";
        default:
            return "Unknown";
    }
}

const char* resetReasonToString(esp_reset_reason_t reason)
{
    switch (reason) {
        case ESP_RST_POWERON:
            return "POWERON";
        case ESP_RST_EXT:
            return "EXT";
        case ESP_RST_SW:
            return "SW";
        case ESP_RST_PANIC:
            return "PANIC";
        case ESP_RST_INT_WDT:
            return "INT_WDT";
        case ESP_RST_TASK_WDT:
            return "TASK_WDT";
        case ESP_RST_WDT:
            return "WDT";
        case ESP_RST_DEEPSLEEP:
            return "DEEPSLEEP";
        case ESP_RST_BROWNOUT:
            return "BROWNOUT";
        case ESP_RST_SDIO:
            return "SDIO";
        default:
            return "UNKNOWN";
    }
}

void buildLogPath(char* path, size_t size, const char* suffix = "")
{
    std::snprintf(path, size, "%s/%s%s", wear_levelling_get_base_path(), LogFileName, suffix);
}

void rotateLogIfNeeded()
{
    char path[96];
    buildLogPath(path, sizeof(path));

    struct stat fileStat {};
    if (stat(path, &fileStat) != 0 || fileStat.st_size < static_cast<off_t>(MaxLogBytes)) {
        return;
    }

    char backupPath[96];
    buildLogPath(backupPath, sizeof(backupPath), ".1");
    std::remove(backupPath);
    std::rename(path, backupPath);
}

}  // namespace

void AppBleHidRemote::logEvent(const char* format, ...) const
{
    char message[220];
    va_list args;
    va_start(args, format);
    std::vsnprintf(message, sizeof(message), format, args);
    va_end(args);

    ESP_LOGI(LogTag, "%s", message);

    rotateLogIfNeeded();

    char path[96];
    buildLogPath(path, sizeof(path));
    FILE* file = std::fopen(path, "a");
    if (file == nullptr) {
        ESP_LOGW(LogTag, "failed to open persistent log: %s", path);
        return;
    }
    std::fprintf(file, "%010lu %s\n", static_cast<unsigned long>(GetHAL().millis()), message);
    std::fclose(file);
}

void AppBleHidRemote::logRemoteSnapshot(const char* reason)
{
    if (!_remote) {
        if (_remote_snapshot_valid) {
            logEvent("%s remote=null", reason);
            _remote_snapshot_valid = false;
        }
        return;
    }

    const auto state       = _remote->state();
    const int error        = _remote->lastError();
    const bool speechReady = _remote->isSpeechReady();
    const bool speechActive = _remote->isSpeechActive();
    const auto serviceState = _remote->speechServiceState();
    const auto hostStatus  = _remote->hostStatus();
    const uint16_t hostErr = _remote->hostError();

    if (_remote_snapshot_valid && state == _logged_state && error == _logged_error &&
        serviceState == _logged_service_state && speechReady == _logged_speech_ready &&
        speechActive == _logged_speech_active &&
        hostStatus == _logged_host_status && hostErr == _logged_host_error) {
        return;
    }

    logEvent("%s state=%s err=%d service=%s speechReady=%d speechActive=%d host=%s hostErr=%u", reason,
             model::bleHidStateToString(state), error, model::speechServiceStateToString(serviceState),
             speechReady ? 1 : 0, speechActive ? 1 : 0, hostStatusToString(hostStatus), hostErr);

    _remote_snapshot_valid  = true;
    _logged_state           = state;
    _logged_error           = error;
    _logged_service_state   = serviceState;
    _logged_speech_ready    = speechReady;
    _logged_speech_active   = speechActive;
    _logged_host_status     = hostStatus;
    _logged_host_error      = hostErr;
}

void AppBleHidRemote::onCreate()
{
    mclog::tagInfo(getAppInfo().name, "on create");
    logEvent("on create reset=%s(%d) log=%s/%s", resetReasonToString(esp_reset_reason()), esp_reset_reason(),
             wear_levelling_get_base_path(), LogFileName);
    _remote = std::make_unique<model::BleHidRemote>();
}

void AppBleHidRemote::onOpen()
{
    mclog::tagInfo(getAppInfo().name, "on open");
    logEvent("on open");

    if (!_remote) {
        _remote = std::make_unique<model::BleHidRemote>();
        logEvent("remote recreated");
    }

    {
        LvglLockGuard lock;
        _view = std::make_unique<view::BleHidRemoteView>();
        _view->init(lv_screen_active());
    }

    _remote->start();
    _right_long_latched      = false;
    _speech_start_pending    = false;
    _speech_end_feedback     = false;
    _home_latched            = false;
    _close_requested_by_home = false;
    _remote_snapshot_valid   = false;
    _last_wheel_log_at       = 0;
    logRemoteSnapshot("after start");
}

void AppBleHidRemote::onRunning()
{
    constexpr uint32_t SpeechHoldMs      = 500;
    constexpr uint32_t VibrationSettleMs = 70;

    auto& hal = GetHAL();
    hal.updateButtonStates(false);
    const uint32_t now = hal.millis();

    if (hal.btnA.isHolding() && hal.btnB.isHolding()) {
        if (!_home_latched) {
            _home_latched = true;
            _close_requested_by_home = true;
            logEvent("home combo detected btnA=holding btnB=holding");
            logRemoteSnapshot("before home close");
            if (_remote) {
                _remote->stopSpeech(true);
            }
            _speech_start_pending = false;
            close();
        }
        return;
    }
    if (hal.btnA.isReleased() && hal.btnB.isReleased()) {
        _home_latched = false;
    }

    bool keyFlashed = false;
    bool leftKey    = false;
    if (_remote && hal.btnA.wasClicked()) {
        keyFlashed = _remote->sendKeyTap(model::BleHidRemote::Key::Escape);
        leftKey    = true;
        logEvent("left button tap ESC queued=%d", keyFlashed ? 1 : 0);
        hal.vibrate(20, 60);
    }

    if (hal.btnB.wasPressed()) {
        _right_long_latched   = false;
        _speech_start_pending = false;
        logEvent("right button pressed");
    }
    if (_remote && hal.btnB.isPressed() && !_right_long_latched && hal.btnB.pressedFor(SpeechHoldMs)) {
        _right_long_latched = true;
        if (_remote->isSpeechReady()) {
            logEvent("right hold speech start scheduled");
            hal.vibrate(20, 70);
            _speech_start_at      = now + VibrationSettleMs;
            _speech_start_pending = true;
        } else {
            logEvent("right hold rejected speech not ready");
            logRemoteSnapshot("speech not ready");
            hal.vibrate(160, 100);
        }
    }
    if (_remote && _speech_start_pending && static_cast<int32_t>(now - _speech_start_at) >= 0) {
        _speech_start_pending = false;
        if (hal.btnB.isPressed()) {
            if (!_remote->startSpeech()) {
                logEvent("speech start failed");
                logRemoteSnapshot("speech start failed");
                hal.vibrate(160, 100);
            } else {
                logEvent("speech start ok");
            }
        }
    }
    if (_remote && hal.btnB.wasReleased()) {
        _speech_start_pending = false;
        if (_right_long_latched) {
            if (_remote->isSpeechActive()) {
                logEvent("right release stop speech");
                _remote->stopSpeech(false);
                _speech_end_feedback = true;
            } else {
                logEvent("right release after hold speech inactive");
            }
        } else {
            keyFlashed = _remote->sendKeyTap(model::BleHidRemote::Key::Enter);
            leftKey    = false;
            logEvent("right button tap ENTER queued=%d", keyFlashed ? 1 : 0);
            hal.vibrate(20, 60);
        }
    }
    if (_remote && _speech_end_feedback && !_remote->isSpeechActive()) {
        _speech_end_feedback = false;
        hal.vibrate(20, 70);
        logEvent("speech end feedback");
    }

    if (!_remote) {
        logEvent("running without remote instance");
        return;
    }

    logRemoteSnapshot("state change");

    int8_t wheelDelta = 0;
    bool pairComputer = false;
    if (_view) {
        LvglLockGuard lock;
        if (keyFlashed) {
            _view->flashKey(leftKey);
        }
        _view->update(_remote->state(), _remote->lastError(), _remote->speechServiceState(), _remote->hostError());
        wheelDelta   = _view->consumeWheelDelta();
        pairComputer = _view->consumePairRequested();
    }

    if (pairComputer) {
        const bool started = _remote->pairNewComputer();
        logEvent("pair new computer requested result=%d", started ? 1 : 0);
        logRemoteSnapshot("after pair request");
    } else if (wheelDelta != 0) {
        if (_last_wheel_log_at == 0 || now - _last_wheel_log_at >= 1000) {
            logEvent("wheel delta=%d", static_cast<int>(wheelDelta));
            _last_wheel_log_at = now;
        }
        _remote->sendWheel(wheelDelta);
    }
}

void AppBleHidRemote::onClose()
{
    mclog::tagInfo(getAppInfo().name, "on close");
    logEvent("on close reason=%s", _close_requested_by_home ? "home-combo" : "external-or-state");
    logRemoteSnapshot("before stop");

    if (_remote) {
        _remote->stopSpeech(true);
        _remote->stop();
    }

    LvglLockGuard lock;
    _view.reset();
    logRemoteSnapshot("after close");
}

void AppBleHidRemote::onDestroy()
{
    logEvent("on destroy");
    if (_remote) {
        _remote->stop();
    }
    _remote.reset();
}
