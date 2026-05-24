from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata
import random
import time
import json
import math
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageSegment, Event, GroupMessageEvent, PrivateMessageEvent
from nonebot.params import CommandArg
from nonebot.log import logger

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="fishing",
    description="模拟钓鱼插件",
    usage="""
钓鱼: /fish [地点]
查看钓鱼记录: /fish_record
查看排行榜: /fish_rank
添加特殊垃圾: /add_trash 垃圾名称
查看特殊垃圾: /list_trash
删除特殊垃圾: /del_trash 序号
添加自定义宝藏: /add_treasure 宝藏名称 价格(20-100)
查看自定义宝藏: /list_treasure
删除自定义宝藏: /del_treasure 序号
钓鱼帮助: /fish_help
当前季节: /season
""",
    config=Config,
)

config = get_plugin_config(Config)

# 导入 file_edit 插件
from nonebot import require
require("plugins.file_edit")
require("plugins.coin")
# 注意：这里导入的 get_coins 和 get_user_info 签名必须与您的 coin 插件实际导出一致
from plugins.coin import get_coins, get_user_info, consume_coins
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
    "custom_treasure": f"{FISHING_ROOT}/custom_treasure.json",  # 自定义宝藏文件
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

# 自定义宝藏管理
def save_custom_treasure(treasure_list: List[Dict[str, Any]]) -> bool:
    """保存自定义宝藏列表"""
    try:
        write_file(DATA_FILES["custom_treasure"], json.dumps(treasure_list, ensure_ascii=False, indent=2))
        return True
    except Exception as e:
        logger.error(f"保存自定义宝藏失败: {e}")
        return False

def load_custom_treasure() -> List[Dict[str, Any]]:
    """加载自定义宝藏列表（只加载未被钓走的）"""
    try:
        data = read_file(DATA_FILES["custom_treasure"])
        if data:
            all_treasure = json.loads(data)
            # 只返回未被钓走的宝藏
            return [t for t in all_treasure if not t.get("fished", False)]
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
    
    # 初始化自定义宝藏文件
    try:
        custom_treasure = load_custom_treasure()
        if custom_treasure is None:
            # 创建空的自定义宝藏列表
            save_custom_treasure([])
    except:
        save_custom_treasure([])

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
    
    # 直接从所有垃圾中随机选择
    return random.choice(all_trash)

def get_all_treasure_items() -> List[Dict[str, Any]]:
    """获取所有宝藏物品（基础宝藏 + 自定义宝藏）"""
    # 基础宝藏
    base_treasure = []
    for item in config.base_treasure_items:
        base_treasure.append({
            "name": item["name"],
            "type": "base",
            "value": random.randint(config.treasure_value_range[0], config.treasure_value_range[1])
        })
    
    # 自定义宝藏（只包含未被钓走的）
    custom_treasure = load_custom_treasure()
    
    return base_treasure + custom_treasure

def get_random_treasure() -> Optional[Dict[str, Any]]:
    """随机获取一个宝藏（基础宝藏或自定义宝藏）"""
    all_treasure = get_all_treasure_items()
    
    if not all_treasure:
        return None
    
    return random.choice(all_treasure)

def calculate_fish_value(fish_detail: Dict) -> int:
    """计算鱼的价值
    鱼重 = 平均重量 * 0.8 ~ 1.2 随机波动
    价值 = 鱼重 * 每斤价格，四舍五入取整
    """
    avg_weight = fish_detail["avg_weight"]
    price_per_jin = fish_detail["price_per_jin"]
    # 随机波动 0.8 ~ 1.2
    weight = avg_weight * (0.8 + 0.4 * random.random())
    value = weight * price_per_jin
    return int(round(value))

# 季节相关函数
def get_current_season() -> str:
    """获取当前季节"""
    return config.get_current_season()

def get_season_display_name(season: str) -> str:
    """获取季节的显示名称"""
    season_names = {
        "spring": "春季",
        "summer": "夏季", 
        "autumn": "秋季",
        "winter": "冬季"
    }
    return season_names.get(season, "未知季节")

# 钓鱼地点相关函数
def get_fishing_spot_display_name(spot: str) -> str:
    """获取钓鱼地点的显示名称"""
    spot_names = {
        "pond": "池塘",
        "sea": "海洋", 
        "river": "河流"
    }
    return spot_names.get(spot, "未知地点")

