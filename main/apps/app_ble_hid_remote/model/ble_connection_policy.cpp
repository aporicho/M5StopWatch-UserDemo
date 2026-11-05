/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#include "ble_connection_policy.h"

namespace model {

namespace {
constexpr uint8_t RemoteUserTerminatedConnection = 0x13;
constexpr uint8_t LocalHostTerminatedConnection  = 0x16;
}  // namespace

BleConnectionState BleConnectionPolicy::start(bool hasBond)
{
    _state = hasBond ? BleConnectionState::ReconnectDirected : BleConnectionState::PairingAdvertising;
    return _state;
}

BleConnectionState BleConnectionPolicy::beginPairing()
{
    _state = BleConnectionState::PairingAdvertising;
    return _state;
}

BleConnectionState BleConnectionPolicy::requestReconnect(bool hasBond)
{
    _state = hasBond ? BleConnectionState::ReconnectDirected : BleConnectionState::UnpairedIdle;
    return _state;
}

BleConnectionState BleConnectionPolicy::linkConnected(bool alreadyEncryptedAndBonded)
{
    _state = alreadyEncryptedAndBonded ? BleConnectionState::Connected : BleConnectionState::Securing;
    return _state;
}

BleConnectionState BleConnectionPolicy::secured(bool bonded)
{
    _state = bonded ? BleConnectionState::Connected : BleConnectionState::Error;
    return _state;
}

BleConnectionState BleConnectionPolicy::advertisingComplete()
{
    if (_state == BleConnectionState::ReconnectDirected) {
        _state = BleConnectionState::ReconnectFiltered;
    } else if (_state == BleConnectionState::ReconnectFiltered) {
        _state = BleConnectionState::BondedIdle;
    } else if (_state == BleConnectionState::PairingAdvertising) {
        _state = BleConnectionState::UnpairedIdle;
    }
    return _state;
}

BleConnectionState BleConnectionPolicy::disconnected(uint8_t hciReason, bool hasBond, bool pairingRequested)
{
    if (pairingRequested) {
        _state = BleConnectionState::PairingAdvertising;
    } else if (!hasBond) {
        _state = BleConnectionState::UnpairedIdle;
    } else if (isGracefulRemoteDisconnect(hciReason) || hciReason == LocalHostTerminatedConnection) {
        _state = BleConnectionState::BondedIdle;
    } else {
        _state = BleConnectionState::ReconnectDirected;
    }
    return _state;
}

BleConnectionState BleConnectionPolicy::pairingCancelled(bool hasBond)
{
    _state = hasBond ? BleConnectionState::BondedIdle : BleConnectionState::UnpairedIdle;
    return _state;
}

BleConnectionState BleConnectionPolicy::fail()
{
    _state = BleConnectionState::Error;
    return _state;
}

BleConnectionState BleConnectionPolicy::stop()
{
    _state = BleConnectionState::Stopped;
    return _state;
}

BleAdvertisingMode BleConnectionPolicy::advertisingMode() const
{
    switch (_state) {
        case BleConnectionState::PairingAdvertising:
            return BleAdvertisingMode::PairingLimited;
        case BleConnectionState::ReconnectDirected:
            return BleAdvertisingMode::ReconnectDirected;
        case BleConnectionState::ReconnectFiltered:
            return BleAdvertisingMode::ReconnectFiltered;
        default:
            return BleAdvertisingMode::None;
    }
}

int32_t BleConnectionPolicy::advertisingDurationMs() const
{
    switch (_state) {
        case BleConnectionState::PairingAdvertising:
            return PairingDurationMs;
        case BleConnectionState::ReconnectDirected:
            return DirectedDurationMs;
        case BleConnectionState::ReconnectFiltered:
            return FilteredDurationMs;
        default:
            return 0;
    }
}

bool BleConnectionPolicy::isGracefulRemoteDisconnect(uint8_t hciReason)
{
    return hciReason == RemoteUserTerminatedConnection;
}

const char* bleConnectionStateToString(BleConnectionState state)
{
    switch (state) {
        case BleConnectionState::Stopped:
            return "Stopped";
        case BleConnectionState::Starting:
            return "Starting";
        case BleConnectionState::UnpairedIdle:
            return "Unpaired idle";
        case BleConnectionState::PairingAdvertising:
            return "Waiting for pairing";
        case BleConnectionState::ReconnectDirected:
            return "Reconnecting (directed)";
        case BleConnectionState::ReconnectFiltered:
            return "Reconnecting (filtered)";
        case BleConnectionState::Connecting:
            return "Connecting";
        case BleConnectionState::Securing:
            return "Securing";
        case BleConnectionState::Connected:
            return "Connected";
        case BleConnectionState::BondedIdle:
            return "Bonded idle";
        case BleConnectionState::Error:
            return "Bluetooth error";
        default:
            return "Unknown";
    }
}

const char* bleAdvertisingModeToString(BleAdvertisingMode mode)
{
    switch (mode) {
        case BleAdvertisingMode::None:
            return "none";
        case BleAdvertisingMode::PairingLimited:
            return "pairing_limited";
        case BleAdvertisingMode::ReconnectDirected:
            return "reconnect_directed";
        case BleAdvertisingMode::ReconnectFiltered:
            return "reconnect_filtered";
        default:
            return "unknown";
    }
}

}  // namespace model
