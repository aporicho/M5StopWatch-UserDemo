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
