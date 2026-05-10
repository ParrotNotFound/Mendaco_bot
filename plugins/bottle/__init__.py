from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="bottle",
    description="",
    usage="",
    config=Config,
)

config = get_plugin_config(Config)

from nonebot import require
require("plugins.file_edit")
from plugins.file_edit import (
    read_csv_file,
    write_csv_file,
    safe_path,
    append_csv_rows,
    plugin_dir
)

require("plugins.maimaidx_music")
from plugins.maimaidx_music import total_list
require("plugins.image")
from plugins.image import text_to_image2, image_to_base64
config = get_plugin_config(Config)

from pathlib import Path
import random
import time
import aiohttp
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageSegment, Event
from nonebot.params import CommandArg

# 常量定义
BOTTLE_ROOT = plugin_dir / "bottles"
BOTTLE_DATA = {
    "num": BOTTLE_ROOT / "num.txt",
    "text": BOTTLE_ROOT / "text",
    "pic": BOTTLE_ROOT / "pic",
    "user": BOTTLE_ROOT / "user"
}

# 初始化目录
for d in BOTTLE_DATA.values():
    if isinstance(d, Path):
        d.mkdir(parents=True, exist_ok=True)

def get_user_nickname(event: Event) -> str:
    """从事件中获取用户昵称（QQ昵称）"""
    try:
        # 尝试从事件中获取用户昵称
        if hasattr(event, 'sender') and hasattr(event.sender, 'nickname'):
            return event.sender.nickname
        elif hasattr(event, 'get_user_id'):
            # 如果没有昵称，返回QQ号
            return event.get_user_id()
        else:
            return "未知用户"
    except:
        return "未知用户"

def parse_image_urls(message: Message) -> list:
    """从消息中提取图片URL"""
    return [
        seg.data["url"] for seg in message
        if seg.type == "image" and "url" in seg.data
    ]

async def update_bottle_counter() -> int:
    """更新并获取漂流瓶编号"""
    counter_file = BOTTLE_DATA["num"]
    
    try:
        content = await read_csv_file(counter_file)
        num = int(content[0][0]) if content else 0
    except FileNotFoundError:
        num = 0
    
    num += 1
    await write_csv_file(counter_file, [[str(num)]])
    return num

async def save_bottle_data(num: int, user_id: str, nickname: str, text: str, images: list):
    """保存漂流瓶数据（包含QQ昵称）"""
    # 保存文本
    text_file = BOTTLE_DATA["text"] / f"{num}.txt"
    await write_csv_file(text_file, [[text]])
    
    # 保存图片链接
    if images:
        pic_file = BOTTLE_DATA["pic"] / f"{num}.csv"
        await write_csv_file(pic_file, [[url] for url in images])
    
    # 保存用户信息（QQ号、昵称、时间戳）
    user_file = BOTTLE_DATA["user"] / f"{num}.csv"
    await write_csv_file(user_file, [
        [user_id, nickname, str(int(time.time()))]
    ])

throw_bottle = on_command('throw')

@throw_bottle.handle()
async def handle_throw(event: Event, message: Message = CommandArg()):
    user_id = event.get_user_id()
    text = message.extract_plain_text().strip()
    images = parse_image_urls(event.message)
    
    # 获取用户昵称（QQ昵称）
    nickname = get_user_nickname(event)
    
    # 更新漂流瓶计数器
    try:
        num = await update_bottle_counter()
    except Exception as e:
        await throw_bottle.finish(f"更新漂流瓶编号失败：{str(e)}")
    
    # 保存数据（包含昵称）
    try:
        await save_bottle_data(num, user_id, nickname, text, images)
    except Exception as e:
        await throw_bottle.finish(f"保存数据失败：{str(e)}")
    
    # 构建响应消息
    msg = MessageSegment.text(
        f"{nickname}的漂流瓶已投掷！漂流瓶id: {num}\n内容：{text}"
    )
    if images:
        msg += MessageSegment.image(images[0])
    
    await throw_bottle.send(msg)

