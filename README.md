# 会议记录（Meeting Notes）

本地优先的会议 / 课程录音转写与纪要工具。桌面端用 FunASR 完成中文转写、标点和说话人分离，用 Ollama 生成结构化纪要；安卓端负责录音与断点上传；PC 在长时间空闲时自动领取云端任务，在本机转写并把结果同步回去。

音频默认只在本机处理；云端控制面只做配对、任务队列、文件中转和笔记存储，不运行 ASR/LLM。远程访问通过 Tailscale Serve 发布到 tailnet 内，不开放公网端口。

## 功能

- **本地转写**：支持常见音频/视频文件，自动转成 16kHz WAV 后送入 FunASR。
- **会议 / 课程**：自动判断内容类型，分别生成会议纪要和课程笔记。
- **说话人分离**：cam++ 声纹聚类，可在生成前手工映射 `0=张三,1=李四`。
- **分类归档**：按 `年/月/日期_类型_主题` 写入资料库，同时生成 Markdown 纪要、逐字稿和元数据。
- **本机工作台**：Gradio 界面浏览资料库、上传处理、查看进度。
- **托盘客户端**：常驻内存约 40MB；关闭工作台窗口即释放 WebUI 与浏览器窗口，再次启动只重开窗口。
- **安卓 App**：录音/暂停/续录、断点分片上传、笔记列表与搜索、Markdown 预览、附件下载。
- **空闲代理**：Windows 计划任务每 2 分钟检查一次；空闲满 10 分钟、接电源、CPU/GPU 低负载时才领取任务，不常驻轮询。
- **保留策略**：服务器音频最多 5GB、最多 30 天；笔记和转写稿永久保留，置顶记录不自动清理。

## 架构

```text
┌──────────────┐   录音 / 分片上传 / 浏览下载   ┌──────────────────────┐
│  Android App │ ─────────────────────────────▶ │  FastAPI + SQLite    │
└──────────────┘        HTTPS（Tailscale）      │  任务队列 / 文件仓库  │
                                                └──────────┬───────────┘
┌──────────────┐   领取任务 / 回传结果                     │
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

计划任务每 2 分钟执行一次 `app.cloud_agent run --once`，不常驻进程。卸载任务：

```powershell
powershell -ExecutionPolicy Bypass -File tools\install_agent_task.ps1 -Uninstall
```

### 4. 安装手机 App

```bash
cd android
./gradlew assembleDebug
```

APK 位于 `android/app/build/outputs/apk/debug/app-debug.apk`。安装后在 App 内填写服务器地址和 `pair-code --role phone` 生成的一次性配对码。

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `MEETING_LLM` | `qwen3.5:9b` | 摘要模型 |
| `MEETING_LLM_FAST` | `qwen3.5:4b` | 快速模型 |
| `MEETING_ASR_DEVICE` | `auto` | `auto` / `cuda` / `cpu` |
| `MEETING_CHUNK_CHARS` | `4000` | 长转写分段摘要的字符阈值 |
| `MEETING_NUM_CTX` | `8192` | Ollama 上下文长度 |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama 地址 |

云端配置见 `/etc/meeting-notes.env`，完整 API 契约见 [docs/cloud-architecture.md](docs/cloud-architecture.md)。

## 测试

```bash
pip install -r server/requirements-dev.txt
pytest -q server/tests
```

## 数据与隐私

- 本地音频、转写和纪要默认只写入 `data/`，不会上传，除非配置了云端代理。
- 云端设备令牌保存在 `data/cloud/agent.json`；服务端只存令牌哈希。
- 云端音频默认 30 天后或被 LRU 清理；笔记与逐字稿不参与 5GB 配额。
- 项目没有遥测；除配置的云端地址外不会主动外连。
- 录音前请确认已获得所有参与者同意，并遵守当地法律与组织规定。

## 许可证

本项目以 [MIT License](LICENSE) 发布。第三方依赖与模型的许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 致谢

FunASR、ModelScope、Ollama、Gradio、pywebview、pystray 以及所有依赖项目的维护者。
