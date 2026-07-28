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

### 固件自动化测试

开发回归可以构建带测试入口的固件。这个入口只注入按钮和触摸输入，不直接打开应用、不直接改 BLE 状态、不绕过配对，因此测试走的是实际用户路径：从 Launcher 选择应用、打开 **BLE Remote**、等待广播或连接，再按键触发语音链路。

正式固件保留 USB Serial/JTAG 只读诊断日志。测试固件通过同一个 USB 口额外接收用户输入事件；这个输入入口只在 `sdkconfig.defaults.test` 里启用，正式固件不启用 `CONFIG_M5_TEST_CONTROL`。

```bash
. /Users/aporicho/.espressif/v5.5.4/esp-idf/export.sh
idf.py -B build-test -D SDKCONFIG=build-test/sdkconfig -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.test" -p /dev/cu.usbmodem101 build flash
python tools/firmware_hil.py smoke --port /dev/cu.usbmodem101
```

`tools/firmware_hil.py` 抽象的是用户操作：

- `left` / `right` 按键的 tap、hold、release。
- 屏幕 touch、tap、swipe。
- 通过 Launcher 导航并点按图标打开应用。
- 读取测试状态、应用列表和 BLE Remote 状态，用于等待“广播中 / 配对中 / 已连接”。

常用旅程：

```bash
python tools/firmware_hil.py smoke --port /dev/cu.usbmodem101
python tools/firmware_hil.py smoke --port /dev/cu.usbmodem101 --skip-ble-check
python tools/firmware_hil.py voice-link --port /dev/cu.usbmodem101
python tools/firmware_hil.py diagnose-not-found --port /dev/cu.usbmodem101
```

`smoke` 会从 Launcher 打开 **BLE Remote**，等待手表进入广播、配对或已连接状态，并可继续运行桌面 BLE 服务检查。`voice-link` 会通过右键长按和松开模拟一次听写入口。`diagnose-not-found` 用于蓝牙扫不到时输出应用状态和 BLE Remote 状态。

注意：BLE 只在手表切到 **BLE Remote** 应用后广播。自动化测试会通过 Launcher 用户路径打开它；如果跑普通固件或手表停留在别的应用，电脑端扫描不到是正常现象。

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

macOS 安装器会校验 Release 签名，把自带运行时的 `M5StopWatch.app` 原子安装到 `~/Applications`，注册当前用户的 LaunchAgent，然后打开 App 并立即退出。安装阶段不等待权限、不要求手表在线、不安装 Python 或 Homebrew，也不要求钥匙串密码。

蓝牙物理连接由操作系统的 HID 栈负责；后台服务只会附加已经由系统连接的手表，不会扫描、配对或把用户主动断开的设备重新连上。

### 快速体验

1. 运行一键安装命令，等待 App 自动打开；安装器此时已经结束，终端无需继续等待。
2. 在 App 的“设置 → 权限”中分别点击蓝牙和文本输入授权。系统只会在用户点击后显示授权请求。
3. 在手表上打开 **BLE Remote**。首次使用时手表显示等待配对；在电脑的系统蓝牙设置中选择 **M5StopWatch HID** 完成连接。
4. 在桌面 App 安装或选择语音模型。需要智能纠错时，在“设置 → 智能纠错”选择模型：默认轻量档约 563 MB，增强档约 924 MB；两个模型可以共存并随时切换。这里也可填写个人词典、调整模拟打字速度。
5. 手表显示语音就绪后，聚焦文本窗口，按住手表右键说话并松开。识别结果会模拟逐字输入；松开后仅在能安全核对当前文本时替换纠错后的部分。
6. macOS 可运行 `~/.local/bin/ble-stt status` 查看状态；Linux 和 Windows 使用 `ble-stt status`。转写历史和指令历史可以分别从对应卡片清空，不会删除诊断日志。

手表只保留一台电脑的 Bond。开机或打开 BLE Remote 时只进行一次有界回连：1.28 秒高占空比定向广播，加上 accept-list 快速广播，总计不超过 5 秒；失败后关闭射频。电脑端主动断开时不会自动回连，需要在手表上点 **Reconnect**。要换电脑时选择 **Pair new computer**：旧 Bond 和隐私身份会立即清除，没有回退槽位，然后由新电脑在系统蓝牙设置中主动连接。广播包在连接前就声明 Mouse Appearance、HID UUID 和名称，因此系统应直接识别为鼠标类 HID。

如果在电脑系统蓝牙设置中点了“忽略 / 删除设备”，电脑侧配对密钥已经消失，手表无法证明再次出现的电脑仍是原主机。此时同样要在手表断开页点 **Pair new** 并确认，再从电脑系统蓝牙设置重新连接；断开页会同时保留 **Reconnect**，供电脑仍持有原密钥时使用。

### 全链路性能监测

固件、BLE 服务、语音识别、智能纠错、指令匹配和模拟打字都带有低开销耗时埋点。首页显示最近一次语音输入的首字延迟、松手到结果和松手到输入完成耗时；“诊断 → 性能”提供设备与电脑双泳道瀑布图、阶段明细，以及相同模型和设置下的 p50 / p95 基线。等待、用户主动停顿和实际计算会分类显示，避免把录音时长误判成性能瓶颈。

性能历史只保存在本机，最多保留最近 200 次语音会话和 20 次服务生命周期；记录不包含音频、转写文字、窗口标题或设备标识，也不会上传。手表与电脑会进行多次时钟同步；同步不确定度超过 10 ms 时，界面不会展示无法可靠计算的跨设备单向延迟。新版性能特征是可选扩展，旧固件和旧桌面服务仍可继续使用原有音频协议。

```bash
~/.local/bin/ble-stt performance show --json
~/.local/bin/ble-stt performance clear --json
```

模型选择、日志、诊断、升级、卸载、平台差异和开发说明见[完整的 BLE STT 中文指南](tools/ble_stt/README.md)。

当前 macOS 包采用项目固定的自签证书，为跨版本文字输入授权提供稳定代码身份；用户端不会安装或信任该证书。它不是 Apple Developer ID 公证发行版，不承诺浏览器下载后双击安装时没有 Gatekeeper 提示。Release RSA 签名和固定证书指纹校验不等同于 Apple 公证。
