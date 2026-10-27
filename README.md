# 会议记录（Meeting Notes）

本地优先的会议 / 课程录音转写与纪要工具。桌面端用 FunASR 完成中文转写、标点和说话人分离，用 Ollama 生成结构化纪要；安卓端负责录音与断点上传；PC 联网时自动预取待转写音频，空闲时在本机转写，恢复联网后把结果同步回去。

音频默认只在本机处理；云端控制面只做配对、任务队列、文件中转和笔记存储，不运行 ASR/LLM。远程访问通过 Tailscale Serve 发布到 tailnet 内，不开放公网端口。

## 功能

- **本地转写**：支持常见音频/视频文件，自动转成 16kHz WAV 后送入 FunASR；超过 30 分钟的长录音按停顿自动分段、逐段识别后合并时间轴。
- **会议 / 课程**：自动判断内容类型，分别生成会议纪要和课程笔记。
- **说话人分离**：cam++ 声纹聚类，可在生成前手工映射 `0=张三,1=李四`；长录音分段转写时发言人按段独立编号。
- **分类归档**：按 `年/月/日期_类型_主题` 写入资料库，同时生成 Markdown 纪要、逐字稿和元数据。
- **本机工作台**：Gradio 界面浏览资料库、上传处理、查看进度。
- **托盘客户端**：常驻内存约 40MB；关闭工作台窗口即释放 WebUI 与浏览器窗口，再次启动只重开窗口。
- **安卓 App**：录音/暂停/续录、前台上传与并发分片断点续传、笔记本地缓存秒开、笔记列表与搜索、Markdown 预览、附件下载、应用内检查更新。
- **空闲代理**：服务器有新音频时通过长连接立即通知电脑；电脑常驻一个轻量监听（约 28MB，无 GPU），联网时预取未转写音频到本地队列（默认最多 2 个），空闲满 10 分钟、接电源、CPU/GPU 低负载时离线转写，联网后自动回传。另有 30 分钟兜底检查，断网期间仍可继续使用已预取的音频。
- **保留策略**：服务器音频最多 5GB、最多 30 天；笔记和转写稿永久保留，置顶记录不自动清理。

## 架构

```text
┌──────────────┐   录音 / 分片上传 / 浏览下载   ┌──────────────────────┐
│  Android App │ ─────────────────────────────▶ │  FastAPI + SQLite    │
└──────────────┘        HTTPS（Tailscale）      │  任务队列 / 文件仓库  │
                                                └──────────┬───────────┘
┌──────────────┐   预取音频 / 回传结果                     │
│  PC 空闲代理 │ ◀─────────────────────────────────────────┘
│  FunASR      │
│  Ollama      │ ──▶ 本地资料库（Markdown / 逐字稿 / 元数据）
└──────────────┘
```

## 目录

```text
app/                本地转写流水线、Gradio 工作台、托盘客户端、空闲代理
server/             云端控制面（FastAPI、SQLite、配对、上传、任务租约）
android/            安卓 App（Kotlin + Jetpack Compose）
deploy/             systemd 单元、安装脚本、上线手册
docs/               云端架构与 API 契约
tools/              快捷方式、计划任务安装脚本
assets/             图标
```

运行时数据都在 `data/`（已被 `.gitignore` 排除）；FunASR 模型缓存在 `models/`。

## 环境要求

**桌面端**

