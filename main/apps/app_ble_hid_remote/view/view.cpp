/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#include "view.h"

#include <algorithm>
#include <cstdio>

#include <assets/assets.h>
#include <hal/hal.h>

using namespace view;
using namespace uitk::lvgl_cpp;

namespace {

constexpr int PanelSize               = 466;
constexpr int GestureLockDistance     = 12;
constexpr int PixelsPerWheelStep      = 32;
constexpr int GestureButtonBoundary   = 342;
constexpr int MaxWheelStepsPerConsume = 8;
constexpr uint32_t KeyFlashDurationMs = 130;
constexpr uint32_t TapMaxDurationMs   = 280;
constexpr uint32_t MultiTapTimeoutMs  = 600;
constexpr int TapMaxMovement          = 14;

constexpr uint32_t BackgroundColor       = 0x171A21;
constexpr uint32_t SurfaceColor          = 0x292E39;
constexpr uint32_t SurfaceActiveColor    = 0x3467D7;
constexpr uint32_t PrimaryTextColor      = 0xFFFFFF;
constexpr uint32_t SecondaryTextColor    = 0xAEB7C8;
constexpr uint32_t ConnectedColor        = 0x4AD78C;
constexpr uint32_t AdvertisingColor      = 0x65A9FF;
constexpr uint32_t StartingColor         = 0xF4CA63;
constexpr uint32_t ErrorColor            = 0xFF7187;
constexpr uint32_t ForgetButtonColor     = 0x3A404D;
constexpr uint32_t DialogBackgroundColor = 0x292E39;

void configureKeyPanel(Container& panel, int x)
{
    panel.setSize(174, 112);
    panel.align(LV_ALIGN_CENTER, x, -37);
    panel.setBgColor(lv_color_hex(SurfaceColor));
    panel.setBgOpa(LV_OPA_COVER);
    panel.setBorderWidth(0);
    panel.setRadius(36);
    panel.setPaddingAll(0);
    panel.removeFlag(LV_OBJ_FLAG_SCROLLABLE);
    panel.removeFlag(LV_OBJ_FLAG_CLICKABLE);
}

}  // namespace

void ForgetBondDialog::init(lv_obj_t* parent)
{
    _confirmed = false;
    _cancelled = false;

    _panel = std::make_unique<Container>(parent);
    _panel->align(LV_ALIGN_CENTER, 0, 0);
    _panel->setSize(404, 226);
    _panel->setBgColor(lv_color_hex(DialogBackgroundColor));
    _panel->setBgOpa(LV_OPA_COVER);
    _panel->setBorderColor(lv_color_hex(0x596170));
    _panel->setBorderWidth(3);
    _panel->setRadius(54);
    _panel->setPaddingAll(0);
    _panel->removeFlag(LV_OBJ_FLAG_SCROLLABLE);
    _panel->moveForeground();

    _title = std::make_unique<Label>(_panel->get());
    _title->setText("Forget computer?");
    _title->setTextFont(&MontserratSemiBold26);
    _title->setTextColor(lv_color_hex(PrimaryTextColor));
    _title->align(LV_ALIGN_TOP_MID, 0, 29);

    _message = std::make_unique<Label>(_panel->get());
    _message->setText("A new computer can pair afterwards");
    _message->setTextFont(&lv_font_montserrat_16);
    _message->setTextColor(lv_color_hex(SecondaryTextColor));
    _message->align(LV_ALIGN_TOP_MID, 0, 70);

    _confirm_button = std::make_unique<Button>(_panel->get());
    _confirm_button->setSize(150, 62);
    _confirm_button->align(LV_ALIGN_BOTTOM_MID, -87, -25);
    _confirm_button->setRadius(LV_RADIUS_CIRCLE);
    _confirm_button->setBorderWidth(0);
    _confirm_button->setShadowWidth(0);
    _confirm_button->setBgColor(lv_color_hex(ErrorColor));
    _confirm_button->label().setText("Forget");
    _confirm_button->label().setTextFont(&lv_font_montserrat_22);
    _confirm_button->label().setTextColor(lv_color_hex(PrimaryTextColor));
    _confirm_button->label().align(LV_ALIGN_CENTER, 0, 0);
    _confirm_button->onClick().connect([this]() { _confirmed = true; });

    _cancel_button = std::make_unique<Button>(_panel->get());
    _cancel_button->setSize(150, 62);
    _cancel_button->align(LV_ALIGN_BOTTOM_MID, 87, -25);
    _cancel_button->setRadius(LV_RADIUS_CIRCLE);
    _cancel_button->setBorderWidth(0);
    _cancel_button->setShadowWidth(0);
    _cancel_button->setBgColor(lv_color_hex(0x4B5260));
    _cancel_button->label().setText("Cancel");
    _cancel_button->label().setTextFont(&lv_font_montserrat_22);
    _cancel_button->label().setTextColor(lv_color_hex(PrimaryTextColor));
    _cancel_button->label().align(LV_ALIGN_CENTER, 0, 0);
    _cancel_button->onClick().connect([this]() { _cancelled = true; });
}

