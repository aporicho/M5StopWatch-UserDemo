# M5StopWatch BLE 语音输入服务

手表上的 **BLE Remote** 应用会把按住说话时的音频传给电脑，由常驻的本地服务完成语音识别，并把稳定片段以模拟打字效果输入到录音开始时聚焦的窗口。可选的 Qwen 本地模型会在松开按键后进行一次保守纠错。音频、词典和识别过程均保留在电脑本机。

| 平台 | 蓝牙 | 文字输入 | 语音识别 | 登录服务 |
| --- | --- | --- | --- | --- |
| Linux / Hyprland | BlueZ / Bleak | `hyprctl` + `wtype`，AT-SPI 安全核对 | faster-whisper | systemd 用户服务 |
| Apple Silicon macOS 15.0+ | CoreBluetooth / Bleak | `M5StopWatch.app` PostEvent 权限 + Quartz，AX 安全核对 | MLX Whisper | App 固定路径 + LaunchAgent |
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
3. 注册当前用户的 LaunchAgent，打开 `M5StopWatch.app`，然后立即结束安装。

安装阶段不再要求手表在线，不下载语音模型，也不强制完成真实语音测试。蓝牙配对和模型准备发生在首次使用：服务连接手表后先报告“正在准备”，在服务进程内完成模型下载和加载，真正可识别后才报告“语音输入已就绪”。

同一时间只能运行一个安装或升级过程。安装器不会等待权限、读取回车或吞掉 `Ctrl-C`；在事务提交前被中断会恢复旧 App、LaunchAgent、维护安装器和命令链接。macOS 不修改 `.zprofile`、`.profile`、TCC 数据库、LaunchServices、Launchpad 或 Dock，维护命令固定安装在 `~/.local/bin/ble-stt`。

一般不需要管理员权限。macOS 仅安装到当前用户的 `~/Applications`，辅助功能开关必须由用户本人确认；只有 Linux 缺少 Python、BlueZ 或 `wtype` 等系统软件包时才可能请求 `sudo`。

可通过环境变量调整安装行为：

- `BLE_STT_SKIP_TEST=1`：Linux/Windows 跳过交互式 BLE 和语音测试；macOS 安装本身不执行这类测试。
- `BLE_STT_MODEL=medium`：覆盖默认语音模型；新安装默认使用 `small`。
- `BLE_STT_ENGINE=auto`：选择识别后端；默认已是 `auto`。
- `BLE_STT_VERSION=ble-stt-v0.4.0`：固定到指定 Release 标签。
- `BLE_STT_ASSET_BASE=...`：从可信的内部 Release 镜像下载安装资源。

## macOS 安装与授权边界

macOS 仍以同一个 `curl | sh` 命令作为正式入口。安装脚本先把发布证书转换为 DER 并核对内嵌的固定 SHA-256 指纹，再用证书公钥验证 App ZIP 和维护安装器的 RSA-SHA256 分离签名；解压后还会核对固定 Bundle ID、arm64 主程序以及 App 内嵌签名证书是否为同一证书。任一项不符都会在停止旧服务之前失败。

该验证过程不会把自签证书加入系统钥匙串或信任设置，因此不会要求管理员密码，也不会留下临时信任。

安装完成后，在 App 的“设置 → 权限”中点击按钮发起授权。文字输入使用 `CGRequestPostEventAccess` 请求专门的键盘事件发送权限，而不是读取完整的 Accessibility 窗口树；macOS 仍把它显示在“辅助功能”页面。蓝牙权限同样只在用户点击后请求。安装器和后台服务都不会主动弹权限窗口。列表中显示 **M5StopWatch**，无需点击 `+`、粘贴 Python 路径或输入钥匙串密码。

日常逐字输入只使用 Quartz PostEvent，并用前台应用 PID 防止文字泄漏到另一个应用。启用智能纠错后，服务在最终替换前会通过 AX 读取当前聚焦文本框的值和选区，仅当光标前的后缀与本次已经输入的内容逐字一致时才选中并替换；读不到、选区变化或内容不一致都会放弃覆盖，只追加尚未提交的尾音。服务不会遍历窗口、读取其他控件或复制文本内容。按住说话期间如果切换到另一个应用，本次文字输入会被取消。

当前包使用项目持有的长期自签证书，而不是 Apple Developer ID，并且未经过 Apple 公证。固定证书与 Release RSA 签名可以阻止错误签名或被替换的 App 被静默升级，但不等同于 Apple 对开发者身份的背书。首次执行 `curl | sh` 的信任起点仍是 GitHub HTTPS。本版本支持上述终端一键安装，不承诺从浏览器下载后双击 App 时没有 Gatekeeper 提示；面向普通用户公开分发前应改用 Developer ID 签名与公证。