def validate_fishing_spot(spot: str) -> Tuple[bool, str]:
    """验证钓鱼地点是否有效"""
    valid_spots = ["pond", "sea", "river"]
    if spot in valid_spots:
        return True, spot
    return False, config.default_fishing_spot

def parse_fishing_spot_arg(arg: str) -> str:
    """解析钓鱼地点参数"""
    spot_mapping = {
        "池塘": "pond", "pond": "pond", "默认": "pond", "普通": "pond",
        "海钓": "sea", "海洋": "sea", "sea": "sea", "大海": "sea",
        "河钓": "river", "河流": "river", "river": "river", "小河": "river"
    }
    return spot_mapping.get(arg.lower(), config.default_fishing_spot)

# 修改原有的鱼类相关函数
def get_fish_by_season_and_spot(season: str, spot: str) -> List[Dict]:
    """根据季节和地点获取符合条件的鱼类"""
    current_fishes = []
    
    for fish in config.fish_details:
        # 检查栖息地
        if spot not in fish.habitats:
            continue
        
        # 检查季节
        if season not in fish.seasons:
            continue
        
        current_fishes.append(fish)
    
    return current_fishes

def get_random_fish_by_spot(spot: str) -> Tuple[Optional[str], int]:
    """根据钓鱼地点随机获取一条鱼，返回鱼的名字和价值"""
    # 获取当前季节
    current_season = get_current_season()
    
    # 获取符合条件的鱼类
    available_fishes = get_fish_by_season_and_spot(current_season, spot)
    
    if not available_fishes:
        # 如果没有符合条件的鱼，返回None
        return None, 0
    
    # 计算总概率
    total_prob = sum(fish.probability for fish in available_fishes)
    if total_prob <= 0:
        return None, 0
    
    # 根据概率随机选择一条鱼
    rand_val = random.random() * total_prob
    cumulative = 0.0
    selected_fish = None
    
    for fish in available_fishes:
        cumulative += fish.probability
        if rand_val <= cumulative:
            selected_fish = fish
            break
    
    if selected_fish is None:
        return None, 0
    
    # 计算价值
    fish_detail = {
        "name": selected_fish.name,
        "avg_weight": selected_fish.avg_weight,
        "price_per_jin": selected_fish.price_per_jin
    }
    value = calculate_fish_value(fish_detail)
    
    return selected_fish.name, value

# 修改钓鱼核心函数
def do_fishing_by_spot(spot: str) -> Tuple[str, str, str, int]:
    """根据指定地点执行钓鱼，返回(结果类型, 物品类型, 物品名称, 获得银币)"""
    # 获取当前地点的概率配置
    spot_prob = config.fishing_spots.get(spot, config.fishing_spots["pond"])
    
    probability_air = spot_prob.get("probability_air", 0.3)
    probability_trash = spot_prob.get("probability_trash", 0.35)
    probability_fish = spot_prob.get("probability_fish", 0.3)
    probability_treasure = spot_prob.get("probability_treasure", 0.05)
    
    rand = random.random()
    
    if rand < probability_air:
        return "air", "air", "空军", 0
    elif rand < probability_air + probability_trash:
        # 随机获取垃圾
        trash_item = get_random_trash()
        trash_type = trash_item.get("type", "base")
        trash_name = trash_item.get("name", "未知垃圾")
        
        # 如果是特殊垃圾，更新其被钓到的次数
        if trash_type == "special":
            trash_id = trash_item.get("id")
            update_special_trash_stats(trash_id)
        
        return "trash", trash_type, trash_name, config.trash_normal_value
    elif rand < probability_air + probability_trash + probability_fish:
        # 钓到鱼
        fish_name, fish_value = get_random_fish_by_spot(spot)
        if fish_name is None:
            # 如果没有钓到鱼，默认给一个基础值
            return "fish", "fish", "未知的鱼", config.fish_normal_value
        
        return "fish", "fish", fish_name, fish_value
    else:
        # 钓到宝藏
        treasure = get_random_treasure()
        if treasure is None:
            # 没有宝藏，默认给一个基础宝藏
            base_treasure = random.choice(config.base_treasure_items)
            treasure_name = base_treasure["name"]
            treasure_value = random.randint(config.treasure_value_range[0], config.treasure_value_range[1])
            treasure_type = "base"
        else:
            treasure_name = treasure["name"]
            treasure_type = treasure["type"]
            if treasure_type == "custom":
                treasure_value = treasure["value"]
                # 标记为已被钓走
                mark_treasure_as_fished(treasure["id"], "system")
            else:
                treasure_value = treasure["value"]
        
        return "treasure", treasure_type, treasure_name, treasure_value

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
        "type": "special",  # 明确标记为特殊垃圾
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

