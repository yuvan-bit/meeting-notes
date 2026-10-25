# 项目交接说明

> 更新时间：2026-10-26
> 适用对象：接手本项目的开发者或 AI 代理
> 先读：`README.md`（安装与使用）、本文件（当前状态与注意事项）

## 1. 一分钟了解

这是一个本地优先的会议 / 课程录音转写与纪要系统：

- **安卓 App**：录音、暂停/续录、分片上传、浏览笔记、应用内更新。
- **云控制面**：FastAPI + SQLite，负责配对、任务队列、音频中转、笔记存储和应用更新。只部署在 Tailscale 内，不开放公网 HTTP 端口。
- **PC 空闲代理**：Windows 计划任务每 2 分钟检查一次；用户空闲满 10 分钟、接电源、CPU/GPU 低负载时领取任务，在本机用 FunASR + Ollama 转写并回传。
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

- 已发布：**0.2.2（versionCode 4）**，12MB，签名证书 `CN=Meeting Notes`。
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
                                  │ 领取任务 / 回传结果
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
- `app/cloud/ollama.py` 新增 `ensure_ollama()`：领取任务前先检查 11434；不在时优先触发 `OllamaKeepAlive` 计划任务，再尝试直接启动。
- `tools/install_agent_task.ps1` 现在同时安装：
  - `MeetingNotesCloudAgent`：每 2 分钟检查队列；
  - `OllamaKeepAlive`：每 5 分钟检查并拉起 Ollama。
- `tools/ollama-keepalive.cmd` 是保活脚本源文件，安装时复制到 `%LOCALAPPDATA%\MeetingNotes\ollama-keepalive.cmd`。
- `server/tests/test_cloud_agent.py` 已把 Ollama 检查替换为 mock，测试不再依赖本机 Ollama。

如果 Ollama 以后再次被关闭，代理会记录「Ollama 未运行，暂不领取任务」并保留队列，保活任务会在 5 分钟内把它拉起来，不会再把任务打到 failed。

## 6. 常用命令

### 测试

```powershell
# 服务端（FastAPI/SQLite/配对/上传/笔记/更新）
.venv\Scripts\python.exe -m pytest server/tests -q

# PC 端（长音频分段等辅助逻辑）
.venv\Scripts\python.exe -m pytest tests -q
```

最近一次结果：服务端 31 项通过，PC 端 6 项通过。

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
   - `tools/install_agent_task.ps1`、`tools/ollama-keepalive.cmd`
   - `HANDOFF.md`（本次故障与修复）

**不要提交**：

- `promo/`：约 170MB，含最终片和中间素材，已加入 `.gitignore`；如需长期归档，放 GitHub Release 或移出仓库。
- `data/`、`.venv/`、APK、签名文件、部署笔记，均已被 `.gitignore` 覆盖。

## 8. 待办与下一步

1. **直连已完成**（UDP 41641，PC/手机均 direct）；下次手机上传时确认实际分片速率，并继续观察隧道是否保持在 direct。
2. 在手机上安装 0.2.2，确认：
   - 笔记列表 / 详情第二次打开是秒显；
   - 断网或 Tailscale 未连时仍能看到缓存，详情页会显示「上次缓存」提示；
   - 上传通知栏显示进度，短录音能很快完成。
3. 队列中的 26 分钟录音已处理完成（notes=5，队列为空）；继续观察下一次夜间任务是否正常。
4. `promo/` 已加入 `.gitignore`；如需长期归档，发布到 GitHub Release 或移出仓库。
5. 视情况在手机上把 Tailscale 设为「始终开启 VPN」并关闭其电池优化，减少隧道断开。

## 9. 约束与安全注意事项

- **共享服务器**：同机跑着 Koishi / NapCat。除 2026-10-25 经用户同意新增的 UFW `41641/udp`、以及 2026-10-26 经用户同意新增的安全组 UDP 41641 外，不要改动 UFW、安全组、其他 systemd 单元或端口。
- **安全组现状**：除 UDP 41641 外，还有系统创建的全量 ICMP、SSH 22、RDP 3389 入方向规则。Linux 上未监听 RDP，但 3389 对 `0.0.0.0/0` 开放并不必要，建议后续单独确认是否删除；不要顺手改动。
- **公网暴露**：FastAPI 仍只监听回环，通过 Tailscale Serve 提供 HTTPS。UDP 41641 只承载 WireGuard，不直接暴露 HTTP。
- **密钥边界**：服务器 token、配对码、SSH `target.json`、Android keystore、`/android/keystore.properties` 只在本地保存。不要读取、打印或提交。
- **隐私**：不要把真实会议标题、纪要正文、本机绝对路径写进公开文档、宣传片或提交信息。
- **应用更新**：Android 必须继续使用现有稳定签名；发布前核对 `versionCode` 严格递增。
- **资源限制**：服务器 2C2G，`meeting-notes.service` 内存上限 300MB；线上分片大小 1MB（`MEETING_CHUNK_MB=1`）。不要随意加大并发或分片，先看内存和磁盘。
- **Ollama 保活**：不要删除 `OllamaKeepAlive` 计划任务。摘要依赖本机 Ollama；代理领取前会检查，缺失时会跳过领取而不是把任务打成 failed。
- **服务器版本号**：服务端健康检查的 `version` 仍是 `0.1.0`，属于历史配置；排查时不要拿它和 Android 版本混淆。

## 10. 快速验收清单

```text
[ ] /health 返回 ok=true，notes 数量符合预期
[x] 长音频任务在 Ollama 运行时能完成分片下载、转写和摘要；队列清空
[x] OllamaKeepAlive 任务每 5 分钟检查，Ollama 停止后能自动拉起
[ ] /api/v1/app/latest 返回 version_code=4 / 0.2.2
[ ] 手机安装 0.2.2 后能打开笔记，且二次打开秒显
[ ] 新录一段 1 分钟音频，通知栏出现上传进度并很快完成
[ ] PC 空闲满 10 分钟后，agent.log 出现领取任务
[x] 安全组放行后 tailscale ping 显示 direct（PC/手机均为 53ms 左右）
[ ] git status 中没有 data/、APK、keystore、promo/ 等不应提交的内容
```
