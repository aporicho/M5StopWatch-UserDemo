/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include "../model/ble_hid_remote.h"

#include <cstdint>
#include <memory>

#include <smooth_lvgl.hpp>
#include <uitk/short_namespace.hpp>

namespace view {

class ForgetBondDialog {
public:
    void init(lv_obj_t* parent);
    bool isConfirmed() const
    {
        return _confirmed;
    }
    bool isCancelled() const
    {
        return _cancelled;
    }

private:
    std::unique_ptr<uitk::lvgl_cpp::Container> _panel;
    std::unique_ptr<uitk::lvgl_cpp::Label> _title;
    std::unique_ptr<uitk::lvgl_cpp::Label> _message;
    std::unique_ptr<uitk::lvgl_cpp::Button> _confirm_button;
    std::unique_ptr<uitk::lvgl_cpp::Button> _cancel_button;
    bool _confirmed = false;
    bool _cancelled = false;
};

class BleHidRemoteView {
public:
    void init(lv_obj_t* parent);
    void update(model::BleHidRemote::State state, int lastError, bool speechReady, bool speechActive,
                model::BleHidRemote::HostStatus hostStatus, uint16_t hostError);
    void flashKey(bool leftKey);
    int8_t consumeWheelDelta();
    bool consumeForgetRequested();

private:
    void updateStatus(model::BleHidRemote::State state, int lastError, bool speechReady, bool speechActive,
                      model::BleHidRemote::HostStatus hostStatus, uint16_t hostError);
    bool updateUiToggleGesture();
    void setControlsVisible(bool visible);
    void updateGesture(model::BleHidRemote::State state);
    void resetGesture();
    void showForgetDialog();

    std::unique_ptr<uitk::lvgl_cpp::Container> _panel;
    std::unique_ptr<uitk::lvgl_cpp::Container> _controls_layer;
    std::unique_ptr<uitk::lvgl_cpp::Container> _status_panel;
    std::unique_ptr<uitk::lvgl_cpp::Container> _status_dot;
    std::unique_ptr<uitk::lvgl_cpp::Label> _status_label;
    std::unique_ptr<uitk::lvgl_cpp::Label> _device_label;
    std::unique_ptr<uitk::lvgl_cpp::Container> _left_key_panel;
    std::unique_ptr<uitk::lvgl_cpp::Container> _right_key_panel;
    std::unique_ptr<uitk::lvgl_cpp::Label> _left_key_label;
    std::unique_ptr<uitk::lvgl_cpp::Label> _right_key_label;
    std::unique_ptr<uitk::lvgl_cpp::Label> _left_hint_label;
    std::unique_ptr<uitk::lvgl_cpp::Label> _right_hint_label;
    std::unique_ptr<uitk::lvgl_cpp::Label> _gesture_label;
    std::unique_ptr<uitk::lvgl_cpp::Label> _gesture_hint_label;
    std::unique_ptr<uitk::lvgl_cpp::Button> _forget_button;
    std::unique_ptr<ForgetBondDialog> _forget_dialog;

    model::BleHidRemote::State _displayed_state = model::BleHidRemote::State::Stopped;
    int _displayed_error                        = 0;
    bool _displayed_speech_ready                = false;
    bool _displayed_speech_active               = false;
    model::BleHidRemote::HostStatus _displayed_host_status = model::BleHidRemote::HostStatus::Waiting;
    uint16_t _displayed_host_error                         = 0;
    uint32_t _left_flash_until                  = 0;
    uint32_t _right_flash_until                 = 0;
    uint32_t _tap_started_at                    = 0;
    uint32_t _last_tap_at                       = 0;
    uint8_t _tap_count                          = 0;
    bool _forget_requested                      = false;
    bool _controls_visible                      = false;
    bool _tap_pressing                          = false;
    bool _tap_moved                             = false;
    bool _gesture_pressing                      = false;
    bool _gesture_locked                        = false;
    bool _gesture_rejected                      = false;
    lv_point_t _gesture_start{};
    lv_point_t _gesture_last{};
    lv_point_t _tap_start{};
    int _gesture_remainder = 0;
    int _wheel_pending     = 0;
};

}  // namespace view