void BleHidRemoteView::init(lv_obj_t* parent)
{
    _forget_requested = false;
    _wheel_pending    = 0;
    resetGesture();

    _panel = std::make_unique<Container>(parent);
    _panel->align(LV_ALIGN_CENTER, 0, 0);
    _panel->setSize(PanelSize, PanelSize);
    _panel->setRadius(0);
    _panel->setBorderWidth(0);
    _panel->setPaddingAll(0);
    _panel->setBgColor(lv_color_hex(BackgroundColor));
    _panel->setBgOpa(LV_OPA_COVER);
    _panel->removeFlag(LV_OBJ_FLAG_SCROLLABLE);

    _controls_layer = std::make_unique<Container>(_panel->get());
    _controls_layer->align(LV_ALIGN_CENTER, 0, 0);
    _controls_layer->setSize(PanelSize, PanelSize);
    _controls_layer->setRadius(0);
    _controls_layer->setBorderWidth(0);
    _controls_layer->setPaddingAll(0);
    _controls_layer->setBgOpa(LV_OPA_TRANSP);
    _controls_layer->removeFlag(LV_OBJ_FLAG_SCROLLABLE);
    _controls_layer->removeFlag(LV_OBJ_FLAG_CLICKABLE);

    _status_panel = std::make_unique<Container>(_controls_layer->get());
    _status_panel->setSize(300, 52);
    _status_panel->align(LV_ALIGN_TOP_MID, 0, 27);
    _status_panel->setBgColor(lv_color_hex(SurfaceColor));
    _status_panel->setBgOpa(LV_OPA_COVER);
    _status_panel->setBorderWidth(0);
    _status_panel->setRadius(LV_RADIUS_CIRCLE);
    _status_panel->setPaddingAll(0);
    _status_panel->removeFlag(LV_OBJ_FLAG_SCROLLABLE);
    _status_panel->removeFlag(LV_OBJ_FLAG_CLICKABLE);

    _status_dot = std::make_unique<Container>(_status_panel->get());
    _status_dot->setSize(14, 14);
    _status_dot->align(LV_ALIGN_LEFT_MID, 23, 0);
    _status_dot->setRadius(LV_RADIUS_CIRCLE);
    _status_dot->setBorderWidth(0);
    _status_dot->setPaddingAll(0);
    _status_dot->setBgColor(lv_color_hex(StartingColor));
    _status_dot->setBgOpa(LV_OPA_COVER);

    _status_label = std::make_unique<Label>(_status_panel->get());
    _status_label->setText("Starting Bluetooth...");
    _status_label->setTextFont(&lv_font_montserrat_18);
    _status_label->setTextColor(lv_color_hex(PrimaryTextColor));
    _status_label->align(LV_ALIGN_LEFT_MID, 51, 0);

    _device_label = std::make_unique<Label>(_controls_layer->get());
    _device_label->setText("M5StopWatch HID + STT  |  PIN 123456");
    _device_label->setTextFont(&lv_font_montserrat_16);
    _device_label->setTextColor(lv_color_hex(SecondaryTextColor));
    _device_label->align(LV_ALIGN_TOP_MID, 0, 88);

    _left_key_panel = std::make_unique<Container>(_controls_layer->get());
    configureKeyPanel(*_left_key_panel, -96);
    _right_key_panel = std::make_unique<Container>(_controls_layer->get());
    configureKeyPanel(*_right_key_panel, 96);

    _left_key_label = std::make_unique<Label>(_left_key_panel->get());
    _left_key_label->setText("ESC");
    _left_key_label->setTextFont(&lv_font_montserrat_36);
    _left_key_label->setTextColor(lv_color_hex(PrimaryTextColor));
    _left_key_label->align(LV_ALIGN_CENTER, 0, -10);
    _left_hint_label = std::make_unique<Label>(_left_key_panel->get());
    _left_hint_label->setText("LEFT BUTTON");
    _left_hint_label->setTextFont(&lv_font_montserrat_10);
    _left_hint_label->setTextColor(lv_color_hex(SecondaryTextColor));
    _left_hint_label->align(LV_ALIGN_CENTER, 0, 30);

    _right_key_label = std::make_unique<Label>(_right_key_panel->get());
    _right_key_label->setText("ENTER");
    _right_key_label->setTextFont(&lv_font_montserrat_28);
    _right_key_label->setTextColor(lv_color_hex(PrimaryTextColor));
    _right_key_label->align(LV_ALIGN_CENTER, 0, -10);
    _right_hint_label = std::make_unique<Label>(_right_key_panel->get());
    _right_hint_label->setText("TAP ENTER / HOLD TALK");
    _right_hint_label->setTextFont(&lv_font_montserrat_10);
    _right_hint_label->setTextColor(lv_color_hex(SecondaryTextColor));
    _right_hint_label->align(LV_ALIGN_CENTER, 0, 30);

    _gesture_label = std::make_unique<Label>(_controls_layer->get());
    _gesture_label->setText(LV_SYMBOL_UP "  SWIPE  " LV_SYMBOL_DOWN);
    _gesture_label->setTextFont(&lv_font_montserrat_22);
    _gesture_label->setTextColor(lv_color_hex(PrimaryTextColor));
    _gesture_label->align(LV_ALIGN_CENTER, 0, 65);

    _gesture_hint_label = std::make_unique<Label>(_controls_layer->get());
    _gesture_hint_label->setText("Touch screen controls the mouse wheel");
    _gesture_hint_label->setTextFont(&lv_font_montserrat_16);
    _gesture_hint_label->setTextColor(lv_color_hex(SecondaryTextColor));
    _gesture_hint_label->align(LV_ALIGN_CENTER, 0, 96);

    _forget_button = std::make_unique<Button>(_controls_layer->get());
    _forget_button->setSize(210, 54);
    _forget_button->align(LV_ALIGN_BOTTOM_MID, 0, -31);
    _forget_button->setRadius(LV_RADIUS_CIRCLE);
    _forget_button->setBorderWidth(0);
    _forget_button->setShadowWidth(0);
    _forget_button->setBgColor(lv_color_hex(ForgetButtonColor));
    _forget_button->label().setText("Forget computer");
    _forget_button->label().setTextFont(&lv_font_montserrat_18);
    _forget_button->label().setTextColor(lv_color_hex(PrimaryTextColor));
    _forget_button->label().align(LV_ALIGN_CENTER, 0, 0);
    _forget_button->onClick().connect([this]() { showForgetDialog(); });

    _displayed_state = model::BleHidRemote::State::Stopped;
    _displayed_error = 0;
    updateStatus(model::BleHidRemote::State::Starting, 0, false, false,
                 model::BleHidRemote::HostStatus::Waiting, 0);
    setControlsVisible(false);
}

