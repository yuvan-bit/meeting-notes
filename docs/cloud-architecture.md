# 会议记录云端方案（v1）

## 1. 目标与非目标

**目标**

- 安卓端录音、断点上传；PC 联网时预取待转写音频，空闲时自动转写，恢复联网后回传；手机在线浏览和下载。
- 服务器只做控制面、存储面和同步，不跑 ASR/LLM。
- 服务器音频默认不超过 5GB，按保留策略清理；笔记和转写稿永久保留。
- 与现有桌面客户端共用同一套归档格式：`minutes.md`、`transcript.*`、`meta.json`。

**非目标**

- 不做实时转写、多人协作、在线编辑、语音通话。
- 不在 2C2G 服务器上跑模型，不把 Gradio 暴露到公网。
- v1 不做 iOS、Web 端、分享链接。

## 2. 拓扑

```text
Android App
  录音 → 本地队列 → 分片上传 → 浏览/下载
        │ HTTPS（WireGuard/Tailscale/隧道）
        ▼
2C2G 服务器
  FastAPI + SQLite(WAL) + 音频仓库 + 笔记仓库
        ▲ 任务租约/心跳/结果回传
        │
PC 通知监听（登录常驻，一条长连接等待服务器推送）
  服务器新音频 → 立即触发
PC 空闲代理（30 分钟兜底检查）
  联网预取音频 → 本地队列 → 空闲检测 → 现有 FunASR/Ollama pipeline
  → 本地归档 + outbox → 联网时回传结果
```

- 预取不会占用服务器任务租约：音频先下载到 `data/cloud/prefetch/`，任务在服务器保持 `queued`；转写完成后结果进入 `data/cloud/outbox/`，联网时按 `queued` 任务回传。断网期间仍可继续转写已预取音频。
- 当前按单 PC 代理设计；多个 PC 同时预取同一任务会重复计算，但结果回传有 job_id 幂等约束。

- 服务器：任意 2C2G 及以上的 Linux 主机，不运行 ASR/LLM。
- 服务使用独立用户、独立目录、独立 systemd 单元，内存上限 300MB。
- 推荐用 Tailscale Serve 仅发布到 tailnet，不暴露公网端口。

## 3. 组件与目录

### 服务器

```text
/opt/meeting-notes/                 # 代码 + venv
/var/lib/meeting-notes/
  meeting.db                        # SQLite
  audio/YYYY/MM/<recording_id>.m4a  # 原始音频
  notes/YYYY/MM/<job_id>/           # 笔记与转写稿
  tmp/<recording_id>/<chunk>.part   # 上传分片
  app/latest.apk                    # 已发布的安卓安装包
  app/latest.json                   # 版本、SHA-256、大小、更新说明
  .pairing_pepper                   # 配对码 pepper，600 权限
```

服务监听 `127.0.0.1:8000`，通过 VPN/反向代理访问。systemd 单元：

```ini
[Service]
User=meeting
MemoryHigh=240M
MemoryMax=300M
Restart=always
```

### PC 代理

- 由 Windows 计划任务每 30 分钟执行一次 `python -m app.cloud_agent run --once` 作为兜底；登录后另有 `app.notify_listener` 常驻，保持一条 `/api/v1/agent/notifications` 长连接。服务器收到新音频后通过长连接立即唤醒 PC，不要求 PC 高频轮询。
- 复用 `app.pipeline.run_pipeline`；与本地 UI 共用处理锁，避免同时抢 GPU。
- 空闲判定：用户无输入 ≥10 分钟、CPU ≤25%、GPU ≤30%（检测可用时）、接通电源、无本地任务。
- 任务开始后阻止系统睡眠；完成/失败后释放。

### 安卓

- Kotlin + Jetpack Compose，minSdk 26。
- 录音：`MediaRecorder` + 前台服务，AAC/M4A，16kHz、32kbps、单声道；支持暂停/续录。
- 上传：WorkManager + OkHttp，8MB 分片、SHA-256、断点续传、指数退避。
- 浏览：笔记列表、类型筛选、搜索、Markdown 渲染、附件下载、已下载离线缓存。
- 配对：服务器地址 + 一次性配对码；token 存 Keystore 加密存储。

## 4. 数据模型

| 表 | 关键字段 | 说明 |
|---|---|---|
| devices | id, name, role, token_hash, revoked | role: phone/pc |
| pairing_codes | code_hash, role, expires_at, used_at | 一次性配对码 |
| recordings | id, device_id, title, content_type, size_bytes, sha256, status, audio_path, pinned, audio_deleted_at | 上传与保留状态 |
| recording_chunks | recording_id, idx, size_bytes, sha256, path | 分片幂等 |
| jobs | id, recording_id, status, attempts, lease_owner, lease_expires_at, error | 任务队列 |
| notes | job_id, content_type, topic, summary, files_json | 笔记索引 |
| events | job_id, type, message | 审计/排障 |

