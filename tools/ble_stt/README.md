# M5StopWatch BLE 语音输入服务

手表上的 **BLE Remote** 应用会把按住说话时的音频传给电脑，由常驻的本地服务完成语音识别，并把稳定的识别片段输入到录音开始时聚焦的窗口。音频和识别过程均保留在电脑本机。

| 平台 | 蓝牙 | 文字输入 | 语音识别 | 登录服务 |
| --- | --- | --- | --- | --- |
| Linux / Hyprland | BlueZ / Bleak | `hyprctl` + `wtype` | faster-whisper | systemd 用户服务 |
| Apple Silicon macOS 14.4+ | CoreBluetooth / Bleak | `M5StopWatch.app` 辅助功能 + Quartz | MLX Whisper | App 固定路径 + LaunchAgent |
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
2. macOS 校验 App ZIP 的 SHA-256 与固定证书 RSA 签名，并核对 Bundle ID、arm64 架构和内嵌签名证书指纹，然后把自带运行时的 `M5StopWatch.app` 安装到 `~/Applications`；Linux 则在用户目录创建隔离环境。
3. macOS 打开辅助功能设置并等待用户启用 **M5StopWatch**；不安装 Python 或 Homebrew，也不要求粘贴路径。
4. 下载并实际运行一次默认的 `medium` 模型，确保首次日常使用不会在后台等待模型。
5. 引导蓝牙配对，并要求完成一次真实的按住说话测试。
6. 所有检查通过后注册登录服务；后台进程连续健康检查通过后，才原子替换已校验 SHA-256 的维护安装器和 `ble-stt` 管理命令。

模型文件较大，安装期间会显示下载进度。安装中断后可以直接重试，已经完成的模型缓存会被复用。Linux 继续按版本隔离；macOS 会在切换前备份旧 App 和 LaunchAgent。新版本验证失败时，两种平台都会保留或恢复原有可用版本。

同一时间只能运行一个安装或升级过程。macOS 权限检查会打开“系统设置 → 隐私与安全性 → 辅助功能”，列表中显示的是固定身份的 **M5StopWatch**；开启后安装器会自动继续。等待最多 120 秒，期间按 `Ctrl-C` 会立即退出。安装、升级、拒绝授权、测试失败或取消时，安装器都会停止新服务、移除未完成版本并恢复原 App、LaunchAgent 和命令链接，不会再进入无法退出的 Enter 重试循环。

一般不需要管理员权限。macOS 仅安装到当前用户的 `~/Applications`，辅助功能开关必须由用户本人确认；只有 Linux 缺少 Python、BlueZ 或 `wtype` 等系统软件包时才可能请求 `sudo`。

可通过环境变量调整安装行为：

- `BLE_STT_SKIP_TEST=1`：跳过交互式 BLE 和语音测试；macOS 的 App 验签、辅助功能授权和模型准备仍会执行。
- `BLE_STT_MODEL=small`：使用体积更小、速度更快的模型。
- `BLE_STT_ENGINE=auto`：选择识别后端；默认已是 `auto`。
- `BLE_STT_VERSION=ble-stt-v0.3.3`：固定到指定 Release 标签。
- `BLE_STT_ASSET_BASE=...`：从可信的内部 Release 镜像下载安装资源。

## macOS 安装与授权边界

macOS 仍以同一个 `curl | sh` 命令作为正式入口。安装脚本先把发布证书转换为 DER 并核对内嵌的固定 SHA-256 指纹，再用证书公钥验证 App ZIP 的 RSA-SHA256 分离签名，同时校验 ZIP 的 SHA-256；解压后还会核对固定 Bundle ID、arm64 主程序以及 App 内嵌签名证书是否为同一证书。任一项不符都会在停止旧服务之前失败。维护安装器同样必须通过 SHA-256 和 RSA 签名验证，并且只会在新服务健康后替换。

该验证过程不会把自签证书加入系统钥匙串或信任设置，因此不会要求管理员密码，也不会留下临时信任。

辅助功能授权无法由安装器替用户打开，这是 macOS 的安全边界。首次安装时系统中会出现 **M5StopWatch**，用户只需开启一次；权限归属于固定 Bundle ID、固定可执行路径和固定签名身份，不再归属于某个版本虚拟环境中的 Python。正常使用同一证书覆盖升级时无需粘贴路径；未来如果轮换证书，macOS 可能要求重新确认授权。

当前包使用项目持有的长期自签证书，而不是 Apple Developer ID，并且未经过 Apple 公证。证书指纹校验可以阻止错误签名或被替换的 App 被静默安装，但不等同于 Apple 对开发者身份的背书。本版本支持上述终端一键安装，不承诺从浏览器下载后双击 App 时没有 Gatekeeper 提示；面向普通用户公开分发前应改用 Developer ID 签名与公证。

## 配对与安装验证

安装期间请在手表上保持 **BLE Remote** 打开。

- **macOS**：保持 BLE Remote 打开，由安装器连接加密特征并触发自动配对；无需提前在蓝牙设置中手动连接，也不需要输入 PIN。系统打开辅助功能设置后，只需开启已经出现的 **M5StopWatch**，无需点击 `+` 或粘贴路径。
- **Windows / Linux**：保持 BLE Remote 打开后连接 `M5StopWatch HID`；使用 Secure Connections 自动加密配对，不需要输入 PIN。

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

`ble-stt upgrade` 会下载并完整验证新 App 和维护安装器，停止旧 LaunchAgent 后依次完成权限、模型、BLE 和语音测试，最后才注册新服务。新服务必须连续两次报告为运行中，之后才提交 App、安装器和命令链接。从 0.3.1/0.3.2 的 Python 安装升级时会复用现有设备配置和模型缓存；新 App 启动成功后再清理旧虚拟环境。任一步失败或按 `Ctrl-C` 取消都会恢复旧服务。

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

如果另一台电脑持续自动重连，请在 BLE Remote 屏幕连续轻点三次打开控制页，再选择 **Pair new computer**。手表会记住并暂时拒绝最后连接的电脑以及已有绑定，新电脑加密配对成功后才删除旧绑定。固件无法命令另一台电脑停止主动重试；若要停止 Linux 自己的重连通知，还需在那台 Linux 的蓝牙设置中“忘记”`M5StopWatch HID`。若 macOS 系统里存在失败连接留下的旧条目，也可先移除后重试。

## 本地开发

Linux 直接运行仓库内的安装器时，会使用当前工作区源码，而不是 Release 资源：

```bash
./tools/ble_stt/install.sh
```

macOS 安装必须使用发布时注入固定证书指纹的 Release 安装器。仓库中的源码安装器保留明确的指纹占位符并会主动拒绝安装，避免开发构建绕过验签；本地开发可直接运行 Python 单元测试，完整 App 安装则使用 CI 生成并签名的 Release 资源。

Windows PowerShell：

```powershell
tools\ble_stt\install.ps1
```

不下载模型的单元测试：

```bash
PYTHONPATH=tools/ble_stt python -m unittest discover -s tools/ble_stt/tests -v
```

发布标签采用 `ble-stt-v<版本>` 格式，例如 `ble-stt-v0.3.3`。标签版本必须与 `tools/ble_stt/pyproject.toml` 中的版本一致。GitHub Actions 会生成 POSIX/Windows 安装器、源码资源、`M5StopWatch-macos-arm64.zip`、各自的 SHA-256 和 RSA 签名，以及公开签名证书；发布前还必须把长期签名证书指纹注入 macOS 使用的一行安装器，源码和 Release 中都不得包含私钥。
