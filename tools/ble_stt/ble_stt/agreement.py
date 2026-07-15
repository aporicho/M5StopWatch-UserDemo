from __future__ import annotations

def common_prefix(left: str, right: str) -> str:
    length = min(len(left), len(right))
    index = 0
    while index < length and left[index] == right[index]:
        index += 1
    return left[:index]


def stable_extension(previous: str, current: str, committed: str) -> tuple[str, str]:
    agreed = common_prefix(previous, current)
    if not agreed.startswith(committed):
        return "", committed

    # Do not commit the last unfinished ASCII word. CJK characters do not need
    # a whitespace boundary and can be committed individually.
    safe = agreed
    if safe and safe[-1].isascii() and safe[-1].isalnum():
        boundary = len(safe)
        while boundary > len(committed) and safe[boundary - 1].isascii() and (
            safe[boundary - 1].isalnum() or safe[boundary - 1] in "_-.'"
        ):
            boundary -= 1
        safe = safe[:boundary]
    if len(safe) <= len(committed):
        return "", committed
    return safe[len(committed):], safe
