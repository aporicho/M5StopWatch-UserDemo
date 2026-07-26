/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include "sdkconfig.h"
#include "model/ble_hid_remote.h"
#include "view/view.h"

#include <mooncake.h>

#include <memory>

class AppBleHidRemote : public mooncake::AppAbility {
public:
    AppBleHidRemote();

#ifdef CONFIG_M5_TEST_CONTROL
    struct TestSnapshot {
        bool hasRemote            = false;
        const char* state         = "none";
        int lastError             = 0;
        const char* lastErrorStage = "none";
        const char* speechService = "none";
        const char* hostStatus    = "none";
        uint16_t hostError        = 0;
        bool speechReady          = false;
        bool speechActive         = false;
    };
    TestSnapshot testSnapshot() const;
#endif

    void onCreate() override;
    void onOpen() override;
    void onRunning() override;
    void onClose() override;
    void onDestroy() override;

private:
    void logEvent(const char* format, ...) const;
    void logRemoteSnapshot(const char* reason);
    bool executeMappedEvent(model::UserEvent event, int8_t value = 0);
    bool executeMappedAction(const model::UserActionMapping& mapping, int8_t value);
    bool scheduleSpeechStart();
    bool stopSpeechFromMapping(bool abort = false);
    bool handleHomeCombo();
    void handleButtonPressAndHold(bool leftButton);
    void handleButtonRelease(bool leftButton);
    void tickPendingSpeechStart(uint32_t now);
    void handleSpeechEndFeedback();
    void handleViewEvents(uint32_t now);

    std::unique_ptr<model::BleHidRemote> _remote;
    std::unique_ptr<view::BleHidRemoteView> _view;
    uint32_t _speech_start_at      = 0;
    uint32_t _last_wheel_log_at    = 0;
    bool _left_long_latched        = false;
    bool _right_long_latched       = false;
    bool _speech_start_pending     = false;
    bool _speech_end_feedback      = false;
    bool _home_latched             = false;
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
