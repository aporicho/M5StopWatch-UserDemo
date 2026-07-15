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
    std::unique_ptr<model::BleHidRemote> _remote;
    std::unique_ptr<view::BleHidRemoteView> _view;
    uint32_t _speech_start_at       = 0;
    bool _right_long_latched        = false;
    bool _speech_start_pending      = false;
    bool _speech_end_feedback       = false;
    bool _home_latched              = false;
};
