/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#include "speech_codec.h"

#include <algorithm>

namespace model::speech {
namespace {

constexpr std::array<int, 89> StepTable = {
    7,    8,     9,     10,    11,    12,    13,    14,    16,    17,    19,    21,    23,    25,    28,
    31,   34,    37,    41,    45,    50,    55,    60,    66,    73,    80,    88,    97,    107,   118,
    130,  143,   157,   173,   190,   209,   230,   253,   279,   307,   337,   371,   408,   449,   494,
    544,  598,   658,   724,   796,   876,   963,   1060,  1166,  1282,  1411,  1552,  1707,  1878,  2066,
    2272, 2499,  2749,  3024,  3327,  3660,  4026,  4428,  4871,  5358,  5894,  6484,  7132,  7845,  8630,
    9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
};

constexpr std::array<int, 16> IndexTable = {
    -1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8,
};

uint8_t encodeNibble(int sample, int& predictor, int& stepIndex)
{
    const int step = StepTable[stepIndex];
    int difference = sample - predictor;
    uint8_t nibble = 0;
    if (difference < 0) {
        nibble |= 0x08;
        difference = -difference;
    }

    int delta = step >> 3;
    if (difference >= step) {
        nibble |= 0x04;
        difference -= step;
        delta += step;
    }
    if (difference >= (step >> 1)) {
        nibble |= 0x02;
        difference -= step >> 1;
        delta += step >> 1;
    }
    if (difference >= (step >> 2)) {
        nibble |= 0x01;
        delta += step >> 2;
    }

    predictor += (nibble & 0x08) ? -delta : delta;
    predictor = std::clamp(predictor, -32768, 32767);
    stepIndex = std::clamp(stepIndex + IndexTable[nibble], 0, 88);
    return nibble;
}

}  // namespace

void resample44k1To16k(const int16_t* input, std::array<int16_t, OutputSamplesPerFrame>& output)
{
    // Each frame is exactly 20 ms, so 882 input samples map to 320 output
    // samples without carrying a fractional phase into the next frame.
    constexpr uint32_t Numerator   = 441;
    constexpr uint32_t Denominator = 160;
    for (std::size_t index = 0; index < output.size(); ++index) {
        const uint32_t position = static_cast<uint32_t>(index) * Numerator;
        const std::size_t left  = position / Denominator;
        const uint32_t fraction = position % Denominator;
        const std::size_t right = std::min(left + 1, InputSamplesPerFrame - 1);
        const int32_t mixed     = static_cast<int32_t>(input[left]) * (Denominator - fraction) +
                                  static_cast<int32_t>(input[right]) * fraction;
        output[index]           = static_cast<int16_t>(mixed / static_cast<int32_t>(Denominator));
    }
}

void encodeImaAdpcm(const std::array<int16_t, OutputSamplesPerFrame>& input,
                    std::array<uint8_t, AdpcmBlockBytes>& output, int& stepIndex)
{
    int predictor = input[0];
    stepIndex     = std::clamp(stepIndex, 0, 88);
    output.fill(0);
    output[0] = static_cast<uint8_t>(predictor & 0xFF);
    output[1] = static_cast<uint8_t>((predictor >> 8) & 0xFF);
    output[2] = static_cast<uint8_t>(stepIndex);
    output[3] = 0;

    for (std::size_t sample = 1; sample < input.size(); ++sample) {
        const uint8_t nibble   = encodeNibble(input[sample], predictor, stepIndex);
        const std::size_t byte = 4 + ((sample - 1) / 2);
        const bool highNibble  = ((sample - 1) & 1U) != 0;
        output[byte] |= highNibble ? static_cast<uint8_t>(nibble << 4) : nibble;
    }
}

}  // namespace model::speech
