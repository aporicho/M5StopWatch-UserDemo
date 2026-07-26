/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#include "user_event_mapping.h"

#include <algorithm>
#include <cstring>

#include <esp_log.h>
#include <hal/utils/settings/settings.h>

namespace model {
namespace {

constexpr char Tag[]       = "EVENT-MAP";
constexpr char Namespace[] = "ble_remote";
constexpr char BlobKey[]   = "mapping_v1";

constexpr uint8_t ModNone = 0x00;

constexpr uint8_t KeyEscape = 0x29;
constexpr uint8_t KeyEnter  = 0x28;

constexpr UserActionMapping DefaultMappings[] = {
    {UserEvent::ButtonLeftTap, UserActionType::HidKeyboardTap, KeyEscape, ModNone, 0, 0},
    {UserEvent::ButtonRightTap, UserActionType::HidKeyboardTap, KeyEnter, ModNone, 0, 0},
    {UserEvent::ButtonRightHold, UserActionType::VoiceHoldStart, 0, 0, 0, 0},
    {UserEvent::ButtonRightReleaseAfterHold, UserActionType::VoiceHoldStop, 0, 0, 0, 0},
    {UserEvent::TouchScrollDelta, UserActionType::HidMouseWheel, 1, 0, 0, 0},
    {UserEvent::TouchTripleTap, UserActionType::DeviceToggleControls, 0, 0, 0, 0},
    {UserEvent::ButtonBothHold, UserActionType::DeviceGoHome, 0, 0, 0, 0},
};

bool validEvent(UserEvent event)
{
    return event >= UserEvent::ButtonLeftTap && event <= UserEvent::ButtonBothHold;
}

bool validAction(UserActionType action)
{
    return action <= UserActionType::DeviceGoHome;
}

UserActionMapping sanitize(UserActionMapping record)
{
    if (!validEvent(record.event)) {
        record.event = UserEvent::None;
    }
    if (!validAction(record.action)) {
        record.action = UserActionType::None;
    }
    if (record.event == UserEvent::ButtonBothHold) {
        record.action = UserActionType::DeviceGoHome;
        record.param0 = 0;
        record.param1 = 0;
        record.param2 = 0;
        record.flags  = 0;
    }
    if (record.action == UserActionType::HidMouseWheel && record.param0 == 0) {
        record.param0 = 1;
    }
    return record;
}

void appendRecord(uint8_t* output, std::size_t offset, const UserActionMapping& record)
{
    output[offset + 0] = static_cast<uint8_t>(record.event);
    output[offset + 1] = static_cast<uint8_t>(record.action);
    output[offset + 2] = record.param0;
    output[offset + 3] = record.param1;
    output[offset + 4] = static_cast<uint8_t>(record.param2 & 0xFF);
    output[offset + 5] = static_cast<uint8_t>((record.param2 >> 8) & 0xFF);
    output[offset + 6] = static_cast<uint8_t>(record.flags & 0xFF);
    output[offset + 7] = static_cast<uint8_t>((record.flags >> 8) & 0xFF);
}

UserActionMapping readRecord(const uint8_t* input, std::size_t offset)
{
    return sanitize({
        .event  = static_cast<UserEvent>(input[offset + 0]),
        .action = static_cast<UserActionType>(input[offset + 1]),
        .param0 = input[offset + 2],
        .param1 = input[offset + 3],
        .param2 = static_cast<int16_t>(input[offset + 4] | (input[offset + 5] << 8)),
        .flags  = static_cast<uint16_t>(input[offset + 6] | (input[offset + 7] << 8)),
    });
}

}  // namespace

UserEventMapper::UserEventMapper()
{
    applyDefaultRecords();
}

void UserEventMapper::load()
{
    Settings settings(Namespace);
    std::array<uint8_t, WireHeaderSize + MaxRecords * WireRecordSize> buffer{};
    std::size_t length = buffer.size();
    const esp_err_t result = settings.GetBlob(BlobKey, buffer.data(), &length);
    if (result != ESP_OK || !updateFromWire(buffer.data(), length)) {
        applyDefaultRecords();
        ESP_LOGI(Tag, "using default event mapping");
    } else {
        ESP_LOGI(Tag, "loaded %u event mapping record(s)", static_cast<unsigned>(_count));
    }
}

bool UserEventMapper::save() const
{
    std::array<uint8_t, WireHeaderSize + MaxRecords * WireRecordSize> buffer{};
    const std::size_t length = writeWire(buffer.data(), buffer.size());
    Settings settings(Namespace, true);
    const esp_err_t result = settings.SetBlob(BlobKey, buffer.data(), length);
    if (result != ESP_OK) {
        ESP_LOGW(Tag, "failed to save event mapping: %s", esp_err_to_name(result));
        return false;
    }
    return true;
}

bool UserEventMapper::updateFromWire(const uint8_t* data, std::size_t length)
{
    if (data == nullptr || length < WireHeaderSize || data[0] != WireMagic0 || data[1] != WireMagic1 ||
        data[2] != MappingVersion) {
        return false;
    }
    const uint8_t count = data[3];
    if (count > MaxRecords || length != static_cast<std::size_t>(WireHeaderSize + count * WireRecordSize)) {
        return false;
    }

    std::array<UserActionMapping, MaxRecords> next{};
    std::size_t nextCount = 0;
    for (uint8_t index = 0; index < count; ++index) {
        const UserActionMapping record = readRecord(data, WireHeaderSize + index * WireRecordSize);
        if (record.event == UserEvent::None) {
            continue;
        }
        bool replaced = false;
        for (std::size_t existing = 0; existing < nextCount; ++existing) {
            if (next[existing].event == record.event) {
                next[existing] = record;
                replaced       = true;
                break;
            }
        }
        if (!replaced && nextCount < MaxRecords) {
            next[nextCount++] = record;
        }
    }

    _records = next;
    _count   = nextCount;
    setRecord({UserEvent::ButtonBothHold, UserActionType::DeviceGoHome, 0, 0, 0, 0});
    return true;
}

std::size_t UserEventMapper::writeWire(uint8_t* data, std::size_t capacity) const
{
    if (data == nullptr || capacity < WireHeaderSize) {
        return 0;
    }
    const std::size_t count = std::min(_count, static_cast<std::size_t>(MaxRecords));
    const std::size_t need  = WireHeaderSize + count * WireRecordSize;
    if (capacity < need) {
        return 0;
    }
    data[0] = WireMagic0;
    data[1] = WireMagic1;
    data[2] = MappingVersion;
    data[3] = static_cast<uint8_t>(count);
    for (std::size_t index = 0; index < count; ++index) {
        appendRecord(data, WireHeaderSize + index * WireRecordSize, sanitize(_records[index]));
    }
    return need;
}

UserActionMapping UserEventMapper::actionFor(UserEvent event) const
{
    for (std::size_t index = 0; index < _count; ++index) {
        if (_records[index].event == event) {
            return sanitize(_records[index]);
        }
    }
    for (const auto& record : DefaultMappings) {
        if (record.event == event) {
            return record;
        }
    }
    return {event, UserActionType::None, 0, 0, 0, 0};
}

void UserEventMapper::applyDefaultRecords()
{
    _records = {};
    _count   = 0;
    for (const auto& record : DefaultMappings) {
        setRecord(record);
    }
}

bool UserEventMapper::setRecord(const UserActionMapping& value)
{
    const UserActionMapping record = sanitize(value);
    if (record.event == UserEvent::None) {
        return false;
    }
    for (std::size_t index = 0; index < _count; ++index) {
        if (_records[index].event == record.event) {
            _records[index] = record;
            return true;
        }
    }
    if (_count >= MaxRecords) {
        return false;
    }
    _records[_count++] = record;
    return true;
}

const char* userEventToId(UserEvent event)
{
    switch (event) {
        case UserEvent::ButtonLeftTap:
            return "button.left.tap";
        case UserEvent::ButtonLeftHold:
            return "button.left.hold";
        case UserEvent::ButtonLeftReleaseAfterHold:
            return "button.left.release_after_hold";
        case UserEvent::ButtonRightTap:
            return "button.right.tap";
        case UserEvent::ButtonRightHold:
            return "button.right.hold";
        case UserEvent::ButtonRightReleaseAfterHold:
            return "button.right.release_after_hold";
        case UserEvent::TouchTap:
            return "touch.tap";
        case UserEvent::TouchDoubleTap:
            return "touch.double_tap";
        case UserEvent::TouchTripleTap:
            return "touch.triple_tap";
        case UserEvent::TouchHold:
            return "touch.hold";
        case UserEvent::TouchSwipeUp:
            return "touch.swipe_up";
        case UserEvent::TouchSwipeDown:
            return "touch.swipe_down";
        case UserEvent::TouchSwipeLeft:
            return "touch.swipe_left";
        case UserEvent::TouchSwipeRight:
            return "touch.swipe_right";
        case UserEvent::TouchScrollDelta:
            return "touch.scroll_delta";
        case UserEvent::ButtonBothHold:
            return "button.both.hold";
        case UserEvent::None:
        default:
            return "none";
    }
}

const char* userActionToId(UserActionType action)
{
    switch (action) {
        case UserActionType::HidKeyboardTap:
            return "hid.keyboard.tap";
        case UserActionType::HidMouseWheel:
            return "hid.mouse.wheel";
        case UserActionType::HidMouseClick:
            return "hid.mouse.click";
        case UserActionType::HidMediaControl:
            return "hid.media.control";
        case UserActionType::VoiceHoldStart:
            return "voice.hold.start";
        case UserActionType::VoiceHoldStop:
            return "voice.hold.stop";
        case UserActionType::VoiceToggle:
            return "voice.toggle";
        case UserActionType::DevicePairNewComputer:
            return "device.pair_new_computer";
        case UserActionType::DeviceShowControls:
            return "device.show_controls";
        case UserActionType::DeviceHideControls:
            return "device.hide_controls";
        case UserActionType::DeviceToggleControls:
            return "device.toggle_controls";
        case UserActionType::DeviceGoHome:
            return "device.go_home";
        case UserActionType::None:
        default:
            return "none";
    }
}

}  // namespace model
