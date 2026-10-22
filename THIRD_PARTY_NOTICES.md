# Third-Party Notices

本项目以 MIT 许可证发布（见 [LICENSE](LICENSE)）。运行时依赖、模型和平台组件遵循各自的许可证；下表为主要组件，完整清单以实际安装的依赖包元数据为准。

## 本地转写与摘要

| 组件 | 用途 | 许可证 |
|---|---|---|
| [FunASR](https://github.com/modelscope/FunASR) | 语音识别、VAD、标点、说话人分离 | MIT |
| [ModelScope](https://github.com/modelscope/modelscope) | 模型下载与缓存 | Apache-2.0 |
| [PyTorch](https://github.com/pytorch/pytorch) | 推理运行时 | BSD-3-Clause |
| [Ollama](https://github.com/ollama/ollama) | 本地大模型推理 | MIT |
| [Gradio](https://github.com/gradio-app/gradio) | 本机工作台界面 | Apache-2.0 |
| [pywebview](https://github.com/r0x0r/pywebview) | 桌面窗口（可选） | BSD-3-Clause |
| [pythonnet](https://github.com/pythonnet/pythonnet) | pywebview 的 Windows 运行时（可选） | MIT |
| [pystray](https://github.com/moses-palmer/pystray) | 系统托盘 | LGPLv3 |
| [Pillow](https://github.com/python-pillow/Pillow) | 托盘图标处理 | MIT-CMU (HPND) |

FunASR、Ollama 等模型权重不随本仓库分发，首次运行时按需下载；其使用条件以对应模型页面的许可证为准。

## 云端控制面

| 组件 | 用途 | 许可证 |
|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | HTTP API | MIT |
| [Uvicorn](https://github.com/encode/uvicorn) | ASGI 服务器 | BSD-3-Clause |
| [Pydantic](https://github.com/pydantic/pydantic) | 数据校验 | MIT |
| [python-multipart](https://github.com/Kludex/python-multipart) | 分片上传解析 | Apache-2.0 |
| [SQLite](https://sqlite.org/) | 元数据存储 | Public Domain |

## PC 代理与通用库

| 组件 | 用途 | 许可证 |
|---|---|---|
| [httpx](https://github.com/encode/httpx) | HTTP 客户端 | BSD-3-Clause |
| [requests](https://github.com/psf/requests) | HTTP 客户端 | Apache-2.0 |
| [soundfile](https://github.com/bastibe/python-soundfile) | 音频读写 | BSD-3-Clause |
| [NumPy](https://github.com/numpy/numpy) | 数值计算 | BSD-3-Clause |

## Android App

| 组件 | 用途 | 许可证 |
|---|---|---|
| [AndroidX / Jetpack Compose / Material 3](https://developer.android.com/jetpack) | UI 与生命周期 | Apache-2.0 |
| [WorkManager](https://developer.android.com/topic/libraries/architecture/workmanager) | 后台上传调度 | Apache-2.0 |
| [OkHttp](https://github.com/square/okhttp) | 网络与分片上传 | Apache-2.0 |
| [kotlinx.serialization](https://github.com/Kotlin/kotlinx.serialization) | JSON 序列化 | Apache-2.0 |
| [Markwon](https://github.com/noties/Markwon) | Markdown 渲染 | Apache-2.0 |
| [Kotlin](https://kotlinlang.org/) | 开发语言 | Apache-2.0 |

Android 运行环境中的 Google Play Services、Microsoft Edge WebView2 等平台组件不随本仓库分发，遵循各自的服务条款。