## 首次使用、配对与模型

macOS 安装成功后，在手表上打开 **BLE Remote**，再到“系统设置 → 蓝牙”选择 **M5StopWatch HID**。Linux 和 Windows 也必须由系统蓝牙界面完成首次连接。系统 HID 栈拥有物理连接；后台服务只在系统报告 `Connected` 后附加语音 GATT，不会扫描名称、调用 BlueZ `Connect`、自动删除设备或替用户发起配对。

配对和回连遵循以下规则：

- 第一次使用以及确认 **Pair new computer** 后，手表进行 30–60 ms Limited Discoverable 广播，最长 180 秒；只能由电脑主动连接。
- 日常打开 **BLE Remote** 或异常掉线时，先做最长 1.28 秒高占空比定向广播，再做 accept-list 快速广播；整个窗口合计不超过 5 秒，失败后关闭射频。
- 用户在电脑蓝牙设置中点击“断开”时，手表直接进入已绑定空闲，不广播、不重连；需要继续使用时在手表控制页点击 **Reconnect**。
- 手表只保存一个 Bond。**Pair new computer** 会先断开当前连接，再永久删除旧 Bond 并轮换 IRK，没有回退槽位；旧电脑不能凭旧身份抢占配对窗口。
- 如果用户在电脑端“忽略 / 删除设备”，电脑已经丢失原配对密钥，手表无法再确认它是原主机。此时在手表断开页点 **Pair new** 并确认后再配对；该页面同时提供 **Reconnect**，供原密钥仍存在时恢复连接。
- 配对窗口以外只接受 controller accept-list 中的唯一已绑定电脑。
- 广播包直接声明鼠标外观，因此系统在连接前也应显示为鼠标类设备；连接后仍是鼠标、键盘和语音服务组成的复合设备。

新安装默认使用 `small` 模型。桌面 App 的 Model 面板会显示模型来源、缓存大小和安装状态，并提供 `Small`、`Medium`、`Large`、`Turbo` 四个主选项。模型缓存独立于 App 版本，后续升级会复用；后台服务每次重新启动后会先加载当前配置的模型，再报告就绪。

点击“安装”“更新”或“修复”后，主按钮会显示当前动作；下载阶段同时显示真实字节数、总大小和百分比。可以在下载和准备阶段取消，进入文件校验与原子安装后不再允许中断。关闭设置页不会停止任务，首页会继续显示进度；下载被取消或网络中断后，缓存会保留，重新选择“继续安装”即可断点续传。纠错模型采用同一套交互，同一时间只执行一个模型任务。

如果希望在打开手表前预先下载并验证模型，可以运行：

```bash
~/.local/bin/ble-stt prepare --engine mlx --model small
```

也可以通过模型管理命令查看、切换和维护模型：

```bash
~/.local/bin/ble-stt models status --json
~/.local/bin/ble-stt models list --json
~/.local/bin/ble-stt models use --model medium --engine auto
~/.local/bin/ble-stt models install --model medium --engine auto
~/.local/bin/ble-stt models repair --model medium --engine auto
~/.local/bin/ble-stt models delete --model medium --engine auto
```

体验时先聚焦一个空白文本窗口，再按住手表右键说话并松开。手表会显示“正在聆听”和“正在识别”。短按右键仍然发送 Enter；一次语音输入结束后不会自动提交识别出的文字。

## 智能纠错、词典与模拟打字

设置页提供三层语言信息：Whisper/Qwen 自带的语言知识、默认开启的精简常用词包，以及用户自己的个人词典。内置词包覆盖常见计算机词、固件/烧录/蓝牙等中文词和 M5StopWatch 产品名，只作为识别偏置，不会强制替换；个人词典优先级最高，并在最终纠错中受到严格保护。系统不会把大型通用词典整体塞进 Whisper 提示词，每次最多发送少量词条，避免拖慢识别或挤占音频上下文。

智能纠错默认关闭，并且不随 App 下载模型。设置页提供两个经过固定版本与 SHA-256 校验的选项：

- `轻量（lite）`：`Qwen3.5-0.8B-Q4_0.gguf`，下载 563,036,064 字节（界面显示约 537 MB），默认推荐，优先节省磁盘与内存。
- `增强（balanced）`：`qwen2.5-1.5b-instruct-q3_k_m.gguf`，下载 924,455,968 字节（界面显示约 882 MB），上下文纠错更强，但仍小于 1 GB。

