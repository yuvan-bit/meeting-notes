# 上线与联调手册（Tailscale + 手机 / 电脑配对）

本手册把控制面部署到一台 Linux 服务器，仅监听 `127.0.0.1:8000`，再通过 Tailscale Serve 发布到 tailnet 内（不暴露公网），最后完成 PC / 手机配对与端到端验收。示例域名统一写成 `meeting-server.<tailnet>.ts.net`，请替换为你的实际 MagicDNS 名称。

## 0. 需要你准备

- 一个 Tailscale 账号（免费个人版即可）。当前 tailnet 已启用 MagicDNS；Serve 需在管理后台启用一次（同时确认 HTTPS Certificates 已开启），HTTPS 证书由 Serve 自动签发。
- 一台 Android 8.0 及以上的手机。
- 确保本机（PC）已安装并登录同一个 Tailscale 账号。

## 1. 服务器接入 Tailscale

均通过现有 SSH 通道执行，不需要改 UFW 或安全组。Tailscale 只做纯出网连接。

```bash
# 1) 安装（官方脚本，安装后服务自启）
curl -fsSL https://tailscale.com/install.sh | sudo sh

# 2) 登录：会输出一个一次性登录链接，用浏览器打开并在页面上确认设备
sudo tailscale up

# 3) 确认已入网
tailscale status

# 4) 仅把控制面发布到 tailnet，不暴露公网
#    首次使用需由 tailnet 管理员在后台启用 Serve；
#    若提示 "Serve is not enabled on your tailnet"，打开命令输出的链接启用一次后重试。
#    --yes 只跳过交互确认，不能代替后台启用。
sudo tailscale serve --bg --yes 8000
sudo tailscale serve status
```

MagicDNS 已启用；HTTPS 证书由 Serve 自动签发，前提是 tailnet 已开启 HTTPS Certificates。随后在任意已加入 tailnet 的设备访问：

```text
https://meeting-server.<tailnet>.ts.net/health
```

应返回 `{"ok":true,...}`。此时服务器仍应只监听 `127.0.0.1:8000`，可用 `ss -ltnp | grep 8000` 复查。

> **云厂商内网 DNS 注意**：部分实例的内网 DNS `100.100.2.136/138` 不可达，而这两个地址又落在 Tailscale 的 `100.64.0.0/10` 网段内，会导致 Serve 的 ACME 证书签发超时。已新增 `/etc/netplan/60-dns.yaml`，关闭 DHCP DNS 并固定 `223.5.5.5`、`119.29.29.29`，执行 `netplan apply` 生效。换服务器时需要同样处理。

## 2. 配对电脑（PC 代理）

在服务器生成一次性 PC 配对码（10 分钟有效，只用一次）：

```bash
cd /opt/meeting-notes
sudo -u meeting .venv/bin/python -m server.cli pair-code --role pc
```

在本项目目录执行配对（把地址和配对码换成实际值）：

```powershell
.venv\Scripts\python.exe -m app.cloud_agent pair --url https://meeting-server.<tailnet>.ts.net --code <PC配对码>
.venv\Scripts\python.exe -m app.cloud_agent status
```

云代理不再常驻内存：注册一个每 2 分钟执行一次 `run --once` 的计划任务（当前用户任务，无需管理员权限；单实例锁保证不会并发）：

```powershell
powershell -ExecutionPolicy Bypass -File tools\install_agent_task.ps1
```

桌面客户端启动时会额外触发一次检查。卸载计划任务：`powershell -ExecutionPolicy Bypass -File tools\install_agent_task.ps1 -Uninstall`。
手动前台运行调试：`start_agent.bat`。

代理默认条件：空闲满 600 秒、接通电源、CPU ≤ 25%、GPU ≤ 30%、本机没有正在跑的转写任务。每 2 分钟检查一次，条件不满足就直接退出等下一轮。日志在 `data\cloud\agent.log`。

