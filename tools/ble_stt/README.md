# M5StopWatch BLE 语音输入服务

手表上的 **BLE Remote** 应用会把按住说话时的音频传给电脑，由常驻的本地服务完成语音识别，并把稳定的识别片段输入到录音开始时聚焦的窗口。音频和识别过程均保留在电脑本机。

| 平台 | 蓝牙 | 文字输入 | 语音识别 | 登录服务 |
| --- | --- | --- | --- | --- |
| Linux / Hyprland | BlueZ / Bleak | `hyprctl` + `wtype` | faster-whisper | systemd 用户服务 |
| Apple Silicon macOS 15.0+ | CoreBluetooth / Bleak | `M5StopWatch.app` PostEvent 权限 + Quartz | MLX Whisper | App 固定路径 + LaunchAgent |
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

macOS 安装器只负责安装本身：

1. 下载最新稳定 Release，验证 App ZIP 和维护安装器的 RSA-SHA256 签名。
2. 核对 App 的 Bundle ID、arm64 架构和固定签名证书指纹，再把自带运行时的 `M5StopWatch.app` 原子安装到 `~/Applications`。
3. 使用 macOS 专门的 PostEvent API 请求文字输入权限，并打开“系统设置 → 隐私与安全性 → 辅助功能”。列表中显示 **M5StopWatch**，无需点击 `+`、粘贴 Python 路径或输入钥匙串密码。
4. 注册当前用户的 LaunchAgent；后台进程连续健康检查通过后提交安装。

安装阶段不再要求手表在线，不下载语音模型，也不强制完成真实语音测试。蓝牙配对和模型准备发生在首次使用：服务连接手表后先报告“正在准备”，在服务进程内完成模型下载和加载，真正可识别后才报告“语音输入已就绪”。

同一时间只能运行一个安装或升级过程。权限等待不设固定超时，开启 **M5StopWatch** 后安装器会自动继续；按 `Ctrl-C` 会立即退出并恢复旧 App、LaunchAgent、维护安装器和命令链接。macOS 不修改 `.zprofile` 或 `.profile`，维护命令固定安装在 `~/.local/bin/ble-stt`。

一般不需要管理员权限。macOS 仅安装到当前用户的 `~/Applications`，辅助功能开关必须由用户本人确认；只有 Linux 缺少 Python、BlueZ 或 `wtype` 等系统软件包时才可能请求 `sudo`。

可通过环境变量调整安装行为：

- `BLE_STT_SKIP_TEST=1`：Linux/Windows 跳过交互式 BLE 和语音测试；macOS 安装本身不执行这类测试。
- `BLE_STT_MODEL=small`：首次使用时准备体积更小、速度更快的模型。
- `BLE_STT_ENGINE=auto`：选择识别后端；默认已是 `auto`。
- `BLE_STT_VERSION=ble-stt-v0.3.3`：固定到指定 Release 标签。
- `BLE_STT_ASSET_BASE=...`：从可信的内部 Release 镜像下载安装资源。

## macOS 安装与授权边界

macOS 仍以同一个 `curl | sh` 命令作为正式入口。安装脚本先把发布证书转换为 DER 并核对内嵌的固定 SHA-256 指纹，再用证书公钥验证 App ZIP 和维护安装器的 RSA-SHA256 分离签名；解压后还会核对固定 Bundle ID、arm64 主程序以及 App 内嵌签名证书是否为同一证书。任一项不符都会在停止旧服务之前失败。

该验证过程不会把自签证书加入系统钥匙串或信任设置，因此不会要求管理员密码，也不会留下临时信任。

文字输入使用 `CGRequestPostEventAccess` 请求专门的键盘事件发送权限，而不是读取完整的 Accessibility 窗口树。macOS 仍把这个权限显示在“辅助功能”页面。首次安装时系统中会出现 **M5StopWatch**，用户必须亲自开启；权限归属于固定 Bundle ID 和固定签名身份，不再归属于某个版本虚拟环境中的 Python。正常使用同一证书覆盖升级时不需要粘贴路径；未来如果轮换证书，macOS 可能要求重新确认授权。

