# FlowHMR2Warudo

**以FlowHMR为核心动作模型、面向Warudo的实时动作捕捉工程。**

输入电脑摄像头、DroidCam或视频，通过人物检测、身体感知和FlowHMR动作求解，输出VMC动作到Warudo。当前发布Windows本地源码版。

本项目的工程工作集中在Warudo接入、原生控制界面、输入与传输、低开销监控、运行生命周期管理及推理优化。FlowHMR模型、视觉组件、复用的实时运行代码与本项目新增功能是不同层次，具体见[架构与工程改造](docs/ARCHITECTURE.md)。

此仓库是可安装的源码发行版，不是自带环境的便携整合包。**不包含 Python、venv、已安装依赖、FFmpeg可执行文件、模型权重或个人配置。** 当前文档与启动脚本面向 Windows 本机推理；不宣称提供完整 Linux 服务端部署。

## 功能

- 原生桌面控制窗口，不必运行浏览器；关闭窗口同步结束本程序后台，不关闭Warudo。
- 视频选择及预处理、摄像头检测与选择（包括DroidCam兼容处理）。
- 固定首帧预览、5秒数字监控，减少渲染开销；本机画面直传。
- 目标20/25/30 FPS、SAM间隔、身体/手部层数、Flow步数、检测尺寸和手部模式。
- 延迟预算200/300/400/500/600/700/800/1000ms，SAM批次1/2。
- 保留torch.compile、Fast SAM优化和Flow CUDA Graph路径。低延迟选项不是性能保证。

## 环境与安装（自行配置）

面向熟悉Python和CUDA的用户。仓库不创建或附带环境；可以使用venv、Conda或其他环境管理工具。以下命令在你选定并激活的环境内执行，推荐 **Python 3.12 x64 / Windows 10或11 / NVIDIA CUDA GPU**。

### 1. 系统依赖

- NVIDIA驱动需支持CUDA 12.8，使用PyTorch官方cu128 wheel。
- Python需包含Tcl/Tk（原生GUI使用tkinter）。
- 自行安装FFmpeg，确保 `ffmpeg` 和 `ffprobe` 在PATH；也支持自行放到 `tools/bin/`。
- 8GB显卡可尝试低负载，实时性取决于GPU、参数和Warudo的渲染负担，不承诺固定帧率。

### 2. Python依赖

```powershell
# 先自行创建并激活环境，然后在仓库根目录执行：
python -m pip install --upgrade pip
python -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
python -m pip install -r requirements.txt
python -m pip check
python scripts/check_environment.py
```

`requirements.txt`包含应用额外依赖，并以editable方式安装 `engine/pyproject.toml` 中的引擎依赖；`constraints.txt`约束已验证的Torch、Triton、NumPy、OpenCV、WebSocket和PyAV版本。
不要把CUDA版Torch安装步骤省略后误装成CPU版。环境不必叫 `.venv`，启动器使用当前Python，后台也使用同一解释器。

### 3. 模型

见 [模型说明](docs/MODELS.md)。可复制已有整合包的 `engine/models`，或在当前环境运行：

```powershell
python scripts/download_models.py
```

下载需要联网及相应模型访问权限；应用运行阶段默认只使用本机通信。

## 运行

先在Warudo加载已经配置VMC接收的角色，通常UDP `127.0.0.1:39539`，再在激活的环境中运行：

```powershell
python -I portable_entry.py client/native_app.py
```

- 选择视频，或刷新摄像头列表后选择设备；点击「开始输出到 Warudo」。
- 调参必须停止采集 → 修改 → 应用参数 → 重新开始。
- 关闭GUI会停止其采集/转发/后台，不结束Warudo；异常后台可执行 `powershell -ExecutionPolicy Bypass -File stop_local.ps1`，仅匹配当前仓库入口启动的Python进程。
- 固定首帧预览、5秒刷新数字是刻意的低开销设计。
- `start.cmd`只是同一命令的快捷入口，请从已激活环境的终端执行；不是自动环境安装器。

参数说明见 [参数与运行说明](docs/USAGE.md)。

## 参数起点

先用800ms延迟、SAM批次2。电脑跟不上时可点「8GB低负载」，必要时再改20FPS。
更低延迟可能增加欠载；700ms/批次1可逐步尝试，但不保证任意设备稳定。不要一次把精度参数拉满。

## 开发与测试

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest engine/tests
python -m unittest discover -s tests
```

本次源码适配的检查与边界见 [验证说明](docs/VALIDATION.md)。新电脑仍需检查驱动、FFmpeg、模型及实际Warudo效果；未声称在干净机器上完成全新下载验收。

## 隐私

首次运行在本机生成通信令牌。`state/`、摄像头/视频、日志、缓存与权重均被git忽略。分享诊断前仍应自行检查。

## 核心模型与许可

核心动作模型是 [FlowHMR](https://github.com/flowhmr/flowhmr)。身体感知使用SAM 3D Body及Fast SAM适配，实时人物检测使用YOLO26m；FlowHMR2Warudo负责面向Warudo的应用集成与工程改造。

仓库代码继续按 [AGPL-3.0](LICENSE) 发布；这不是对所有依赖和模型的统一重新授权。第三方代码、已修改的复用组件和模型各自的来源及许可集中记录于 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，原有许可与版权声明保留。

本仓库不分发模型权重。模型的获取、使用及分发须遵守对应来源的条款。
