/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include "sdkconfig.h"

namespace test_control {

#ifdef CONFIG_M5_TEST_CONTROL
void start();
void update();
#else
inline void start() {}
inline void update() {}
#endif

}  // namespace test_control
