# 项目交接说明

> 更新时间：2026-10-26
> 适用对象：接手本项目的开发者或 AI 代理
> 先读：`README.md`（安装与使用）、本文件（当前状态与注意事项）

## 1. 一分钟了解

这是一个本地优先的会议 / 课程录音转写与纪要系统：

- **安卓 App**：录音、暂停/续录、分片上传、浏览笔记、应用内更新。
- **云控制面**：FastAPI + SQLite，负责配对、任务队列、音频中转、笔记存储和应用更新。只部署在 Tailscale 内，不开放公网 HTTP 端口。
- **PC 空闲代理**：Windows 计划任务每 2 分钟检查一次；联网时把未转写音频预取到本地队列，用户空闲满 10 分钟、接电源、CPU/GPU 低负载时离线转写，恢复联网后自动回传。断网期间仍可继续处理已预取的音频。
- **PC 工作台**：Gradio 界面，支持本机上传处理、资料库浏览、一键把本地纪要同步到手机。

数据默认留在本机。服务器音频最多保留 5GB / 30 天，笔记和转写稿永久保留。

## 2. 当前状态（2026-10-26 凌晨）

### 仓库

- 分支：`main`
- 最后提交：`f313a1e Fix desktop shortcut: blank workbench window and duplicate-launch dialog`
- 本次改动已提交到 `main`；是否已推送以 `git status -sb` 为准。
- 公开仓库：`github.com/yuvan-bit/meeting-notes`（MIT）。提交前确认没有私有纪要、密钥或部署信息。

### 线上部署

- 服务：`meeting-notes.service`（`/opt/meeting-notes`），数据目录 `/var/lib/meeting-notes`。
- 对外访问：Tailscale Serve 把 443 转发到 `127.0.0.1:8000`；FastAPI 本身不监听公网。
- Tailscale 直连已建立（2026-10-26）：安全组新增 UDP 41641，PC 和手机均已走 `direct`。
- 同机共存：Koishi、NapCat。**不要改动这两个服务**，也不要动无关端口。
- 服务器健康检查当时返回：5 条笔记、队列为空（2026-10-26 07:40）。
- 服务器版本字段仍为 `0.1.0`，与 Android 版本号无关。

### 安卓发布

- 已发布：**0.2.3（versionCode 5）**，12MB，签名证书 `CN=Meeting Notes`。
- 发布方式：服务器 `server.cli publish-apk`，客户端通过 `/api/v1/app/latest` 检查更新。
- 手机升级路径：App →「设置」→「应用更新」。
- 本地构建产物：`android/app/build/outputs/apk/release/app-release.apk`（被 `.gitignore` 忽略，不要提交）。

### 队列

2026-10-26 凌晨有一个 26 分钟录音进入队列。代理在 03:21 领取，但前两次因旧版整文件下载在 1MB 处超时，第三次下载成功后 **Ollama 未运行**，摘要阶段失败并被标记 failed。修复后已重新排队，07:37 成功生成笔记，队列恢复为空。

日志：`data/cloud/agent.log`。详细修复见 5.5。

## 3. 架构与数据流

```text
Android 录音 ──分片上传──▶ FastAPI 控制面（SQLite + 文件仓库）
                                  ▲
                                  │ 预取音频 / 回传结果
                       PC 空闲代理（FunASR + Ollama）
                                  │
                                  ▼
                        本机资料库 data/library/年/月/...
                                  │
                    工作台「同步到手机」/ CLI push
                                  ▼
                         FastAPI 笔记接口 ──▶ Android 笔记列表
```

关键点：

- 手机上传的是音频；PC 领取后下载音频、在本机转写，再把纪要 / 逐字稿回传。
- PC 本地直接处理的录音**不经过服务器队列**，需要手动同步到手机（见第 5 节）。
- 笔记列表和详情在手机上做本地缓存，先显示缓存再后台刷新。

## 4. 目录速查