由于不再读取 AX 窗口对象，服务用前台应用 PID 防止识别期间把文字输到另一个应用。按住说话期间不要在同一个应用内切换文档窗口；如果切换到了另一个应用，本次文字输入会被取消。

当前包使用项目持有的长期自签证书，而不是 Apple Developer ID，并且未经过 Apple 公证。固定证书与 Release RSA 签名可以阻止错误签名或被替换的 App 被静默升级，但不等同于 Apple 对开发者身份的背书。首次执行 `curl | sh` 的信任起点仍是 GitHub HTTPS。本版本支持上述终端一键安装，不承诺从浏览器下载后双击 App 时没有 Gatekeeper 提示；面向普通用户公开分发前应改用 Developer ID 签名与公证。

## 首次使用、配对与模型

macOS 安装成功后再打开手表上的 **BLE Remote**。后台服务会连接加密特征并触发自动配对；无需提前在蓝牙设置中手动连接，也不需要输入 PIN。Windows / Linux 同样使用 Secure Connections 自动加密配对。

第一次连接时，服务会下载并在当前后台进程中加载默认的 `medium` 模型。手表会保持“正在准备语音模型”，只有模型真正可以识别后才显示“语音输入已就绪”。模型缓存独立于 App 版本，后续升级会复用；后台服务每次重新启动后仍会从本地缓存加载模型，再报告就绪。

如果希望在打开手表前预先下载并验证模型，可以运行：

```bash
~/.local/bin/ble-stt prepare --engine mlx --model medium
```

体验时先聚焦一个空白文本窗口，再按住手表右键说话并松开。手表会显示“正在聆听”和“正在识别”。短按右键仍然发送 Enter；一次语音输入结束后不会自动提交识别出的文字。

## 日常使用与管理

服务会在用户登录后自动启动。macOS 安装器不会改动 shell 配置，因此以下示例使用固定命令路径：

```bash
~/.local/bin/ble-stt
~/.local/bin/ble-stt status
```

macOS 维护命令：

```bash
~/.local/bin/ble-stt doctor --request-permissions
~/.local/bin/ble-stt doctor --ble
~/.local/bin/ble-stt test
~/.local/bin/ble-stt logs -n 100
~/.local/bin/ble-stt logs --follow
~/.local/bin/ble-stt restart
~/.local/bin/ble-stt upgrade
~/.local/bin/ble-stt uninstall
~/.local/bin/ble-stt uninstall --purge-models
```

Linux 和 Windows 的命令名仍是 `ble-stt`。

普通卸载会保留已经下载的模型，方便以后快速重装；加上 `--purge-models` 才会同时删除模型缓存。

macOS 的 `upgrade` 会先下载并验证新 App 和维护安装器，再停止旧 LaunchAgent、原子切换 App、确认文字输入权限并注册新服务。已有授权的正常升级会直接通过该检查。新服务必须连续两次报告为运行中，之后才提交安装；失败或按 `Ctrl-C` 取消会恢复旧服务。设备配置和模型缓存独立保存，不需要在每次升级时重新配对或重新下载。

排障时也可以在前台运行服务：

```bash
~/.local/bin/ble-stt run --engine auto --model medium
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

发布标签采用 `ble-stt-v<版本>` 格式，例如 `ble-stt-v0.3.3`。标签版本必须与 `tools/ble_stt/pyproject.toml` 中的版本一致。GitHub Actions 会生成 POSIX/Windows 安装器、带 SHA-256 的源码资源、`M5StopWatch-macos-arm64.zip`、App 与维护安装器的 RSA 签名，以及公开签名证书；发布前还必须把长期签名证书指纹注入 macOS 使用的一行安装器，源码和 Release 中都不得包含私钥。签名所需的临时钥匙串只存在于 GitHub Actions 构建机，安装用户不会接触它。