async def load_bottle_data(num: int) -> dict:
    """加载漂流瓶数据（包含QQ昵称）"""
    data = {}
    
    # 加载文本
    text_file = BOTTLE_DATA["text"] / f"{num}.txt"
    try:
        text_data = await read_csv_file(text_file)
        data["text"] = text_data[0][0] if text_data else ""
    except:
        data["text"] = ""
    
    # 加载图片
    pic_file = BOTTLE_DATA["pic"] / f"{num}.csv"
    data["images"] = []
    try:
        pic_data = await read_csv_file(pic_file)
        if pic_data and not isinstance(pic_data, str):
            data["images"] = [row[0] for row in pic_data]
    except:
        pass
    
    # 加载用户信息
    user_file = BOTTLE_DATA["user"] / f"{num}.csv"
    data["user_id"] = ""
    data["user_nickname"] = ""
    data["timestamp"] = ""
    data["comments"] = []
    
    try:
        user_data = await read_csv_file(user_file)
        if user_data and not isinstance(user_data, str):
            if len(user_data) > 0:
                # 第一行是发布者信息
                if len(user_data[0]) >= 3:  # 新格式：QQ号, 昵称, 时间戳
                    data["user_id"] = user_data[0][0]
                    data["user_nickname"] = user_data[0][1]
                    data["timestamp"] = user_data[0][2]
                elif len(user_data[0]) >= 1:  # 旧格式兼容
                    data["user_id"] = user_data[0][0]
                    data["user_nickname"] = data["user_id"]  # 如果没有昵称，使用QQ号
                    if len(user_data[0]) >= 2:
                        data["timestamp"] = user_data[0][1]
                
                # 剩余行是评论
                if len(user_data) > 1:
                    data["comments"] = user_data[1:]
    except:
        pass
    
    return data

pick_bottle = on_command('bottle')

@pick_bottle.handle()
async def handle_pick(event: Event):
    # 获取漂流瓶总数
    try:
        counter = await read_csv_file(BOTTLE_DATA["num"])
        max_num = int(counter[0][0]) if counter else 0
    except Exception:
        await pick_bottle.finish("漂流瓶数据加载失败")
    
    if max_num == 0:
        await pick_bottle.finish("现在还没有漂流瓶呢")
    
    # 随机尝试获取有效漂流瓶
    for _ in range(3):
        num = random.randint(1, max_num)
        try:
            data = await load_bottle_data(num)
            if not data or not data.get("text"):
                continue
        except Exception:
            continue
        
        # 获取发布者信息（使用保存的QQ昵称）
        publisher_name = data.get("user_nickname", data.get("user_id", "未知用户"))
        
        # 构建消息
        msg = MessageSegment.text(
            f"捡到了来自 {publisher_name} 的漂流瓶！\n"
            f"ID: {num}\n内容：{data['text']}\n"
        )
        
        # 添加图片
        for img_url in data.get("images", [])[:3]:  # 最多显示3张图片
            msg += MessageSegment.image(img_url)
        
        # 添加评论
        comments = data.get("comments", [])
        if comments:
            msg += MessageSegment.text("\n\n近期评论：")
            for comment in comments[-3:]:  # 显示最近3条评论
                if len(comment) >= 3:  # 新格式：QQ号, 昵称, 评论
                    commenter_name = comment[1] if comment[1] else comment[0]
                    comment_text = comment[2] if len(comment) > 2 else ""
                elif len(comment) >= 2:  # 旧格式：QQ号, 评论
                    commenter_name = comment[0]
                    comment_text = comment[1] if len(comment) > 1 else ""
                else:
                    continue
                
                msg += MessageSegment.text(f"\n{commenter_name}：{comment_text}")
        else:
            msg += MessageSegment.text("\n发送 /comment 添加评论")
        
        await pick_bottle.send(msg)
        return
    
    await pick_bottle.finish("暂时没有可捡的漂流瓶")

bottle_comment = on_command('comment')

@bottle_comment.handle()
async def handle_comment(event: Event, message: Message = CommandArg()):
    args = message.extract_plain_text().split(maxsplit=1)
    if len(args) < 2:
        await bottle_comment.finish("格式错误，正确格式：/comment <漂流瓶ID> <评论内容>")
    
    num, comment = args
    user_id = event.get_user_id()
    
    # 获取评论者QQ昵称
    commenter_nickname = get_user_nickname(event)
    
    # 验证评论内容
    if len(comment) > 100:
        await bottle_comment.finish("评论内容不能超过100字")
    
    # 保存评论（包含QQ号和昵称）
    try:
        user_file = BOTTLE_DATA["user"] / f"{num}.csv"
        # 新格式：QQ号, 昵称, 评论内容
        await append_csv_rows(
            filename=user_file,
            header=[],  # 不需要表头
            rows=[[user_id, commenter_nickname, comment]],
            delimiter="|"
        )
    except Exception as e:
        await bottle_comment.finish(f"评论失败：{str(e)}")
    
    # 使用保存的昵称回复
    await bottle_comment.send(
        f"评论成功！\n{commenter_nickname}：{comment}"
    )