# ComfyUI Plugin

## 简介
这是一个用于集成 ComfyUI 图片生成能力的插件。通过此插件，用户可以通过对话发送提示词，调用本地或远程的 ComfyUI 服务生成图片。

## 功能特性
- **文生图**: 支持通过提示词生成图片。
- **图生图**: 支持基于原图和提示词生成新的图片。
- **自定义工作流**: 支持加载外部 ComfyUI 工作流 JSON 文件。
- **自动参数替换**: 自动替换工作流中的 `${prompt}` (提示词)、`${seed}` (随机种子) 和 `${image}` (原图路径)。
- **异步处理**: 使用异步 HTTP 请求与 ComfyUI 交互，确保高效响应。

## 安装与依赖

### Python 依赖
插件运行需要以下 Python 库：
- `aiohttp`

### ComfyUI 环境
你需要有一个正在运行的 ComfyUI 实例。
1. 确保 ComfyUI 已启动并可以访问（默认地址 `http://127.0.0.1:8000`）。
2. 准备 API 格式的工作流文件（JSON 格式）。

## 配置说明
插件支持通过配置文件（如 `config.toml`）进行如下设置：

| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- |:---|
| `comfyui.base_url` | string | `http://127.0.0.1:8000` | ComfyUI 服务器的基础 URL |
| `comfyui.text_to_image_workflow` | string | `text_to_image_z_image_turbo_api.json` | 文生图工作流文件路径。在 `workflow/` 目录下。 |
| `comfyui.image_to_image_workflow` | string | `image_to_image_api.json` | 图生图工作流文件路径。在 `workflow/` 目录下。 |

## 工作流准备指南
为了让插件能够动态修改提示词、随机种子和输入图片，你需要对 ComfyUI 导出的 API JSON 文件进行微调：

1. **导出 API 格式工作流**: 在 ComfyUI 界面设置中开启 "Enable Dev mode Options"，然后点击 "Save (API Format)" 按钮导出 JSON。
2. **添加占位符**:
    - **提示词**: 找到输入提示词的节点（例如 `CLIPTextEncode`），将其 `text` 字段的值修改为 `"${prompt}"`。
    - **随机种子**: 找到控制随机种子的节点（例如 `KSampler`），将其 `seed` 字段的值修改为 `"${seed}"`。
    - **输入图片 (仅图生图)**: 找到加载图片的节点（例如 `LoadImage`），将其 `image` 字段的值修改为 `"${image}"`。

**示例片段**:
```json
"6": {
  "inputs": {
    "text": "${prompt}",
    "clip": [ "5", 0 ]
  },
  "class_type": "CLIPTextEncode"
},
"3": {
  "inputs": {
    "seed": "${seed}",
    "steps": 20,
    "cfg": 8,
    "sampler_name": "euler",
    "scheduler": "normal",
    "denoise": 1,
    "model": [ "4", 0 ],
    "positive": [ "6", 0 ],
    "negative": [ "7", 0 ],
    "latent_image": [ "5", 0 ]
  },
  "class_type": "KSampler"
},
"10": {
  "inputs": {
    "image": "${image}",
    "upload": "image"
  },
  "class_type": "LoadImage"
}
```

## 使用方法
插件加载成功后，可以通过自然语言指令触发图片生成，例如：

**文生图**:
- "帮我画一张赛博朋克风格的城市夜景"
- "生成图片：一只在草地上奔跑的柯基"

**图生图**:
- "把这张图变成素描风格" (需引用一张图片)
- "参考这张图生成类似的动漫角色"

## 目录结构
```
comfyui_plugin/
├── plugin.py           # 插件核心逻辑代码
├── _manifest.json      # 插件元数据定义
├── workflow/           # 存放工作流文件的目录
│   ├── text_to_image_z_image_turbo_api.json # 默认文生图工作流
│   └── image_to_image_api.json              # 默认图生图工作流
└── README.md           # 项目说明文档
```