| 路径 | 作用 |
| --- | --- |
| `app/` | PC 工作台、流水线、资料库、云端代理 |
| `app/cloud/` | 云端客户端、配对凭据、本地纪要导入 |
| `app/webui.py` | Gradio 工作台，资料库页有「同步到手机」 |
| `server/` | FastAPI 控制面、SQLite、配对、上传、笔记、应用更新 |
| `server/routers/notes.py` | 笔记列表 / 详情 / 下载 / 置顶 / 本地导入 |
| `android/` | Android App（Kotlin + Compose） |
| `android/.../upload/` | 前台上传、并发分片、续传 |
| `android/.../data/NoteCache.kt` | 笔记列表 / 详情磁盘缓存 |
| `deploy/` | systemd 单元、服务器安装脚本、发布说明 |
| `tools/` | 桌面快捷方式、计划任务、签名配置脚本 |
| `data/` | 本机资料库与运行状态（**不入库**） |
| `promo/` | 宣传片源材料与成片（**未跟踪，约 170MB，不要直接提交**） |

## 5. 本次交接前完成的功能

### 5.1 本地纪要同步到手机

问题：PC 直接导入的录音不会进入服务器队列，手机上永远看不到。

已完成：

- 服务端新增 `POST /api/v1/notes/import`，仅 PC 设备可调用。
  - 必填 `local_id` 和 `minutes.md`；允许的结果文件与任务回传一致。
  - 以「设备 + local_id」做确定性 ID，重复同步只刷新内容，不产生副本。
  - 不上传音频，也不上传本机路径；服务端用占位 recording/job 满足笔记查询的 JOIN。
- PC 客户端新增 `app/cloud/importer.py` 和 `CloudClient.import_note()`。
- 命令行：`python -m app.cloud_agent push "<资料库条目目录或 job_id>"`。
- 工作台：资料库选中记录 →「同步到手机」。当前正在运行的旧工作台需关闭重开一次才会出现该按钮。
- 测试：`server/tests/test_note_import.py` 覆盖 PC 权限、手机令牌 403、重复导入、缺少 minutes、非法文件、设备隔离。

当时已把一篇本地会议纪要补传到服务器，手机端笔记总数从 3 变为 4，详情和文件下载均验证通过。

### 5.2 安卓上传性能

服务器时间戳显示：一次 6.2MB 上传传完第 1 个分片后停了约 20 分钟，恢复后剩余 5.5MB 只用 8 秒。根因是后台上传任务被系统挂起、WorkManager 进入长时间退避，不是音频太大。

0.2.1 起：

- 上传改为**前台服务 + 加急任务**，通知栏显示分片进度；
- 3 个分片并发；
- 同一个分片最多尝试 3 次（间隔 1.5 秒、3 秒），全部失败后交给 WorkManager 线性 15 秒退避；
- 失败后清理 OkHttp 连接池再重试；
- App 回到前台时自动拉起待上传记录；「重试上传」会立即打断退避。

0.2.2 追加：

- 笔记列表和详情本地缓存，打开即显示，后台刷新；
- 列表刷新失败时继续显示缓存；详情刷新失败时保留缓存并提示「当前显示上次缓存」；
- App 恢复时预热一次 `/api/v1/me`（60 秒节流），减少 Tailscale 重连等待；
- 配对 / 解除配对时清空笔记缓存，避免串服务器数据。

### 5.3 Tailscale 直连

背景：PC 和手机到服务器都在走 DERP 中继，实测单连接约 58–84 KiB/s，笔记加载和更新下载都慢。

已完成（2026-10-26）：

- 服务器 UFW 已放行 `41641/udp`（IPv4 + IPv6），tailscaled 正在监听该端口。
- 阿里云安全组已加入方向规则：自定义 UDP，`41641/41641`，来源 `0.0.0.0/0`，描述 `Tailscale WireGuard direct`。
- 直连已建立：PC 和手机 `tailscale ping` 均显示 `direct`，RTT 约 **53ms**（之前 180–740ms）。
- PC → 服务器下载 2MiB 用 2.3 秒，约 **885 KiB/s ≈ 7.25 Mbps**（之前约 102 KiB/s）。
- 笔记列表接口降到 **0.08–0.21 秒**（之前 0.3–0.8 秒）。
- 控制台显示公网带宽峰值为 **5 Mbps**（按流量计费）；大文件下载仍受这个出网峰值影响，手机上传走入口带宽，通常会更高。
- 手机直连已建立；实际上传速度待下一次录音上传时用服务器分片时间戳确认。

无需重启 Tailscale。若某台设备又回到 DERP，在该设备上开关一次 Tailscale 触发重新握手。

### 5.4 宣传片

宣传片已完成并通过逐段检查：

