# Third-Party Notices

本项目源码以 MIT 许可证发布（见 [LICENSE](LICENSE)）。第三方组件继续遵循各自的许可证；本文件列出与分发和再发布相关的重点组件。

## 仓库内直接包含的第三方作品

| 作品 | 位置 | 许可证 | 说明 |
|---|---|---|---|
| Gradle Wrapper（`gradle-wrapper.jar`、`gradlew`、`gradlew.bat`） | `android/` | Apache-2.0 | Copyright Gradle Inc.；许可证全文见 [licenses/Apache-2.0.txt](licenses/Apache-2.0.txt)，NOTICE 见 [licenses/Gradle-NOTICE.txt](licenses/Gradle-NOTICE.txt) |
| Material Design `mic` 图标路径 | `android/app/src/main/res/drawable/ic_mic.xml`、`ic_launcher_foreground.xml` | Apache-2.0 | Copyright Google LLC；来自 [Material Icons](https://github.com/google/material-design-icons)，许可证全文见 [licenses/Apache-2.0.txt](licenses/Apache-2.0.txt) |

上述文件保留其原始许可证，不被本项目的 MIT 许可证重新授权。`assets/` 下的应用图标为本项目自绘资源。

## 运行时依赖（由包管理器安装，未随仓库分发）

### 本地转写与摘要

| 组件 | 用途 | 许可证 |
|---|---|---|
| [FunASR](https://github.com/modelscope/FunASR) | 语音识别、VAD、标点、说话人分离 | MIT |
| FunASR 模型（SeACo-Paraformer、FSMN-VAD、CT-Punc、CAM++） | 中文转写与说话人分离权重 | Apache-2.0（模型 README 声明） |
| [ModelScope](https://github.com/modelscope/modelscope) | 模型下载与缓存 | Apache-2.0 |
| [PyTorch](https://github.com/pytorch/pytorch) / torchaudio | 推理运行时 | BSD-3-Clause |
| [Ollama](https://github.com/ollama/ollama) | 本地大模型推理 | MIT |
| Qwen3.5-9B / Qwen3.5-4B 权重 | 默认摘要模型 | Apache-2.0（ModelScope 模型页与模型内置 LICENSE） |
| [Gradio](https://github.com/gradio-app/gradio) | 本机工作台界面 | Apache-2.0 |
| [pywebview](https://github.com/r0x0r/pywebview) | 桌面窗口（可选） | BSD-3-Clause |
| [pythonnet](https://github.com/pythonnet/pythonnet) | pywebview 的 Windows 运行时（可选） | MIT |
| [pystray](https://github.com/moses-palmer/pystray) | 系统托盘 | **LGPLv3** |
| [Pillow](https://github.com/python-pillow/Pillow) | 托盘图标处理 | MIT-CMU (HPND) |
| [librosa](https://github.com/librosa/librosa) | FunASR 音频特征 | ISC |
| [soxr](https://github.com/dofuuz/python-soxr) | 重采样（librosa 依赖） | **LGPL-2.1-or-later** |
| [certifi](https://github.com/certifi/python-certifi) | CA 证书包 | MPL-2.0 |
| [tqdm](https://github.com/tqdm/tqdm) | 进度显示 | MPL-2.0 AND MIT |
| [orjson](https://github.com/ijl/orjson) | JSON 序列化 | MPL-2.0 AND (Apache-2.0 OR MIT) |

FunASR、Qwen 等模型权重不随本仓库分发，首次运行时按需下载。重新分发权重时，需同时保留对应的 Apache-2.0 许可证与 NOTICE。

### 云端控制面

| 组件 | 用途 | 许可证 |
|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | HTTP API | MIT |
| [Uvicorn](https://github.com/encode/uvicorn) | ASGI 服务器 | BSD-3-Clause |
| [Pydantic](https://github.com/pydantic/pydantic) | 数据校验 | MIT |
| [python-multipart](https://github.com/Kludex/python-multipart) | 分片上传解析 | Apache-2.0 |
| [SQLite](https://sqlite.org/) | 元数据存储 | Public Domain |

### Android

| 组件 | 用途 | 许可证 |
|---|---|---|
| [AndroidX / Jetpack Compose / Material 3](https://developer.android.com/jetpack) | UI 与生命周期 | Apache-2.0 |
| [WorkManager](https://developer.android.com/topic/libraries/architecture/workmanager) | 后台上传调度 | Apache-2.0 |
| [OkHttp](https://github.com/square/okhttp) | 网络与分片上传 | Apache-2.0 |
| [kotlinx.serialization](https://github.com/Kotlin/kotlinx.serialization) | JSON 序列化 | Apache-2.0 |
| [Markwon](https://github.com/noties/Markwon) | Markdown 渲染 | Apache-2.0 |
| [Kotlin](https://kotlinlang.org/) | 开发语言 | Apache-2.0 |
| [JUnit 4](https://github.com/junit-team/junit4) | 单元测试（仅测试配置） | EPL-1.0 |

### 外部程序

| 程序 | 说明 |
|---|---|
| [FFmpeg](https://ffmpeg.org/) | 本项目通过 `subprocess` 调用用户自行安装的 `ffmpeg` 可执行文件，不随仓库或安装包分发。用户机器上的 GPL 构建（如 `--enable-gpl --enable-version3`）仍受其自身许可证约束。 |

## 分发时的合规要点

- **pystray（LGPLv3）**：源码以动态 `import` 使用，未修改、未随仓库分发，因此本项目代码可继续使用 MIT。若将来打包成独立 EXE 或安装包，需要附上 LGPLv3 文本、提供 pystray 源码或书面获取方式，并允许用户替换该库。
- **soxr（LGPL-2.1-or-later）**：由 FunASR → librosa 间接安装，当前同样未随仓库分发。若打包二进制，需要满足 LGPL-2.1 的替换与源码提供要求。
- **FFmpeg（可能是 GPL）**：仅以独立进程方式调用，不链接其代码，因此不构成衍生作品。若将来随安装包分发 FFmpeg，需改用合规的 LGPL 构建，或按 GPL 要求提供完整对应源码与许可证。
- **Apache-2.0 组件**：仓库内直接包含的 Gradle Wrapper 和 Material 图标已附 Apache-2.0 全文与 Gradle NOTICE；再发布时请保留这些文件。
- **模型权重**：本仓库不包含任何模型权重。再发布 Qwen 或 FunASR 权重时，需保留 Apache-2.0 许可证与相关 NOTICE。
- **MPL-2.0 组件**（certifi、tqdm、orjson）：以未修改的依赖形式使用；若修改其源码并分发，需公开对应文件的修改。

## 完整性说明

本表覆盖直接依赖和已确认的重点传递依赖。发布二进制安装包前，建议额外运行：

```bash
pip install pip-licenses
pip-licenses --format=markdown --with-urls
```

Android 端可使用 Gradle 的依赖许可报告插件生成完整清单。当前仓库只分发源码，Python 与 Maven 依赖由用户环境安装。
