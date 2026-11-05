#include "ble_connection_policy.h"

#include <cassert>

int main()
{
    using model::BleAdvertisingMode;
    using model::BleConnectionPolicy;
    using model::BleConnectionState;

    BleConnectionPolicy policy;
    assert(policy.start(false) == BleConnectionState::PairingAdvertising);
    assert(policy.advertisingMode() == BleAdvertisingMode::PairingLimited);
    assert(policy.advertisingDurationMs() == 180000);
    assert(policy.advertisingComplete() == BleConnectionState::UnpairedIdle);

    assert(policy.start(true) == BleConnectionState::ReconnectDirected);
    assert(policy.advertisingDurationMs() == 1280);
    assert(policy.advertisingComplete() == BleConnectionState::ReconnectFiltered);
    assert(policy.advertisingDurationMs() == 3720);
    assert(policy.advertisingComplete() == BleConnectionState::BondedIdle);

    assert(policy.requestReconnect(true) == BleConnectionState::ReconnectDirected);
    assert(policy.linkConnected(true) == BleConnectionState::Connected);
    assert(policy.disconnected(0x13, true, false) == BleConnectionState::BondedIdle);
    assert(policy.requestReconnect(true) == BleConnectionState::ReconnectDirected);
    assert(policy.linkConnected(false) == BleConnectionState::Securing);
    assert(policy.secured(true) == BleConnectionState::Connected);
    assert(policy.disconnected(0x08, true, false) == BleConnectionState::ReconnectDirected);

    assert(policy.disconnected(0x16, true, true) == BleConnectionState::PairingAdvertising);
    assert(policy.pairingCancelled(false) == BleConnectionState::UnpairedIdle);
    assert(policy.beginPairing() == BleConnectionState::PairingAdvertising);
    assert(policy.secured(false) == BleConnectionState::Error);
    assert(policy.stop() == BleConnectionState::Stopped);
    return 0;
}
