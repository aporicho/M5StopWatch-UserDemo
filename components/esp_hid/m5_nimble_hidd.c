/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/*
 * ESP-IDF 5.5's nimble_hidd.c builds HID Information from these two macros,
 * but does not expose them in esp_hid_device_config_t.  Include the upstream
 * implementation with both unsupported product capabilities disabled.  The
 * public ESP-IDF API and the remainder of the component stay untouched.
 */
#include "esp_hid_common.h"

#undef ESP_HID_FLAGS_REMOTE_WAKE
#undef ESP_HID_FLAGS_NORMALLY_CONNECTABLE
#define ESP_HID_FLAGS_REMOTE_WAKE 0
#define ESP_HID_FLAGS_NORMALLY_CONNECTABLE 0

#include M5_UPSTREAM_NIMBLE_HIDD
