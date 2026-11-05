from __future__ import annotations

from collections.abc import Iterable


# Compact bias lists are more useful to Whisper than a full dictionary: the
# base model already knows ordinary words, while product and computing terms
# are disproportionately likely to be split or substituted by ASR.
STANDARD_LEXICON_PACKS: dict[str, tuple[str, ...]] = {
    "general": (
        "安装",
        "卸载",
        "下载",
        "更新",
        "文件",
        "桌面",
        "页面",
        "窗口",
        "输入框",
        "按钮",
        "列表",
        "状态栏",
        "通知",
        "声音",
        "电量",
        "版本",
        "问题",
        "正常",
        "检查",
        "备份",
        "配置文件",
        "缓存目录",
        "服务",
        "后台服务",
        "权限",
        "设置",
        "模型",
        "词典",
        "语音识别",
        "简体中文",
        "英文",
    ),
    "computing": (
        "远端仓库",
        "安装驱动",
        "工作群",
        "一条错误",
        "准备中",
        "恢复正常",
        "运行测试",
        "系统版本",
        "当前窗口",
        "麦克风权限",
        "电池电量",
        "重启服务",
        "日志文件",
        "配对请求",
        "音频数据",
        "按住按钮",
        "释放按钮",
        "当前输入框",
        "固件版本",
        "设备列表",
        "错误提示",
        "缓存目录",
        "蓝牙广播",
        "扫描设备",
        "重新连接",
        "用户界面",
        "快捷键",
        "打开终端",
        "复制文本",
        "发送通知",
        "下载模型",
        "识别结果",
        "macOS 蓝牙配对",
        "Whisper 识别结果",
        "USB 数据线还没有连好",
        "Git commit 已经提交完成",
        "npm run build 执行失败",
        "GitHub 上创建一个仓库",
        "llama-server 的端口被占用",
        "M5StopWatch 固件需要重新烧录",
        "BLE 设备正在发送广播",
        "执行",
        "提交",
        "配对",
        "连好",
        "日志",
        "后台",
        "广播",
        "Bluetooth",
        "macOS",
        "Linux",
        "Windows",
        "Python",
        "Whisper",
        "Qwen",
        "GitHub",
        "README",
        "网站",
        "仓库",
        "代码",
        "驱动",
        "工作群",
        "接口",
        "错误",
        "开启",
        "连接",
        "校验",
        "日志文件",
        "开发者模式",
        "网络连接",
        "音频数据",
        "命令",
        "终端",
        "文本",
        "快捷键",
        "运行测试",
        "设备",
        "固件",
        "烧录",
        "蓝牙",
        "配对",
        "命令行",
        "工具链",
    ),
    "product": (
        "M5Stack",
        "M5StopWatch",
        "BLE",
        "HID",
        "MLX Whisper",
        "OpenCC",
        "llama.cpp",
    ),
}


def standard_terms(packs: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for pack in packs:
        for term in STANDARD_LEXICON_PACKS.get(str(pack), ()):
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(term)
    return tuple(result)


def merge_prompt_terms(
    personal_terms: Iterable[str],
    packs: Iterable[str],
    *,
    limit: int = 96,
) -> tuple[str, ...]:
    """Merge personal and standard terms, keeping personal terms first."""
    result: list[str] = []
    seen: set[str] = set()
    for term in (*tuple(personal_terms), *standard_terms(packs)):
        value = str(term).strip()
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= limit:
            break
    return tuple(result)


def _longest_common_span(left: str, right: str) -> int:
    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    longest = 0
    for left_value in left:
        current = [0]
        for index, right_value in enumerate(right, start=1):
            value = previous[index - 1] + 1 if left_value == right_value else 0
            current.append(value)
            longest = max(longest, value)
        previous = current
    return longest


def contextual_prompt_terms(
    text: str,
    terms: Iterable[str],
    *,
    limit: int = 32,
) -> tuple[str, ...]:
    """Select sentence-relevant hints without forcing domain terms into clean text."""

    value = str(text)
    normalized = tuple(dict.fromkeys(str(term).strip() for term in terms if str(term).strip()))
    exact = tuple(term for term in normalized if term in value)
    ranked: list[tuple[int, int, int, str]] = []
    for order, term in enumerate(normalized):
        if term in value:
            ranked.append((2, len(term), -order, term))
            continue
        shared = _longest_common_span(term, value)
        if shared < 2:
            continue
        if any(candidate in term and shared == len(candidate) for candidate in exact):
            continue
        ranked.append((1, shared, -order, term))
    ranked.sort(reverse=True)
    return tuple(item[-1] for item in ranked[: max(0, limit)])


def conservative_lexicon_correction(
    text: str,
    terms: Iterable[str],
    *,
    max_changes: int = 2,
) -> str:
    """Apply only unambiguous one-character phrase and repetition repairs."""

    value = str(text)
    candidates = tuple(dict.fromkeys(str(term).strip() for term in terms if len(str(term).strip()) >= 2))
    for _ in range(max(0, max_changes)):
        replacements: set[str] = set()
        for term in candidates:
            if len(term) >= 4:
                for start in range(0, len(value) - len(term) + 1):
                    source = value[start : start + len(term)]
                    if source == term:
                        continue
                    differences = [
                        index
                        for index, (left, right) in enumerate(zip(source, term))
                        if left != right
                    ]
                    if len(differences) == 1 and 0 < differences[0] < len(term) - 1:
                        replacements.add(value[:start] + term + value[start + len(term) :])
            repeated = term + term[-1]
            if repeated in value:
                replacements.add(value.replace(repeated, term, 1))
        if len(replacements) != 1:
            break
        corrected = replacements.pop()
        if corrected == value:
            break
        value = corrected
    return value
