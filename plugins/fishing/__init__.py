from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata
import random
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageSegment, Event, GroupMessageEvent, PrivateMessageEvent
from nonebot.adapters.console import Message, MessageSegment, Event
from nonebot.params import CommandArg
from nonebot.log import logger

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="fishing",
    description="模拟钓鱼插件",
    usage="""
钓鱼: /fish
查看钓鱼记录: /fish_record
查看排行榜: /fish_rank
添加特殊垃圾: /add_trash 垃圾名称
查看特殊垃圾: /list_trash
删除特殊垃圾: /del_trash 序号
钓鱼帮助: /fish_help
""",
    config=Config,
)

config = get_plugin_config(Config)

# 导入 file_edit 插件
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

# 文件路径定义
FISHING_ROOT = "fishing"
DATA_FILES = {
    "users": f"{FISHING_ROOT}/users",  # 用户数据目录
    "global": f"{FISHING_ROOT}/global.json",  # 全局数据文件
    "special_trash": f"{FISHING_ROOT}/special_trash.json",  # 特殊垃圾文件
    "temp": f"{FISHING_ROOT}/temp"  # 临时数据目录
}
# 特殊垃圾管理


def save_special_trash(trash_list: List[Dict[str, Any]]) -> bool:
    """保存特殊垃圾列表"""
    try:
        write_file(DATA_FILES["special_trash"], json.dumps(trash_list, ensure_ascii=False, indent=2))
        return True
    except Exception as e:
        logger.error(f"保存特殊垃圾失败: {e}")
        return False
def load_special_trash() -> List[Dict[str, Any]]:
    """加载特殊垃圾列表"""
    try:
        data = read_file(DATA_FILES["special_trash"])
        if data:
            return json.loads(data)
    except:
        pass
    return []
# 初始化文件目录
def init_directories():
    """初始化所需的目录结构"""
    try:
        for path in DATA_FILES.values():
            if "/" in path and not path.endswith((".json", ".csv", ".txt")):
                # 这是目录，确保存在
                write_file(path + "/.keep", "")  # 创建一个空文件确保目录存在
    except:
        pass
    
    # 初始化特殊垃圾文件
    try:
        special_trash = load_special_trash()
        if special_trash is None:
            # 创建空的特殊垃圾列表
            save_special_trash([])
    except:
        save_special_trash([])

init_directories()

# 辅助函数
def get_user_id(event: Event) -> str:
    """获取用户ID"""
    return event.get_user_id()

def get_user_nickname(event: Event) -> str:
    """获取用户昵称"""
    try:
        if hasattr(event, 'sender') and hasattr(event.sender, 'nickname'):
            return event.sender.nickname
        return get_user_id(event)
    except:
        return get_user_id(event)

def get_group_id(event: Event) -> Optional[str]:
    """获取群组ID（如果是群消息）"""
    if isinstance(event, GroupMessageEvent):
        return str(event.group_id)
    return None



def get_all_trash_items() -> List[Dict[str, Any]]:
    """获取所有垃圾物品（基础垃圾 + 特殊垃圾）"""
    # 基础垃圾转换为字典格式
    base_trash = [{"name": item, "type": "base"} for item in config.trash_items]
    
    # 特殊垃圾
    special_trash = load_special_trash()
    
    return base_trash + special_trash

def get_random_trash() -> Dict[str, Any]:
    """随机获取一个垃圾（基础垃圾或特殊垃圾）"""
    all_trash = get_all_trash_items()
    
    if not all_trash:
        # 如果没有垃圾，返回一个默认的基础垃圾
        return {"name": "未知垃圾", "type": "base"}
    
    # 根据权重决定是基础垃圾还是特殊垃圾
    if random.random() < config.special_trash_weight and len(all_trash) > len(config.trash_items):
        # 从特殊垃圾中随机选择
        special_trash = load_special_trash()
        if special_trash:
            return random.choice(special_trash)
    
    # 从所有垃圾中随机选择
    return random.choice(all_trash)

