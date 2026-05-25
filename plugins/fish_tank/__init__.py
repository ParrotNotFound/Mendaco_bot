from nonebot import get_plugin_config, on_command, on_message, get_driver
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import (
    Message, 
    MessageEvent, 
    GroupMessageEvent, 
    PrivateMessageEvent,
    MessageSegment
)
from nonebot.params import CommandArg, EventPlainText
from nonebot.log import logger
import random
import time
import json
import math
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any, Set
from pathlib import Path
import os
import io
import hashlib
import base64
from PIL import Image, ImageDraw, ImageFilter
import numpy as np
from collections import defaultdict

from .config import TankConfig

__plugin_meta__ = PluginMetadata(
    name="群聊鱼缸",
    description="每个群聊的独立鱼缸，可以添加鱼并查看鱼缸",
    usage="""
添加鱼: /add_fish <单条价值> <加入个数>
查看鱼缸: /tank
清理过期鱼: /clean_tank
鱼缸帮助: /tank_help
""",
    config=TankConfig,
)

config = get_plugin_config(TankConfig)

# 导入coin插件
from nonebot import require
require("plugins.coin")
from plugins.coin import consume_coins, get_coins, get_user_info

# 导入文件编辑器插件
require("plugins.file_edit")
from plugins.file_edit import (
    read_file,
    write_file,
    safe_path,
    plugin_dir
)

# 导入rembg进行抠图
try:
    from rembg import remove, new_session
    REMBG_AVAILABLE = True
except ImportError:
    logger.warning("rembg未安装，抠图功能将不可用")
    REMBG_AVAILABLE = False
    remove = None
    new_session = None