两个模型可以同时安装；像语音模型一样，先在下拉框选择，再执行“安装”或“使用”，切换已安装模型不需要重新下载。升级发现旧版约 2.5 GB 的 Qwen3-4B 时，会先完整下载并验证所选新模型，成功后再回收旧模型；下载失败不会破坏旧文件。

推理通过只监听 `127.0.0.1`、带随机 API 密钥的 `llama-server` 完成；运行时固定为经过 SHA-256 校验的 llama.cpp `b9000`，macOS 包直接内置，Linux/Windows 首次安装纠错模型时自动下载。模型会结合整句修正能够唯一判断的同音、近音、漏字、重复字和语义离群词；数字、日期、金额、URL、邮箱、路径、英文片段和个人词条必须保持不变。程序还会拒绝超过 20% 编辑距离、异常语言或过长输出，超时或校验失败时原文照常使用。

模拟打字默认开启，速度为每秒 40 个字符。可在设置页调整到每秒 10–100 个字符，并开启积压自动加速（最高每秒 120 个字符）。应用会按 Unicode 字素簇输入，因此 emoji、组合重音和中文不会被拆成半个字符。转写历史与指令历史各自带“清空”按钮；清空只影响界面历史并持久化清空时间，诊断日志仍保留。

命令行也可管理这些设置和模型：

```bash
~/.local/bin/ble-stt voice-settings status --json
~/.local/bin/ble-stt voice-settings save --json --payload '{"correction":{"enabled":true,"glossary":["M5StopWatch"]},"typing":{"characters_per_second":40}}'
~/.local/bin/ble-stt voice-settings install-model --model lite --json
~/.local/bin/ble-stt voice-settings use-model --model balanced --json
~/.local/bin/ble-stt voice-settings repair-model --model balanced --json
~/.local/bin/ble-stt voice-settings delete-model --model balanced --json
```

删除纠错模型会保留已校验的轻量运行时，后续重新安装无需再次下载它；普通升级和卸载仍沿用现有的模型缓存保留规则。

## 全链路性能监测

每次按住说话都会生成一条独立的性能记录，覆盖手表按键、录音启动、音频采集与编码、BLE 通知、电脑收包与解码、滚动和最终 STT、稳定文本判断、智能纠错、指令匹配、文本注入和模拟打字。服务启动、系统蓝牙等待、GATT 附加、订阅和模型加载则记录为生命周期样本。

桌面 App 首页显示最常用的三个体验指标：首字延迟、松手到结果就绪、松手到输入完成。“诊断 → 性能”可以切换两种时间线：

- **处理路径**：只显示 I/O 和实际计算，适合寻找优化点。
- **完整链路**：同时显示等待和设计内停顿，适合解释用户实际感受到的总延迟。

阶段会明确标记为 `work`、`io`、`wait` 或 `intentional`。界面自动找出最近一次最长的非等待阶段，并仅使用模式、STT 模型、纠错模型和打字设置完全相同的记录计算 p50 / p95；少于 20 条时会提示样本不足，不把不兼容配置混成一条基线。

固件性能特征 UUID 为 `7f3a1007-6b2e-4c6d-a7c0-5e0d8b1f9a01`，它是现有语音服务内的可选加密特征，不修改原音频和状态数据包。服务连接后执行 5 次轻量时钟同步并选择往返耗时最小的样本；估计不确定度不超过 10 ms 时才合并设备与电脑时间线，否则只展示各自能够可靠测量的阶段，不虚构 BLE 单向延迟。

记录默认写入日志目录的 `ble-stt-performance.json`，最多保留最近 200 次语音会话和 20 次服务生命周期。文件只含阶段名、耗时、模型与功能开关，不含音频、转写或指令文字、个人词典、窗口标题、设备地址或设备 ID，也不会上传。可以在性能页确认后清空，或使用命令行：

```bash
~/.local/bin/ble-stt performance show --json
~/.local/bin/ble-stt performance clear --json
```

Linux 和 Windows 使用 `ble-stt` 命令名。旧固件没有性能特征时，新服务会自动降级为仅记录电脑侧数据；旧服务连接新固件时则会忽略新增特征。

### 纠错质量评测

仓库内置 `270` 条显式输入与期望结果，覆盖语义完全无关的错词、同音/近音、漏字、重复字、中英混输、数字/日期/URL/路径保护、正常句防误改、标点、提示注入和个人词条。默认单元测试会逐条检查语料结构、保护规则和最终安全校验，但不会在 CI 下载大模型。

本机安装模型后可运行真实推理评测：