- 新片：`promo/meeting-notes-promo-preview.mp4`，约 3 分 49 秒，86MB，1080p / 30fps。
- 旧片：`promo/meeting-notes-promo.mp4`，约 3 分 42 秒，84MB，**保留未动**。
- 源材料：`promo/render.py`、`promo/frames.py`、`promo/music.py`、`promo/narration.py`、`promo/segments.json`，音频和帧在 `promo/audio`、`promo/frames`。
- `promo/` 整体约 170MB，已加入 `.gitignore`，**不要强制 `git add`**；需要归档时放 Release 或本地存储。

### 5.5 PC 代理可靠性（2026-10-26）

夜间任务失败的根因不是电脑没开，而是：

- 前两次下载音频时，旧版整文件流在 1MB 处停顿，触发 120 秒读超时；
- 第三次下载成功，但 Ollama 没有运行，摘要阶段连接 `127.0.0.1:11434` 被拒绝，任务耗尽 3 次尝试后标记 failed。

修复：

- `CloudClient.download_audio()` 改为 **1MB Range 分片下载**，每片最多重试 3 次，按 `Content-Range` 校验连续性，最后校验整文件 SHA-256；同样 6.5MB 音频从反复超时变为约 10 秒完成。
- `app/cloud/ollama.py` 新增 `ensure_ollama()`：预取/转写前先检查 11434；不在时优先触发 `OllamaKeepAlive` 计划任务，再尝试直接启动。
- `tools/install_agent_task.ps1` 现在同时安装：
  - `MeetingNotesCloudAgent`：30 分钟兜底检查队列；
  - `MeetingNotesNotifyListener`：登录后常驻，等待服务器推送；
  - `OllamaKeepAlive`：每 5 分钟检查并拉起 Ollama。
- `tools/ollama-keepalive.vbs` 是保活脚本源文件，安装时复制到 `%LOCALAPPDATA%\MeetingNotes\ollama-keepalive.vbs`；计划任务用 `wscript.exe //B //Nologo` 运行，**不要改回 .cmd**，否则每 5 分钟会闪一次 cmd 窗口。
- `server/tests/test_cloud_agent.py` 已把 Ollama 检查替换为 mock，测试不再依赖本机 Ollama。

如果 Ollama 以后再次被关闭，代理会记录「Ollama 未运行，暂不转写」并保留本地队列，保活任务会在 5 分钟内把它拉起来，不会再把任务打到 failed。

### 5.6 预取、离线转写与联网回传（2026-10-28）

代理流程已从「联网领取→立刻下载→立刻转写→立刻上传」改为三段解耦：

1. **联网预取**：收到服务器推送（或 30 分钟兜底 tick）时调用 `GET /api/v1/agent/jobs/queued` 查看排队任务，把音频下载到 `data/cloud/prefetch/<job_id>/`，默认最多保留 2 个；预取不占服务器租约，任务在服务器仍保持 `queued`。
2. **空闲转写**：本地队列存在时，仍按空闲 10 分钟、接电源、CPU/GPU 低负载的条件启动 FunASR + Ollama；断网也能转写。结果写入 `data/cloud/outbox/<job_id>/`。
3. **联网回传**：每次 tick 先 `flush_outbox`；服务器允许 PC 对 `queued` 任务直接回传结果（不消耗尝试次数），上传成功即置 `done`。断网时结果留在 outbox，恢复后自动重试。

相关实现：

- `app/cloud/config.py`：新增 `PREFETCH_DIR` 与 `prefetch_limit`（默认 2）。
- `app/cloud/agent.py`：新增 `prefetch_jobs`、`_prefetch_job`、`next_local_job`、`process_local_job`；转写不再持有租约或心跳线程。
- `app/cloud/client.py`：新增 `queued_jobs()`；音频下载使用 1MB Range 分片。
- `server/routers/agent.py`：新增 `GET /agent/jobs/queued`；`POST /agent/jobs/{id}/result` 允许 `queued` 任务直接接收结果；过期租约在预取列表前回收。
- 本地失败的任务最多重试 3 次，之后移入 `data/cloud/orphaned/`，避免无限占用 GPU；服务器任务仍保留在队列，可人工处理。
- 当前按**单 PC 代理**设计：预取不占租约，多个 PC 同时预取同一任务会重复计算；回传按 job_id 幂等，但不要同时运行多个代理实例。