- Windows 10/11（托盘与应用窗口逻辑仅适配 Windows）
- Python 3.11（64 位）
- [ffmpeg](https://ffmpeg.org/) 已加入 `PATH`
- [Ollama](https://ollama.com/)，默认模型 `qwen3.5:9b` 和 `qwen3.5:4b`
- 可选 NVIDIA GPU；CPU 也能跑，但速度较慢

**云端**

- Linux 服务器，Python 3.10+，建议 2 核 2GB 起
- 手机、PC、服务器加入同一个 Tailscale 网络
- 安卓 8.0+；构建需要 JDK 17 与 Android SDK 35

## 本地使用

```powershell
python -m venv .venv
.venv\Scripts\activate

# 按显卡选择 PyTorch 轮子；requirements.txt 注释里使用的是 CUDA 12.8
pip install torch --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt

# 首次运行会下载 FunASR 模型到 models/，需要数 GB 空间
.venv\Scripts\python.exe -m app.cli --check
```

处理一个文件：

```powershell
.venv\Scripts\python.exe -m app.cli "D:\recordings\meeting.m4a" --type meeting --hotwords "项目名 人名"
.venv\Scripts\python.exe -m app.cli "D:\recordings\lesson.mp4" --type course --speakers "0=张老师,1=李同学"
```

`--type` 可选 `auto`、`meeting`、`course`。结果写入 `data/library/`。

启动界面：

- `start.bat`：打开本机工作台（Gradio）。
- `start_client.bat`：启动托盘客户端，并打开工作台；关闭工作台窗口后托盘继续运行。
- `start_agent.bat`：前台运行云代理，便于调试。

Ollama 不在客户端启动时强制拉起；生成纪要时会自动尝试启动，摘要完成后卸载模型。若希望进一步降低待机内存，可以关闭 Ollama 的开机自启。

## 云端部署

### 1. 部署控制面

把仓库放到服务器的 `/opt/meeting-notes`，然后：

```bash
cd /opt/meeting-notes
sudo bash deploy/install-server.sh
```

脚本会创建 `meeting` 系统用户、虚拟环境、`/var/lib/meeting-notes` 数据目录和 systemd 单元，服务只监听 `127.0.0.1:8000`。保留策略、监听地址等可在 `/etc/meeting-notes.env` 中调整：

```ini
MEETING_DATA_DIR=/var/lib/meeting-notes
MEETING_HOST=127.0.0.1
MEETING_PORT=8000
MEETING_AUDIO_MAX_MB=5120
MEETING_AUDIO_RETENTION_DAYS=30
```

### 2. 通过 Tailscale 发布

按 [deploy/go-live.md](deploy/go-live.md) 安装 Tailscale、启用 Serve，并确认：

```bash
sudo tailscale serve --bg --yes 8000
sudo tailscale serve status
curl https://meeting-server.<tailnet>.ts.net/health
```

服务仍然只监听回环地址，Tailscale Serve 只把 443 映射到本机 8000，不暴露公网。

如果笔记和大文件加载偏慢，通常是 Tailscale 走了 DERP 中继。可在云服务器安全组和 UFW 同时放行 **UDP 41641**，让客户端与服务器建立直连：

```bash
sudo ufw allow 41641/udp comment 'tailscale direct'
tailscale ping <服务器主机名>   # 出现 direct 即已直连
```

该端口只承载 Tailscale 的 WireGuard 加密流量，不会把 FastAPI 暴露到公网。

### 3. 配对 PC

```bash
# 服务器
cd /opt/meeting-notes
sudo -u meeting .venv/bin/python -m server.cli pair-code --role pc
```

```powershell
# 本机
.venv\Scripts\python.exe -m app.cloud_agent pair --url https://meeting-server.<tailnet>.ts.net --code <配对码>
powershell -ExecutionPolicy Bypass -File tools\install_agent_task.ps1
```

安装脚本会注册三个计划任务：

- `MeetingNotesCloudAgent`：每 30 分钟兜底执行一次 `app.cloud_agent run --once`；
- `MeetingNotesNotifyListener`：登录后常驻，保持一条服务器长连接；服务器收到新音频时立即回复并触发代理，电脑不再每 2 分钟查询队列；
- `OllamaKeepAlive`：每 5 分钟检查 Ollama，缺失时自动拉起。

卸载任务：

```powershell
powershell -ExecutionPolicy Bypass -File tools\install_agent_task.ps1 -Uninstall
```

本机直接处理的录音不会经过服务器队列。要把这类历史纪要补到手机端，在资料库选中记录后点「同步到手机」，或使用命令行：

```powershell
.venv\Scripts\python.exe -m app.cloud_agent push "data\library\2026\10\<条目目录>"
```

同步以 `设备 + 本地 job_id` 去重，重复执行只会刷新内容，不会在手机上产生副本。只上传纪要与逐字稿，不上传音频和本机路径信息。

### 4. 安装手机 App

开发调试：

```bash
cd android
./gradlew assembleDebug
```

APK 位于 `android/app/build/outputs/apk/debug/app-debug.apk`。安装后在 App 内填写服务器地址和 `pair-code --role phone` 生成的一次性配对码。

正式使用需要固定签名，才能让后续版本覆盖安装：

```powershell
powershell -ExecutionPolicy Bypass -File tools\setup_android_signing.ps1
```

脚本会交互式询问签名密码，生成 `android/keystore/release.jks` 和 `android/keystore.properties`；两者都已排除在 Git 之外。请离线备份 keystore 和密码，丢失后将无法覆盖安装后续版本。

```bash
cd android
./gradlew assembleRelease
```

APK 位于 `android/app/build/outputs/apk/release/app-release.apk`。首次从旧的 debug 签名包切换到正式签名包时，Android 会拒绝覆盖安装；请先上传未同步的录音，卸载旧版后手动安装一次。此后 App 启动时会自动检查新版本，也可以到“设置 → 应用更新”手动检查、下载并调起系统安装器。系统会要求允许“安装未知应用”，不会静默安装。

正式版只接受 HTTPS 服务器地址；服务器地址未写协议时默认补全 `https://`。调试构建允许显式填写 `http://` 以便本机联调，配对页会显示明文传输警告。不要在日常使用的手机上通过公网明文 HTTP 传输设备令牌和录音。

### 5. 发布安卓更新

递增 `android/app/build.gradle.kts` 中的 `versionCode`，构建 release APK，然后把 APK 传到服务器并发布：

```bash
sudo -u meeting .venv/bin/python -m server.cli publish-apk /path/meeting-notes.apk \
  --version-code 3 --version-name 0.2.1 --changelog "修复若干问题"
```

发布内容写入 `/var/lib/meeting-notes/app/latest.json` 和 `latest.apk`。App 通过 `GET /api/v1/app/latest` 检查版本，下载后校验 SHA-256 与文件大小，再交给系统安装器。更新接口不需要设备令牌，因此只能通过 Tailscale 暴露，不要直接开到公网。

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `MEETING_LLM` | `qwen3.5:9b` | 摘要模型 |
| `MEETING_LLM_FAST` | `qwen3.5:4b` | 快速模型 |
| `MEETING_ASR_DEVICE` | `auto` | `auto` / `cuda` / `cpu` |
| `MEETING_ASR_CHUNK_THRESHOLD_S` | `1800` | 超过该时长的音频自动分段转写 |
| `MEETING_ASR_CHUNK_TARGET_S` | `900` | 每段的目标时长（秒） |
| `MEETING_ASR_CHUNK_MIN_S` | `300` | 每段最短时长（秒） |
| `MEETING_ASR_CHUNK_MAX_S` | `1200` | 每段最长时长（秒） |
| `MEETING_CHUNK_CHARS` | `4000` | 长转写分段摘要的字符阈值 |
| `MEETING_NUM_CTX` | `8192` | Ollama 上下文长度 |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama 地址 |

云端配置见 `/etc/meeting-notes.env`，完整 API 契约见 [docs/cloud-architecture.md](docs/cloud-architecture.md)。

## 测试

```bash
pip install -r server/requirements-dev.txt
pytest -q server/tests tests
```

## 交接

当前部署状态、未提交改动、已知问题和待办事项见 [HANDOFF.md](HANDOFF.md)。

## 数据与隐私

- 本地音频、转写和纪要默认只写入 `data/`，不会上传，除非配置了云端代理。
- 云端设备令牌保存在 `data/cloud/agent.json`；服务端只存令牌哈希。
- 云端音频默认 30 天后或被 LRU 清理；笔记与逐字稿不参与 5GB 配额。
- 项目没有遥测；除配置的云端地址外不会主动外连。
- 录音前请确认已获得所有参与者同意，并遵守当地法律与组织规定。

## 许可证

本项目以 [MIT License](LICENSE) 发布。第三方依赖与模型的许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 鸣谢

感谢 FunASR、ModelScope、Ollama、Qwen、Gradio、pywebview、pystray、FFmpeg、AndroidX / Jetpack Compose、Tailscale 等开源项目及其维护者。本项目的转写、摘要、界面与远程访问能力，都建立在这些工作之上。