时间统一存 UTC ISO8601；ID 使用 `rec_`/`job_` 前缀 + UUID hex。

## 5. API v1

所有业务接口前缀 `/api/v1`，除配对、健康检查和安卓更新清单/安装包下载外都需要
`Authorization: Bearer <device_token>`。

### 认证

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/pair` | `{code, device_name, role}` → `{device_id, token, role}`，配对码一次性 |
| GET | `/me` | 当前设备信息 |
| GET | `/health` | 无鉴权；返回版本、队列数、磁盘剩余，不含敏感信息 |

### 应用更新

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/app/latest` | 无鉴权；版本号、SHA-256、大小、更新说明、apk_url；未发布返回 404 |
| GET | `/app/apk` | 无鉴权；下载最新 APK，响应头含 X-APK-SHA256 |

`python -m server.cli publish-apk` 把 APK 和元数据写入 `data/app/latest.apk` 与
`latest.json`。客户端下载后会校验大小与 SHA-256，再交给 Android 系统安装器；
不会静默安装。

### 手机端

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/recordings` | 初始化上传：title、content_type、filename、size、sha256 → recording_id、chunk_size、total_chunks |
| PUT | `/recordings/{id}/chunks/{idx}` | 原始字节；`X-Chunk-SHA256` 可选；幂等 |
| GET | `/recordings/{id}/chunks` | 返回已上传与缺失分片序号，供客户端续传 |
| POST | `/recordings/{id}/complete` | 校验分片、合并音频、创建 job；重复调用返回同一 job |
| GET | `/recordings` | 我的录音与任务状态 |
| GET | `/recordings/{id}` | 单条状态、任务状态、note_id |
| GET | `/recordings/{id}/audio` | 播放/下载；已清理返回 410 |
| GET | `/notes` | `content_type`、`q`、`limit`、`offset` |
| GET | `/notes/{job_id}` | 详情 + `minutes_markdown` + 文件列表 |
| GET | `/notes/{job_id}/files/{name}` | 下载白名单文件 |
| POST | `/notes/{job_id}/pin` | `{pinned: bool}`，置顶保护音频 |

### PC 代理

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/agent/jobs/next` | 原子领取一个任务；无任务返回 204 |
| POST | `/agent/jobs/{id}/heartbeat` | 续租，返回租约到期时间 |
| GET | `/agent/recordings/{id}/audio` | 下载待转写音频 |
| POST | `/agent/jobs/{id}/result` | multipart 上传笔记与转写稿 |
| POST | `/agent/jobs/{id}/fail` | `{error}`；未超次数回到 queued |

结果文件白名单：`minutes.md`、`transcript.md`、`transcript.txt`、`transcript.srt`、
`transcript.json`、`meta.json`。单文件上限 20MB。

## 6. 任务状态机

```text
recordings: uploading → uploaded → processing → done
                         └──────────────→ upload_failed（可续传）

jobs: queued → leased → done
          ↑       ├── heartbeat 续租
          └───────┘ 租约过期/失败且 attempts < 3
                  └── failed（attempts >= 3）
```

- 租约默认 900 秒，心跳间隔 60 秒；领取时 `attempts += 1`。
- 租约过期任务可被任意 PC 重新领取；同一任务只允许一个有效租约。
- 结果上传幂等：重复提交返回已有 note，不重复计费。
- 失败原因写入 `jobs.error`，手机可见。

## 7. 保留策略

- 仅统计音频；笔记、转写稿不占 5GB 配额。
- 默认：音频总量 ≤ 5GB 且保留 ≤ 30 天；先按过期，再按 LRU 删除。
- 跳过：排队中/转写中、置顶、上传未完成。
- 删除后 `audio_deleted_at` 置位，手机显示“音频已清理”，笔记仍可访问。
- 清理由 `python -m server.cli cleanup` 执行，服务器每日 cron/systemd timer 调用。
- 置顶音频计入 5GB；若置顶本身超限，只告警不删除。

## 8. 安全

- 配对码 8 位、10 分钟过期、一次性、服务端只存 HMAC；配对接口限流。
- 设备 token 32 字节随机，服务端只存 SHA-256；可单独 revoke。
- 上传文件名不落地；音频用服务端生成 ID；分片大小/序号/总大小严格校验。
- 结果文件名白名单；禁止路径穿越；Markdown 由客户端渲染时禁用原始 HTML。
- 服务只监听 VPN/localhost；不开放 8000 到公网；不暴露 `/docs` 给公网。
- 不记录 token、配对码、音频内容；日志只记 job_id/设备 ID。
- 服务器备份加密；至少备份 SQLite + notes，音频可选。

## 9. 里程碑

1. **M1**：控制面 MVP，pytest 通过。
2. **M2**：服务器部署，PC 配对并完成任务领取。
3. **M3**：PC 空闲代理端到端。
4. **M4**：安卓录音、上传、浏览、下载可用。
5. **M5**：断点续传、5GB 清理、备份、异常恢复。