### 5.7 服务器推送通知（2026-10-28）

为了避免电脑每 2 分钟查询一次队列，新增服务器到电脑的推送：

- 服务端 `GET /api/v1/agent/notifications?since=<version>&wait=300` 保持一条长连接；手机上传完成、生成 job 后调用 `server/notify.py` 的 `bump()` 唤醒等待中的 PC。版本号使用纳秒时间戳，服务器重启后 PC 重连也能立即收到变化。
- PC 端 `app/notify_listener.py` 登录后常驻，保持一条长连接；收到变化后触发一次 `pythonw -m app.cloud_agent run --once`。监听器约 28MB，无 GPU、无控制台窗口，**不轮询任务队列**。
- 计划任务新增 `MeetingNotesNotifyListener`（登录启动）；`MeetingNotesCloudAgent` 从每 2 分钟改为 **30 分钟兜底**。推送丢失、监听器重启或服务器重启时，兜底任务仍会补上。
- PC 不需要开放入站端口，也不需要 Windows 防火墙规则；长连接由 PC 主动建立，服务器有新音频时立即回复，效果等同服务器通知。
- 相关文件：`server/notify.py`、`server/routers/agent.py`、`server/routers/recordings.py`、`app/notify_listener.py`、`tools/install_agent_task.ps1`、`server/tests/test_agent_prefetch.py`。
- 监听器每 5 分钟会因长连接超时重连一次，这是空闲等待，不是任务队列轮询；实际任务查询只在收到通知或 30 分钟兜底时发生。

### 5.8 ffmpeg/ffprobe 缺失与队列恢复（2026-10-28）

19:00–21:00 的现象不是代理没运行：

- 18:02–20:58 外网中断，预取和监听日志都是 `SSL: UNEXPECTED_EOF_WHILE_READING`；但一个约 27MB、1 小时 51 分的录音已经在断网前预取到本地。
- 19:02:50 和 19:32:48 代理两次尝试本地转写，都因为 **`找不到 ffprobe`** 立即失败；第三次失败后任务被移入 `data/cloud/orphaned/`，所以 20:02、20:32 的兜底轮次显示「本地没有待转写音频」。
- 20:58 网络恢复，监听器收到新通知；21:03 又预取了一个约 24MB、1 小时 40 分的录音。

修复：

- 把 ffmpeg 9.0.2 的 `ffmpeg.exe` 和 `ffprobe.exe` 放到 `data/tools/ffmpeg/bin/`；`app/config.py` 会把它自动前置到 `PATH`，不再依赖计划任务的系统 PATH。
- `process_local_job` 增加媒体工具预检：缺少 ffmpeg/ffprobe 时只记录警告并**保留本地音频**，不消耗失败次数，也不把任务移入 orphan。
- 已把 27MB 的 orphan 任务移回 `data/cloud/prefetch/`，重置 failures=0，并用 ffprobe 验证可读。
- 当前服务器队列 **5**、本地预取 **5**（总时长约 8 小时 14 分，约 120MB）。其中 3 个是 10-27 因 ffprobe 失败、已重新排队的任务；另外 2 个是 10-28 的排队任务。全量拉取绕过了默认 `prefetch_limit=2`；后续自动预取仍保留 2 个的限额。两段时长接近（约 1 小时 40 分）的音频按服务器队列原样保留，未自行去重。
- **不要删除 `data/tools/ffmpeg/`**；如果以后升级 ffmpeg，保持 `ffmpeg.exe`、`ffprobe.exe` 在该目录或系统 PATH。

### 5.9 全量测试与环境修复（2026-10-29）

全量回归时发现项目 `.venv` 的基础 Python 已被破坏：`C:\Users\asus\AppData\Local\Python\pythoncore-3.11-64` 只剩 DLL 和 pythonw，缺少 `python.exe` 与 `Lib`，所有 `python`/`pythonw` 启动都会失败，计划任务的代理也受影响。

处理：

- 安装 Python 3.11.9 到 `C:\Users\asus\AppData\Local\Programs\Python\Python311`。
- 更新 `.venv/pyvenv.cfg` 的 `home`/`executable` 指向新安装；原文件备份为 `.venv/pyvenv.cfg.bak-20261028`。
- 验证 `venv` 可导入 `httpx`、`torch`，`cloud_agent status` 正常；计划任务运行结果 `LastTaskResult=0`。
- 若 `.venv` 需要重建，使用 Python 3.11.9 x64，并保留现有 `data/cloud/agent.json` 配对信息。