def add_custom_treasure(treasure_name: str, value: int, added_by: str, added_nickname: str) -> Tuple[bool, str]:
    """添加自定义宝藏"""
    # 检查宝藏名称是否为空
    if not treasure_name or treasure_name.strip() == "":
        return False, "宝藏名称不能为空"
    
    treasure_name = treasure_name.strip()
    
    # 检查长度限制
    if len(treasure_name) > 100:
        return False, "宝藏名称太长了，请控制在100个字符以内"
    
    # 检查价值范围
    min_val, max_val = config.treasure_value_range
    if value < min_val or value > max_val:
        return False, f"宝藏价值必须在{min_val}到{max_val}之间"
    
    # 加载现有自定义宝藏
    custom_treasure = load_custom_treasure()
    # 注意：load_custom_treasure只返回未被钓走的，我们需要加载全部来判断名称重复
    try:
        all_treasure_data = read_file(DATA_FILES["custom_treasure"])
        if all_treasure_data:
            all_custom_treasure = json.loads(all_treasure_data)
        else:
            all_custom_treasure = []
    except:
        all_custom_treasure = []
    
    # 检查是否已达到数量限制
    if len(all_custom_treasure) >= config.max_custom_treasure_count:
        return False, f"自定义宝藏数量已达到上限({config.max_custom_treasure_count}个)，无法添加更多"
    
    # 检查是否已存在相同的宝藏（包括已被钓走的）
    for treasure in all_custom_treasure:
        if treasure["name"] == treasure_name:
            return False, f"自定义宝藏 '{treasure_name}' 已存在"
    
    # 检查是否是基础宝藏
    for base_treasure in config.base_treasure_items:
        if base_treasure["name"] == treasure_name:
            return False, f"'{treasure_name}' 已经是基础宝藏了"
    
    # 添加新宝藏
    new_treasure = {
        "id": len(all_custom_treasure) + 1,
        "name": treasure_name,
        "type": "custom",
        "value": value,
        "added_by": added_by,
        "added_nickname": added_nickname,
        "added_time": int(time.time()),
        "fished": False,  # 是否已被钓走
        "fished_by": None,  # 被谁钓走
        "fished_time": None  # 被钓走的时间
    }
    
    all_custom_treasure.append(new_treasure)
    
    if save_custom_treasure(all_custom_treasure):
        return True, f"成功添加自定义宝藏: {treasure_name}，价值{value}银币"
    else:
        return False, "保存自定义宝藏失败"

def mark_treasure_as_fished(treasure_id: int, user_id: str) -> bool:
    """标记宝藏为已被钓走"""
    try:
        all_treasure_data = read_file(DATA_FILES["custom_treasure"])
        if all_treasure_data:
            all_custom_treasure = json.loads(all_treasure_data)
        else:
            all_custom_treasure = []
    except:
        all_custom_treasure = []
    
    for treasure in all_custom_treasure:
        if treasure["id"] == treasure_id and not treasure.get("fished", False):
            treasure["fished"] = True
            treasure["fished_by"] = user_id
            treasure["fished_time"] = int(time.time())
            return save_custom_treasure(all_custom_treasure)
    
    return False

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

