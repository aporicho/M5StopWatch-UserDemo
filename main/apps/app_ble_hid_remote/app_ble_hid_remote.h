/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include "model/ble_hid_remote.h"
#include "view/view.h"

#include <mooncake.h>

#include <memory>

class AppBleHidRemote : public mooncake::AppAbility {
public:
    AppBleHidRemote();

    void onCreate() override;
    void onOpen() override;
    void onRunning() override;
    void onClose() override;
    void onDestroy() override;

private:
    void logEvent(const char* format, ...) const;
    void logRemoteSnapshot(const char* reason);

    std::unique_ptr<model::BleHidRemote> _remote;
    std::unique_ptr<view::BleHidRemoteView> _view;
    uint32_t _speech_start_at      = 0;
    uint32_t _last_wheel_log_at    = 0;
    bool _right_long_latched       = false;
    bool _speech_start_pending     = false;
    bool _speech_end_feedback      = false;
    bool _home_latched             = false;
    bool _close_requested_by_home  = false;
    bool _remote_snapshot_valid    = false;
    model::BleHidRemote::State _logged_state = model::BleHidRemote::State::Stopped;
    model::BleHidRemote::SpeechServiceState _logged_service_state =
        model::BleHidRemote::SpeechServiceState::Disconnected;
    model::BleHidRemote::HostStatus _logged_host_status = model::BleHidRemote::HostStatus::Waiting;
    int _logged_error              = 0;
    uint16_t _logged_host_error    = 0;
    bool _logged_speech_ready      = false;
    bool _logged_speech_active     = false;
};
