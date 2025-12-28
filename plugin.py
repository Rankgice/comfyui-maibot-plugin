import json
import re
import base64
import random
import time
import asyncio
import aiohttp
import os
import logging
from typing import List, Tuple, Type, Optional, Dict, Any
from src.plugin_system import (
    BasePlugin, register_plugin, BaseAction,
    ComponentInfo, ActionActivationType, ConfigField
)

# 配置日志
logger = logging.getLogger("comfyui_plugin")

# ===== Action组件 =====

class GenerateImageAction(BaseAction):
    """生成图片Action - 调用ComfyUI生成图片"""

    # === 基本信息 ===
    action_name = "generate_image"
    action_description = "根据提示词生成图片"
    activation_type = ActionActivationType.ALWAYS

    # === 功能描述 ===
    action_parameters = {
        "prompt": "生成图片的提示词",
        "image_type": "画图类型: text_to_image (文生图) or image_to_image (图生图)",
        "origin_image": "图生图时用到的原图片的完整描述 (可选)"
    }
    action_require = ["需要生成图片时使用", "用户想要画图时使用"]
    associated_types = ["image", "text"]

    async def execute(self) -> Tuple[bool, str]:
        """执行生成图片动作"""
        logger.info(f"GenerateImageAction Input: message={self.action_message}, data={self.action_data}")


        prompt_text = self.action_data.get("prompt", "")
        if not prompt_text:
            logger.warning("GenerateImageAction: 没有提供提示词")
            return False, "没有提供提示词"

        # 获取参数
        image_type = self.action_data.get("image_type", "text_to_image")
        origin_image = self.action_data.get("origin_image", "")

        # 获取配置
        base_url = self.get_config("comfyui.base_url", "http://127.0.0.1:8000")

        # 如果没有提供图片，尝试从上下文提取 (picid)
        # 逻辑：如果是图生图模式但没图片，或者我们想支持自动检测
        if image_type == "image_to_image":
             # 尝试从 processed_plain_text 提取 picid
            picid = None
            if hasattr(self, 'action_message') and hasattr(self.action_message, 'processed_plain_text'):
                text = getattr(self.action_message, 'processed_plain_text', '')
                match = re.search(r'picid:([a-zA-Z0-9-]+)', text)
                if match:
                    picid = match.group(1)
                    logger.info(f"Extracted picid from context: {picid}")

            if picid:
                # 只有在明确是图生图，或者当前是文生图但我们想自动切换时才处理
                # 这里保留自动切换逻辑
                try:
                    logger.info(f"🗄️ 尝试从数据库获取图片路径...")
                    from src.common.database.database_model import Images
                    image = Images.get_or_none(Images.image_id == picid)
                    if image and hasattr(image, 'path') and image.path:
                        image_path = image.path
                        if os.path.exists(image_path):
                            # 上传图片到 ComfyUI
                            uploaded_filename = await self._upload_image(base_url, image_path)
                            if uploaded_filename:
                                origin_image = uploaded_filename
                                logger.info(f"✅ 成功上传图片, Filename: {uploaded_filename}")
                            else:
                                logger.error("❌ 上传图片失败")
                        else:
                            logger.warning(f"⚠️ 图片文件不存在: {image_path}")
                except Exception as e:
                    logger.error(f"❌ 处理图片失败: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
        
        # 根据类型选择工作流配置
        if image_type == "image_to_image":
            workflow_config_key = "comfyui.image_to_image_workflow"
            default_workflow = "image_to_image_api.json" # 假设默认值
        else:
            workflow_config_key = "comfyui.text_to_image_workflow"
            default_workflow = "text_to_image_z_image_turbo_api.json"

        # 默认只写文件名，代码中处理相对路径
        workflow_filename = "workflow/" + self.get_config(workflow_config_key, default_workflow)

        # 处理相对路径：如果不是绝对路径，则认为是在插件目录下
        if not os.path.isabs(workflow_filename):
            current_dir = os.path.dirname(__file__)
            workflow_file = os.path.join(current_dir, workflow_filename)
        else:
            workflow_file = workflow_filename

        logger.info(f"GenerateImageAction: 开始生成图片, Prompt='{prompt_text}', BaseURL='{base_url}', Workflow='{workflow_file}'")
        await self.send_text(f"正在生成图片，提示词：{prompt_text}，请稍候...")

        try:
            # 1. 加载工作流模板并替换参数
            if not os.path.exists(workflow_file):
                logger.error(f"GenerateImageAction: 工作流文件不存在: {workflow_file}")
                await self.send_text(f"图片生成失败：工作流文件不存在 ({workflow_file})")
                return False, f"工作流文件不存在: {workflow_file}"
            
            logger.debug(f"GenerateImageAction: 正在加载工作流文件: {workflow_file}")
            with open(workflow_file, 'r', encoding='utf-8') as f:
                workflow_template = f.read()

            # 2. 替换 Prompt 和 Seed
            # 生成随机种子
            seed = random.randint(1, 10000000000)
            
            # 执行替换
            # ${prompt} -> json.dumps(prompt_text) 确保转义正确
            # ${seed} -> str(seed)
            workflow_str = workflow_template.replace('"${prompt}"', json.dumps(prompt_text))
            workflow_str = workflow_str.replace('"${seed}"', str(seed))
            
            # 如果是图生图，替换图片
            if image_type == "image_to_image":
                # 假设模板中有 "${image}" 占位符
                # 使用 json.dumps 确保生成的 JSON 格式正确 (包含引号)
                workflow_str = workflow_str.replace('"${image}"', json.dumps(origin_image))
            logger.info(f"GenerateImageAction: 请求工作流: {workflow_str}")
            try:
                workflow = json.loads(workflow_str)
            except json.JSONDecodeError as e:
                logger.error(f"GenerateImageAction: 解析工作流JSON失败: {e}")
                await self.send_text(f"图片生成失败：解析工作流配置失败 ({e})")
                return False, f"解析工作流JSON失败: {e}"

            logger.debug(f"GenerateImageAction: 工作流已准备就绪 (Seed={seed})")

            # 3. 提交任务
            logger.info("GenerateImageAction: 正在提交任务到 ComfyUI...")
            prompt_id = await self._queue_prompt(base_url, workflow)
            if not prompt_id:
                logger.error("GenerateImageAction: 提交任务失败")
                await self.send_text("图片生成失败：提交任务给 ComfyUI 失败，请检查服务器是否正常运行。")
                return False, "提交任务失败"
            
            logger.info(f"GenerateImageAction: 任务提交成功, PromptID={prompt_id}")

            # 4. 轮询状态
            logger.info(f"GenerateImageAction: 开始轮询任务状态, PromptID={prompt_id}")
            image_filename = await self._poll_history(base_url, prompt_id)
            if not image_filename:
                logger.error("GenerateImageAction: 生成失败或超时")
                await self.send_text("图片生成失败：等待结果超时或生成过程中出错。")
                return False, "生成失败或超时"
            
            logger.info(f"GenerateImageAction: 图片生成成功, Filename={image_filename}")

            # 5. 构建图片URL
            image_url = f"{base_url}/view?filename={image_filename}&subfolder=&type=output"
            logger.info(f"GenerateImageAction: 图片URL: {image_url}")
            
            # 发送图片
            if hasattr(self, 'send_image'):
                 try:
                     async with aiohttp.ClientSession() as session:
                         async with session.get(image_url) as resp:
                             if resp.status == 200:
                                 image_data = await resp.read()
                                 base64_image = base64.b64encode(image_data).decode('utf-8')
                                 await self.send_image(base64_image)
                             else:
                                 logger.error(f"GenerateImageAction: 下载图片失败, Status={resp.status}")
                                 await self.send_text(f"图片生成成功，但下载失败：{image_url}")
                 except Exception as e:
                     logger.error(f"GenerateImageAction: 处理图片失败: {e}")
                     await self.send_text(f"图片生成成功：{image_url}")
            else:
                 await self.send_text(f"图片生成成功：{image_url}")

            return True, f"成功生成图片: {image_filename}"

        except Exception as e:
            logger.exception(f"GenerateImageAction: 发生未捕获异常: {e}")
            await self.send_text(f"图片生成失败：发生内部错误 ({str(e)})")
            return False, f"发生错误: {str(e)}"


    async def _queue_prompt(self, base_url: str, workflow: Dict[str, Any]) -> Optional[str]:
        """提交任务到 ComfyUI"""
        url = f"{base_url}/prompt"
        payload = {"prompt": workflow}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("prompt_id")
                    else:
                        logger.error(f"Queue Prompt Failed: Status={resp.status}, Body={await resp.text()}")
        except Exception as e:
            logger.error(f"Queue Prompt Exception: {e}")
        return None

    async def _poll_history(self, base_url: str, prompt_id: str, timeout: int = 60) -> Optional[str]:
        """轮询历史记录获取结果"""
        start_time = time.time()
        url = f"{base_url}/history/{prompt_id}"
        
        async with aiohttp.ClientSession() as session:
            while time.time() - start_time < timeout:
                try:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            history = await resp.json()
                            if prompt_id in history:
                                logger.info(f"Poll History: Found history for {prompt_id}")
                                return self._extract_filename(history[prompt_id])
                        else:
                            logger.warning(f"Poll History: Status={resp.status}")
                except Exception as e:
                    logger.error(f"Poll History Exception: {e}")
                
                await asyncio.sleep(1)
        
        logger.error(f"Poll History: Timeout after {timeout}s")
        return None

    async def _upload_image(self, base_url: str, image_path: str, subfolder: str = "temp", overwrite: bool = True) -> Optional[str]:
        """上传图片到 ComfyUI"""
        url = f"{base_url}/upload/image"
        try:
            filename = os.path.basename(image_path)
            import mimetypes
            content_type, _ = mimetypes.guess_type(image_path)
            if not content_type:
                content_type = 'image/png'
                
            data = aiohttp.FormData()
            data.add_field('image',
                           open(image_path, 'rb'),
                           filename=filename,
                           content_type=content_type)
            data.add_field('subfolder', subfolder)
            data.add_field('overwrite', str(overwrite).lower())

            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if 'name' in result:
                            return subfolder + "/" + result['name']
                        else:
                            logger.error(f"Upload Image: No name in response: {result}")
                    else:
                        logger.error(f"Upload Image Failed: Status={resp.status}, Body={await resp.text()}")
        except Exception as e:
            logger.error(f"Upload Image Exception: {e}")
        return None

    def _extract_filename(self, task_data: Dict[str, Any]) -> Optional[str]:
        """从历史记录中提取文件名"""
        try:
            outputs = task_data.get("outputs", {})
            for node_id, node_output in outputs.items():
                if "images" in node_output:
                    for img in node_output["images"]:
                        if "filename" in img:
                            return img["filename"]
        except Exception as e:
            logger.error(f"Extract Filename Exception: {e}")
        return None

@register_plugin
class ComfyUIPlugin(BasePlugin):
    """ComfyUI 插件 - 集成 ComfyUI 图片生成"""

    # 插件基本信息
    plugin_name = "comfyui_plugin"
    enable_plugin = True
    dependencies = []
    python_dependencies = ["aiohttp"]
    config_file_name = "config.toml"

    # 配置Schema定义
    config_schema = {
        "comfyui": {
            "base_url": ConfigField(type=str, default="http://127.0.0.1:8000", description="ComfyUI 服务器地址"),
            "text_to_image_workflow": ConfigField(type=str, default="text_to_image_z_image_turbo_api.json", description="文生图工作流文件路径 (相对插件目录或绝对路径)"),
            "image_to_image_workflow": ConfigField(type=str, default="image_to_image_api.json", description="图生图工作流文件路径 (相对插件目录或绝对路径)"),
        }
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        return [
            (GenerateImageAction.get_action_info(), GenerateImageAction),
        ]