def add_special_trash(trash_name: str, added_by: str, added_nickname: str) -> Tuple[bool, str]:
    """添加特殊垃圾"""
    # 检查垃圾名称是否为空
    if not trash_name or trash_name.strip() == "":
        return False, "垃圾名称不能为空"
    
    trash_name = trash_name.strip()
    
    # 检查长度限制
    if len(trash_name) > 100:
        return False, "垃圾名称太长了，请控制在100个字符以内"
    
    # 加载现有特殊垃圾
    special_trash = load_special_trash()
    
    # 检查是否已达到数量限制
    if len(special_trash) >= config.max_special_trash_count:
        return False, f"特殊垃圾数量已达到上限({config.max_special_trash_count}个)，无法添加更多"
    
    # 检查是否已存在相同的垃圾
    for trash in special_trash:
        if trash["name"] == trash_name:
            return False, f"特殊垃圾 '{trash_name}' 已存在"
    
    # 检查是否是基础垃圾
    if trash_name in config.trash_items:
        return False, f"'{trash_name}' 已经是基础垃圾了"
    
    # 添加新垃圾
    new_trash = {
        "id": len(special_trash) + 1,
        "name": trash_name,
        "added_by": added_by,
        "added_nickname": added_nickname,
        "added_time": int(time.time()),
        "fished_count": 0,  # 被钓到的次数
        "last_fished_time": None  # 上次被钓到的时间
    }
    
    special_trash.append(new_trash)
    
    if save_special_trash(special_trash):
        return True, f"成功添加特殊垃圾: {trash_name}"
    else:
        return False, "保存特殊垃圾失败"

def delete_special_trash(trash_id: int) -> Tuple[bool, str]:
    """删除特殊垃圾"""
    special_trash = load_special_trash()
    
    # 查找要删除的垃圾
    for i, trash in enumerate(special_trash):
        if trash["id"] == trash_id:
            trash_name = trash["name"]
            del special_trash[i]
            
            # 重新编号
            for j, t in enumerate(special_trash):
                t["id"] = j + 1
            
            if save_special_trash(special_trash):
                return True, f"已删除特殊垃圾: {trash_name}"
            else:
                return False, "保存特殊垃圾列表失败"
    
    return False, f"未找到ID为 {trash_id} 的特殊垃圾"

# 用户数据管理
def get_user_file_path(user_id: str) -> str:
    """获取用户数据文件路径"""
    return f"{DATA_FILES['users']}/{user_id}.json"

def load_user_data(user_id: str) -> Dict:
    """加载用户钓鱼数据"""
    user_file = get_user_file_path(user_id)
    try:
        data = read_file(user_file)
        if data:
            return json.loads(data)
    except:
        pass
    
    # 返回默认数据
    return {
        "user_id": user_id,
        "total_count": 0,  # 总钓鱼次数
        "last_fishing_time": [],  # 最近钓鱼时间戳列表
        "air_count": 0,  # 空军次数
        "fish_count": 0,  # 钓到鱼的总次数
        "treasure_count": 0,  # 钓到宝物的总次数
        "trash_count": 0,  # 钓到垃圾的总次数
        "special_trash_count": 0,  # 钓到特殊垃圾的次数
        "fish_details": {},  # 每种鱼的详细数量
        "trash_details": {},  # 每种垃圾的详细数量
        "special_trash_details": {},  # 每种特殊垃圾的详细数量
        "treasure_details": {}  # 每种宝物的详细数量
    }

def save_user_data(user_id: str, data: Dict) -> bool:
    """保存用户钓鱼数据"""
    try:
        user_file = get_user_file_path(user_id)
        write_file(user_file, json.dumps(data, ensure_ascii=False, indent=2))
        return True
    except Exception as e:
        logger.error(f"保存用户数据失败: {e}")
        return False

def load_global_data() -> Dict:
    """加载全局数据"""
    try:
        data = read_file(DATA_FILES["global"])
        if data:
            return json.loads(data)
    except:
        pass
    
    # 返回默认数据
    return {
        "total_fishing_count": 0,  # 全服总钓鱼次数
        "today_fishing_count": 0,  # 今日钓鱼次数
        "today_air_count": 0,  # 今日空军次数
        "today_treasure_count": 0,  # 今日宝物次数
        "last_update_date": datetime.now().strftime("%Y-%m-%d")  # 最后更新日期
    }