def delete_custom_treasure(treasure_id: int) -> Tuple[bool, str]:
    """删除自定义宝藏（只能删除未被钓走的）"""
    try:
        all_treasure_data = read_file(DATA_FILES["custom_treasure"])
        if all_treasure_data:
            all_custom_treasure = json.loads(all_treasure_data)
        else:
            all_custom_treasure = []
    except:
        all_custom_treasure = []
    
    for i, treasure in enumerate(all_custom_treasure):
        if treasure["id"] == treasure_id:
            if treasure.get("fished", False):
                return False, "该宝藏已被钓走，无法删除"
            
            treasure_name = treasure["name"]
            del all_custom_treasure[i]
            
            # 重新编号
            for j, t in enumerate(all_custom_treasure):
                t["id"] = j + 1
            
            if save_custom_treasure(all_custom_treasure):
                return True, f"已删除自定义宝藏: {treasure_name}"
            else:
                return False, "保存自定义宝藏列表失败"
    
    return False, f"未找到ID为 {treasure_id} 的自定义宝藏"

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
            user_data = json.loads(data)
            # 关键：检查并初始化新版本可能缺失的字段，确保向前兼容
            if "spot_stats" not in user_data:
                user_data["spot_stats"] = {}
            # 确保基础字段存在
            user_data.setdefault("user_id", user_id)
            user_data.setdefault("total_count", 0)
            user_data.setdefault("last_fishing_time", [])
            user_data.setdefault("air_count", 0)
            user_data.setdefault("fish_count", 0)
            user_data.setdefault("treasure_count", 0)
            user_data.setdefault("trash_count", 0)
            user_data.setdefault("special_trash_count", 0)
            user_data.setdefault("fish_details", {})
            user_data.setdefault("trash_details", {})
            user_data.setdefault("special_trash_details", {})
            user_data.setdefault("treasure_details", {})
            user_data.setdefault("total_coin_earned", 0)
            user_data.setdefault("treasure_owned", [])
            return user_data
    except Exception as e:
        logger.warning(f"加载用户 {user_id} 数据失败或格式旧，使用默认值: {e}")
    
    # 返回默认数据 (新版本完整结构)
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
        "treasure_details": {},  # 每种宝物的详细数量
        "total_coin_earned": 0,  # 通过钓鱼获得的总银币
        "treasure_owned": [],  # 拥有的宝藏（自定义宝藏）
        "spot_stats": {}  # 新增：按地点统计
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
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 如果是新的一天，重置今日统计
    if data.get("last_update_date") != today:
        data["today_fishing_count"] = 0
        data["today_air_count"] = 0
        data["today_treasure_count"] = 0
        data["last_update_date"] = today
    
    save_global_data(data)

def update_special_trash_stats(trash_id: int):
    """更新特殊垃圾的统计信息"""
    special_trash = load_special_trash()
    
    for trash in special_trash:
        if trash["id"] == trash_id:
            trash["fished_count"] = trash.get("fished_count", 0) + 1
            trash["last_fished_time"] = int(time.time())
            break
    
    save_special_trash(special_trash)

def update_user_stats(user_id: str, spot: str, result_type: str, item_type: str, item_name: str, coin_earned: int) -> Dict:
    """更新用户统计数据（增加地点统计）"""
    data = load_user_data(user_id)
    
    # 更新总次数
    data["total_count"] = data.get("total_count", 0) + 1
    
    # 关键：安全地更新地点统计，确保 spot_stats 字段存在
    if "spot_stats" not in data:
        data["spot_stats"] = {}
    if spot not in data["spot_stats"]:
        data["spot_stats"][spot] = {
            "count": 0,
            "air_count": 0,
            "fish_count": 0,
            "treasure_count": 0,
            "trash_count": 0
        }
    
    data["spot_stats"][spot]["count"] += 1
    
    # 添加当前时间戳
    now = int(time.time())
    if "last_fishing_time" not in data:
        data["last_fishing_time"] = []
    data["last_fishing_time"].append(now)
    
    # 更新获得的银币总数
    data["total_coin_earned"] = data.get("total_coin_earned", 0) + coin_earned
    
    # 根据结果类型更新统计数据
    if result_type == "air":
        data["air_count"] = data.get("air_count", 0) + 1
        data["spot_stats"][spot]["air_count"] += 1
    elif result_type == "trash":
        data["trash_count"] = data.get("trash_count", 0) + 1
        data["spot_stats"][spot]["trash_count"] += 1
        
        if item_type == "special":
            data["special_trash_count"] = data.get("special_trash_count", 0) + 1
            if "special_trash_details" not in data:
                data["special_trash_details"] = {}
            data["special_trash_details"][item_name] = data["special_trash_details"].get(item_name, 0) + 1
        else:
            if "trash_details" not in data:
                data["trash_details"] = {}
            data["trash_details"][item_name] = data["trash_details"].get(item_name, 0) + 1
    elif result_type == "fish":
        data["fish_count"] = data.get("fish_count", 0) + 1
        data["spot_stats"][spot]["fish_count"] += 1
        
        if "fish_details" not in data:
            data["fish_details"] = {}
        data["fish_details"][item_name] = data["fish_details"].get(item_name, 0) + 1
    elif result_type == "treasure":
        data["treasure_count"] = data.get("treasure_count", 0) + 1
        data["spot_stats"][spot]["treasure_count"] += 1
        
        if "treasure_details" not in data:
            data["treasure_details"] = {}
        data["treasure_details"][item_name] = data["treasure_details"].get(item_name, 0) + 1
        
        if item_type == "custom":
            if "treasure_owned" not in data:
                data["treasure_owned"] = []
            treasure_info = {
                "name": item_name,
                "value": coin_earned,
                "time": now
            }
            data["treasure_owned"].append(treasure_info)
    
    # 保存数据
    if save_user_data(user_id, data):
        return data
    else:
        raise Exception("保存用户数据失败")