测试结果：

- 服务端 `pytest server/tests -q`：**36 passed**。
- PC 端 `pytest tests -q`：**6 passed**。
- Android `assembleRelease` + `testReleaseUnitTest`：**BUILD SUCCESSFUL**；APK 0.2.3 / versionCode 5，签名证书一致。
- Android `lintRelease`：修复 2 个 `MissingPermission` 错误（通知权限检查）和 API 30 前台服务类型守卫后 **0 errors, 4 warnings**；已作为 **0.2.3 / versionCode 5** 发布（SHA-256 `d323a9fa…`）。
- 线上只读冒烟：`/health` queue 5 / notes 5；queued API 5；通知长连接 2 秒等待正常；Tailscale 直连 66ms。
- 当前 5 个本地预取任务仍在等电脑空闲处理，测试没有触发转写，也没有改动业务数据。

## 6. 常用命令

### 测试

```powershell
# 服务端（FastAPI/SQLite/配对/上传/笔记/更新）
.venv\Scripts\python.exe -m pytest server/tests -q

# PC 端（长音频分段等辅助逻辑）
.venv\Scripts\python.exe -m pytest tests -q
```

最近一次结果：服务端 36 项通过，PC 端 6 项通过。

### 本机

```powershell
# 工作台
.venv\Scripts\python.exe -m app.webui

# 托盘客户端（正常入口）
.venv\Scripts\python.exe -m app.client

# 云代理单轮
.venv\Scripts\python.exe -m app.cloud_agent run --once

# 同步本地纪要
.venv\Scripts\python.exe -m app.cloud_agent push "data\library\2026\10\<条目目录>"
```

### Android 构建

```powershell
cd android
$env:JAVA_HOME = "C:\path\to\jdk-17"
C:\path\to\gradle-8.9\bin\gradle.bat assembleRelease
```

- 使用项目现有的稳定签名密钥；**不要轮换密钥**，否则已安装的 App 无法应用内更新。
- 遇到 Windows 文件被占用导致 `mergeDexRelease` 失败：先 `gradle --stop`，删除 `android/app/build/intermediates/dex/release/mergeDexRelease`，再重试。
- 增量构建偶尔显示 `UP-TO-DATE` 但产物未更新；发布前建议停 daemon 后全量构建一次，并核对 versionCode / 签名。

### 发布 APK

把签名 APK 上传到服务器后，以 `meeting` 用户执行：

```bash
cd /opt/meeting-notes
sudo -u meeting env MEETING_DATA_DIR=/var/lib/meeting-notes \
  .venv/bin/python -m server.cli publish-apk /tmp/meeting-notes.apk \
  --version-code <code> --version-name <版本> --changelog "<说明>"
```

发布后验证 `/api/v1/app/latest` 的 `version_code` 和 `sha256` 与本地 APK 一致。

### 服务端代码更新

- 代码在 `/opt/meeting-notes`，更新前先备份 `server/`。
- 上传后保持 `root:root`，目录 755、文件 644；数据目录仍由 `meeting` 用户写入。
- 先做 `py_compile` / 导入检查，再 `systemctl restart meeting-notes`。
- 服务没有自动重载，改 Python 文件必须重启。
- 验证 `/health`、查看 `journalctl -u meeting-notes -n 50`，并确认 `koishi`、`napcat`、`tailscaled` 仍为 active。

## 7. 本次改动的提交拆分

本次工作已提交到 `main`，可用 `git log --oneline -5` 查看完整哈希：

1. **`feat: sync local library notes to phone`**
   - `server/routers/notes.py`
   - `server/tests/test_note_import.py`（新）
   - `app/cloud/client.py`
   - `app/cloud/importer.py`（新）
   - `app/cloud_agent.py`
   - `app/webui.py`
