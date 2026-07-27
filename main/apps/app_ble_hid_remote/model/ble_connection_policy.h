/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include <cstdint>

namespace model {

enum class BleConnectionState : uint8_t {
    Stopped,
    Starting,
    UnpairedIdle,
    PairingAdvertising,
    ReconnectDirected,
    ReconnectFiltered,
    Connecting,
    Securing,
    Connected,
    BondedIdle,
    Error,
};

enum class BleAdvertisingMode : uint8_t {
    None,
    PairingLimited,
    ReconnectDirected,
    ReconnectFiltered,
};

class BleConnectionPolicy {
public:
    static constexpr int32_t DirectedDurationMs  = 1280;
    static constexpr int32_t ReconnectDurationMs = 5000;
    static constexpr int32_t FilteredDurationMs  = ReconnectDurationMs - DirectedDurationMs;
    static constexpr int32_t PairingDurationMs   = 180000;

    BleConnectionState start(bool hasBond);
    BleConnectionState beginPairing();
    BleConnectionState requestReconnect(bool hasBond);
    BleConnectionState linkConnected(bool alreadyEncryptedAndBonded);
    BleConnectionState secured(bool bonded);
    BleConnectionState advertisingComplete();
    BleConnectionState disconnected(uint8_t hciReason, bool hasBond, bool pairingRequested);
    BleConnectionState pairingCancelled(bool hasBond);
    BleConnectionState fail();
    BleConnectionState stop();

    BleConnectionState state() const
    {
        return _state;
    }

    BleAdvertisingMode advertisingMode() const;
    int32_t advertisingDurationMs() const;

    static bool isGracefulRemoteDisconnect(uint8_t hciReason);

private:
    BleConnectionState _state = BleConnectionState::Stopped;
};

const char* bleConnectionStateToString(BleConnectionState state);
const char* bleAdvertisingModeToString(BleAdvertisingMode mode);

}  // namespace model