void BleHidRemoteView::update(model::BleHidRemote::State state, int lastError, bool speechReady, bool speechActive,
                              model::BleHidRemote::HostStatus hostStatus, uint16_t hostError)
{
    if (state != _displayed_state || (state == model::BleHidRemote::State::Error && lastError != _displayed_error) ||
        speechReady != _displayed_speech_ready || speechActive != _displayed_speech_active ||
        hostStatus != _displayed_host_status || hostError != _displayed_host_error) {
        updateStatus(state, lastError, speechReady, speechActive, hostStatus, hostError);
    }

    const uint32_t now = GetHAL().millis();
    if (_left_flash_until != 0 && static_cast<int32_t>(now - _left_flash_until) >= 0) {
        _left_flash_until = 0;
        _left_key_panel->setBgColor(lv_color_hex(SurfaceColor));
    }
    if (_right_flash_until != 0 && static_cast<int32_t>(now - _right_flash_until) >= 0) {
        _right_flash_until = 0;
        _right_key_panel->setBgColor(lv_color_hex(SurfaceColor));
    }

    if (updateUiToggleGesture()) {
        return;
    }

    if (_forget_dialog) {
        resetGesture();
        if (_forget_dialog->isConfirmed()) {
            _forget_requested = true;
            _forget_dialog.reset();
        } else if (_forget_dialog->isCancelled()) {
            _forget_dialog.reset();
        }
        return;
    }

    updateGesture(state);
}

