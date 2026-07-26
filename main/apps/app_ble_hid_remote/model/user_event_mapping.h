/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace model {

enum class UserEvent : uint8_t {
    None                      = 0,
    ButtonLeftTap             = 1,
    ButtonLeftHold            = 2,
    ButtonLeftReleaseAfterHold = 3,
    ButtonRightTap            = 4,
    ButtonRightHold           = 5,
    ButtonRightReleaseAfterHold = 6,
    TouchTap                  = 7,
    TouchDoubleTap            = 8,
    TouchTripleTap            = 9,
    TouchHold                 = 10,
    TouchSwipeUp              = 11,
    TouchSwipeDown            = 12,
    TouchSwipeLeft            = 13,
    TouchSwipeRight           = 14,
    TouchScrollDelta          = 15,
    ButtonBothHold            = 16,
};

enum class UserActionType : uint8_t {
    None                 = 0,
    HidKeyboardTap       = 1,
    HidMouseWheel        = 2,
    HidMouseClick        = 3,
    HidMediaControl      = 4,
    VoiceHoldStart       = 5,
    VoiceHoldStop        = 6,
    VoiceToggle          = 7,
    DevicePairNewComputer = 8,
    DeviceShowControls   = 9,
    DeviceHideControls   = 10,
    DeviceToggleControls = 11,
    DeviceGoHome         = 12,
    VoiceCommandStart    = 13,
    VoiceCommandStop     = 14,
};

struct UserActionMapping {
    UserEvent event       = UserEvent::None;
    UserActionType action = UserActionType::None;
    uint8_t param0        = 0;
    uint8_t param1        = 0;
    int16_t param2        = 0;
    uint16_t flags        = 0;
};

class UserEventMapper {
public:
    static constexpr uint8_t MappingVersion = 1;
    static constexpr uint8_t MaxRecords     = 24;
    static constexpr uint8_t WireHeaderSize = 4;
    static constexpr uint8_t WireRecordSize = 8;
    static constexpr uint8_t WireMagic0     = 0x4D;  // M
    static constexpr uint8_t WireMagic1     = 0x35;  // 5

    UserEventMapper();

    void load();
    bool save() const;
    bool updateFromWire(const uint8_t* data, std::size_t length);
    std::size_t writeWire(uint8_t* data, std::size_t capacity) const;
    UserActionMapping actionFor(UserEvent event) const;

private:
    void applyDefaultRecords();
    bool setRecord(const UserActionMapping& record);

    std::array<UserActionMapping, MaxRecords> _records{};
    std::size_t _count = 0;
};

const char* userEventToId(UserEvent event);
const char* userActionToId(UserActionType action);

}  // namespace model
