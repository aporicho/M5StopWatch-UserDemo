# M5StopWatch BLE 语音输入服务

手表上的 **BLE Remote** 应用会把按住说话时的音频传给电脑，由常驻的本地服务完成语音识别，并把稳定的识别片段输入到录音开始时聚焦的窗口。音频和识别过程均保留在电脑本机。

| 平台 | 蓝牙 | 文字输入 | 语音识别 | 登录服务 |
| --- | --- | --- | --- | --- |
| Linux / Hyprland | BlueZ / Bleak | `hyprctl` + `wtype` | faster-whisper | systemd 用户服务 |
| Apple Silicon macOS | CoreBluetooth / Bleak | 辅助功能 + Quartz | MLX Whisper | LaunchAgent |
| Windows 11 | WinRT / Bleak | `GetForegroundWindow` + `SendInput` | faster-whisper | 计划任务 |

## 一键安装

macOS 或 Linux：

```bash
curl -fsSL https://github.com/aporicho/M5StopWatch-UserDemo/releases/latest/download/ble-stt-install.sh | sh
```

Windows PowerShell：

```powershell
irm https://github.com/aporicho/M5StopWatch-UserDemo/releases/latest/download/ble-stt-install.ps1 | iex
```

安装器会依次完成以下工作：

1. 下载最新的稳定 Release，并校验 SHA-256。
2. 在当前用户目录创建隔离的安装环境，不污染系统 Python。
3. 安装当前平台所需的蓝牙、文字输入和语音识别后端。
4. 下载并实际运行一次默认的 `medium` 模型，确保首次日常使用不会在后台等待模型。
5. 检查文字输入权限，引导蓝牙配对，并要求完成一次真实的按住说话测试。
6. 所有检查通过后注册登录服务和 `ble-stt` 管理命令。

模型文件较大，安装期间会显示下载进度。安装中断后可以直接重试，已经完成的模型缓存会被复用。安装、升级和回滚按版本隔离；新版本验证失败时会保留原有可用版本。

一般不需要管理员权限。只有电脑缺少 Python、BlueZ 或 `wtype` 等系统软件包时，Linux 安装器才可能请求 `sudo`。

可通过环境变量调整安装行为：

- `BLE_STT_SKIP_TEST=1`：跳过交互式手表测试，适合无人值守安装。
- `BLE_STT_MODEL=small`：使用体积更小、速度更快的模型。
- `BLE_STT_ENGINE=auto`：选择识别后端；默认已是 `auto`。
- `BLE_STT_VERSION=ble-stt-v0.3.0`：固定到指定 Release 标签。
- `BLE_STT_ASSET_BASE=...`：从可信的内部 Release 镜像下载安装资源。

## 配对与安装验证

安装期间请在手表上保持 **BLE Remote** 打开。

- **macOS**：CoreBluetooth 首次连接时会发起配对。接受蓝牙提示，并按安装器提示在“系统设置 → 隐私与安全性 → 辅助功能”中允许显示的 Python 可执行程序。
- **Windows / Linux**：使用系统蓝牙设置配对 `M5StopWatch HID`，系统要求 PIN 时输入 `123456`。

最终测试时，先聚焦一个空白文本窗口，再按住手表右键说话并松开。手表会依次显示“正在准备语音模型”“语音输入已就绪”“正在聆听”和“正在识别”。短按右键仍然发送 Enter；一次语音输入结束后不会自动提交识别出的文字。

## 日常使用与管理

服务会在用户登录后自动启动。直接运行以下任一命令可以查看简要健康状态：

```bash
ble-stt
ble-stt status
```

三个平台使用相同的维护命令：

```bash
ble-stt doctor --request-permissions
ble-stt doctor --ble
ble-stt test
ble-stt logs -n 100
ble-stt logs --follow
ble-stt restart
ble-stt upgrade
ble-stt uninstall
ble-stt uninstall --purge-models
```

普通卸载会保留已经下载的模型，方便以后快速重装；加上 `--purge-models` 才会同时删除模型缓存。

排障时也可以在前台运行服务：

```bash
ble-stt run --engine auto --model medium
ble-stt run --engine faster-whisper --device cpu --model small
```

旧版命令（例如 `ble-stt --model small`）仍会自动转发到 `run`，以保持兼容。设备标识会在首次发现后自动缓存；`--device-id` 和旧的 `--address` 别名只用于排障。

## 日志位置

- Linux：`~/.local/state/m5stopwatch`
- macOS：`~/Library/Logs/M5StopWatch`
- Windows：`%LOCALAPPDATA%\M5StopWatch\Logs`

如果操作系统中的旧绑定只暴露 HID 服务，没有语音 GATT 服务，请先在手表上选择 **Forget computer**，再从电脑的蓝牙设置中移除该设备，然后重新配对。

## 本地开发

直接运行仓库内的安装器时，会使用当前工作区源码，而不是 Release 资源：

macOS 或 Linux：

```bash
./tools/ble_stt/install.sh
```

Windows PowerShell：

```powershell
tools\ble_stt\install.ps1
```

不下载模型的单元测试：

```bash
PYTHONPATH=tools/ble_stt python -m unittest discover -s tools/ble_stt/tests -v
```

发布标签采用 `ble-stt-v<版本>` 格式，例如 `ble-stt-v0.3.0`。标签版本必须与 `tools/ble_stt/pyproject.toml` 中的版本一致，GitHub Actions 会生成带 SHA-256 校验文件的 POSIX 和 Windows 安装资源。