2. **`perf(android): foreground parallel upload and note cache`**
   - `android/app/build.gradle.kts`（0.2.2 / versionCode 4）
   - `android/app/src/main/AndroidManifest.xml`（dataSync 前台服务）
   - `upload/UploadWorker.kt`、`upload/UploadScheduler.kt`
   - `data/ApiClient.kt`、`data/Models.kt`、`data/NoteCache.kt`（新）
   - `MainActivity.kt`、`MeetingApp.kt`
   - `NotesScreen.kt`、`NoteDetailScreen.kt`、`RecordScreen.kt`、`PairingScreen.kt`、`SettingsScreen.kt`
3. **`docs: add handoff notes and ignore promo workspace`**
   - `README.md`、`HANDOFF.md`、`.gitignore`
4. **`docs: record Tailscale direct connection`**
   - `HANDOFF.md`（直连验证与实测速率）
5. **`fix(agent): keep Ollama available and resume stalled downloads`**
   - `app/cloud/client.py`、`app/cloud/agent.py`、`app/cloud/ollama.py`
   - `server/tests/test_cloud_agent.py`
   - `tools/install_agent_task.ps1`、`tools/ollama-keepalive.vbs`
   - `HANDOFF.md`（本次故障与修复）
6. **`feat(agent): prefetch audio and process offline`**
   - `app/cloud/agent.py`、`app/cloud/client.py`、`app/cloud/config.py`
   - `server/routers/agent.py`、`server/tests/test_agent_prefetch.py`、`server/tests/test_cloud_agent.py`
   - `README.md`、`docs/cloud-architecture.md`、`HANDOFF.md`
7. **`feat(agent): push new-audio notifications to the PC`**
   - `server/notify.py`、`server/routers/agent.py`、`server/routers/recordings.py`
   - `app/notify_listener.py`
   - `tools/install_agent_task.ps1`
   - `server/tests/test_agent_prefetch.py`、`README.md`、`docs/cloud-architecture.md`、`HANDOFF.md`
8. **`fix(agent): require ffmpeg and recover orphaned audio`**
   - `app/config.py`、`app/cloud/agent.py`
   - `README.md`、`HANDOFF.md`
9. **`fix(android): guard revocable notification permission`**
   - `android/.../MeetingApp.kt`、`android/.../recording/RecordingService.kt`
   - `HANDOFF.md`（全量测试记录）
10. **`release: Android 0.2.3`**
    - `android/app/build.gradle.kts`（versionCode 5 / 0.2.3）
    - `HANDOFF.md`

**不要提交**：

- `promo/`：约 170MB，含最终片和中间素材，已加入 `.gitignore`；如需长期归档，放 GitHub Release 或移出仓库。
- `data/`、`.venv/`、APK、签名文件、部署笔记，均已被 `.gitignore` 覆盖。

## 8. 待办与下一步

1. **直连已完成**（UDP 41641，PC/手机均 direct）；下次手机上传时确认实际分片速率，并继续观察隧道是否保持在 direct。
2. 在手机上安装 0.2.3，确认：
   - 笔记列表 / 详情第二次打开是秒显；
   - 断网或 Tailscale 未连时仍能看到缓存，详情页会显示「上次缓存」提示；
   - 上传通知栏显示进度，短录音能很快完成。
3. 当前服务器队列 5 个任务、本地预取 5 个（总约 8 小时 14 分）；3 个是此前 ffprobe 失败后重新排队的任务，已全部拉到本地。等电脑空闲后依次处理，确认能从本地转写到 queued 回传。
4. `promo/` 已加入 `.gitignore`；如需长期归档，发布到 GitHub Release 或移出仓库。
5. 视情况在手机上把 Tailscale 设为「始终开启 VPN」并关闭其电池优化，减少隧道断开。
6. 保留 `data/tools/ffmpeg/bin`（ffmpeg/ffprobe）；如果系统升级或清理，先确认这两个程序仍在，否则代理会暂不转写并保留队列。

## 9. 约束与安全注意事项

