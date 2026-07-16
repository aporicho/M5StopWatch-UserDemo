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
- Apple Silicon Mac（macOS 15.0+）
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

macOS 仍然使用上面同一条一行命令。安装器会校验 Release 签名，把自带运行时的 `M5StopWatch.app` 安装到 `~/Applications`，请求一次文字输入权限，然后注册当前用户的 LaunchAgent。整个过程不安装 Python 或 Homebrew，不要求粘贴路径，不要求手表在线，也不会询问钥匙串密码。

语音模型和蓝牙配对属于首次使用流程，不再作为“安装是否成功”的门槛。第一次打开手表上的 **BLE Remote** 时，后台服务会自动配对并准备默认模型；手表会先显示准备中，模型真正加载完成后才显示语音输入就绪。

### 快速体验

1. 运行一键安装命令。macOS 会打开“系统设置 → 隐私与安全性 → 辅助功能”，启用自动出现的 **M5StopWatch**；安装器会继续等待，不设 120 秒超时，按 `Ctrl-C` 可以取消并恢复旧版本。
2. 安装成功后，在手表上打开 **BLE Remote**。macOS 会自动触发加密配对，无需提前手动连接，也不需要输入 PIN。第一次使用还会下载并加载语音模型。
3. 手表显示语音输入就绪后，聚焦一个文本窗口，按住手表右键说话，然后松开。识别结果会写入该应用，但不会自动提交或发送。
4. macOS 可运行 `~/.local/bin/ble-stt status` 查看状态；Linux 和 Windows 使用 `ble-stt status`。

如果旧电脑持续自动重连，请连续轻点手表屏幕三次，选择 **Pair new computer**，并在旧 Linux 电脑上忘记 `M5StopWatch HID`。

模型选择、日志、诊断、升级、卸载、平台差异和开发说明见[完整的 BLE STT 中文指南](tools/ble_stt/README.md)。

当前 macOS 包采用项目固定的自签证书，为跨版本文字输入授权提供稳定代码身份；用户端不会安装或信任该证书。它不是 Apple Developer ID 公证发行版，不承诺浏览器下载后双击安装时没有 Gatekeeper 提示。Release RSA 签名和固定证书指纹校验不等同于 Apple 公证。
