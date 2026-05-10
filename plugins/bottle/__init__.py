from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata
import random
import time
import json
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageSegment, Event
from nonebot.params import CommandArg

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="bottle",
    description="漂流瓶插件",
    usage="投掷漂流瓶: /throw 内容\n捡漂流瓶: /bottle\n评论漂流瓶: /comment 瓶号 评论",
    config=Config,
)

config = get_plugin_config(Config)

# 导入其他插件
from nonebot import require
require("plugins.file_edit")
from plugins.file_edit import (
    read_csv_file,
    write_csv_file,
    safe_path,
    append_csv_rows,
    plugin_dir,
    read_file,
    write_file
)

# 常量定义
BOTTLE_ROOT = "bottles"
BOTTLE_DIRS = {
    "text": f"{BOTTLE_ROOT}/text",
    "pic": f"{BOTTLE_ROOT}/pic", 
    "user": f"{BOTTLE_ROOT}/user"
}
BOTTLE_FILES = {
    "num": f"{BOTTLE_ROOT}/num"
}

def get_user_nickname(event: Event) -> str:
    """从事件中获取用户昵称（QQ昵称）"""
    try:
        if hasattr(event, 'sender') and hasattr(event.sender, 'nickname'):
            return event.sender.nickname
        elif hasattr(event, 'get_user_id'):
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

def read_counter_file() -> int:
    """读取计数器文件"""
    counter_file = BOTTLE_FILES["num"] + ".csv"
    try:
        result = read_csv_file(counter_file)
        if isinstance(result, str):  # 错误信息
            print(f"[DEBUG] 读取计数器文件失败: {result}")
            return 0
        if result and result[0]:
            return int(result[0][0])
    except Exception as e:
        print(f"[DEBUG] 读取计数器文件异常: {e}")
    return 0

def write_counter_file(num: int) -> bool:
    """写入计数器文件"""
    counter_file = BOTTLE_FILES["num"]
    result = write_csv_file(counter_file, [[str(num)]])
    if result is not True:
        print(f"[DEBUG] 写入计数器文件失败: {result}")
    return result is True

def update_bottle_counter() -> int:
    """更新并获取漂流瓶编号"""
    num = read_counter_file()
    num += 1
    if write_counter_file(num):
        return num
    else:
        raise Exception("写入计数器文件失败")

def save_bottle_data(num: int, user_id: str, nickname: str, text: str, images: list):
    """保存漂流瓶数据，使用纯文本和JSON格式"""
    # 保存文本（使用纯文本文件，避免逗号问题）
    if text.strip():
        text_file = f"{BOTTLE_DIRS['text']}/{num}.txt"
        try:
            write_file(text_file, text)
        except Exception as e:
            raise Exception(f"保存文本失败: {e}")
    
    # 保存图片链接（使用JSON格式）
    if images:
        pic_file = f"{BOTTLE_DIRS['pic']}/{num}.json"
        try:
            # 将图片链接列表保存为JSON
            write_file(pic_file, json.dumps(images, ensure_ascii=False, indent=2))
        except Exception as e:
            raise Exception(f"保存图片失败: {e}")
    
    # 保存用户信息（使用JSON格式）
    user_file = f"{BOTTLE_DIRS['user']}/{num}.json"
    user_data = {
        "user_id": user_id,
        "user_nickname": nickname,
        "timestamp": int(time.time()),
        "comments": []  # 初始评论为空列表
    }
    try:
        write_file(user_file, json.dumps(user_data, ensure_ascii=False, indent=2))
    except Exception as e:
        raise Exception(f"保存用户信息失败: {e}")

throw_bottle = on_command('throw')

