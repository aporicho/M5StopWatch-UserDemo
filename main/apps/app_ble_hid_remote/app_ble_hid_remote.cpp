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

#include <algorithm>
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
constexpr uint32_t SpeechHoldMs      = 500;
constexpr uint32_t VibrationSettleMs = 70;

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

#ifdef CONFIG_M5_TEST_CONTROL
AppBleHidRemote::TestSnapshot AppBleHidRemote::testSnapshot() const
{
    TestSnapshot snapshot{};
    if (!_remote) {
        return snapshot;
    }
    snapshot.hasRemote      = true;
    snapshot.state          = model::bleHidStateToString(_remote->state());
    snapshot.lastError      = _remote->lastError();
    snapshot.lastErrorStage = _remote->lastErrorStage();
    snapshot.speechService  = model::speechServiceStateToString(_remote->speechServiceState());
    snapshot.hostStatus     = hostStatusToString(_remote->hostStatus());
    snapshot.hostError      = _remote->hostError();
    snapshot.speechReady    = _remote->isSpeechReady();
    snapshot.speechActive   = _remote->isSpeechActive();
    return snapshot;
}
#endif

bool AppBleHidRemote::scheduleSpeechStart()
{
    if (!_remote || !_remote->isSpeechReady()) {
        logEvent("speech start rejected not ready");
        logRemoteSnapshot("speech not ready");
        GetHAL().vibrate(160, 100);
        return false;
    }

    const uint32_t now = GetHAL().millis();
    logEvent("speech start scheduled");
    GetHAL().vibrate(20, 70);
    _speech_start_at      = now + VibrationSettleMs;
    _speech_start_pending = true;
    return true;
}

bool AppBleHidRemote::stopSpeechFromMapping(bool abort)
{
    if (!_remote || !_remote->isSpeechActive()) {
        return false;
    }
    _remote->stopSpeech(abort);
    _speech_end_feedback = !abort;
    return true;
}

bool AppBleHidRemote::executeMappedAction(const model::UserActionMapping& mapping, int8_t value)
{
    if (!_remote) {
        return false;
    }

    switch (mapping.action) {
        case model::UserActionType::None:
            return false;
        case model::UserActionType::HidKeyboardTap:
            return _remote->sendKeyboardShortcut(mapping.param0, mapping.param1);
        case model::UserActionType::HidMouseWheel: {
            int delta = value;
            if (delta == 0) {
                delta = mapping.param2 == 0 ? 1 : mapping.param2;
            }
            const int multiplier = mapping.param0 == 0 ? 1 : mapping.param0;
            delta *= multiplier;
            if (mapping.param1 != 0) {
                delta = -delta;
            }
            delta = std::clamp(delta, -127, 127);
            return _remote->sendWheel(static_cast<int8_t>(delta));
        }
        case model::UserActionType::HidMouseClick:
            return _remote->sendMouseClick(mapping.param0 == 0 ? 1 : mapping.param0);
        case model::UserActionType::HidMediaControl:
            return _remote->sendMediaControl(static_cast<uint16_t>(mapping.param2));
        case model::UserActionType::VoiceHoldStart:
        case model::UserActionType::VoiceCommandStart:
            return scheduleSpeechStart();
        case model::UserActionType::VoiceHoldStop:
        case model::UserActionType::VoiceCommandStop:
            return stopSpeechFromMapping(false);
        case model::UserActionType::VoiceToggle:
            if (_remote->isSpeechActive()) {
                return stopSpeechFromMapping(false);
            }
            return scheduleSpeechStart();
        case model::UserActionType::DevicePairNewComputer:
            return _remote->pairNewComputer();
        case model::UserActionType::DeviceShowControls:
            if (_view) {
                _view->showControls();
                return true;
            }
            return false;
        case model::UserActionType::DeviceHideControls:
            if (_view) {
                _view->hideControls();
                return true;
            }
            return false;
        case model::UserActionType::DeviceToggleControls:
            if (_view) {
                _view->toggleControls();
                return true;
            }
            return false;
        case model::UserActionType::DeviceGoHome:
            logEvent("close requested by mapped event");
            _speech_start_pending = false;
            if (_remote) {
                _remote->stopSpeech(true);
            }
            close();
            return true;
        default:
            return false;
    }
}

bool AppBleHidRemote::executeMappedEvent(model::UserEvent event, int8_t value)
{
    if (!_remote || event == model::UserEvent::None) {
        return false;
    }

    const model::UserActionMapping mapping = _remote->mappingFor(event);
    const bool handled                     = executeMappedAction(mapping, value);
    _remote->notifyUserEvent(event, mapping.action, value, handled);
    logEvent("event=%s action=%s value=%d handled=%d", model::userEventToId(event),
             model::userActionToId(mapping.action), static_cast<int>(value), handled ? 1 : 0);
    return handled;
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
    _left_long_latched       = false;
    _right_long_latched      = false;
    _speech_start_pending    = false;
    _speech_end_feedback     = false;
    _home_latched            = false;
    _remote_snapshot_valid   = false;
    _last_wheel_log_at       = 0;
    logRemoteSnapshot("after start");
}