void BleHidRemoteView::flashKey(bool leftKey)
{
    const uint32_t until = GetHAL().millis() + KeyFlashDurationMs;
    if (leftKey) {
        _left_flash_until = until;
        _left_key_panel->setBgColor(lv_color_hex(SurfaceActiveColor));
    } else {
        _right_flash_until = until;
        _right_key_panel->setBgColor(lv_color_hex(SurfaceActiveColor));
    }
}

int8_t BleHidRemoteView::consumeWheelDelta()
{
    const int delta = std::clamp(_wheel_pending, -MaxWheelStepsPerConsume, MaxWheelStepsPerConsume);
    _wheel_pending -= delta;
    return static_cast<int8_t>(delta);
}

bool BleHidRemoteView::consumeForgetRequested()
{
    const bool requested = _forget_requested;
    _forget_requested    = false;
    return requested;
}

void BleHidRemoteView::updateStatus(model::BleHidRemote::State state, int lastError, bool speechReady,
                                    bool speechActive, model::BleHidRemote::HostStatus hostStatus,
                                    uint16_t hostError)
{
    const char* text = "Stopped";
    uint32_t color   = SecondaryTextColor;
    char errorText[40];

    switch (state) {
        case model::BleHidRemote::State::Starting:
            text  = "Starting Bluetooth...";
            color = StartingColor;
            break;
        case model::BleHidRemote::State::Advertising:
            text  = "Pair on your computer";
            color = AdvertisingColor;
            break;
        case model::BleHidRemote::State::Connected:
            if (speechActive) {
                text  = "Listening...";
                color = ErrorColor;
            } else {
                switch (hostStatus) {
                    case model::BleHidRemote::HostStatus::Preparing:
                        text  = "Preparing speech model...";
                        color = AdvertisingColor;
                        break;
                    case model::BleHidRemote::HostStatus::Ready:
                        text  = speechReady ? "Speech input ready" : "Connecting speech input...";
                        color = speechReady ? ConnectedColor : AdvertisingColor;
                        break;
                    case model::BleHidRemote::HostStatus::Recognizing:
                        text  = "Recognizing...";
                        color = AdvertisingColor;
                        break;
                    case model::BleHidRemote::HostStatus::PermissionError:
                        text  = "Computer permission needed";
                        color = ErrorColor;
                        break;
                    case model::BleHidRemote::HostStatus::ModelError:
                        text  = "Speech model error";
                        color = ErrorColor;
                        break;
                    case model::BleHidRemote::HostStatus::HostError:
                        if (hostError != 0) {
                            std::snprintf(errorText, sizeof(errorText), "STT helper error (%u)", hostError);
                            text = errorText;
                        } else {
                            text = "STT helper error";
                        }
                        color = ErrorColor;
                        break;
                    case model::BleHidRemote::HostStatus::Waiting:
                    default:
                        text  = speechReady ? "Speech input ready" : "HID connected - run STT helper";
                        color = speechReady ? ConnectedColor : AdvertisingColor;
                        break;
                }
            }
            break;
        case model::BleHidRemote::State::Error:
            std::snprintf(errorText, sizeof(errorText), "Bluetooth error (%d)", lastError);
            text  = errorText;
            color = ErrorColor;
            break;
        case model::BleHidRemote::State::Stopped:
        default:
            break;
    }

    _status_label->setText(text);
    _status_dot->setBgColor(lv_color_hex(color));
    _displayed_state = state;
    _displayed_error = lastError;
    _displayed_speech_ready  = speechReady;
    _displayed_speech_active = speechActive;
    _displayed_host_status   = hostStatus;
    _displayed_host_error    = hostError;
}

