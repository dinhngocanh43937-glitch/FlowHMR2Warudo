# 架构与工程改造

## 数据路径

```
摄像头 / DroidCam / 视频
    → client：采集、设备选择、视频准备、本机帧传输
    → server：输入队列、会话控制、检测与推理适配
    → YOLO26m + SAM 3D Body / Fast SAM
    → FlowHMR：窗口动作求解
    → 动作拼接与播放
    → VMC动作转发 → Warudo
```

## 本项目工程层

- `client/native_app.py`：原生控制界面，参数设置及开始/停止/退出管理。
- `client/media_tools.py`等：视频准备、摄像头枚举及兼容处理。
- `client/local_frames.py`与`server/local_frames.py`：本机帧直传，降低重复编码开销。
- `server/backend.py`等：本地服务、动作桥接、会话控制和参数持久化。
- `server/fastsam_runtime/`：Fast SAM集成及裁剪、提示缓存、稀疏反馈等优化适配；内部vendor代码有独立来源。
- `server/cuda_graphs.py`、`cached_solver.py`等：Flow求解路径的运行优化。
- `server/frame_rate_adapter.py`：目标帧率与引擎采样契约适配。
- 固定首帧预览、低频数字监控，减少与Warudo竞争的显示负担。

上述条目描述本项目集成及修改的功能边界，不把引用的模型、第三方优化思路或vendor实现归为本项目原创。

## 模型与复用运行组件

FlowHMR承担核心动作模型与求解。SAM/DINO承担身体与视觉感知，YOLO承担人物检测。
`engine/src/persona_flowhmr`保留并改造了已有的实时窗口、拼接和播放运行代码。文件夹名保留用于导入兼容；这是实现来源说明，不是应用品牌定位。

整体定位是FlowHMR驱动的Warudo应用工程，而非单独发布一个模型算法，也不宣称所有代码均从零实现。组件来源与许可见[第三方说明](../THIRD_PARTY_NOTICES.md)。