def get_result_message(spot: str, result_type: str, item_type: str, item_name: str, coin_earned: int, user_data: Dict) -> str:
    """生成结果消息（增加地点信息）"""
    spot_name = get_fishing_spot_display_name(spot)
    
    messages = {
        "air": [
            f"在{spot_name}钓鱼，什么都没钓到！水面平静得像镜子一样。",
            f"在{spot_name}钓鱼，鱼饵被吃光了，但鱼却没上钩。",
            f"今天{spot_name}的鱼儿似乎都很聪明，一条都没钓到。",
            f"在{spot_name}耐心等待了很久，结果还是一无所获。"
        ],
        "trash_base": [
            f"在{spot_name}钓到了一个{item_name}，真是让人哭笑不得。",
            f"在{spot_name}钓鱼，没想到钓上来的竟然是{item_name}，看来水里有不少垃圾。",
            f"在{spot_name}收获了一个{item_name}，虽然不是鱼，但也算是清理了水域。",
            f"在{spot_name}提起钓竿，发现钩子上挂着{item_name}，有点失望。"
        ],
        "trash_special": [
            f"🎉 在{spot_name}钓到了群友搬的石！\n{item_name}",
            f"在{spot_name}钓到了一个{item_name}，真是让人哭笑不得。",
            f"🎉 在{spot_name}好消息！钓到了{item_name}！",
            f"🎉 在{spot_name}钓到了创意垃圾：\n{item_name}"
        ],
        "fish": [
            f"在{spot_name}钓到了一条{item_name}！今晚可以加餐了！",
            f"在{spot_name}钓鱼，一条漂亮的{item_name}上钩了！收获不错！",
            f"在{spot_name}经过耐心等待，终于钓到了一条{item_name}！",
            f"在{spot_name}钓上鱼了，{item_name}在阳光下闪闪发光，真是个不错的收获！"
        ],
        "treasure": [
            f"哇！竟然在{spot_name}钓到了{item_name}！发大财了！",
            f"在{spot_name}钓上了金光闪闪的{item_name}！这可是稀有宝物！",
            f"在{spot_name}钓到东西了，不敢相信！钓竿竟然勾住了{item_name}！",
            f"传说中的{item_name}被你在{spot_name}钓到了！运气爆棚！"
        ]
    }
    
    # 选择消息类型
    if result_type == "air":
        msg_type = "air"
    elif result_type == "trash":
        msg_type = "trash_special" if item_type == "special" else "trash_base"
    elif result_type == "fish":
        msg_type = "fish"
    else:
        msg_type = "treasure"
    
    # 获取随机消息
    base_msg = random.choice(messages.get(msg_type, ["钓鱼结束"]))
    
    # 添加货币信息
    if coin_earned > 0:
        base_msg += f"\n💰 获得银币: {coin_earned}枚"
    
    # 添加统计信息
    current_season = get_current_season()
    season_name = get_season_display_name(current_season)
    
    stats_msg = f"\n\n📊 本次钓鱼结果：{item_name}"
    stats_msg += f"\n📍 钓鱼地点：{spot_name}"
    stats_msg += f"\n🍂 当前季节：{season_name}"
    
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
        if item_type == "custom":
            stats_msg += f"\n🎁 这是自定义宝藏，现已归你所有！"
    
    stats_msg += f"\n🎣 总钓鱼次数：{user_data.get('total_count', 0)}次"
    stats_msg += f"\n💰 钓鱼总收益：{user_data.get('total_coin_earned', 0)}银币"
    
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
async def handle_fish(event: Event, message: Message = CommandArg()):
    """处理钓鱼命令，支持指定地点"""
    user_id = get_user_id(event)
    nickname = get_user_nickname(event)
    message_id = event.message_id if hasattr(event, 'message_id') else None
    
    # 解析参数
    arg_text = message.extract_plain_text().strip()
    
    # 确定钓鱼地点
    if arg_text:
        spot = parse_fishing_spot_arg(arg_text)
    else:
        spot = config.default_fishing_spot
    
    # 验证钓鱼地点
    is_valid, final_spot = validate_fishing_spot(spot)
    spot_name = get_fishing_spot_display_name(final_spot)
    
    # 检查是否可以钓鱼
    can_fish_result, msg = can_fish(user_id)
    if not can_fish_result:
        await fish.finish(msg)
    
    # 如果是海钓，检查是否需要额外费用
    extra_cost = 0
    if final_spot == "sea":
        extra_cost = config.sea_fishing_extra_cost
        coin_balance, exp, _ = await get_user_info(user_id)
        if coin_balance < extra_cost:
            await fish.finish(f"💰 海钓需要额外消耗{extra_cost}银币，当前只有{coin_balance}银币")
        
        # 消耗额外费用
        result = await consume_coins(user_id, extra_cost, 0, nickname)
        if result[0] is None:
            await fish.finish("❌ 银币消费失败，无法进行海钓")
    
    # 更新全局统计
    update_global_stats()
    
    # 执行钓鱼
    result_type, item_type, item_name, coin_earned = do_fishing_by_spot(final_spot)
    
    try:
        # 更新用户数据
        user_data = update_user_stats(user_id, final_spot, result_type, item_type, item_name, coin_earned)
        
        # 更新全局今日统计
        global_data = load_global_data()
        global_data["total_fishing_count"] = global_data.get("total_fishing_count", 0) + 1
        global_data["today_fishing_count"] = global_data.get("today_fishing_count", 0) + 1
        
        if result_type == "air":
            global_data["today_air_count"] = global_data.get("today_air_count", 0) + 1
        elif result_type == "treasure":
            global_data["today_treasure_count"] = global_data.get("today_treasure_count", 0) + 1
        
        save_global_data(global_data)
        
        # 关键：向后兼容的银币发放逻辑
        # 先尝试新版本的 get_coins 调用 (带 exp_multiple 和 nickname)
        # 如果失败，回退到旧版本的调用 (只有 user_id 和 amount)
        exp_multiple = config.sea_fishing_exp_multiple if final_spot == "sea" else 1.0
        try:
            # 尝试新版本调用
            await get_coins(user_id, coin_earned, exp_multiple, nickname)
        except TypeError as e:
            if "positional arguments" in str(e) or "takes" in str(e):
                # 很可能是参数数量不匹配，尝试旧版本调用
                logger.info(f"检测到旧版 coin 插件，使用兼容模式调用 get_coins")
                await get_coins(user_id, coin_earned)
            else:
                # 其他错误，继续抛出
                raise
        
        # 生成结果消息
        result_msg = get_result_message(final_spot, result_type, item_type, item_name, coin_earned, user_data)
        
        # 添加额外提示
        if final_spot == "sea":
            result_msg += f"\n\n🌊 海钓额外消耗：{extra_cost}银币"
            result_msg += f"\n🌟 海钓经验倍数：{exp_multiple}倍"
        
        if message_id:
            result_msg = MessageSegment.reply(message_id) + result_msg
        await fish.send(result_msg)
        
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