bool AppBleHidRemote::handleHomeCombo()
{
    auto& hal = GetHAL();
    if (hal.btnA.isHolding() && hal.btnB.isHolding()) {
        if (!_home_latched) {
            _home_latched = true;
            logEvent("home combo detected btnA=holding btnB=holding");
            logRemoteSnapshot("before home close");
            executeMappedEvent(model::UserEvent::ButtonBothHold);
        }
        return true;
    }
    if (hal.btnA.isReleased() && hal.btnB.isReleased()) {
        _home_latched = false;
    }
    return false;
}

void AppBleHidRemote::handleButtonPressAndHold(bool leftButton)
{
    auto& hal   = GetHAL();
    auto& button = leftButton ? hal.btnA : hal.btnB;
    bool& latch = leftButton ? _left_long_latched : _right_long_latched;
    const auto holdEvent =
        leftButton ? model::UserEvent::ButtonLeftHold : model::UserEvent::ButtonRightHold;

    if (button.wasPressed()) {
        latch = false;
        _speech_start_pending = false;
    }
    if (_remote && button.isPressed() && !latch && button.pressedFor(SpeechHoldMs)) {
        latch = true;
        executeMappedEvent(holdEvent);
    }
}

void AppBleHidRemote::handleButtonRelease(bool leftButton)
{
    auto& hal   = GetHAL();
    auto& button = leftButton ? hal.btnA : hal.btnB;
    bool& latch = leftButton ? _left_long_latched : _right_long_latched;
    const auto releaseAfterHoldEvent = leftButton ? model::UserEvent::ButtonLeftReleaseAfterHold
                                                  : model::UserEvent::ButtonRightReleaseAfterHold;
    const auto tapEvent = leftButton ? model::UserEvent::ButtonLeftTap : model::UserEvent::ButtonRightTap;

    if (!_remote || !button.wasReleased()) {
        return;
    }
    _speech_start_pending = false;
    if (latch) {
        executeMappedEvent(releaseAfterHoldEvent);
    } else {
        const bool handled = executeMappedEvent(tapEvent);
        if (handled && _view) {
            LvglLockGuard lock;
            _view->flashKey(leftButton);
        }
    }
    hal.vibrate(20, 60);
}

void AppBleHidRemote::tickPendingSpeechStart(uint32_t now)
{
    if (_remote && _speech_start_pending && static_cast<int32_t>(now - _speech_start_at) >= 0) {
        _speech_start_pending = false;
        if (!_remote->startSpeech()) {
            logEvent("speech start failed");
            logRemoteSnapshot("speech start failed");
            GetHAL().vibrate(160, 100);
        } else {
            logEvent("speech start ok");
        }
    }
}

void AppBleHidRemote::handleSpeechEndFeedback()
{
    if (_remote && _speech_end_feedback && !_remote->isSpeechActive()) {
        _speech_end_feedback = false;
        GetHAL().vibrate(20, 70);
        logEvent("speech end feedback");
    }
}

void AppBleHidRemote::handleViewEvents(uint32_t now)
{
    if (!_remote) {
        logEvent("running without remote instance");
        return;
    }

    logRemoteSnapshot("state change");

    int8_t wheelDelta = 0;
    bool pairComputer = false;
    model::UserEvent touchEvent = model::UserEvent::None;
    if (_view) {
        LvglLockGuard lock;
        _view->update(_remote->state(), _remote->lastError(), _remote->speechServiceState(), _remote->hostError());
        wheelDelta   = _view->consumeWheelDelta();
        touchEvent   = _view->consumeTouchEvent();
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
        executeMappedEvent(model::UserEvent::TouchScrollDelta, wheelDelta);
    }
    if (touchEvent != model::UserEvent::None) {
        executeMappedEvent(touchEvent);
    }
}

void AppBleHidRemote::onRunning()
{
    auto& hal = GetHAL();
    hal.updateButtonStates(false);
    const uint32_t now = hal.millis();

    if (handleHomeCombo()) {
        return;
    }

    handleButtonPressAndHold(true);
    handleButtonRelease(true);
    handleButtonPressAndHold(false);
    tickPendingSpeechStart(now);
    handleButtonRelease(false);
    handleSpeechEndFeedback();
    handleViewEvents(now);
}

void AppBleHidRemote::onClose()
{
    mclog::tagInfo(getAppInfo().name, "on close");
    logEvent("on close");
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
