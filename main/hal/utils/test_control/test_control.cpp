/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#include "test_control.h"

#ifdef CONFIG_M5_TEST_CONTROL

#include <apps/app_ble_hid_remote/app_ble_hid_remote.h>
#include <apps/app_launcher/app_launcher.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>
#include <hal/hal.h>
#include <mooncake.h>
#include <mooncake_log.h>

#include <cctype>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace test_control {
namespace {

constexpr const char* Tag            = "M5-TEST";
constexpr const char* ResponsePrefix = "@@M5TEST ";
constexpr std::size_t MaxCommandSize = 256;

struct RawCommand {
    char line[MaxCommandSize]{};
};

QueueHandle_t s_command_queue = nullptr;

void printSeparator(bool& first)
{
    if (!first) {
        std::printf(",");
    }
    first = false;
}

void printJsonString(const char* value)
{
    std::printf("\"");
    if (value != nullptr) {
        for (const char* cursor = value; *cursor != '\0'; ++cursor) {
            const unsigned char c = static_cast<unsigned char>(*cursor);
            switch (c) {
                case '"':
                    std::printf("\\\"");
                    break;
                case '\\':
                    std::printf("\\\\");
                    break;
                case '\b':
                    std::printf("\\b");
                    break;
                case '\f':
                    std::printf("\\f");
                    break;
                case '\n':
                    std::printf("\\n");
                    break;
                case '\r':
                    std::printf("\\r");
                    break;
                case '\t':
                    std::printf("\\t");
                    break;
                default:
                    if (c < 0x20) {
                        std::printf("\\u%04x", c);
                    } else {
                        std::printf("%c", c);
                    }
                    break;
            }
        }
    }
    std::printf("\"");
}

void printKey(const char* key)
{
    printJsonString(key);
    std::printf(":");
}

void printStringField(bool& first, const char* key, const char* value)
{
    printSeparator(first);
    printKey(key);
    printJsonString(value == nullptr ? "" : value);
}

void printBoolField(bool& first, const char* key, bool value)
{
    printSeparator(first);
    printKey(key);
    std::printf(value ? "true" : "false");
}

void printNumberField(bool& first, const char* key, long long value)
{
    printSeparator(first);
    printKey(key);
    std::printf("%lld", value);
}

void beginResponse()
{
    std::printf("%s{", ResponsePrefix);
}

void endResponse()
{
    std::printf("}\n");
    std::fflush(stdout);
}

const char* findValue(const char* line, const char* key)
{
    if (line == nullptr || key == nullptr) {
        return nullptr;
    }

    char quoted_key[48]{};
    if (std::snprintf(quoted_key, sizeof(quoted_key), "\"%s\"", key) >= static_cast<int>(sizeof(quoted_key))) {
        return nullptr;
    }

    const std::size_t quoted_key_length = std::strlen(quoted_key);
    const char* cursor                  = line;
    while ((cursor = std::strstr(cursor, quoted_key)) != nullptr) {
        const char* value = cursor + quoted_key_length;
        while (*value != '\0' && std::isspace(static_cast<unsigned char>(*value)) != 0) {
            ++value;
        }
        if (*value == ':') {
            cursor = value;
            break;
        }
        cursor += quoted_key_length;
    }
    if (cursor == nullptr || *cursor != ':') {
        return nullptr;
    }

    ++cursor;
    while (*cursor != '\0' && std::isspace(static_cast<unsigned char>(*cursor)) != 0) {
        ++cursor;
    }
    return cursor;
}

bool readString(const char* line, const char* key, char* output, std::size_t outputSize)
{
    if (output == nullptr || outputSize == 0) {
        return false;
    }
    output[0] = '\0';

    const char* cursor = findValue(line, key);
    if (cursor == nullptr || *cursor != '"') {
        return false;
    }
    ++cursor;

    std::size_t written = 0;
    while (*cursor != '\0' && *cursor != '"') {
        char c = *cursor++;
        if (c == '\\' && *cursor != '\0') {
            const char escaped = *cursor++;
            switch (escaped) {
                case '"':
                case '\\':
                case '/':
                    c = escaped;
                    break;
                case 'b':
                    c = '\b';
                    break;
                case 'f':
                    c = '\f';
                    break;
                case 'n':
                    c = '\n';
                    break;
                case 'r':
                    c = '\r';
                    break;
                case 't':
                    c = '\t';
                    break;
                default:
                    c = escaped;
                    break;
            }
        }
        if (written + 1 < outputSize) {
            output[written++] = c;
        }
    }
    if (*cursor != '"') {
        output[0] = '\0';
        return false;
    }
    output[written] = '\0';
    return true;
}

int readInt(const char* line, const char* key, int fallback)
{
    const char* cursor = findValue(line, key);
    if (cursor == nullptr) {
        return fallback;
    }
    char* end = nullptr;
    const long value = std::strtol(cursor, &end, 10);
    if (end == cursor) {
        return fallback;
    }
    return static_cast<int>(value);
}

const char* appStateToString(mooncake::AppAbility::State_t state)
{
    switch (state) {
        case mooncake::AppAbility::StateGoOpen:
            return "opening";
        case mooncake::AppAbility::StateRunning:
            return "running";
        case mooncake::AppAbility::StateGoClose:
            return "closing";
        case mooncake::AppAbility::StateSleeping:
            return "sleeping";
        case mooncake::AppAbility::StateNull:
        default:
            return "null";
    }
}

void respondError(const char* cmd, const char* message)
{
    bool first = true;
    beginResponse();
    printBoolField(first, "ok", false);
    printStringField(first, "cmd", cmd == nullptr ? "" : cmd);
    printStringField(first, "message", message == nullptr ? "" : message);
    endResponse();
}

void printAppsArray()
{
    std::printf("[");
    bool first = true;
    for (const auto& props : mooncake::GetMooncake().getAllAppProps()) {
        printSeparator(first);
        bool app_first = true;
        std::printf("{");
        printNumberField(app_first, "id", static_cast<long long>(props.appID));
        printStringField(app_first, "name", props.info.name.c_str());
        printStringField(app_first, "state", appStateToString(mooncake::GetMooncake().getAppCurrentState(props.appID)));
        std::printf("}");
    }
    std::printf("]");
}

int launcherSelectedIndex()
{
    for (const auto& props : mooncake::GetMooncake().getAllAppProps()) {
        if (props.info.name != "Launcher") {
            continue;
        }
        auto* ability = mooncake::GetMooncake().getAppAbilityManager()->getAbilityInstance(props.appID);
        if (ability == nullptr) {
            return -1;
        }
        return static_cast<AppLauncher*>(ability)->testSelectedIndex();
    }
    return -1;
}

void printBleSnapshotObject()
{
    std::printf("{");
    bool first = true;
    for (const auto& props : mooncake::GetMooncake().getAllAppProps()) {
        if (props.info.name != "BLE Remote") {
            continue;
        }
        printNumberField(first, "app_id", static_cast<long long>(props.appID));
        printStringField(first, "app_state", appStateToString(mooncake::GetMooncake().getAppCurrentState(props.appID)));
        auto* ability = mooncake::GetMooncake().getAppAbilityManager()->getAbilityInstance(props.appID);
        if (ability == nullptr) {
            printBoolField(first, "has_remote", false);
            std::printf("}");
            return;
        }
        const auto snapshot = static_cast<AppBleHidRemote*>(ability)->testSnapshot();
        printBoolField(first, "has_remote", snapshot.hasRemote);
        printStringField(first, "state", snapshot.state);
        printNumberField(first, "last_error", snapshot.lastError);
        printStringField(first, "last_error_stage", snapshot.lastErrorStage);
        printStringField(first, "speech", snapshot.speechService);
        printStringField(first, "host", snapshot.hostStatus);
        printNumberField(first, "host_error", snapshot.hostError);
        printBoolField(first, "speech_ready", snapshot.speechReady);
        printBoolField(first, "speech_active", snapshot.speechActive);
        std::printf("}");
        return;
    }
    printBoolField(first, "has_remote", false);
    std::printf("}");
}

void printBleSnapshotField(bool& first)
{
    printSeparator(first);
    printKey("ble_remote");
    printBleSnapshotObject();
}

void respondState(const char* cmd, bool includeApps)
{
    bool first = true;
    beginResponse();
    printBoolField(first, "ok", true);
    printStringField(first, "cmd", cmd);
    printNumberField(first, "uptime_ms", static_cast<long long>(GetHAL().millis()));
    printNumberField(first, "launcher_selected_index", launcherSelectedIndex());
    if (includeApps) {
        printSeparator(first);
        printKey("apps");
        printAppsArray();
    }
    printBleSnapshotField(first);
    endResponse();
}

void handlePing()
{
    bool first = true;
    beginResponse();
    printBoolField(first, "ok", true);
    printStringField(first, "cmd", "ping");
    printNumberField(first, "version", 1);
    printNumberField(first, "uptime_ms", static_cast<long long>(GetHAL().millis()));
    printBoolField(first, "input_only", true);
    endResponse();
}

void handleButton(const RawCommand& request)
{
    char button[16]{};
    char state[16]{};
    if (!readString(request.line, "button", button, sizeof(button)) ||
        !readString(request.line, "state", state, sizeof(state))) {
        respondError("button", "button and state are required");
        return;
    }
    const bool left = std::strcmp(button, "left") == 0;
    if (!left && std::strcmp(button, "right") != 0) {
        respondError("button", "button must be left or right");
        return;
    }
    const bool down = std::strcmp(state, "down") == 0;
    if (!down && std::strcmp(state, "up") != 0) {
        respondError("button", "state must be down or up");
        return;
    }

    GetHAL().setSyntheticButtonState(left, down);

    bool first = true;
    beginResponse();
    printBoolField(first, "ok", true);
    printStringField(first, "cmd", "button");
    printStringField(first, "button", button);
    printStringField(first, "state", state);
    endResponse();
}

void handleTouch(const RawCommand& request)
{
    char state[16]{};
    if (!readString(request.line, "state", state, sizeof(state))) {
        respondError("touch", "state is required");
        return;
    }
    const bool pressed = std::strcmp(state, "up") != 0;
    if (pressed && std::strcmp(state, "down") != 0 && std::strcmp(state, "move") != 0) {
        respondError("touch", "state must be down, move, or up");
        return;
    }

    const int x = readInt(request.line, "x", -1);
    const int y = readInt(request.line, "y", -1);
    if (pressed && (x < 0 || y < 0)) {
        respondError("touch", "x and y are required for down/move");
        return;
    }

    GetHAL().setSyntheticTouchState(pressed, x, y);

    bool first = true;
    beginResponse();
    printBoolField(first, "ok", true);
    printStringField(first, "cmd", "touch");
    printStringField(first, "state", state);
    printNumberField(first, "x", x);
    printNumberField(first, "y", y);
    endResponse();
}

void handleClearInput()
{
    GetHAL().clearSyntheticInput();

    bool first = true;
    beginResponse();
    printBoolField(first, "ok", true);
    printStringField(first, "cmd", "clear_input");
    endResponse();
}

void handleCommand(const RawCommand& raw)
{
    char cmd[32]{};
    if (!readString(raw.line, "cmd", cmd, sizeof(cmd))) {
        respondError("", "cmd is required");
        return;
    }

    if (std::strcmp(cmd, "ping") == 0) {
        handlePing();
    } else if (std::strcmp(cmd, "apps") == 0) {
        respondState("apps", true);
    } else if (std::strcmp(cmd, "state") == 0) {
        respondState("state", false);
    } else if (std::strcmp(cmd, "ble_state") == 0) {
        bool first = true;
        beginResponse();
        printBoolField(first, "ok", true);
        printStringField(first, "cmd", "ble_state");
        printBleSnapshotField(first);
        endResponse();
    } else if (std::strcmp(cmd, "button") == 0) {
        handleButton(raw);
    } else if (std::strcmp(cmd, "touch") == 0) {
        handleTouch(raw);
    } else if (std::strcmp(cmd, "clear_input") == 0) {
        handleClearInput();
    } else {
        respondError(cmd, "unknown command");
    }
}

void serialTask(void*)
{
    RawCommand command{};
    while (true) {
        if (std::fgets(command.line, sizeof(command.line), stdin) == nullptr) {
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        const std::size_t length = std::strlen(command.line);
        if (length == 0) {
            continue;
        }
        while (command.line[0] != '\0' &&
               (command.line[std::strlen(command.line) - 1] == '\n' ||
                command.line[std::strlen(command.line) - 1] == '\r')) {
            command.line[std::strlen(command.line) - 1] = '\0';
        }
        if (command.line[0] == '\0') {
            continue;
        }
        if (s_command_queue != nullptr) {
            xQueueSend(s_command_queue, &command, portMAX_DELAY);
        }
    }
}

}  // namespace

void start()
{
    if (s_command_queue != nullptr) {
        return;
    }
    s_command_queue = xQueueCreate(8, sizeof(RawCommand));
    if (s_command_queue == nullptr) {
        mclog::tagError(Tag, "failed to create command queue");
        return;
    }
    if (xTaskCreate(serialTask, "m5_test_ctl", 4096, nullptr, 1, nullptr) != pdPASS) {
        mclog::tagError(Tag, "failed to create serial task");
        vQueueDelete(s_command_queue);
        s_command_queue = nullptr;
        return;
    }
    mclog::tagInfo(Tag, "USB synthetic user-input test control enabled");
}

void update()
{
    if (s_command_queue == nullptr) {
        return;
    }

    RawCommand command{};
    while (xQueueReceive(s_command_queue, &command, 0) == pdTRUE) {
        handleCommand(command);
    }
}

}  // namespace test_control

#endif