```bash
PYTHONPATH=tools/ble_stt python3 tools/ble_stt/scripts/evaluate_correction.py
```

评测会报告总精确率、应纠正准确率、应保持准确率、误改数、分类结果以及 mean/p50/p95/max 延迟。比较候选 GGUF 时无需覆盖当前模型：

```bash
PYTHONPATH=tools/ble_stt python3 tools/ble_stt/scripts/evaluate_correction.py \
  --model-path /path/to/candidate.gguf \
  --minimum-accuracy 0.50 --minimum-preservation 0.90 \
  --minimum-semantic 0.20 --minimum-mixed-english 0.80
```

如需把完整真实模型评测接入本机 `unittest`，设置 `BLE_STT_RUN_CORRECTION_EVAL=1`；未设置时该项会明确显示为跳过。

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
~/.local/bin/ble-stt journey-test --rounds 25 --duration 1800
~/.local/bin/ble-stt logs -n 100
~/.local/bin/ble-stt logs --follow
~/.local/bin/ble-stt restart
~/.local/bin/ble-stt upgrade
~/.local/bin/ble-stt uninstall
~/.local/bin/ble-stt uninstall --purge-models
```

Linux 和 Windows 的命令名仍是 `ble-stt`。

普通卸载会保留已经下载的模型，方便以后快速重装；加上 `--purge-models` 才会同时删除模型缓存。

macOS 的 `upgrade` 会先下载并验证新 App 和维护安装器，再停止旧 LaunchAgent、原子切换 App 并注册新服务。新服务必须连续两次报告为运行中，之后才提交安装；失败或按 `Ctrl-C` 取消会恢复旧服务。设备配置和模型缓存独立保存，不需要在每次升级时重新配对或重新下载。

排障时也可以在前台运行服务：

```bash
~/.local/bin/ble-stt run --engine auto --model medium
```

完整实体旅程回归使用 `journey-test`。运行前先聚焦一个空白文本窗口，再按提示在手表 BLE Remote 中完成多轮按住说话；命令会从 `ble-stt-events.log` 自动统计会话、文字输入和异常，并把报告与日志复制到 `test-artifacts/<时间戳>/`。

旧版命令（例如 `ble-stt --model small`）仍会自动转发到 `run`，以保持兼容。设备标识只用于匹配系统已经连接的设备，绝不会触发扫描或物理连接；`--device-id` 和旧的 `--address` 别名只用于排障。

## 日志位置

- Linux：`~/.local/state/m5stopwatch`
- macOS：`~/Library/Logs/M5StopWatch`
- Windows：`%LOCALAPPDATA%\M5StopWatch\Logs`

主要文件：

- `ble-stt-events.log`：带时间戳的结构化运行日志，包含启动环境、BLE 连接、模型准备、语音会话、文本注入和异常栈；会自动轮转。
- `ble-stt.log`：后台服务 stdout 兼容日志。
- `ble-stt-error.log`：后台服务 stderr 兼容日志。

如果另一台电脑仍弹出重连，先确认那台电脑运行的是本版本服务；它只能读取 BlueZ `Paired/Connected` 状态，不能发起 `Connect`。随后在手表控制页选择 **Pair new computer**，并在新电脑的系统蓝牙设置中连接。若系统里保留旧条目，由用户在对应系统蓝牙设置中手动移除，服务不会擅自删除。

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

桌面 App 发布包如果需要内置 `Small` starter 模型，先准备当前平台模型快照，再要求打包脚本校验模型存在：

```bash
cd tools/ble_stt/desktop
npm run prepare-starter-model
BLE_STT_REQUIRE_STARTER_MODEL=1 npm run build:mac
```

发布标签采用 `ble-stt-v<版本>` 格式，例如 `ble-stt-v0.4.0`。标签版本必须与 `tools/ble_stt/pyproject.toml` 中的版本一致。GitHub Actions 会生成 POSIX/Windows 安装器、带 SHA-256 的源码资源、`M5StopWatch-macos-arm64.zip`、App 与维护安装器的 RSA 签名，以及公开签名证书；发布前还必须把长期签名证书指纹注入 macOS 使用的一行安装器，源码和 Release 中都不得包含私钥。签名所需的临时钥匙串只存在于 GitHub Actions 构建机，安装用户不会接触它。

桌面/Helper 打包还会下载固定的 llama.cpp 官方二进制并核对仓库中记录的 SHA-256。不要直接改成 `latest`：较新的官方 macOS 产物可能使用比产品最低版本更高的 SDK 构建，当前固定的 `b9000` 已在 macOS 15 实机启动验证。
