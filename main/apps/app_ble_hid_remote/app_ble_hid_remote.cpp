/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#include "app_ble_hid_remote.h"

#include <assets/assets.h>
#include <hal/hal.h>
#include <mooncake_log.h>
#include <smooth_lvgl.hpp>

AppBleHidRemote::AppBleHidRemote()
{
    setAppInfo().name = "BLE Remote";
    setAppInfo().icon = (void*)&icon_ble_hid;
}

void AppBleHidRemote::onCreate()
{
    mclog::tagInfo(getAppInfo().name, "on create");
    _remote = std::make_unique<model::BleHidRemote>();
}

void AppBleHidRemote::onOpen()
{
    mclog::tagInfo(getAppInfo().name, "on open");

    if (!_remote) {
        _remote = std::make_unique<model::BleHidRemote>();
    }

    {
        LvglLockGuard lock;
        _view = std::make_unique<view::BleHidRemoteView>();
        _view->init(lv_screen_active());
    }

    _remote->start();
    _right_long_latched   = false;
    _speech_start_pending = false;
    _speech_end_feedback  = false;
    _home_latched         = false;
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
        hal.vibrate(20, 60);
    }

    if (hal.btnB.wasPressed()) {
        _right_long_latched   = false;
        _speech_start_pending = false;
    }
    if (_remote && hal.btnB.isPressed() && !_right_long_latched && hal.btnB.pressedFor(SpeechHoldMs)) {
        _right_long_latched = true;
        if (_remote->isSpeechReady()) {
            hal.vibrate(20, 70);
            _speech_start_at      = now + VibrationSettleMs;
            _speech_start_pending = true;
        } else {
            hal.vibrate(160, 100);
        }
    }
    if (_remote && _speech_start_pending && static_cast<int32_t>(now - _speech_start_at) >= 0) {
        _speech_start_pending = false;
        if (hal.btnB.isPressed()) {
            if (!_remote->startSpeech()) {
                hal.vibrate(160, 100);
            }
        }
    }
    if (_remote && hal.btnB.wasReleased()) {
        _speech_start_pending = false;
        if (_right_long_latched) {
            if (_remote->isSpeechActive()) {
                _remote->stopSpeech(false);
                _speech_end_feedback = true;
            }
        } else {
            keyFlashed = _remote->sendKeyTap(model::BleHidRemote::Key::Enter);
            leftKey    = false;
            hal.vibrate(20, 60);
        }
    }
    if (_remote && _speech_end_feedback && !_remote->isSpeechActive()) {
        _speech_end_feedback = false;
        hal.vibrate(20, 70);
    }

    if (!_remote) {
        return;
    }

    int8_t wheelDelta = 0;
    bool pairComputer = false;
    if (_view) {
        LvglLockGuard lock;
        if (keyFlashed) {
            _view->flashKey(leftKey);
        }
        _view->update(_remote->state(), _remote->lastError(), _remote->isSpeechReady(), _remote->isSpeechActive(),
                      _remote->hostStatus(), _remote->hostError());
        wheelDelta   = _view->consumeWheelDelta();
        pairComputer = _view->consumePairRequested();
    }

    if (pairComputer) {
        _remote->pairNewComputer();
    } else if (wheelDelta != 0) {
        _remote->sendWheel(wheelDelta);
    }
}

void AppBleHidRemote::onClose()
{
    mclog::tagInfo(getAppInfo().name, "on close");

    if (_remote) {
        _remote->stopSpeech(true);
        _remote->stop();
    }

    LvglLockGuard lock;
    _view.reset();
}

void AppBleHidRemote::onDestroy()
{
    if (_remote) {
        _remote->stop();
    }
    _remote.reset();
}