@throw_bottle.handle()
async def handle_throw(event: Event, message: Message = CommandArg()):
    user_id = event.get_user_id()
    text = message.extract_plain_text().strip()
    images = parse_image_urls(event.message)
    
    if not text and not images:
        await throw_bottle.finish("漂流瓶内容不能为空，请添加文字或图片")
    
    nickname = get_user_nickname(event)
    
    try:
        num = update_bottle_counter()
    except Exception as e:
        await throw_bottle.finish(f"更新漂流瓶编号失败：{str(e)}")
    
    try:
        save_bottle_data(num, user_id, nickname, text, images)
    except Exception as e:
        await throw_bottle.finish(f"保存数据失败：{str(e)}")
    
    # 构建响应消息
    if text and images:
        msg_content = f"包含文字和图片的漂流瓶"
    elif text:
        msg_content = f"文字漂流瓶"
    elif images:
        msg_content = f"图片漂流瓶（{len(images)}张）"
    
    msg = MessageSegment.text(f"{nickname}的{msg_content}已投掷！漂流瓶id: {num}\n")
    if text:
        msg += MessageSegment.text(f"内容：{text}\n")
    
    if images:
        msg += MessageSegment.image(images[0])
    
    await throw_bottle.send(msg)

def load_bottle_data(num: int) -> dict:
    """加载漂流瓶数据，使用纯文本和JSON格式"""
    data = {}
    print(f"[DEBUG] 开始加载漂流瓶 {num} 的数据")
    
    # 加载文本（纯文本文件）
    text_file = f"{BOTTLE_DIRS['text']}/{num}.txt"
    try:
        data["text"] = read_file(text_file)
        print(f"[DEBUG] 漂流瓶 {num} 文本加载成功: {data['text'][:50]}...")
    except Exception as e:
        print(f"[DEBUG] 漂流瓶 {num} 文本读取失败: {e}")
        data["text"] = ""
    
    # 加载图片（JSON格式）
    pic_file = f"{BOTTLE_DIRS['pic']}/{num}.json"
    data["images"] = []
    try:
        images_json = read_file(pic_file)
        data["images"] = json.loads(images_json)
        print(f"[DEBUG] 漂流瓶 {num} 加载了 {len(data['images'])} 张图片")
    except Exception as e:
        print(f"[DEBUG] 漂流瓶 {num} 图片读取失败: {e}")
    
    # 加载用户信息（JSON格式）
    user_file = f"{BOTTLE_DIRS['user']}/{num}.json"
    data["user_id"] = ""
    data["user_nickname"] = ""
    data["timestamp"] = ""
    data["comments"] = []
    
    try:
        user_json = read_file(user_file)
        user_data = json.loads(user_json)
        data["user_id"] = user_data.get("user_id", "")
        data["user_nickname"] = user_data.get("user_nickname", "")
        data["timestamp"] = user_data.get("timestamp", "")
        data["comments"] = user_data.get("comments", [])
        print(f"[DEBUG] 漂流瓶 {num} 用户信息加载成功: {data['user_nickname']}")
        print(f"[DEBUG] 漂流瓶 {num} 有 {len(data['comments'])} 条评论")
    except Exception as e:
        print(f"[DEBUG] 漂流瓶 {num} 用户信息读取失败: {e}")
    
    # 检查漂流瓶是否有效
    if not data["text"] and not data["images"]:
        print(f"[DEBUG] 漂流瓶 {num} 无效：文本和图片都为空")
    else:
        print(f"[DEBUG] 漂流瓶 {num} 加载完成，有效")
    
    return data

pick_bottle = on_command('bottle')

