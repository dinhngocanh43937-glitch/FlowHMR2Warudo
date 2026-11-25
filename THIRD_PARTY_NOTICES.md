# 来源与许可说明

## 1. FlowHMR2Warudo：应用工程与发布许可

FlowHMR2Warudo是面向Warudo的实时动作捕捉工程，核心动作求解使用FlowHMR，并结合身体感知、人物检测、输入处理和VMC输出。

本项目的新增与改造工作包括原生控制UI、Warudo接入与转发、摄像头/视频输入及设备选择、视频预处理、本机帧直传、固定首帧预览、低频数字监控、停止与退出管理、参数持久化、目标FPS、延迟预算/SAM批次控制，以及Windows推理优化的适配与集成。它们构成当前应用的工程功能，不代表对上游算法、模型或所有底层组件的原创声明。

本仓库继续使用根目录的[GNU AGPL v3许可证](LICENSE)。原有第三方许可、版权和附加许可声明保持其各自适用范围；本说明不改变它们。

## 2. 核心动作模型：FlowHMR

- 官方项目：https://github.com/flowhmr/flowhmr
- 仓库位置：`engine/vendor/flowhmr/`
- 所含代码许可：Apache-2.0，见[随附原文](engine/vendor/flowhmr/LICENSE)。
- 用途：动作模型、相关网络与推理工具；本项目将其用于实时窗口动作求解。
- 部分随附工具已有实时适配修改，详见[原组件说明](engine/THIRD_PARTY_LICENSES.md)。
- 权重不随此源码仓库分发，下载后按其自身条款使用。

## 3. 视觉感知与检测

| 组件 | 用途 | 随附许可/来源 |
|---|---|---|
| SAM 3D Body | 单帧身体感知 | [Meta SAM许可](engine/vendor/sam-3d-body/LICENSE)，https://github.com/facebookresearch/sam-3d-body |
| DINOv3 | 视觉主干 | [DINOv3许可](engine/vendor/dinov3/LICENSE.md)，https://github.com/facebookresearch/dinov3 |
| Fast SAM 3D Body | SAM推理加速实现与适配基础 | [随附MIT许可](server/fastsam_runtime/fast_impl/vendor/LICENSE)及文件中的Meta声明，https://github.com/yangtiming/Fast-SAM-3D-Body |
| Ultralytics / YOLO26m | 实时人物检测 | [随附AGPL许可](third-party/Fast-SAM-20261124/licenses/Ultralytics-AGPL-3.0.txt)，通过requirements安装；权重单独准备 |
| YOLOX | 原引擎相关检测工具 | [Apache-2.0](engine/vendor/YOLOX/LICENSE)，https://github.com/Megvii-BaseDetection/YOLOX |

Fast SAM来源版本及适配记录见[交接来源记录](third-party/Fast-SAM-20261124/provenance.json)。MIT说明不替代相关Meta代码和模型的条款。

## 4. 实时运行代码的复用与改造

`engine/src/persona_flowhmr/`及配套测试包含来自[laplace-live/persona-flowhmr](https://github.com/laplace-live/persona-flowhmr)的代码及后续改造，包括实时窗口组织、动作拼接、播放和VMC相关实现。该组件是实时运行代码来源，不是FlowHMR核心模型的原创来源，也不代表本项目UI、输入、部署和优化工作的全部来源。

保留`persona_flowhmr`内部包名用于兼容现有导入，不表示运行时依赖安装或打开Persona应用。本项目当前面向Warudo。

该部分原代码按AGPL-3.0发布；原有第三方模型与视觉运行时附加许可说明见[完整原声明](engine/THIRD_PARTY_LICENSES.md)。本次文档调整不删除或扩大原版权方授予的权限。

## 5. 第三方运行依赖与模型

Python包由用户在自己的环境中安装，许可依各包自身声明。FFmpeg由用户自行安装，未把其可执行文件加入此源码仓库。

模型权重、Python运行时、venv、原视频、录屏、个人配置、令牌与缓存不随此源码发行版上传。历史交接资料如描述了权重或环境打包，指的是当时的交接产物，不是当前GitHub源码发行版。