# 添加自定义宝藏命令
add_treasure = on_command("add_treasure", aliases={"添加宝藏", "添加自定义宝藏"}, priority=5, block=True)

@add_treasure.handle()
async def handle_add_treasure(event: Event, message: Message = CommandArg()):
    """添加自定义宝藏"""
    args = message.extract_plain_text().strip().split()
    
    if len(args) < 2:
        await add_treasure.finish("请提供要添加的宝藏名称和价格，格式：/add_treasure 宝藏名称 价格(20-100)")
    
    treasure_name = args[0]
    try:
        value = int(args[1])
    except ValueError:
        await add_treasure.finish("价格必须是数字，格式：/add_treasure 宝藏名称 价格(20-100)")
    
    user_id = get_user_id(event)
    nickname = get_user_nickname(event)
    
    success, result_msg = add_custom_treasure(treasure_name, value, user_id, nickname)
    
    await add_treasure.finish(result_msg)

# 查看自定义宝藏列表命令
list_treasure = on_command("list_treasure", aliases={"自定义宝藏", "查看宝藏"}, priority=5, block=True)

@list_treasure.handle()
async def handle_list_treasure(event: Event):
    """查看自定义宝藏列表（只显示未被钓走的）"""
    custom_treasure = load_custom_treasure()
    
    if not custom_treasure:
        await list_treasure.finish("当前没有自定义宝藏，使用 /add_treasure 宝藏名称 价格 来添加吧！")
    
    # 构建消息
    msg = MessageSegment.text("💰 自定义宝藏列表（未被钓走的）\n")
    msg += MessageSegment.text("=" * 30 + "\n")
    
    for i, treasure in enumerate(custom_treasure, 1):
        added_time = time.strftime("%Y-%m-%d", time.localtime(treasure.get("added_time", 0)))
        added_by = treasure.get("added_nickname", treasure.get("added_by", "未知"))
        value = treasure.get("value", 0)
        
        msg += MessageSegment.text(f"{i}. {treasure['name']} - 价值{value}银币\n")
        msg += MessageSegment.text(f"   添加者：{added_by} | 添加时间：{added_time}\n")
        
        if i < len(custom_treasure):
            msg += MessageSegment.text("   " + "-"*20 + "\n")
    
    msg += MessageSegment.text(f"\n📊 共 {len(custom_treasure)} 个自定义宝藏（未被钓走）")
    
    await list_treasure.send(msg)