桌面客户端以托盘方式常驻（约 40MB）：关闭工作台窗口会同时停止本地 WebUI 和浏览器应用窗口，释放界面内存；再次双击 `start_client.bat` 只会重新打开工作台，不会重复启动托盘。Ollama 不在客户端启动时拉起，只在生成纪要时按需启动，摘要完成后卸载模型。

## 3. 安装手机 App 并配对

需要 JDK 17 与 Android SDK 35，构建 debug APK：

```bash
cd android
./gradlew assembleDebug
```

产物：`android/app/build/outputs/apk/debug/app-debug.apk`。

用 USB、文件传输或网盘把 APK 传到手机后安装（需要允许“安装未知来源应用”）。debug 签名仅用于测试，正式发布前请配置自己的签名。

在服务器生成手机配对码：

```bash
cd /opt/meeting-notes
sudo -u meeting .venv/bin/python -m server.cli pair-code --role phone
```

打开 App，填写：

- 服务器地址：`https://meeting-server.<tailnet>.ts.net`（不要带端口）
- 配对码、设备名称

配对成功后，手机端即可录音、查看笔记、下载纪要/转写文件和音频（音频受保留策略限制）。

## 4. 验收流程

1. 手机录一段 30 秒以上的音频，停止后等待状态变为“已上传”。
2. 让电脑保持联网、接电源、无人操作满 10 分钟；代理会自动领取任务。
3. 在 `data\cloud\agent.log` 看到“本地转写完成”和“结果已同步”。
4. 手机“笔记”页下拉刷新，能看到新笔记；详情页可查看 Markdown 纪要并下载附件。
5. 电脑端资料库也会同步出现一份归档（`data/library/年/月/日期_类型_主题`）。

临时跳过空闲检查做快速验证（会立即占用本机算力）：

```powershell
.venv\Scripts\python.exe -m app.cloud_agent run --once --force
```

## 5. 日常运维

```bash
# 服务器：队列、设备、磁盘统计
cd /opt/meeting-notes
sudo -u meeting .venv/bin/python -m server.cli stats
sudo -u meeting .venv/bin/python -m server.cli list-devices

# 撤销丢失的手机/电脑
sudo -u meeting .venv/bin/python -m server.cli revoke-device <device_id>

# 手动执行音频保留清理（定时器每天 04:30 也会跑）
sudo -u meeting .venv/bin/python -m server.cli cleanup
```

保留策略：音频最多 5GB、最多 30 天，固定（pinned）的记录不会被自动删除；纪要、逐字稿和元数据永久保留。

## 6. 常见问题

- **手机打不开 /health**：先确认手机 Tailscale 已连接，再在服务器执行 `tailscale serve status`（应有 443 → `127.0.0.1:8000`）；若提示 Serve 未启用，按第 1 节打开启用链接。Windows 上 `nslookup` 会绕过 Tailscale 的分离 DNS，判断解析请用 `curl -v` 或 `Resolve-DnsName`。
- **配对返回 401/410**：配对码过期或已用过，重新生成。
- **上传一直“待上传”**：检查手机网络与 App 是否被系统限制后台；重新打开 App 或点“重试上传”。
- **代理不领任务**：看 `data\cloud\agent.log` 中的“暂不领取任务”原因；默认要求接电源且空闲 10 分钟。
- **代理状态 401**：设备可能被撤销，重新生成 PC 配对码并配对。
- **需要换服务器地址**：重新配对会覆盖本机保存的地址与令牌。

## 7. 安全边界

- 服务只监听回环地址，Tailscale Serve 只发布到 tailnet；未开放 8000 到公网，未改 UFW/安全组。
- 配对码一次性、10 分钟有效；设备令牌按设备独立，可在服务器撤销。
- `data\cloud\agent.json` 含本机设备令牌，不要提交或外传；配对码只显示一次。
- 建议在 Tailscale ACL 中只允许你自己的设备访问该服务，作为纵深防御。
