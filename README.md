# M5StopWatch-UserDemo

M5Stack StopWatch 硬件评估固件及配套桌面语音输入服务。

## 固件构建与烧录

### 获取依赖

```bash
python3 ./fetch_repos.py
```

### 工具链

[ESP-IDF v5.5.4](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32s3/index.html)

### 构建

```bash
idf.py build
```

### 烧录

```bash
idf.py flash
```

## BLE 语音输入服务

手表上的 **BLE Remote** 应用可以把按住说话时的音频传给电脑，由电脑本地完成语音识别，再把文字输入到录音开始时聚焦的窗口。音频和识别过程均保留在本机。

目前支持：

- Linux / Hyprland
- Apple Silicon Mac
- Windows 11

### 一键安装

macOS 或 Linux：

```bash
curl -fsSL https://github.com/aporicho/M5StopWatch-UserDemo/releases/latest/download/ble-stt-install.sh | sh
```

Windows PowerShell：

```powershell
irm https://github.com/aporicho/M5StopWatch-UserDemo/releases/latest/download/ble-stt-install.ps1 | iex
```

安装器会校验 Release 下载、创建隔离的用户环境、准备语音模型、引导授权和蓝牙配对，并要求完成一次真实的按住说话测试；全部通过后才会启用登录自启动服务。

### 快速体验

1. 在手表上保持 **BLE Remote** 打开；安装器会触发自动加密配对，macOS 无需提前在蓝牙设置中手动连接，也不需要输入 PIN。
   如果旧电脑持续自动重连，请连续轻点手表屏幕三次，选择 **Pair new computer** 后再继续。
2. macOS 按提示授予“辅助功能”权限；若列表没有 Python，点击 `+`，按 `Shift-Command-G` 粘贴安装器打印的稳定路径后添加。Linux 需要 Hyprland 和 `wtype`，安装器可以补齐缺少的系统软件包。
3. 聚焦一个空白文本窗口，按住手表右键说话，然后松开。识别结果会写入该窗口，但不会自动提交或发送。
4. 运行 `ble-stt status` 查看登录服务、手表配对、语音模型和文字输入权限状态。

模型选择、日志、诊断、升级、卸载、平台差异和开发说明见[完整的 BLE STT 中文指南](tools/ble_stt/README.md)。