# 删除自定义宝藏命令
del_treasure = on_command("del_treasure", aliases={"删除宝藏", "移除宝藏"}, priority=5, block=True)

@del_treasure.handle()
async def handle_del_treasure(event: Event, message: Message = CommandArg()):
    """删除自定义宝藏"""
    treasure_id_str = message.extract_plain_text().strip()
    
    if not treasure_id_str:
        await del_treasure.finish("请提供要删除的宝藏ID，格式：/del_treasure 序号\n使用 /list_treasure 查看所有自定义宝藏")
    
    try:
        treasure_id = int(treasure_id_str)
    except ValueError:
        await del_treasure.finish("宝藏ID必须是数字，格式：/del_treasure 序号")
    
    success, result_msg = delete_custom_treasure(treasure_id)
    await del_treasure.finish(result_msg)

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
    msg += MessageSegment.text(f"钓到宝物：{data.get('treasure_count', 0)}次\n")
    msg += MessageSegment.text(f"钓鱼总收益：{data.get('total_coin_earned', 0)}银币\n\n")
    
    # 显示地点统计（如果存在）
    if data.get("spot_stats"):
        msg += MessageSegment.text("📍 地点统计：\n")
        for spot, stats in data["spot_stats"].items():
            spot_name = get_fishing_spot_display_name(spot)
            msg += MessageSegment.text(f"  {spot_name}：{stats.get('count', 0)}次\n")
        msg += MessageSegment.text("\n")
    
    # 拥有的自定义宝藏
    if data.get("treasure_owned"):
        msg += MessageSegment.text("💰 拥有的自定义宝藏：\n")
        for treasure in data["treasure_owned"][:5]:  # 最多显示5个
            treasure_time = time.strftime("%Y-%m-%d", time.localtime(treasure.get("time", 0)))
            msg += MessageSegment.text(f"  {treasure['name']} - 价值{treasure.get('value', 0)}银币 ({treasure_time})\n")
        if len(data["treasure_owned"]) > 5:
            msg += MessageSegment.text(f"  ... 等{len(data['treasure_owned'])}个宝藏\n")
        msg += MessageSegment.text("\n")
    
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

# 新增命令：查看当前季节
season_cmd = on_command("season", aliases={"季节", "当前季节"}, priority=5, block=True)