@pick_bottle.handle()
async def handle_pick(event: Event):
    try:
        max_num = read_counter_file()
        print(f"[DEBUG] 当前最大漂流瓶编号: {max_num}")
    except Exception as e:
        await pick_bottle.finish(f"漂流瓶数据加载失败: {str(e)}")
    
    if max_num == 0:
        await pick_bottle.finish("现在还没有漂流瓶呢")
    
    tried_nums = set()
    found_valid = False
    
    # 增加尝试次数
    for attempt in range(min(10, max_num * 2)):
        num = random.randint(1, max_num)
        if num in tried_nums:
            continue
        tried_nums.add(num)
        
        print(f"[DEBUG] 尝试捡取漂流瓶 {num} (第{attempt+1}次尝试)")
        
        try:
            data = load_bottle_data(num)
            # 漂流瓶有效条件：有文本或有图片
            if not data.get("text") and not data.get("images"):
                print(f"[DEBUG] 漂流瓶 {num} 无效，跳过")
                continue
                
            found_valid = True
            publisher_name = data.get("user_nickname", data.get("user_id", "未知用户"))
            
            # 构建消息
            msg = MessageSegment.text(f"捡到了来自 {publisher_name} 的漂流瓶！\n")
            msg += MessageSegment.text(f"ID: {num}\n")
            
            if data.get("text"):
                msg += MessageSegment.text(f"内容：{data['text']}\n")
            
            # 添加图片
            for img_url in data.get("images", [])[:3]:
                msg += MessageSegment.image(img_url)
            
            # 添加评论
            comments = data.get("comments", [])
            if comments:
                msg += MessageSegment.text("\n\n近期评论：")
                for comment in comments[-3:]:  # 显示最近3条评论
                    # 评论现在是一个字典
                    if isinstance(comment, dict):
                        commenter_name = comment.get("nickname", comment.get("user_id", "未知用户"))
                        comment_text = comment.get("comment", "")
                    else:
                        # 兼容旧格式（如果是列表）
                        if len(comment) >= 3:
                            commenter_name = comment[1] if comment[1] else comment[0]
                            comment_text = comment[2] if len(comment) > 2 else ""
                        elif len(comment) >= 2:
                            commenter_name = comment[0]
                            comment_text = comment[1] if len(comment) > 1 else ""
                        else:
                            continue
                    
                    msg += MessageSegment.text(f"\n{commenter_name}：{comment_text}")
            else:
                msg += MessageSegment.text("\n发送 /comment 添加评论")
            
            await pick_bottle.send(msg)
            print(f"[DEBUG] 成功捡取漂流瓶 {num}")
            return
            
        except Exception as e:
            print(f"[DEBUG] 捡取漂流瓶 {num} 时发生异常: {e}")
            continue
    
    if not found_valid:
        print(f"[DEBUG] 尝试了 {len(tried_nums)} 个漂流瓶，都无效")
        print(f"[DEBUG] 尝试的漂流瓶ID: {sorted(tried_nums)}")
        await pick_bottle.finish("暂时没有可捡的漂流瓶")

bottle_comment = on_command('comment')

@bottle_comment.handle()
async def handle_comment(event: Event, message: Message = CommandArg()):
    args = message.extract_plain_text().strip().split(maxsplit=1)
    if len(args) < 2:
        await bottle_comment.finish("格式错误，正确格式：/comment <漂流瓶ID> <评论内容>")
    
    try:
        num = int(args[0])
    except ValueError:
        await bottle_comment.finish("漂流瓶ID必须是数字")
    
    comment = args[1]
    user_id = event.get_user_id()
    
    if len(comment) > 100:
        await bottle_comment.finish("评论内容不能超过100字")
    
    commenter_nickname = get_user_nickname(event)
    
    try:
        data = load_bottle_data(num)
        # 检查漂流瓶是否存在：有文本或有图片
        if not data.get("text") and not data.get("images"):
            await bottle_comment.finish(f"漂流瓶 {num} 不存在")
    except Exception as e:
        await bottle_comment.finish(f"检查漂流瓶失败: {str(e)}")
    
    # 读取用户信息文件
    user_file = f"{BOTTLE_DIRS['user']}/{num}.json"
    try:
        user_json = read_file(user_file)
        user_data = json.loads(user_json)
    except Exception as e:
        await bottle_comment.finish(f"读取用户信息失败：{e}")
    
    # 添加新评论
    new_comment = {
        "user_id": user_id,
        "nickname": commenter_nickname,
        "comment": comment,
        "time": int(time.time())
    }
    
    if "comments" not in user_data:
        user_data["comments"] = []
    
    user_data["comments"].append(new_comment)
    
    # 写回文件
    try:
        write_file(user_file, json.dumps(user_data, ensure_ascii=False, indent=2))
    except Exception as e:
        await bottle_comment.finish(f"保存评论失败：{e}")
    
    await bottle_comment.send(f"评论成功！\n{commenter_nickname}：{comment}")