/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace model::speech {

constexpr std::size_t InputSamplesPerFrame  = 882;
constexpr std::size_t OutputSamplesPerFrame = 320;
constexpr std::size_t AdpcmBlockBytes       = 164;

void resample44k1To16k(const int16_t* input, std::array<int16_t, OutputSamplesPerFrame>& output);
void encodeImaAdpcm(const std::array<int16_t, OutputSamplesPerFrame>& input,
                    std::array<uint8_t, AdpcmBlockBytes>& output, int& stepIndex);

}  // namespace model::speech