bool BleHidRemoteView::updateUiToggleGesture()
{
    if (GetHAL().lvTouchpad == nullptr) {
        return false;
    }

    const uint32_t now = GetHAL().millis();
    lv_point_t point;
    lv_indev_get_point(GetHAL().lvTouchpad, &point);
    const bool pressed = lv_indev_get_state(GetHAL().lvTouchpad) == LV_INDEV_STATE_PRESSED;

    if (!pressed) {
        if (_tap_pressing) {
            _tap_pressing = false;
            if (!_tap_moved && now - _tap_started_at <= TapMaxDurationMs) {
                if (_tap_count == 0 || now - _last_tap_at <= MultiTapTimeoutMs) {
                    ++_tap_count;
                } else {
                    _tap_count = 1;
                }
                _last_tap_at = now;

                if (_tap_count >= 3) {
                    _tap_count = 0;
                    setControlsVisible(!_controls_visible);
                    resetGesture();
                    return true;
                }
            } else {
                _tap_count = 0;
            }
        } else if (_tap_count != 0 && now - _last_tap_at > MultiTapTimeoutMs) {
            _tap_count = 0;
        }
        return false;
    }

    if (!_tap_pressing) {
        _tap_pressing   = true;
        _tap_moved      = false;
        _tap_start      = point;
        _tap_started_at = now;
        return false;
    }

    if (std::abs(point.x - _tap_start.x) > TapMaxMovement || std::abs(point.y - _tap_start.y) > TapMaxMovement) {
        _tap_moved = true;
        _tap_count = 0;
    }
    return false;
}

void BleHidRemoteView::setControlsVisible(bool visible)
{
    _controls_visible = visible;
    if (visible) {
        _controls_layer->removeFlag(LV_OBJ_FLAG_HIDDEN);
    } else {
        _controls_layer->addFlag(LV_OBJ_FLAG_HIDDEN);
        _forget_dialog.reset();
        _forget_requested = false;
    }
}

void BleHidRemoteView::updateGesture(model::BleHidRemote::State state)
{
    if (state != model::BleHidRemote::State::Connected || GetHAL().lvTouchpad == nullptr) {
        resetGesture();
        return;
    }

    lv_point_t point;
    lv_indev_get_point(GetHAL().lvTouchpad, &point);
    const bool pressed = lv_indev_get_state(GetHAL().lvTouchpad) == LV_INDEV_STATE_PRESSED;

    if (!pressed) {
        resetGesture();
        return;
    }

    if (!_gesture_pressing) {
        _gesture_pressing  = true;
        _gesture_start     = point;
        _gesture_last      = point;
        _gesture_rejected  = _controls_visible && point.y >= GestureButtonBoundary;
        _gesture_locked    = false;
        _gesture_remainder = 0;
        return;
    }

    if (_gesture_rejected) {
        _gesture_last = point;
        return;
    }

    if (!_gesture_locked) {
        const int totalX = point.x - _gesture_start.x;
        const int totalY = point.y - _gesture_start.y;
        const int absX   = std::abs(totalX);
        const int absY   = std::abs(totalY);
        if (std::max(absX, absY) < GestureLockDistance) {
            _gesture_last = point;
            return;
        }
        if (absY <= absX) {
            _gesture_rejected = true;
            return;
        }
        _gesture_locked    = true;
        _gesture_remainder = totalY;
    } else {
        _gesture_remainder += point.y - _gesture_last.y;
    }

    _gesture_last = point;

    while (_gesture_remainder >= PixelsPerWheelStep) {
        ++_wheel_pending;
        _gesture_remainder -= PixelsPerWheelStep;
    }
    while (_gesture_remainder <= -PixelsPerWheelStep) {
        --_wheel_pending;
        _gesture_remainder += PixelsPerWheelStep;
    }
    _wheel_pending = std::clamp(_wheel_pending, -127, 127);
}

void BleHidRemoteView::resetGesture()
{
    _gesture_pressing  = false;
    _gesture_locked    = false;
    _gesture_rejected  = false;
    _gesture_remainder = 0;
}

void BleHidRemoteView::showForgetDialog()
{
    resetGesture();
    _forget_dialog = std::make_unique<ForgetBondDialog>();
    _forget_dialog->init(_controls_layer->get());
}
