# 模型准备

仓库不包含权重。请先阅读并遵守各模型的许可及访问条款。

## 方法一：复用已有整合包

把整合包的整个 `engine/models` 文件夹复制到本仓库的 `engine/models`。不要复制 `state`、`runtime` 或 `client/receiver.json`。

## 方法二：下载

激活自己的环境后运行 `python scripts/download_models.py`。此步骤联网，应用启动后只使用本机通信。
FlowHMR 使用 Hugging Face 的 `FlowHMR/FlowHMR`；SAM使用 `facebook/sam-3d-body-dinov3`（上游工具支持ModelScope源）；YOLO26m由Ultralytics工具下载。
若访问需要账户或同意条款，请自行完成；可在自己的终端设置 `HF_TOKEN` 后运行下载脚本，不要提交令牌。
网络、模型源或接口变动可能导致下载失败；也可按方法一复制已验证模型。

需要的结构：
```
engine/models/
  motion_stats.json
  smpl_neutral_J_regressor.pt
  flowhmr_latest/config.yml
  flowhmr_latest/flowhmr_latest.ckpt
  sam-3d-body-dinov3/model.ckpt
  sam-3d-body-dinov3/model_config.yaml
  sam-3d-body-dinov3/assets/mhr_model.pt
  yolo26m/yolo26m.pt
  yolox/yolox_l.pth
```

Fast SAM 与 MHR 资产有接口兼容要求。如果出现 MHR asset interface mismatch，请核对模型版本，不要修改模型文件来绕过检查。YOLOX为原引擎工具保留，实时适配器使用YOLO26m。