- **共享服务器**：同机跑着 Koishi / NapCat。除 2026-10-25 经用户同意新增的 UFW `41641/udp`、以及 2026-10-26 经用户同意新增的安全组 UDP 41641 外，不要改动 UFW、安全组、其他 systemd 单元或端口。
- **安全组现状**：除 UDP 41641 外，还有系统创建的全量 ICMP、SSH 22、RDP 3389 入方向规则。Linux 上未监听 RDP，但 3389 对 `0.0.0.0/0` 开放并不必要，建议后续单独确认是否删除；不要顺手改动。
- **公网暴露**：FastAPI 仍只监听回环，通过 Tailscale Serve 提供 HTTPS。UDP 41641 只承载 WireGuard，不直接暴露 HTTP。
- **密钥边界**：服务器 token、配对码、SSH `target.json`、Android keystore、`/android/keystore.properties` 只在本地保存。不要读取、打印或提交。
- **隐私**：不要把真实会议标题、纪要正文、本机绝对路径写进公开文档、宣传片或提交信息。
- **应用更新**：Android 必须继续使用现有稳定签名；发布前核对 `versionCode` 严格递增。
- **资源限制**：服务器 2C2G，`meeting-notes.service` 内存上限 300MB；线上分片大小 1MB（`MEETING_CHUNK_MB=1`）。不要随意加大并发或分片，先看内存和磁盘。
- **Ollama 保活**：不要删除 `OllamaKeepAlive` 计划任务。摘要依赖本机 Ollama；代理转写前会检查，缺失时保留本地队列而不是把任务打成 failed。
- **通知监听**：`MeetingNotesNotifyListener` 是登录常驻的长连接监听（约 28MB、无 GPU）。它不轮询任务队列；不要改成每几秒查询。`MeetingNotesCloudAgent` 的 30 分钟任务只是兜底，不要改回 2 分钟。
- **推送语义**：服务器在 `complete_recording` 生成 job 后调用 `bump()`；监听器触发一次代理，代理仍按预取/空闲/回传流程工作。PC 没有开放入站端口。
- **单 PC 代理**：预取不占服务器租约，当前只应运行一个 PC 代理实例。不要在多台机器同时启用预取，否则会重复下载和计算；结果回传按 job_id 幂等，但不会自动去重计算。
- **离线结果**：服务端允许 PC 对 `queued` 任务直接回传结果，不消耗 attempts；这是离线转写的关键路径，不要收紧成必须持有租约。
- **媒体工具**：ffmpeg 与 ffprobe 是转写前置依赖。当前放在 `data/tools/ffmpeg/bin`，`app/config.py` 会自动加入 PATH；不要只依赖系统 PATH。缺少时 `process_local_job` 会保留本地音频、不计失败次数。
- **Python 运行时**：`.venv` 依赖 `C:\Users\asus\AppData\Local\Programs\Python\Python311\python.exe`（3.11.9）。不要删除；如果 `.venv` 重建，recreate 后要保留 `data/cloud/agent.json` 配对文件。旧 base `pythoncore-3.11-64` 已损坏，`pyvenv.cfg` 已改指向新安装。
- **服务器版本号**：服务端健康检查的 `version` 仍是 `0.1.0`，属于历史配置；排查时不要拿它和 Android 版本混淆。

## 10. 快速验收清单

```text
[ ] /health 返回 ok=true，notes 数量符合预期
[x] 长音频任务在 Ollama 和 ffmpeg/ffprobe 可用时能完成下载、转写和摘要；队列清空
[x] 缺少 ffmpeg/ffprobe 时本地任务保留在 prefetch，不会因连续失败被移入 orphan
[x] Android `assembleRelease`、`testReleaseUnitTest` 通过；`lintRelease` 0 errors（4 warnings）
[x] 服务端 36 项、PC 端 6 项测试通过
[ ] 当前 5 个已预取长录音在电脑空闲后依次完成并回传（总约 8 小时 14 分音频）
[x] OllamaKeepAlive 任务每 5 分钟检查，Ollama 停止后能自动拉起
[ ] /api/v1/app/latest 返回 version_code=5 / 0.2.3
[ ] 手机安装 0.2.3 后能打开笔记，且二次打开秒显
[ ] 新录一段 1 分钟音频，通知栏出现上传进度并很快完成
[ ] 手机上传完成后，PC 的 `notify.log` 立即出现「收到服务器新音频通知」，随后 agent.log 出现「已预取音频」
[ ] 联网时 `data/cloud/prefetch/` 出现任务；断网后仍能完成转写并写入 outbox；恢复联网后自动上传
[ ] PC 空闲满 10 分钟后，agent.log 出现「开始本地转写」而不是旧的「领取任务」
[x] 安全组放行后 tailscale ping 显示 direct（PC/手机均为 53ms 左右）
[ ] git status 中没有 data/、APK、keystore、promo/ 等不应提交的内容
```