@season_cmd.handle()
async def handle_season(event: Event):
    """处理查看季节命令"""
    current_season = get_current_season()
    season_name = get_season_display_name(current_season)
    
    # 获取当前月份
    current_month = datetime.now().month
    month_name = f"{current_month}月"
    
    # 获取当前季节可钓的鱼类
    spots = ["pond", "sea", "river"]
    season_fishes = {}
    
    for spot in spots:
        fishes = get_fish_by_season_and_spot(current_season, spot)
        if fishes:
            spot_name = get_fishing_spot_display_name(spot)
            # 只显示前10种
            fish_names = [fish.name for fish in fishes[:10]]
            if len(fishes) > 10:
                fish_names.append(f"...等{len(fishes)}种")
            season_fishes[spot_name] = fish_names
    
    # 构建消息
    msg = MessageSegment.text(f"📅 当前季节：{season_name} ({month_name})\n")
    msg += MessageSegment.text("=" * 20 + "\n")
    
    if season_fishes:
        msg += MessageSegment.text("🎣 本季特色鱼类：\n")
        for spot_name, fish_list in season_fishes.items():
            if fish_list:
                msg += MessageSegment.text(f"📍 {spot_name}：{', '.join(fish_list)}\n")
    
    msg += MessageSegment.text("\n🌊 钓鱼地点说明：\n")
    msg += MessageSegment.text("  /fish - 默认池塘钓鱼\n")
    msg += MessageSegment.text("  /fish sea - 海钓（需要额外费用）\n")
    msg += MessageSegment.text("  /fish river - 河钓\n")
    
    await season_cmd.send(msg)

# 帮助命令
fish_help = on_command("fish_help", aliases={"钓鱼帮助"}, priority=5, block=True)

@fish_help.handle()
async def handle_fish_help():
    """显示钓鱼帮助"""
    current_season = get_current_season()
    season_name = get_season_display_name(current_season)
    
    msg = MessageSegment.text("🎣 钓鱼插件使用说明\n")
    msg += MessageSegment.text("=" * 20 + "\n")
    msg += MessageSegment.text(f"📅 当前季节：{season_name}\n\n")
    
    msg += MessageSegment.text(f"🎯 命令列表：\n")
    msg += MessageSegment.text(f"  /fish - 池塘钓鱼\n")
    msg += MessageSegment.text(f"  /fish 海钓 - 海洋钓鱼（需额外费用）\n")
    msg += MessageSegment.text(f"  /fish 河钓 - 河流钓鱼\n")
    msg += MessageSegment.text(f"  /season - 查看当前季节\n")
    msg += MessageSegment.text(f"  /fish_record - 查看个人钓鱼记录\n")
    msg += MessageSegment.text(f"  /fish_rank - 查看钓鱼排行榜\n")
    msg += MessageSegment.text(f"  /add_trash 名称 - 添加特殊垃圾\n")
    msg += MessageSegment.text(f"  /add_treasure 名称 价格 - 添加自定义宝藏(20-100)\n")
    
    # 显示各地点概率
    '''
    msg += MessageSegment.text(f"\n📊 各地点钓鱼概率：\n")
    for spot, probs in config.fishing_spots.items():
        spot_name = get_fishing_spot_display_name(spot)
        msg += MessageSegment.text(f"  {spot_name}：")
        msg += MessageSegment.text(f"鱼{probs.get('probability_fish', 0)*100:.0f}% ")
        msg += MessageSegment.text(f"垃圾{probs.get('probability_trash', 0)*100:.0f}% ")
        msg += MessageSegment.text(f"宝藏{probs.get('probability_treasure', 0)*100:.0f}%\n")
    '''
    msg += MessageSegment.text(f"\n⏰ 限制说明：\n")
    msg += MessageSegment.text(f"  每人每小时最多可钓鱼{config.fishing_limit_per_hour}次\n")
    if config.sea_fishing_extra_cost > 0:
        msg += MessageSegment.text(f"  海钓额外消耗：{config.sea_fishing_extra_cost}银币/次\n")
        msg += MessageSegment.text(f"  海钓经验倍数：{config.sea_fishing_exp_multiple}倍\n")
    msg += MessageSegment.text(f"  特殊垃圾数量限制：{config.max_special_trash_count}个\n")
    msg += MessageSegment.text(f"  自定义宝藏数量限制：{config.max_custom_treasure_count}个\n")
    
    await fish_help.send(msg)