def save_global_data(data: Dict) -> bool:
    """保存全局数据"""
    try:
        write_file(DATA_FILES["global"], json.dumps(data, ensure_ascii=False, indent=2))
        return True
    except Exception as e:
        logger.error(f"保存全局数据失败: {e}")
        return False

# 钓鱼逻辑核心函数
def can_fish(user_id: str) -> Tuple[bool, str]:
    """检查用户是否可以钓鱼"""
    data = load_user_data(user_id)
    now = int(time.time())
    
    # 清理一小时前的时间戳
    hour_ago = now - 3600
    recent_times = [t for t in data.get("last_fishing_time", []) if t > hour_ago]
    
    # 更新数据
    data["last_fishing_time"] = recent_times
    
    # 检查是否达到限制
    if len(recent_times) >= config.fishing_limit_per_hour:
        # 计算下次可钓鱼时间
        oldest_time = min(recent_times) if recent_times else 0
        next_time = oldest_time + 3600
        wait_minutes = max(0, (next_time - now) // 60)
        
        if wait_minutes > 0:
            return False, f"每小时只能钓{config.fishing_limit_per_hour}次鱼，请等待{wait_minutes}分钟后重试"
        else:
            return False, f"每小时只能钓{config.fishing_limit_per_hour}次鱼"
    
    return True, ""

def update_global_stats():
    """更新全局统计数据"""
    data = load_global_data()
    today = datetime.now().strftime("%Y-%m-d")
    
    # 如果是新的一天，重置今日统计
    if data.get("last_update_date") != today:
        data["today_fishing_count"] = 0
        data["today_air_count"] = 0
        data["today_treasure_count"] = 0
        data["last_update_date"] = today
    
    save_global_data(data)

def do_fishing() -> Tuple[str, str, str]:
    """执行钓鱼，返回(结果类型, 物品类型, 物品名称)"""
    rand = random.random()
    
    if rand < config.probability_air:
        return "air", "air", "空军"
    elif rand < config.probability_air + config.probability_trash:
        # 随机获取垃圾
        trash_item = get_random_trash()
        trash_type = trash_item.get("type", "base")
        trash_name = trash_item.get("name", "未知垃圾")
        
        # 如果是特殊垃圾，更新其被钓到的次数
        if trash_type == "special":
            trash_id = trash_item.get("id")
            update_special_trash_stats(trash_id)
        
        return "trash", trash_type, trash_name
    elif rand < config.probability_air + config.probability_trash + config.probability_fish:
        item = random.choice(config.fish_items)
        return "fish", "fish", item
    else:
        item = random.choice(config.treasure_items)
        return "treasure", "treasure", item

def update_special_trash_stats(trash_id: int):
    """更新特殊垃圾的统计信息"""
    special_trash = load_special_trash()
    
    for trash in special_trash:
        if trash["id"] == trash_id:
            trash["fished_count"] = trash.get("fished_count", 0) + 1
            trash["last_fished_time"] = int(time.time())
            break
    
    save_special_trash(special_trash)

def update_user_stats(user_id: str, result_type: str, item_type: str, item_name: str) -> Dict:
    """更新用户统计数据"""
    data = load_user_data(user_id)
    
    # 更新总次数
    data["total_count"] = data.get("total_count", 0) + 1
    
    # 添加当前时间戳
    now = int(time.time())
    if "last_fishing_time" not in data:
        data["last_fishing_time"] = []
    data["last_fishing_time"].append(now)
    
    # 根据结果类型更新统计数据
    if result_type == "air":
        data["air_count"] = data.get("air_count", 0) + 1
    elif result_type == "trash":
        data["trash_count"] = data.get("trash_count", 0) + 1
        
        if item_type == "special":
            # 特殊垃圾统计
            data["special_trash_count"] = data.get("special_trash_count", 0) + 1
            
            if "special_trash_details" not in data:
                data["special_trash_details"] = {}
            data["special_trash_details"][item_name] = data["special_trash_details"].get(item_name, 0) + 1
        else:
            # 基础垃圾统计
            if "trash_details" not in data:
                data["trash_details"] = {}
            data["trash_details"][item_name] = data["trash_details"].get(item_name, 0) + 1
    elif result_type == "fish":
        data["fish_count"] = data.get("fish_count", 0) + 1
        # 更新鱼类详细统计
        if "fish_details" not in data:
            data["fish_details"] = {}
        data["fish_details"][item_name] = data["fish_details"].get(item_name, 0) + 1
    elif result_type == "treasure":
        data["treasure_count"] = data.get("treasure_count", 0) + 1
        # 更新宝物详细统计
        if "treasure_details" not in data:
            data["treasure_details"] = {}
        data["treasure_details"][item_name] = data["treasure_details"].get(item_name, 0) + 1
    
    # 保存数据
    if save_user_data(user_id, data):
        return data
    else:
        raise Exception("保存用户数据失败")

def get_result_message(result_type: str, item_type: str, item_name: str, user_data: Dict) -> str:
    """生成结果消息"""
    messages = {
        "air": [
            "哎呀，什么都没钓到！水面平静得像镜子一样。",
            "鱼饵被吃光了，但鱼却没上钩。",
            "今天的鱼儿似乎都很聪明，一条都没钓到。",
            "渔线轻轻动了一下，但提起时却空无一物。",
            "耐心等待了很久，结果还是一无所获。"
        ],
        "trash_base": [
            f"钓到了一个{item_name}，真是让人哭笑不得。",
            f"没想到钓上来的竟然是{item_name}，看来水里有不少垃圾。",
            f"收获了一个{item_name}，虽然不是鱼，但也算是清理了水域。",
            f"提起钓竿，发现钩子上挂着{item_name}，有点失望。"
        ],
        "trash_special": [
            f"🎉 喜报：钓到了群友搬的石！\n{item_name}",
            f"🎉 意外之喜！钓到了群友的石\n{item_name}",
            f"🎉 不得了！钓到了群友的特殊贡献：\n{item_name}",
            f"🎉 惊喜！钓到了群友的创意垃圾：\n{item_name}"
        ],
        "fish": [
            f"钓到了一条{item_name}！今晚可以加餐了！",
            f"一条漂亮的{item_name}上钩了！收获不错！",
            f"经过耐心等待，终于钓到了一条{item_name}！",
            f"{item_name}在阳光下闪闪发光，真是个不错的收获！"
        ],
        "treasure": [
            f"哇！竟然钓到了{item_name}！发大财了！",
            f"金光闪闪的{item_name}！这可是稀有宝物！",
            f"不敢相信！钓竿竟然勾住了{item_name}！",
            f"传说中的{item_name}被你钓到了！运气爆棚！"
        ]
    }
    
    # 选择消息类型
    if result_type == "air":
        msg_type = "air"
    elif result_type == "trash":
        msg_type = "trash_special" if item_type == "special" else "trash_base"
    elif result_type == "fish":
        msg_type = "fish"
    else:  # treasure
        msg_type = "treasure"
    
    # 获取随机消息
    base_msg = random.choice(messages.get(msg_type, ["钓鱼结束"]))
    
    # 添加统计信息
    stats_msg = f"\n\n📊 本次钓鱼结果：{item_name}"
    
    if result_type == "air":
        stats_msg += f"\n🎣 空军次数：{user_data.get('air_count', 0)}次"
    elif result_type == "trash":
        if item_type == "special":
            stats_msg += f"\n🎉 特殊垃圾总数：{user_data.get('special_trash_count', 0)}个"
        else:
            stats_msg += f"\n🗑️ 垃圾总数：{user_data.get('trash_count', 0)}个"
    elif result_type == "fish":
        stats_msg += f"\n🐟 钓到鱼总数：{user_data.get('fish_count', 0)}条"
    elif result_type == "treasure":
        stats_msg += f"\n💰 宝物总数：{user_data.get('treasure_count', 0)}个"
    
    stats_msg += f"\n🎣 总钓鱼次数：{user_data.get('total_count', 0)}次"
    
    # 计算剩余次数
    now = int(time.time())
    hour_ago = now - 3600
    recent_times = [t for t in user_data.get("last_fishing_time", []) if t > hour_ago]
    remaining = config.fishing_limit_per_hour - len(recent_times)
    
    if remaining > 0:
        stats_msg += f"\n⏰ 本小时还可钓鱼次数：{remaining}次"
    else:
        oldest_time = min(recent_times) if recent_times else 0
        wait_time = (oldest_time + 3600 - now) // 60
        stats_msg += f"\n⏰ 下次可钓鱼：{wait_time}分钟后"
    
    return base_msg + stats_msg

# 命令处理器
fish = on_command("fish", aliases={"钓鱼", "钓"}, priority=5, block=True)

@fish.handle()
async def handle_fish(event: Event):
    """处理钓鱼命令"""
    user_id = get_user_id(event)
    nickname = get_user_nickname(event)
    
    # 检查是否可以钓鱼
    can_fish_result, msg = can_fish(user_id)
    if not can_fish_result:
        await fish.finish(msg)
    
    # 更新全局统计
    update_global_stats()
    
    # 执行钓鱼
    result_type, item_type, item_name = do_fishing()
    
    try:
        # 更新用户数据
        user_data = update_user_stats(user_id, result_type, item_type, item_name)
        
        # 更新全局今日统计
        global_data = load_global_data()
        global_data["total_fishing_count"] = global_data.get("total_fishing_count", 0) + 1
        global_data["today_fishing_count"] = global_data.get("today_fishing_count", 0) + 1
        
        if result_type == "air":
            global_data["today_air_count"] = global_data.get("today_air_count", 0) + 1
        elif result_type == "treasure":
            global_data["today_treasure_count"] = global_data.get("today_treasure_count", 0) + 1
        
        save_global_data(global_data)
        
        # 生成结果消息
        result_msg = get_result_message(result_type, item_type, item_name, user_data)
        await fish.send(MessageSegment.text(result_msg))
        
    except Exception as e:
        logger.error(f"钓鱼处理失败: {e}")
        await fish.finish("钓鱼时发生了未知错误，请稍后重试")

# 添加特殊垃圾命令
add_trash = on_command("add_trash", aliases={"添加垃圾", "添加特殊垃圾"}, priority=5, block=True)

@add_trash.handle()
async def handle_add_trash(event: Event, message: Message = CommandArg()):
    """添加特殊垃圾"""
    trash_name = message.extract_plain_text().strip()
    
    if not trash_name:
        await add_trash.finish("请提供要添加的垃圾名称，格式：/add_trash 垃圾名称")
    
    user_id = get_user_id(event)
    nickname = get_user_nickname(event)
    
    success, result_msg = add_special_trash(trash_name, user_id, nickname)
    
    await add_trash.finish(result_msg)

# 查看特殊垃圾列表命令
list_trash = on_command("list_trash", aliases={"特殊垃圾", "查看垃圾"}, priority=5, block=True)

@list_trash.handle()
async def handle_list_trash(event: Event):
    """查看特殊垃圾列表"""
    special_trash = load_special_trash()
    
    if not special_trash:
        await list_trash.finish("当前没有特殊垃圾，使用 /add_trash 垃圾名称 来添加吧！")
    
    # 构建消息
    msg = MessageSegment.text("🗑️ 特殊垃圾列表\n")
    msg += MessageSegment.text("=" * 30 + "\n")
    
    for i, trash in enumerate(special_trash, 1):
        added_time = time.strftime("%Y-%m-%d", time.localtime(trash.get("added_time", 0)))
        fished_count = trash.get("fished_count", 0)
        added_by = trash.get("added_nickname", trash.get("added_by", "未知"))
        
        msg += MessageSegment.text(f"{i}. {trash['name']}\n")
        msg += MessageSegment.text(f"   添加者：{added_by} | 添加时间：{added_time}\n")
        msg += MessageSegment.text(f"   被钓次数：{fished_count}次\n")
        
        if i < len(special_trash):
            msg += MessageSegment.text("   " + "-"*20 + "\n")
    
    msg += MessageSegment.text(f"\n📊 共 {len(special_trash)} 个特殊垃圾")
    msg += MessageSegment.text(f"\n⚖️ 特殊垃圾出现权重：{config.special_trash_weight*100:.0f}%")
    
    await list_trash.send(msg)

# 删除特殊垃圾命令
del_trash = on_command("del_trash", aliases={"删除垃圾", "移除垃圾"}, priority=5, block=True)

@del_trash.handle()
async def handle_del_trash(event: Event, message: Message = CommandArg()):
    """删除特殊垃圾"""
    trash_id_str = message.extract_plain_text().strip()
    
    if not trash_id_str:
        await del_trash.finish("请提供要删除的垃圾ID，格式：/del_trash 序号\n使用 /list_trash 查看所有特殊垃圾")
    
    try:
        trash_id = int(trash_id_str)
    except ValueError:
        await del_trash.finish("垃圾ID必须是数字，格式：/del_trash 序号")
    
    success, result_msg = delete_special_trash(trash_id)
    await del_trash.finish(result_msg)

# 查看个人记录命令
fish_record = on_command("fish_record", aliases={"钓鱼记录", "我的钓鱼"}, priority=5, block=True)

@fish_record.handle()
async def handle_fish_record(event: Event):
    """查看个人钓鱼记录"""
    user_id = get_user_id(event)
    nickname = get_user_nickname(event)
    
    data = load_user_data(user_id)
    
    if data["total_count"] == 0:
        await fish_record.finish(f"{nickname}还没有钓过鱼呢！快来试试/fish吧！")
    
    # 构建消息
    msg = MessageSegment.text(f"🎣 {nickname}的钓鱼记录\n")
    msg += MessageSegment.text("=" * 20 + "\n")
    
    # 基本信息
    msg += MessageSegment.text(f"总钓鱼次数：{data['total_count']}次\n")
    msg += MessageSegment.text(f"空军次数：{data.get('air_count', 0)}次\n")
    msg += MessageSegment.text(f"钓到普通垃圾：{data.get('trash_count', 0) - data.get('special_trash_count', 0)}次\n")
    msg += MessageSegment.text(f"钓到特殊垃圾：{data.get('special_trash_count', 0)}次\n")
    msg += MessageSegment.text(f"钓到鱼：{data.get('fish_count', 0)}次\n")
    msg += MessageSegment.text(f"钓到宝物：{data.get('treasure_count', 0)}次\n\n")
    
    # 详细统计
    if data.get("special_trash_details"):
        msg += MessageSegment.text("🎉 特殊垃圾详情：\n")
        for trash_name, count in sorted(data["special_trash_details"].items(), key=lambda x: x[1], reverse=True)[:3]:
            msg += MessageSegment.text(f"  {trash_name}：{count}次\n")
        msg += MessageSegment.text("\n")
    
    if data.get("fish_details"):
        msg += MessageSegment.text("🐟 鱼类详情：\n")
        for fish_name, count in sorted(data["fish_details"].items(), key=lambda x: x[1], reverse=True)[:3]:
            msg += MessageSegment.text(f"  {fish_name}：{count}次\n")
        msg += MessageSegment.text("\n")
    
    if data.get("treasure_details"):
        msg += MessageSegment.text("💰 宝物详情：\n")
        for treasure, count in sorted(data["treasure_details"].items(), key=lambda x: x[1], reverse=True)[:3]:
            msg += MessageSegment.text(f"  {treasure}：{count}次\n")
        msg += MessageSegment.text("\n")
    
    # 计算当前时段剩余次数
    now = int(time.time())
    hour_ago = now - 3600
    recent_times = [t for t in data.get("last_fishing_time", []) if t > hour_ago]
    remaining = config.fishing_limit_per_hour - len(recent_times)
    
    if remaining > 0:
        msg += MessageSegment.text(f"⏰ 本小时还可钓鱼次数：{remaining}次\n")
    else:
        oldest_time = min(recent_times) if recent_times else 0
        wait_time = (oldest_time + 3600 - now) // 60
        msg += MessageSegment.text(f"⏰ 下次可钓鱼：{wait_time}分钟后\n")
    
    await fish_record.send(msg)

# 排行榜命令
fish_rank = on_command("fish_rank", aliases={"钓鱼榜", "钓鱼排行"}, priority=5, block=True)

@fish_rank.handle()
async def handle_fish_rank(event: Event):
    """查看钓鱼排行榜"""
    global_data = load_global_data()
    special_trash = load_special_trash()
    
    msg = MessageSegment.text("🎣 钓鱼排行榜\n")
    msg += MessageSegment.text("=" * 20 + "\n")
    msg += MessageSegment.text(f"📅 今日统计：\n")
    msg += MessageSegment.text(f"  全服钓鱼次数：{global_data.get('today_fishing_count', 0)}次\n")
    msg += MessageSegment.text(f"  今日空军次数：{global_data.get('today_air_count', 0)}次\n")
    msg += MessageSegment.text(f"  今日宝物次数：{global_data.get('today_treasure_count', 0)}次\n\n")
    msg += MessageSegment.text(f"📈 历史总统计：\n")
    msg += MessageSegment.text(f"  全服总钓鱼次数：{global_data.get('total_fishing_count', 0)}次\n")
    
    if special_trash:
        # 找出最常被钓到的特殊垃圾
        sorted_trash = sorted(special_trash, key=lambda x: x.get("fished_count", 0), reverse=True)[:5]
        
        msg += MessageSegment.text(f"\n🎉 热门特殊垃圾：\n")
        for trash in sorted_trash:
            msg += MessageSegment.text(f"  {trash['name']}：{trash.get('fished_count', 0)}次\n")
    
    await fish_rank.send(msg)

# 帮助命令
fish_help = on_command("fish_help", aliases={"钓鱼帮助"}, priority=5, block=True)

@fish_help.handle()
async def handle_fish_help():
    """显示钓鱼帮助"""
    msg = MessageSegment.text("🎣 钓鱼插件使用说明\n")
    msg += MessageSegment.text("=" * 20 + "\n")
    msg += MessageSegment.text(f"🎯 命令列表：\n")
    msg += MessageSegment.text(f"  /fish - 进行一次钓鱼\n")
    msg += MessageSegment.text(f"  /fish_record - 查看个人钓鱼记录\n")
    msg += MessageSegment.text(f"  /fish_rank - 查看钓鱼排行榜\n")
    msg += MessageSegment.text(f"  /add_trash 名称 - 添加特殊垃圾\n")
    # msg += MessageSegment.text(f"  /list_trash - 查看所有特殊垃圾\n")
    # msg += MessageSegment.text(f"  /del_trash 序号 - 删除特殊垃圾\n")
    msg += MessageSegment.text(f"  /fish_help - 显示此帮助\n\n")
    # msg += MessageSegment.text(f"📊 钓鱼概率：\n")
    # msg += MessageSegment.text(f"  空军：{config.probability_air*100:.0f}%\n")
    # msg += MessageSegment.text(f"  垃圾：{config.probability_trash*100:.0f}%\n")
    # msg += MessageSegment.text(f"  鱼：{config.probability_fish*100:.0f}%\n")
    # msg += MessageSegment.text(f"  宝物：{config.probability_treasure*100:.0f}%\n")
    # msg += MessageSegment.text(f"  特殊垃圾权重：{config.special_trash_weight*100:.0f}%\n\n")
    msg += MessageSegment.text(f"⏰ 限制说明：\n")
    msg += MessageSegment.text(f"  每人每小时最多可钓鱼{config.fishing_limit_per_hour}次\n")
    msg += MessageSegment.text(f"  特殊垃圾数量限制：{config.max_special_trash_count}个\n")
    
    await fish_help.send(msg)