# 初始化目录结构
def init_directories():
    """初始化鱼缸插件所需的目录"""
    # 创建鱼缸数据目录
    data_dir = safe_path(config.tank_data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建鱼图片目录
    images_dir = safe_path(config.fish_images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建静态资源目录
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    
    # 如果不存在默认鱼缸背景，创建一个
    tank_bg_path = static_dir / "tank.png"
    if not tank_bg_path.exists():
        # 创建默认的淡蓝色背景
        bg_color = config.default_tank_color
        bg_size = config.default_tank_size
        
        bg_image = Image.new('RGB', bg_size, bg_color)
        
        # 添加一些装饰
        draw = ImageDraw.Draw(bg_image)
        
        # 画水波效果
        for i in range(5):
            y = bg_size[1] - 50 - i * 20
            draw.ellipse([(0, y), (bg_size[0], y + 40)], 
                        fill=(bg_color[0]-20, bg_color[1]-20, bg_color[2]-20), 
                        outline=(bg_color[0]-30, bg_color[1]-30, bg_color[2]-30))
        
        # 保存
        bg_image.save(tank_bg_path)
        logger.info(f"已创建默认鱼缸背景: {tank_bg_path}")

init_directories()

# 辅助函数
def get_user_id(event: MessageEvent) -> str:
    """获取用户ID"""
    return str(event.get_user_id())

def get_group_id(event: MessageEvent) -> Optional[str]:
    """获取群组ID（如果是群消息）"""
    if isinstance(event, GroupMessageEvent):
        return str(event.group_id)
    return None

def get_group_file_path(group_id: str) -> Path:
    """获取群鱼缸数据文件路径"""
    tank_file = safe_path(f"{config.tank_data_dir}/group_{group_id}.json")
    return tank_file

def get_fish_image_path(group_id: str, fish_id: str) -> Path:
    """获取鱼图片路径"""
    # 为每个群创建独立的图片目录
    group_images_dir = safe_path(f"{config.fish_images_dir}/group_{group_id}")
    group_images_dir.mkdir(parents=True, exist_ok=True)
    
    return group_images_dir / f"{fish_id}.png"

def load_tank_data(group_id: str) -> Dict:
    """加载群鱼缸数据"""
    tank_file = get_group_file_path(group_id)
    
    if not tank_file.exists():
        # 返回默认数据
        return {
            "group_id": group_id,
            "fishes": [],  # 鱼列表
            "total_fish_count": 0,  # 历史总鱼数
            "current_fish_count": 0,  # 当前有效鱼数
            "created_time": datetime.now().isoformat(),
            "updated_time": datetime.now().isoformat()
        }
    
    try:
        data = read_file(str(tank_file))
        if data:
            tank_data = json.loads(data)
            # 确保有所有必需字段
            tank_data.setdefault("group_id", group_id)
            tank_data.setdefault("fishes", [])
            tank_data.setdefault("total_fish_count", 0)
            tank_data.setdefault("current_fish_count", 0)
            tank_data.setdefault("created_time", datetime.now().isoformat())
            tank_data.setdefault("updated_time", datetime.now().isoformat())
            return tank_data
    except Exception as e:
        logger.error(f"加载鱼缸数据失败: {e}")
    
    # 返回默认数据
    return {
        "group_id": group_id,
        "fishes": [],
        "total_fish_count": 0,
        "current_fish_count": 0,
        "created_time": datetime.now().isoformat(),
        "updated_time": datetime.now().isoformat()
    }

def save_tank_data(group_id: str, data: Dict) -> bool:
    """保存群鱼缸数据"""
    try:
        tank_file = get_group_file_path(group_id)
        data["updated_time"] = datetime.now().isoformat()
        write_file(str(tank_file), json.dumps(data, ensure_ascii=False, indent=2))
        return True
    except Exception as e:
        logger.error(f"保存鱼缸数据失败: {e}")
        return False

def calculate_fish_lifetime(value: int) -> Tuple[float, float]:
    """
    计算鱼的保存时间（小时）
    公式: ((value)^0.5) * 24 ± 16 小时
    
    返回: (最小保存时间, 最大保存时间)
    """
    base_time = math.sqrt(value) * 24
    min_time = max(1, base_time - 16)  # 至少1小时
    max_time = base_time + 16
    
    return min_time, max_time

def generate_fish_expire_time(value: int) -> datetime:
    """
    生成鱼的过期时间
    在计算出的时间范围内随机
    """
    min_hours, max_hours = calculate_fish_lifetime(value)
    lifetime_hours = random.uniform(min_hours, max_hours)
    
    expire_time = datetime.now() + timedelta(hours=lifetime_hours)
    return expire_time

def remove_background(image_bytes: bytes) -> Optional[Image.Image]:
    """
    使用rembg移除图片背景
    
    参数:
        image_bytes: 图片字节数据
    
    返回:
        移除背景后的PIL Image对象，或None
    """
    if not REMBG_AVAILABLE or remove is None:
        logger.error("rembg不可用，无法移除背景")
        return None
    
    try:
        # 移除背景
        output_bytes = remove(
            image_bytes,
            alpha_matting=True,
            alpha_matting_foreground_threshold=240,
            alpha_matting_background_threshold=10
        )
        
        # 转换为PIL Image
        result_image = Image.open(io.BytesIO(output_bytes))
        
        return result_image
    except Exception as e:
        logger.error(f"移除背景失败: {e}")
        return None

def clean_expired_fishes(tank_data: Dict) -> Tuple[List[Dict], List[Dict], int]:
    """
    清理过期鱼
    
    参数:
        tank_data: 鱼缸数据
        
    返回:
        (有效鱼列表, 过期鱼列表, 清理的鱼数量)
    """
    current_time = datetime.now()
    expired_fishes = []
    valid_fishes = []
    
    for fish in tank_data.get("fishes", []):
        try:
            expire_time = datetime.fromisoformat(fish.get("expire_time", ""))
            if expire_time > current_time:
                valid_fishes.append(fish)
            else:
                expired_fishes.append(fish)
        except Exception:
            # 如果时间格式错误，视为有效
            valid_fishes.append(fish)
    
    # 返回结果
    expired_count = len(expired_fishes)
    return valid_fishes, expired_fishes, expired_count

def pil_to_base64(pil_image: Image.Image, format: str = 'PNG') -> str:
    """
    将PIL图片转换为base64字符串
    
    参数:
        pil_image: PIL图片对象
        format: 图片格式
    
    返回:
        base64编码的图片字符串
    """
    img_byte_arr = io.BytesIO()
    pil_image.save(img_byte_arr, format=format)
    img_byte_arr.seek(0)
    img_bytes = img_byte_arr.getvalue()
    
    # 转换为base64字符串
    base64_str = base64.b64encode(img_bytes).decode('utf-8')
    return f"base64://{base64_str}"

# 等待状态的用户
waiting_users: Dict[str, Dict] = {}  # key: user_id, value: 等待状态信息

# 命令处理器
add_fish_cmd = on_command("add_fish", aliases={"加鱼", "添加鱼"}, priority=5, block=True)
tank_cmd = on_command("tank", aliases={"鱼缸", "查看鱼缸"}, priority=5, block=True)
clean_tank_cmd = on_command("clean_tank", aliases={"清理鱼缸", "清理"}, priority=5, block=True)
tank_help_cmd = on_command("tank_help", aliases={"鱼缸帮助"}, priority=5, block=True)

@add_fish_cmd.handle()
async def handle_add_fish(event: GroupMessageEvent, args: Message = CommandArg()):
    """处理添加鱼命令"""
    if not REMBG_AVAILABLE:
        await add_fish_cmd.finish("❌ 鱼缸插件功能不完整，无法处理图片背景移除")
    
    user_id = get_user_id(event)
    group_id = get_group_id(event)
    
    if not group_id:
        await add_fish_cmd.finish("❌ 此功能仅在群聊中可用")
    
    # 检查用户是否已经在等待状态
    if user_id in waiting_users:
        await add_fish_cmd.finish("❌ 您已有一个添加鱼的请求在处理中，请先完成或等待超时")
    
    # 解析参数
    arg_text = args.extract_plain_text().strip().split()
    if len(arg_text) < 2:
        await add_fish_cmd.finish("❌ 参数错误，格式: /add_fish <单条价值(3-50)> <加入个数>")
    
    try:
        value = int(arg_text[0])
        count = int(arg_text[1])
    except ValueError:
        await add_fish_cmd.finish("❌ 参数必须是数字，格式: /add_fish <单条价值(3-50)> <加入个数>")
    
    # 验证价值范围
    min_val, max_val = config.fish_value_range
    if value < min_val or value > max_val:
        await add_fish_cmd.finish(f"❌ 单条价值必须在{min_val}到{max_val}之间")
    
    # 验证数量限制
    if count < 1 or count > config.max_fish_per_add:
        await add_fish_cmd.finish(f"❌ 加入数量必须在1到{config.max_fish_per_add}之间")
    
    # 计算总价值
    total_value = value * count
    
    # 检查用户银币是否足够
    coin_balance, exp, nickname = await get_user_info(user_id)
    if coin_balance < total_value:
        await add_fish_cmd.finish(f"❌ 银币不足，需要{total_value}银币，当前只有{coin_balance}银币")
    
    # 设置等待状态
    waiting_users[user_id] = {
        "group_id": group_id,
        "value": value,
        "count": count,
        "total_value": total_value,
        "start_time": time.time(),
        "user_nickname": nickname
    }
    
    # 提示用户发送图片
    await add_fish_cmd.finish(f"🎣 请发送鱼的图片，我将在{config.image_wait_timeout}秒内接收并处理\n💡 注意：图片将自动移除背景")

# 处理用户发送的图片
@on_message(priority=10, block=False)
async def handle_image_message(event: MessageEvent):
    """处理用户发送的图片"""
    user_id = get_user_id(event)
    
    # 检查用户是否在等待状态
    if user_id not in waiting_users:
        return
    
    waiting_data = waiting_users[user_id]
    
    # 检查是否超时
    elapsed_time = time.time() - waiting_data["start_time"]
    if elapsed_time > config.image_wait_timeout:
        del waiting_users[user_id]
        return
    
    # 检查消息中是否有图片
    message = event.get_message()
    for segment in message:
        if segment.type == "image":
            # 获取图片URL
            image_url = segment.data.get("url", "")
            if not image_url:
                continue
            
            try:
                # 下载图片
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(image_url) as resp:
                        if resp.status == 200:
                            image_bytes = await resp.read()
                            
                            # 移除背景
                            fish_image = remove_background(image_bytes)
                            
                            if fish_image is None:
                                await event.reply("❌ 移除背景失败，请尝试更换图片")
                                del waiting_users[user_id]
                                return
                            
                            # 保存图片并添加鱼
                            success, result_msg, processed_fish_image = await add_fish_to_tank(
                                user_id=user_id,
                                group_id=waiting_data["group_id"],
                                value=waiting_data["value"],
                                count=waiting_data["count"],
                                total_value=waiting_data["total_value"],
                                fish_image=fish_image
                            )
                            
                            if success:
                                # 将处理后的鱼图片转换为base64
                                try:
                                    # 调整图片大小以便显示
                                    display_size = (200, 200)  # 显示大小
                                    display_fish_image = processed_fish_image.copy()
                                    display_fish_image.thumbnail(display_size, Image.Resampling.LANCZOS)
                                    
                                    # 转换为base64
                                    img_base64 = pil_to_base64(display_fish_image)
                                    
                                    # 构建包含图片和文本的消息
                                    message_chain = Message()
                                    message_chain.append(MessageSegment.image(img_base64))
                                    message_chain.append(MessageSegment.text("\n" + result_msg))
                                    
                                    await event.reply(message_chain)
                                except Exception as e:
                                    logger.error(f"发送图片消息失败: {e}")
                                    await event.reply(result_msg)
                            else:
                                await event.reply(result_msg)
                            
                            # 清理等待状态
                            del waiting_users[user_id]
                            return
                            
            except Exception as e:
                logger.error(f"处理图片失败: {e}")
                await event.reply(f"❌ 处理图片失败: {str(e)}")
                del waiting_users[user_id]
                return
    
    # 如果消息中没有图片，忽略

async def add_fish_to_tank(user_id: str, group_id: str, value: int, count: int, 
                          total_value: int, fish_image: Image.Image) -> Tuple[bool, str, Image.Image]:
    """
    将鱼添加到鱼缸
    
    返回: (是否成功, 结果消息, 处理后的鱼图片)
    """
    # 消耗银币
    result = await consume_coins(user_id, total_value, 0, "")
    if result[0] is None:
        return False, "❌ 银币消费失败，添加鱼取消", fish_image
    
    # 加载鱼缸数据
    tank_data = load_tank_data(group_id)
    
    # 自动清理过期鱼
    valid_fishes, expired_fishes, expired_count = clean_expired_fishes(tank_data)
    tank_data["fishes"] = valid_fishes
    tank_data["current_fish_count"] = len(valid_fishes)
    
    # 生成唯一的鱼ID
    timestamp = int(time.time())
    
    # 添加鱼
    for i in range(count):
        fish_id = f"{user_id}_{timestamp}_{i}"
        
        # 保存鱼图片
        image_path = get_fish_image_path(group_id, fish_id)
        fish_image.save(image_path, 'PNG')
        
        # 生成过期时间
        expire_time = generate_fish_expire_time(value)
        
        # 创建鱼数据
        fish_data = {
            "id": fish_id,
            "user_id": user_id,
            "value": value,
            "add_time": datetime.now().isoformat(),
            "expire_time": expire_time.isoformat(),
            "image_path": str(image_path.relative_to(safe_path(config.fish_images_dir))),
            "size_factor": random.uniform(0.9, 1.1)  # 随机大小因子
        }
        
        tank_data["fishes"].append(fish_data)
    
    # 更新统计数据
    tank_data["total_fish_count"] = tank_data.get("total_fish_count", 0) + count
    tank_data["current_fish_count"] = tank_data.get("current_fish_count", 0) + count
    
    # 保存数据
    if save_tank_data(group_id, tank_data):
        # 计算保存时间范围
        min_hours, max_hours = calculate_fish_lifetime(value)
        
        result_msg = (
            f"✅ 成功添加{count}条价值{value}的鱼！\n"
            f"💰 消耗银币: {total_value}枚\n"
            f"⏰ 保存时间: {min_hours:.1f}~{max_hours:.1f}小时\n"
            f"🐟 鱼缸现有鱼数: {tank_data['current_fish_count']}条"
        )
        
        if expired_count > 0:
            result_msg += f"\n🧹 自动清理了{expired_count}条过期鱼"
        
        return True, result_msg, fish_image
    else:
        # 保存失败，返还银币
        await get_coins(user_id, total_value, 0, "")
        return False, "❌ 保存鱼缸数据失败，银币已返还", fish_image

@tank_cmd.handle()
async def handle_tank(event: GroupMessageEvent):
    """处理查看鱼缸命令"""
    group_id = get_group_id(event)
    
    if not group_id:
        await tank_cmd.finish("❌ 此功能仅在群聊中可用")
    
    # 加载鱼缸数据
    tank_data = load_tank_data(group_id)
    
    # 自动清理过期鱼
    valid_fishes, expired_fishes, expired_count = clean_expired_fishes(tank_data)
    tank_data["fishes"] = valid_fishes
    tank_data["current_fish_count"] = len(valid_fishes)
    
    # 保存清理后的数据
    if expired_count > 0:
        save_tank_data(group_id, tank_data)
    
    if not valid_fishes:
        await tank_cmd.finish("🐟 鱼缸是空的，快来添加第一条鱼吧！")
    
    # 限制显示的鱼数量
    display_fishes = valid_fishes[:config.max_fish_in_tank]
    
    # 渲染鱼缸图片
    try:
        tank_image = await render_tank_image(group_id, display_fishes)
        
        # 转换为base64
        img_byte_arr = io.BytesIO()
        tank_image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        
        # 构建消息
        total_value = sum(fish["value"] for fish in valid_fishes)
        message_chain = Message()
        
        # 添加鱼缸图片
        message_chain.append(MessageSegment.image(f"base64://{base64.b64encode(img_byte_arr.getvalue()).decode()}"))
        
        # 添加鱼缸统计信息
        info_msg = f"\n🐟 鱼缸统计:\n鱼数: {len(valid_fishes)}条"
        # if expired_count > 0:
        #     info_msg += f"\n🧹 自动清理了{expired_count}条过期鱼"
        message_chain.append(MessageSegment.text(info_msg))
        
        await tank_cmd.finish(message_chain)
        
    except Exception as e:
        logger.error(f"渲染鱼缸失败: {e}")
        # 如果渲染失败，发送文本信息
        total_value = sum(fish["value"] for fish in valid_fishes)
        
        msg = f"🐟 群鱼缸信息\n"
        msg += f"鱼数: {len(valid_fishes)}条\n"
        msg += f"总价值: {total_value}银币\n"
        if expired_count > 0:
            msg += f"过期鱼已清理: {expired_count}条\n"
        
        # 显示前5条鱼
        current_time = datetime.now()
        for i, fish in enumerate(valid_fishes[:5], 1):
            expire_time = datetime.fromisoformat(fish["expire_time"])
            time_left = expire_time - current_time
            hours_left = time_left.total_seconds() / 3600
            
            msg += f"{i}. 价值{fish['value']}的鱼 (剩余{hours_left:.1f}小时)\n"
        
        if len(valid_fishes) > 5:
            msg += f"... 等{len(valid_fishes)}条鱼"
        
        await tank_cmd.finish(msg)

async def render_tank_image(group_id: str, fishes: List[Dict]) -> Image.Image:
    """
    渲染鱼缸图片
    
    参数:
        group_id: 群ID
        fishes: 鱼的数据列表
    
    返回:
        渲染后的鱼缸图片
    """
    # 尝试加载背景图片
    bg_path = Path(__file__).parent / "static" / "tank.png"
    if bg_path.exists():
        try:
            bg_image = Image.open(bg_path).convert("RGBA")
        except:
            bg_image = Image.new("RGBA", config.default_tank_size, 
                                config.default_tank_color + (255,))
    else:
        bg_image = Image.new("RGBA", config.default_tank_size, 
                            config.default_tank_color + (255,))
    
    # 确保背景是RGBA模式
    if bg_image.mode != "RGBA":
        bg_image = bg_image.convert("RGBA")
    
    # 获取鱼缸尺寸
    tank_width, tank_height = bg_image.size
    
    # 按价值排序，价值高的先渲染（在底层）
    fishes_sorted = sorted(fishes, key=lambda x: x["value"])
    
    for fish in fishes_sorted:
        try:
            # 加载鱼图片
            image_path = safe_path(config.fish_images_dir) / fish["image_path"]
            if not image_path.exists():
                continue
            
            fish_img = Image.open(image_path).convert("RGBA")
            
            # 计算鱼的大小
            value = fish["value"]
            size_factor = fish.get("size_factor", 1.0)
            fish_width = int(tank_width * (value ** 0.3) * config.fish_size_multiplier * size_factor)
            
            # 等比例调整高度
            original_width, original_height = fish_img.size
            scale_factor = fish_width / original_width
            fish_height = int(original_height * scale_factor)
            
            # 调整鱼图片大小
            fish_img = fish_img.resize((fish_width, fish_height), Image.Resampling.LANCZOS)
            
            # 随机镜像
            if random.random() > 0.5:
                fish_img = fish_img.transpose(Image.FLIP_LEFT_RIGHT)
            
            # 随机旋转
            rotation_angle = random.uniform(-config.max_rotation_angle, config.max_rotation_angle)
            fish_img = fish_img.rotate(rotation_angle, expand=True, resample=Image.BICUBIC)
            
            # 计算随机位置，避免重叠
            for attempt in range(20):  # 最多尝试20次
                x = random.randint(0, max(1, tank_width - fish_img.width))
                y = random.randint(0, max(1, tank_height - fish_img.height))
                
                # 简单的重叠检查
                if not check_overlap(bg_image, fish_img, x, y, fishes_sorted.index(fish)):
                    # 将鱼图片粘贴到背景上
                    bg_image.paste(fish_img, (x, y), fish_img)
                    break
            else:
                # 如果找不到不重叠的位置，随机放置
                x = random.randint(0, max(1, tank_width - fish_img.width))
                y = random.randint(0, max(1, tank_height - fish_img.height))
                bg_image.paste(fish_img, (x, y), fish_img)
                
        except Exception as e:
            logger.error(f"渲染鱼图片失败: {e}")
            continue
    
    return bg_image

def check_overlap(bg_image: Image.Image, fish_img: Image.Image, x: int, y: int, fish_index: int) -> bool:
    """
    简单的重叠检查
    这里只是示例，实际可以更复杂
    """
    # 获取鱼图片的alpha通道
    if fish_img.mode == 'RGBA':
        alpha = fish_img.split()[3]
        
        # 检查鱼的有效区域
        for i in range(min(10, fish_img.width)):
            for j in range(min(10, fish_img.height)):
                if x + i < bg_image.width and y + j < bg_image.height:
                    # 检查背景像素是否不透明
                    bg_pixel = bg_image.getpixel((x + i, y + j))
                    if bg_pixel[3] > 200:  # 背景不透明
                        # 检查鱼像素是否不透明
                        if i < alpha.width and j < alpha.height:
                            fish_alpha = alpha.getpixel((i, j))
                            if fish_alpha > 50:  # 鱼不透明
                                return True
    return False

@clean_tank_cmd.handle()
async def handle_clean_tank(event: GroupMessageEvent):
    """手动清理过期鱼"""
    group_id = get_group_id(event)
    
    if not group_id:
        await clean_tank_cmd.finish("❌ 此功能仅在群聊中可用")
    
    # 加载鱼缸数据
    tank_data = load_tank_data(group_id)
    
    if not tank_data.get("fishes"):
        await clean_tank_cmd.finish("🐟 鱼缸已经是空的")
    
    # 清理过期鱼
    valid_fishes, expired_fishes, expired_count = clean_expired_fishes(tank_data)
    
    # 更新数据
    tank_data["fishes"] = valid_fishes
    tank_data["current_fish_count"] = len(valid_fishes)
    
    if save_tank_data(group_id, tank_data):
        await clean_tank_cmd.finish(f"✅ 清理完成！\n清理了{expired_count}条过期鱼\n剩余{len(valid_fishes)}条有效鱼")
    else:
        await clean_tank_cmd.finish("❌ 清理失败，请稍后重试")

@tank_help_cmd.handle()
async def handle_tank_help():
    """显示鱼缸帮助"""
    min_val, max_val = config.fish_value_range
    
    help_msg = f"🐟 群聊鱼缸系统帮助\n"
    help_msg += "=" * 20 + "\n\n"
    
    help_msg += f"🎣 添加鱼:\n"
    help_msg += f"  /add_fish <价值{min_val}-{max_val}> <数量>\n"
    help_msg += f"  示例: /add_fish 10 5\n"
    help_msg += f"  说明: 添加5条价值10的鱼，总价值50\n"
    help_msg += f"  限制: 单次最多{config.max_fish_per_add}条\n\n"
    
    help_msg += f"💰 鱼的保存时间:\n"
    help_msg += f"  公式: 价值^{{0.5}}×24±16小时\n"
    help_msg += f"  示例: 价值9的鱼保存约72±16小时\n\n"
    
    help_msg += f"🖼️ 鱼的大小:\n"
    help_msg += f"  公式: 鱼缸长度 × (价值^{{0.3}}) × 0.075\n"
    help_msg += f"  价值越高，鱼越大\n\n"
    
    help_msg += f"🎯 可用命令:\n"
    help_msg += f"  /add_fish - 添加鱼\n"
    help_msg += f"  /tank - 查看鱼缸\n"
    help_msg += f"  /clean_tank - 手动清理过期鱼\n"
    help_msg += f"  /tank_help - 显示此帮助\n\n"
    
    help_msg += f"📝 注意事项:\n"
    help_msg += f"  1. 添加鱼需要消耗相应价值的银币\n"
    help_msg += f"  2. 添加后需要在{config.image_wait_timeout}秒内发送图片\n"
    help_msg += f"  3. 图片会自动移除背景\n"
    help_msg += f"  4. 鱼缸在查看时会自动清理过期鱼\n"
    help_msg += f"  5. 鱼缸最多显示{config.max_fish_in_tank}条鱼\n"
    help_msg += f"  6. 添加鱼成功后，会显示抠图后的鱼图片"
    
    await tank_help_cmd.finish(help_msg)

# 清理过期的等待状态
async def clean_waiting_states():
    """定期清理过期的等待状态"""
    while True:
        await asyncio.sleep(30)  # 每30秒清理一次
        
        current_time = time.time()
        expired_users = []
        
        for user_id, data in waiting_users.items():
            elapsed = current_time - data["start_time"]
            if elapsed > config.image_wait_timeout:
                expired_users.append(user_id)
        
        for user_id in expired_users:
            del waiting_users[user_id]
            logger.info(f"清理用户 {user_id} 的过期等待状态")

# 启动时开始清理任务
@get_driver().on_startup
async def start_cleanup_task():
    """启动清理任务"""
    asyncio.create_task(clean_waiting_states())
    logger.info("鱼缸插件已启动，等待状态清理任务已开始")