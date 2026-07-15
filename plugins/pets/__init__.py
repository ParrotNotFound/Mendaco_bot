"""
宠物系统插件
=============
基于 file_edit 插件实现的简易宠物系统，包含领养、打工、训练、对战、商店等功能。
数据存储在 file_edit 插件目录下的 pets/ 文件夹中。
"""

import json
import random
import time
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from nonebot import get_plugin_config, get_driver, on_command
from nonebot.adapters.onebot.v11 import (
    Message,
    MessageEvent,
    GroupMessageEvent,
    PrivateMessageEvent,
    MessageSegment,
)
from nonebot.params import CommandArg, ArgPlainText
from nonebot.plugin import PluginMetadata
from nonebot.log import logger

from .config import Config, PetTypeConfig, ShopItemConfig

# ===================================================================
#  插件元信息
# ===================================================================
__plugin_meta__ = PluginMetadata(
    name="宠物系统",
    description="简易宠物系统，支持领养、打工、训练、对战、商店等功能",
    usage="""
    /pet_help              - 宠物系统帮助（本页面）
    /adopt <名字> [类型]  - 领养宠物（类型：猫/狗/龙/兔/狐，默认随机）
    /pet                   - 查看宠物状态
    /feed                  - 喂食宠物（消耗25银币）
    /pet_work              - 宠物打工赚银币
    /pet_train             - 宠物训练涨经验（消耗15银币）
    /pet_attack @用户      - 宠物对战（押金20银币）
    /pet_shop              - 宠物商店
    /pet_buy <物品ID>      - 购买物品
    /rename <新名字>       - 给宠物改名
    /release               - 放生宠物（需二次确认）
    /pet_rank              - 宠物等级排行榜
    """,
    extra={"unique_name": "pet_system", "permissions": ["文件读写"]},
    config=Config,
)

# ===================================================================
#  配置加载
# ===================================================================
pet_config = get_plugin_config(Config)

driver = get_driver()

# ===================================================================
#  导入 file_edit 插件工具函数
# ===================================================================
from nonebot import require

require("plugins.file_edit")
from plugins.file_edit import (
    read_file,
    write_file,
    safe_path,
    plugin_dir as file_edit_plugin_dir,
    read_csv_file,
    write_csv_file,
)

# ===================================================================
#  导入 coin 插件
# ===================================================================
require("plugins.coin")
from plugins.coin import get_coins, consume_coins, get_user_info

# ===================================================================
#  常量定义
# ===================================================================
PETS_ROOT = pet_config.pets_data_dir  # 数据根目录
PETS_DIRS = {
    "users": f"{PETS_ROOT}/users",  # 用户宠物数据目录
    "global": f"{PETS_ROOT}/global.json",  # 全局计数器
}

# 冷却记录字典：{user_id: {"work": last_time, "train": last_time, ...}}
_cooldowns: Dict[str, Dict[str, float]] = {}

# 放生确认字典：{user_id: timestamp}
_release_confirm: Dict[str, float] = {}

# 用户文件锁，防止并发写入
_user_locks: Dict[str, asyncio.Lock] = {}


def _get_user_lock(uid: str) -> asyncio.Lock:
    """获取或创建用户的异步锁"""
    if uid not in _user_locks:
        _user_locks[uid] = asyncio.Lock()
    return _user_locks[uid]


# ===================================================================
#  目录初始化
# ===================================================================
def _init_directories():
    """初始化宠物数据目录结构"""
    try:
        for path in PETS_DIRS.values():
            if path.endswith(".json"):
                # 确保父目录存在
                parent = str(Path(path).parent)
                write_file(f"{parent}/.keep", "")
            else:
                write_file(f"{path}/.keep", "")
    except Exception as e:
        logger.warning(f"[宠物系统] 目录初始化警告: {e}")


_init_directories()


# ===================================================================
#  工具函数：获取用户信息
# ===================================================================
def _get_user_id(event: MessageEvent) -> str:
    """从事件中获取用户ID"""
    return str(event.get_user_id())


def _get_user_nickname(event: MessageEvent) -> str:
    """从事件中获取用户昵称"""
    try:
        if hasattr(event, "sender") and hasattr(event.sender, "nickname"):
            return event.sender.nickname or _get_user_id(event)
        return _get_user_id(event)
    except Exception:
        return _get_user_id(event)


def _get_target_user(event: MessageEvent, msg: str) -> Tuple[str, str]:
    """
    从消息中解析 @ 的用户
    返回: (被@的QQ号, 剩余消息文本)
    """
    import re

    # 尝试匹配 @QQ号
    at_match = re.search(r"\[CQ:at,qq=(\d+)]", msg)
    if at_match:
        target_id = at_match.group(1)
        remaining = msg.replace(at_match.group(0), "").strip()
        return target_id, remaining

    # 尝试匹配纯数字（直接输入QQ号）
    parts = msg.strip().split()
    if parts and parts[0].isdigit():
        return parts[0], " ".join(parts[1:])

    return "", msg


# ===================================================================
#  工具函数：宠物文件路径
# ===================================================================
def _get_pet_file_path(uid: str) -> str:
    """获取用户宠物数据文件路径"""
    return f"{PETS_DIRS['users']}/{uid}.json"


# ===================================================================
#  工具函数：冷却检查
# ===================================================================
def _check_cooldown(uid: str, action: str, cooldown: int) -> Tuple[bool, int]:
    """
    检查冷却时间
    返回: (是否可用, 剩余冷却秒数)
    """
    current_time = time.time()
    if uid not in _cooldowns:
        _cooldowns[uid] = {}

    last_time = _cooldowns[uid].get(action, 0)
    elapsed = current_time - last_time

    if elapsed < cooldown:
        remaining = int(cooldown - elapsed)
        return False, remaining

    # 更新冷却时间
    _cooldowns[uid][action] = current_time
    return True, 0


# ===================================================================
#  核心数据函数：宠物数据加载/保存
# ===================================================================
def _get_default_pet_data() -> Dict[str, Any]:
    """获取默认宠物数据结构"""
    return {
        "has_pet": False,  # 是否有宠物
        "name": "",  # 宠物名字
        "pet_type": "",  # 宠物类型
        "level": 1,  # 等级
        "exp": 0,  # 当前经验
        "hp": 100,  # 当前生命值
        "atk": 10,  # 当前攻击力
        "mood": pet_config.initial_mood,  # 心情值
        "fullness": pet_config.initial_fullness,  # 饱腹度
        "wins": 0,  # 胜场
        "losses": 0,  # 败场
        "adopt_time": "",  # 领养时间
        "last_interact": "",  # 最后互动时间
    }


def _load_pet_data(uid: str) -> Dict[str, Any]:
    """
    加载用户宠物数据
    如果文件不存在或出错，返回默认数据
    """
    file_path = _get_pet_file_path(uid)
    try:
        data_str = read_file(file_path)
        if data_str:
            data = json.loads(data_str)
            # 确保所有字段都存在
            default = _get_default_pet_data()
            default.update(data)
            return default
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        logger.debug(f"[宠物系统] 读取宠物数据失败({uid}): {e}")
    except Exception as e:
        logger.warning(f"[宠物系统] 读取宠物数据异常({uid}): {e}")

    return _get_default_pet_data()


def _save_pet_data(uid: str, data: Dict[str, Any]) -> bool:
    """保存用户宠物数据"""
    try:
        file_path = _get_pet_file_path(uid)
        write_file(file_path, json.dumps(data, ensure_ascii=False, indent=2))
        return True
    except Exception as e:
        logger.error(f"[宠物系统] 保存宠物数据失败({uid}): {e}")
        return False


# ===================================================================
#  核心逻辑：宠物属性计算
# ===================================================================
def _calc_level_up_exp(level: int) -> int:
    """计算升级所需经验"""
    return level * pet_config.base_exp_per_level


def _calc_pet_hp(pet_type: str, level: int) -> int:
    """计算宠物当前等级下的生命值"""
    type_config = pet_config.pet_types.get(pet_type)
    base_hp = type_config.base_hp if type_config else 100
    return base_hp + (level - 1) * pet_config.hp_per_level


def _calc_pet_atk(pet_type: str, level: int) -> int:
    """计算宠物当前等级下的攻击力"""
    type_config = pet_config.pet_types.get(pet_type)
    base_atk = type_config.base_atk if type_config else 10
    return base_atk + (level - 1) * pet_config.atk_per_level


def _try_level_up(data: Dict[str, Any]) -> Tuple[bool, int]:
    """
    尝试升级宠物
    返回: (是否升级, 新等级)
    """
    old_level = data["level"]
    while data["level"] < pet_config.max_level:
        needed = _calc_level_up_exp(data["level"])
        if data["exp"] >= needed:
            data["exp"] -= needed
            data["level"] += 1
            # 更新属性
            pet_type = data["pet_type"]
            data["hp"] = _calc_pet_hp(pet_type, data["level"])
            data["atk"] = _calc_pet_atk(pet_type, data["level"])
        else:
            break
    return data["level"] > old_level, data["level"]


# ===================================================================
#  DeepSeek 名字审查
# ===================================================================
async def _review_pet_name(name: str) -> Tuple[bool, str]:
    """
    使用 DeepSeek API 审查宠物名字是否合法
    返回: (是否通过, 原因/建议)
    """
    # 如果未启用审查或未配置API密钥，直接通过
    if not pet_config.enable_name_review or not pet_config.deepseek_api_key:
        return True, ""

    # 基本长度检查
    if len(name) > pet_config.max_pet_name_length:
        return False, f"名字过长，最长{pet_config.max_pet_name_length}个字符"
    if len(name) < 1:
        return False, "名字不能为空"

    try:
        import httpx

        headers = {
            "Authorization": f"Bearer {pet_config.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": pet_config.deepseek_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是一个宠物名字审查员。请判断用户输入的宠物名字是否合适。"
                        "标准：1.不能包含色情、暴力、政治敏感内容；"
                        "2.不能包含侮辱性词汇；"
                        "3.不能包含特殊符号（除·、_外）；"
                        "4.长度适中。"
                        "如果合适请回复：PASS\n"
                        "如果不合适请回复：FAIL|原因"
                    ),
                },
                {"role": "user", "content": f"请审查这个宠物名字：{name}"},
            ],
            "max_tokens": 100,
            "temperature": 0.1,
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                pet_config.deepseek_api_url, headers=headers, json=payload
            )
            resp.raise_for_status()
            result = resp.json()
            content = result["choices"][0]["message"]["content"].strip()

            if content.startswith("PASS"):
                return True, ""
            elif content.startswith("FAIL"):
                reason = content.split("|", 1)[1] if "|" in content else "名字不合规"
                return False, reason
            else:
                # 无法解析返回结果，默认通过
                logger.warning(f"[宠物系统] DeepSeek返回格式异常: {content}")
                return True, ""

    except ImportError:
        logger.warning("[宠物系统] httpx 未安装，跳过名字审查")
        return True, ""
    except Exception as e:
        logger.error(f"[宠物系统] DeepSeek API 调用失败: {e}")
        # API调用失败时默认通过，不影响用户体验
        return True, ""


# ===================================================================
#  核心逻辑：打工收益计算
# ===================================================================
def _calc_work_reward(data: Dict[str, Any]) -> int:
    """计算打工获得的银币"""
    level = data["level"]
    mood = data["mood"]
    mood_ratio = pet_config.work_mood_multiplier + (mood / 100) * 0.5
    base_reward = level * pet_config.work_coin_base * mood_ratio
    random_factor = random.uniform(
        pet_config.work_random_min, pet_config.work_random_max
    )
    return max(1, int(base_reward * random_factor))


# ===================================================================
#  核心逻辑：训练收益计算
# ===================================================================
def _calc_train_reward(data: Dict[str, Any]) -> int:
    """计算训练获得的经验"""
    level = data["level"]
    base_exp = random.randint(pet_config.train_exp_min, pet_config.train_exp_max)
    level_bonus = level * pet_config.train_exp_level_multiplier
    return base_exp + level_bonus


# ===================================================================
#  核心逻辑：对战计算
# ===================================================================
def _calc_battle(
    attacker: Dict[str, Any], defender: Dict[str, Any]
) -> Tuple[bool, int, int]:
    """
    计算对战结果
    返回: (攻击方是否获胜, 攻击方剩余HP, 防守方剩余HP)
    """
    # 攻击方伤害
    atk_damage = int(
        attacker["atk"]
        * random.uniform(
            pet_config.battle_atk_random_min, pet_config.battle_atk_random_max
        )
    )
    # 防守方减免
    def_defense = int(
        defender["atk"]
        * pet_config.battle_defense_multiplier
        * random.uniform(
            pet_config.battle_atk_random_min, pet_config.battle_atk_random_max
        )
    )

    # 互相伤害
    defender_hp_remaining = defender["hp"] - max(1, atk_damage - def_defense)
    atk_hp_remaining = attacker["hp"] - max(
        1, def_defense
    )  # 防御方也会反击造成部分伤害

    # 判定胜负
    attacker_wins = defender_hp_remaining <= 0
    if not attacker_wins and atk_hp_remaining <= 0:
        attacker_wins = False  # 双方都倒的情况下防守方胜

    return attacker_wins, max(0, atk_hp_remaining), max(0, defender_hp_remaining)


# ===================================================================
#  获取宠物类型信息文本
# ===================================================================
def _get_pet_type_info(pet_type: str) -> Optional[PetTypeConfig]:
    """获取宠物类型配置"""
    return pet_config.pet_types.get(pet_type)


# ===================================================================
#  生成宠物状态文本
# ===================================================================
def _format_pet_status(data: Dict[str, Any], uid: str) -> str:
    """格式化宠物状态显示文本"""
    if not data["has_pet"]:
        return "你还没有宠物！使用 /adopt <名字> [类型] 领养一只吧~\n" \
               f"可选类型：{'、'.join(pet_config.pet_types.keys())}"

    type_config = _get_pet_type_info(data["pet_type"])
    emoji = type_config.emoji if type_config else "🐾"

    # 进度条
    def progress_bar(value: int, max_val: int, length: int = 10) -> str:
        filled = int(value / max_val * length)
        filled = max(0, min(length, filled))
        return "█" * filled + "░" * (length - filled)

    # 当前等级经验进度
    if data["level"] >= pet_config.max_level:
        exp_bar = "MAX"
        exp_text = "已满级"
    else:
        needed = _calc_level_up_exp(data["level"])
        exp_bar = progress_bar(data["exp"], needed)
        exp_text = f"{data['exp']}/{needed}"

    mood_bar = progress_bar(data["mood"], pet_config.max_mood)
    fullness_bar = progress_bar(data["fullness"], pet_config.max_fullness)

    lines = [
        f"╔══════════════════════════╗",
        f"║  {emoji} {data['name']} [{data['pet_type']}]",
        f"║  Lv.{data['level']}  🏆{data['wins']}胜 {data['losses']}败",
        f"║  HP: {data['hp']}  ATK: {data['atk']}",
        f"║  经验: {exp_bar} {exp_text}",
        f"║  心情: {mood_bar} {data['mood']}/{pet_config.max_mood}",
        f"║  饱腹: {fullness_bar} {data['fullness']}/{pet_config.max_fullness}",
        f"╚══════════════════════════╝",
    ]
    return "\n".join(lines)


# ===================================================================
#  获取所有用户宠物数据（排行榜用）
# ===================================================================
def _get_all_pets() -> List[Tuple[str, Dict[str, Any]]]:
    """获取所有用户的宠物数据"""
    users_dir = safe_path(PETS_DIRS["users"])
    if not users_dir.exists():
        return []

    pets = []
    for file_path in users_dir.glob("*.json"):
        uid = file_path.stem
        try:
            data = _load_pet_data(uid)
            if data["has_pet"]:
                pets.append((uid, data))
        except Exception:
            continue

    return pets


# ===================================================================
#  命令处理器
# ===================================================================

# -------- 领养宠物 --------
adopt_cmd = on_command(
    "adopt", aliases={"领养"}, priority=5, block=True
)


@adopt_cmd.handle()
async def handle_adopt(event: MessageEvent, args: Message = CommandArg()):
    """处理领养宠物命令"""
    uid = _get_user_id(event)
    nickname = _get_user_nickname(event)
    text = args.extract_plain_text().strip()

    # 检查是否已有宠物
    data = _load_pet_data(uid)
    if data["has_pet"]:
        await adopt_cmd.finish("你已经有一只宠物了！使用 /pet 查看状态~")

    # 解析参数：/adopt 名字 [类型]
    parts = text.split()
    if not parts:
        await adopt_cmd.finish(
            "格式：/adopt <名字> [类型]\n"
            f"可选类型：{'、'.join(pet_config.pet_types.keys())}（默认随机）"
        )

    pet_name = parts[0]
    # 指定类型或随机
    chosen_type = None
    if len(parts) >= 2:
        type_name = parts[1]
        if type_name in pet_config.pet_types:
            chosen_type = type_name
        else:
            await adopt_cmd.finish(
                f"未知类型「{type_name}」，可选：{'、'.join(pet_config.pet_types.keys())}"
            )

    if not chosen_type:
        chosen_type = random.choice(list(pet_config.pet_types.keys()))
        type_info = pet_config.pet_types[chosen_type]

    type_info = pet_config.pet_types[chosen_type]
    cost = type_info.cost

    # 名字审查
    is_valid, reason = await _review_pet_name(pet_name)
    if not is_valid:
        await adopt_cmd.finish(f"😅 名字「{pet_name}」不太合适：{reason}")

    # 检查银币是否足够
    result = await consume_coins(uid, cost, nickname=nickname)
    if result[0] is None:
        coins, _, _ = await get_user_info(uid)
        await adopt_cmd.finish(
            f"😅 银币不够哦！领养{chosen_type}需要 {cost} 银币，你只有 {coins} 银币。\n"
            "去打工赚点钱吧~ /pet_work"
        )

    # 创建宠物数据
    now = datetime.now().isoformat()
    new_pet = {
        "has_pet": True,
        "name": pet_name,
        "pet_type": chosen_type,
        "level": 1,
        "exp": 0,
        "hp": type_info.base_hp,
        "atk": type_info.base_atk,
        "mood": pet_config.initial_mood,
        "fullness": pet_config.initial_fullness,
        "wins": 0,
        "losses": 0,
        "adopt_time": now,
        "last_interact": now,
    }

    if _save_pet_data(uid, new_pet):
        await adopt_cmd.finish(
            f"{type_info.emoji} 恭喜！你领养了一只{chosen_type}「{pet_name}」！\n"
            f"消耗了 {cost} 银币\n"
            f"快使用 /pet 查看它的状态吧~"
        )
    else:
        await adopt_cmd.finish("😅 保存数据失败了，请稍后再试…")


# -------- 查看宠物状态 --------
pet_cmd = on_command("pet", aliases={"宠物", "我的宠物"}, priority=5, block=True)


@pet_cmd.handle()
async def handle_pet(event: MessageEvent):
    """查看自己的宠物状态"""
    uid = _get_user_id(event)
    data = _load_pet_data(uid)

    await pet_cmd.finish(_format_pet_status(data, uid))


# -------- 喂食宠物 --------
feed_cmd = on_command("feed", aliases={"喂食"}, priority=5, block=True)


@feed_cmd.handle()
async def handle_feed(event: MessageEvent):
    """喂食宠物"""
    uid = _get_user_id(event)
    nickname = _get_user_nickname(event)

    data = _load_pet_data(uid)
    if not data["has_pet"]:
        await feed_cmd.finish("你还没有宠物！使用 /adopt 领养一只吧~")

    # 检查冷却
    available, remaining = _check_cooldown(uid, "feed", pet_config.feed_cooldown)
    if not available:
        await feed_cmd.finish(f"⏳ 喂食冷却中，剩余 {remaining} 秒~")

    # 检查是否已满
    if data["fullness"] >= pet_config.max_fullness:
        await feed_cmd.finish(f"{data['name']}已经很饱了，不用再喂啦~")

    # 消耗银币
    result = await consume_coins(uid, pet_config.feed_coin_cost, nickname=nickname)
    if result[0] is None:
        await feed_cmd.finish(
            f"😅 银币不够！喂食需要 {pet_config.feed_coin_cost} 银币"
        )

    # 更新状态
    data["fullness"] = min(
        pet_config.max_fullness, data["fullness"] + pet_config.feed_fullness_gain
    )
    data["mood"] = min(
        pet_config.max_mood, data["mood"] + pet_config.feed_mood_gain
    )
    data["last_interact"] = datetime.now().isoformat()
    _save_pet_data(uid, data)

    await feed_cmd.finish(
        f"🍖 给{data['name']}喂了食物~\n"
        f"饱腹度 +{pet_config.feed_fullness_gain}，心情 +{pet_config.feed_mood_gain}\n"
        f"消耗了 {pet_config.feed_coin_cost} 银币"
    )


# -------- 宠物打工 --------
work_cmd = on_command("pet_work", aliases={"打工"}, priority=5, block=True)


@work_cmd.handle()
async def handle_work(event: MessageEvent):
    """宠物打工赚银币"""
    uid = _get_user_id(event)
    nickname = _get_user_nickname(event)

    async with _get_user_lock(uid):
        data = _load_pet_data(uid)
        if not data["has_pet"]:
            await work_cmd.finish("你还没有宠物！使用 /adopt 领养一只吧~")

        # 检查冷却
        available, remaining = _check_cooldown(
            uid, "work", pet_config.work_cooldown
        )
        if not available:
            await work_cmd.finish(f"⏳ 打工冷却中，剩余 {remaining} 秒~")

        # 检查饱腹度和心情
        if data["fullness"] <= pet_config.min_fullness:
            await work_cmd.finish(
                f"😅 {data['name']}饿坏了，没法打工！先喂食吧 /feed"
            )
        if data["mood"] <= pet_config.min_mood:
            await work_cmd.finish(
                f"😅 {data['name']}心情不好，不想打工~ 去商店买玩具吧 /pet_shop"
            )

        # 计算消耗
        fullness_cost = random.randint(
            pet_config.work_fullness_cost_min, pet_config.work_fullness_cost_max
        )
        mood_cost = random.randint(
            pet_config.work_mood_cost_min, pet_config.work_mood_cost_max
        )

        # 计算收益
        reward = _calc_work_reward(data)

        # 更新状态
        data["fullness"] = max(
            pet_config.min_fullness, data["fullness"] - fullness_cost
        )
        data["mood"] = max(pet_config.min_mood, data["mood"] - mood_cost)
        data["last_interact"] = datetime.now().isoformat()
        _save_pet_data(uid, data)

    # 增加银币（移出锁范围避免死锁）
    new_coins, _ = await get_coins(uid, reward, nickname=nickname)

    await work_cmd.finish(
        f"💼 {data['name']}打工回来了！\n"
        f"赚了 {reward} 银币！(现有 {new_coins} 银币)\n"
        f"消耗了 {fullness_cost} 饱腹度、{mood_cost} 心情值"
    )


# -------- 宠物训练 --------
train_cmd = on_command("pet_train", aliases={"训练"}, priority=5, block=True)


@train_cmd.handle()
async def handle_train(event: MessageEvent):
    """宠物训练涨经验（消耗银币+饱腹度）"""
    uid = _get_user_id(event)
    nickname = _get_user_nickname(event)

    data = _load_pet_data(uid)
    if not data["has_pet"]:
        await train_cmd.finish("你还没有宠物！使用 /adopt 领养一只吧~")

    # 检查冷却
    available, remaining = _check_cooldown(
        uid, "train", pet_config.train_cooldown
    )
    if not available:
        await train_cmd.finish(f"⏳ 训练冷却中，剩余 {remaining} 秒~")

    # 检查饱腹度
    if data["fullness"] < pet_config.train_fullness_cost:
        await train_cmd.finish(
            f"😅 {data['name']}太饿了，训练不动！先喂食吧 /feed"
        )

    # 检查是否满级
    if data["level"] >= pet_config.max_level:
        await train_cmd.finish(f"✨ {data['name']}已经满级了，不用再训练啦~")

    # 消耗银币
    result = await consume_coins(uid, pet_config.train_coin_cost, nickname=nickname)
    if result[0] is None:
        coins, _, _ = await get_user_info(uid)
        await train_cmd.finish(
            f"😅 银币不够！训练需要 {pet_config.train_coin_cost} 银币，你只有 {coins} 银币"
        )

    # 计算收益
    exp_gain = _calc_train_reward(data)

    # 更新状态
    data["fullness"] = max(
        pet_config.min_fullness, data["fullness"] - pet_config.train_fullness_cost
    )
    data["exp"] += exp_gain
    data["last_interact"] = datetime.now().isoformat()

    # 尝试升级
    leveled_up, new_level = _try_level_up(data)
    _save_pet_data(uid, data)

    msg_parts = [
        f"🏋️ {data['name']}训练完了！",
        f"获得 {exp_gain} 经验！",
    ]
    if leveled_up:
        msg_parts.append(f"🎉 升级了！当前等级: Lv.{new_level}")
    else:
        needed = _calc_level_up_exp(data["level"])
        msg_parts.append(
            f"当前经验 {data['exp']}/{needed}"
        )

    msg_parts.append(f"消耗了 {pet_config.train_fullness_cost} 饱腹度")
    msg_parts.append(f"消耗了 {pet_config.train_coin_cost} 银币")
    await train_cmd.finish("\n".join(msg_parts))


# -------- 宠物对战 --------
attack_cmd = on_command(
    "pet_attack", aliases={"攻击", "对战"}, priority=5, block=True
)


@attack_cmd.handle()
async def handle_attack(event: MessageEvent, args: Message = CommandArg()):
    """宠物对战（含押金）"""
    uid = _get_user_id(event)
    nickname = _get_user_nickname(event)
    text = args.extract_plain_text().strip()

    data = _load_pet_data(uid)
    if not data["has_pet"]:
        await attack_cmd.finish("你还没有宠物！使用 /adopt 领养一只吧~")

    # 检查冷却
    available, remaining = _check_cooldown(
        uid, "battle", pet_config.battle_cooldown
    )
    if not available:
        await attack_cmd.finish(f"⏳ 对战冷却中，剩余 {remaining} 秒~")

    # 解析目标
    target_uid, _ = _get_target_user(event, text)
    if not target_uid:
        await attack_cmd.finish(
            "请指定要挑战的用户！例如：/pet_attack @用户"
        )

    # 不能打自己
    if target_uid == uid:
        await attack_cmd.finish("😅 不能对自己的宠物动手啦~")

    target_data = _load_pet_data(target_uid)
    if not target_data["has_pet"]:
        await attack_cmd.finish("对方还没有宠物，无法对战~")

    # ========== 押金逻辑：双方各扣 deposit ==========
    deposit = pet_config.battle_deposit
    # 扣攻击方押金
    atk_deposit_result = await consume_coins(uid, deposit, nickname=nickname)
    if atk_deposit_result[0] is None:
        coins, _, _ = await get_user_info(uid)
        await attack_cmd.finish(
            f"😅 你的银币不够！对战需要 {deposit} 银币押金，你只有 {coins} 银币"
        )
    # 扣防守方押金（防守方可能不在线，直接扣）
    def_deposit_result = await consume_coins(target_uid, deposit)
    if def_deposit_result[0] is None:
        # 防守方没钱，退还攻击方押金
        await get_coins(uid, deposit, nickname=nickname)
        await attack_cmd.finish("😅 对方银币不够付押金，无法对战~")

    # 执行对战
    attacker_wins, atk_hp_left, def_hp_left = _calc_battle(data, target_data)

    # 押金分配：胜者赢走总押金（2倍）
    total_pot = deposit * 2

    # 更新数据
    type_config_self = _get_pet_type_info(data["pet_type"])
    type_config_target = _get_pet_type_info(target_data["pet_type"])
    emoji_self = type_config_self.emoji if type_config_self else "🐾"
    emoji_target = type_config_target.emoji if type_config_target else "🐾"

    if attacker_wins:
        data["wins"] += 1
        target_data["losses"] += 1
        data["exp"] += pet_config.battle_win_exp
        target_data["exp"] += pet_config.battle_lose_exp
        # 胜者赢走全部押金
        await get_coins(uid, total_pot, nickname=nickname)
        result_msg = (
            f"⚔️ 战斗结束！\n"
            f"{emoji_self} {data['name']} 战胜了 {emoji_target} {target_data['name']}！🎉\n"
            f"我方剩余HP: {atk_hp_left}\n"
            f"对方剩余HP: {def_hp_left}\n"
            f"获得 {pet_config.battle_win_exp} 经验！\n"
            f"💰 赢得押金 {total_pot} 银币！"
        )
    else:
        data["losses"] += 1
        target_data["wins"] += 1
        data["exp"] += pet_config.battle_lose_exp
        target_data["exp"] += pet_config.battle_win_exp
        data["mood"] = max(
            pet_config.min_mood, data["mood"] - pet_config.battle_lose_mood_cost
        )
        # 防守方（胜者）赢走全部押金
        await get_coins(target_uid, total_pot)
        result_msg = (
            f"⚔️ 战斗结束！\n"
            f"{emoji_self} {data['name']} 输给了 {emoji_target} {target_data['name']}...😢\n"
            f"我方剩余HP: {atk_hp_left}\n"
            f"对方剩余HP: {def_hp_left}\n"
            f"获得 {pet_config.battle_lose_exp} 经验（安慰奖）\n"
            f"心情 -{pet_config.battle_lose_mood_cost}\n"
            f"💸 押金 {deposit} 银币被对方赢走了！"
        )

    # 尝试升级
    leveled_up_self, new_level_self = _try_level_up(data)
    leveled_up_target, new_level_target = _try_level_up(target_data)

    if leveled_up_self:
        result_msg += f"\n🎉 {data['name']} 升级到 Lv.{new_level_self}！"
    if leveled_up_target:
        result_msg += f"\n🎉 对方的 {target_data['name']} 升级到 Lv.{new_level_target}！"

    data["last_interact"] = datetime.now().isoformat()
    target_data["last_interact"] = datetime.now().isoformat()
    _save_pet_data(uid, data)
    _save_pet_data(target_uid, target_data)

    await attack_cmd.finish(result_msg)


# -------- 宠物商店 --------
shop_cmd = on_command(
    "pet_shop", aliases={"商店", "宠物商店"}, priority=5, block=True
)


@shop_cmd.handle()
async def handle_shop(event: MessageEvent, args: Message = CommandArg()):
    """查看宠物商店"""
    items = pet_config.shop_items

    lines = [
        "╔══════════════════════════╗",
        "║       🛒 宠物商店         ║",
        "╠══════════════════════════╣",
    ]

    for item_id in sorted(items.keys()):
        item = items[item_id]
        lines.append(
            f"║ {item_id}. {item.name}  💰 {item.price}银币"
        )
        lines.append(f"║    └ {item.description}")

    lines.append("╚══════════════════════════╝")
    lines.append("使用 /pet_buy <物品ID> 购买")

    await shop_cmd.finish("\n".join(lines))


# -------- 购买物品 --------
buy_cmd = on_command(
    "pet_buy", aliases={"购买", "买"}, priority=5, block=True
)


@buy_cmd.handle()
async def handle_buy(event: MessageEvent, args: Message = CommandArg()):
    """购买宠物商店物品"""
    uid = _get_user_id(event)
    nickname = _get_user_nickname(event)
    text = args.extract_plain_text().strip()

    if not text or not text.isdigit():
        await buy_cmd.finish("请指定要购买的物品ID！\n使用 /pet_shop 查看商品列表")

    item_id = int(text)
    items = pet_config.shop_items

    if item_id not in items:
        await buy_cmd.finish(f"没有找到ID为 {item_id} 的商品，使用 /pet_shop 查看商品列表")

    item = items[item_id]
    data = _load_pet_data(uid)
    if not data["has_pet"]:
        await buy_cmd.finish("你还没有宠物！使用 /adopt 领养一只吧~")

    # 消耗银币
    result = await consume_coins(uid, item.price, nickname=nickname)
    if result[0] is None:
        coins, _, _ = await get_user_info(uid)
        await buy_cmd.finish(
            f"😅 银币不够！{item.name}需要 {item.price} 银币，你只有 {coins} 银币"
        )

    # 应用效果
    effect_messages = []
    for attr, value in item.effect.items():
        if attr == "fullness":
            old = data["fullness"]
            data["fullness"] = min(pet_config.max_fullness, data["fullness"] + value)
            gained = data["fullness"] - old
            effect_messages.append(f"饱腹度 +{gained}")
        elif attr == "mood":
            old = data["mood"]
            data["mood"] = min(pet_config.max_mood, data["mood"] + value)
            gained = data["mood"] - old
            effect_messages.append(f"心情 +{gained}")
        elif attr == "exp":
            data["exp"] += value
            effect_messages.append(f"经验 +{value}")
            leveled_up, new_level = _try_level_up(data)
            if leveled_up:
                effect_messages.append(f"🎉 升级到 Lv.{new_level}！")

    data["last_interact"] = datetime.now().isoformat()
    _save_pet_data(uid, data)

    await buy_cmd.finish(
        f"✅ 成功购买 {item.name}（{item.price}银币）\n"
        f"{data['name']}使用了物品：{'，'.join(effect_messages)}"
    )


# -------- 宠物改名 --------
rename_cmd = on_command(
    "rename", aliases={"改名", "重命名"}, priority=5, block=True
)


@rename_cmd.handle()
async def handle_rename(event: MessageEvent, args: Message = CommandArg()):
    """给宠物改名"""
    uid = _get_user_id(event)
    text = args.extract_plain_text().strip()

    if not text:
        await rename_cmd.finish("格式：/rename <新名字>")

    new_name = text.strip()
    if len(new_name) > pet_config.max_pet_name_length:
        await rename_cmd.finish(
            f"名字过长！最长 {pet_config.max_pet_name_length} 个字符"
        )

    # DeepSeek 名字审查
    is_valid, reason = await _review_pet_name(new_name)
    if not is_valid:
        await rename_cmd.finish(f"😅 名字「{new_name}」不太合适：{reason}")

    data = _load_pet_data(uid)
    if not data["has_pet"]:
        await rename_cmd.finish("你还没有宠物！使用 /adopt 领养一只吧~")

    old_name = data["name"]
    data["name"] = new_name
    data["last_interact"] = datetime.now().isoformat()
    _save_pet_data(uid, data)

    await rename_cmd.finish(f"✅ {old_name} 改名为 {new_name} 啦~")


# -------- 放生宠物 --------
release_cmd = on_command(
    "release", aliases={"放生"}, priority=5, block=True
)


@release_cmd.handle()
async def handle_release(event: MessageEvent):
    """放生宠物（需二次确认）"""
    uid = _get_user_id(event)
    now = time.time()

    # 检查是否已有确认
    if uid in _release_confirm and (now - _release_confirm[uid]) < 30:
        # 确认放生
        data = _load_pet_data(uid)
        if not data["has_pet"]:
            _release_confirm.pop(uid, None)
            await release_cmd.finish("你还没有宠物呢~")

        pet_name = data["name"]
        # 重置数据
        new_data = _get_default_pet_data()
        if _save_pet_data(uid, new_data):
            _release_confirm.pop(uid, None)
            await release_cmd.finish(f"🕊️ {pet_name}被放生了…愿你找到更好的归宿~")
        else:
            await release_cmd.finish("😅 放生失败，请稍后再试…")
    else:
        # 初次确认
        data = _load_pet_data(uid)
        if not data["has_pet"]:
            await release_cmd.finish("你还没有宠物呢~")

        _release_confirm[uid] = now
        await release_cmd.finish(
            f"⚠️ 确定要放生 {data['name']} 吗？\n"
            f"再发一次 /release 确认（30秒内有效）\n"
            f"放生后数据将不可恢复！"
        )


# -------- 宠物排行榜 --------
rank_cmd = on_command(
    "pet_rank", aliases={"宠物排行", "宠物排行榜"}, priority=5, block=True
)


@rank_cmd.handle()
async def handle_rank(event: MessageEvent):
    """宠物等级排行榜"""
    all_pets = _get_all_pets()

    if not all_pets:
        await rank_cmd.finish("目前还没有人领养宠物呢~ 快来领养一只吧 /adopt")

    # 按等级降序排序，等级相同按经验降序
    all_pets.sort(key=lambda x: (x[1]["level"], x[1]["exp"]), reverse=True)

    limit = pet_config.rank_limit
    top_pets = all_pets[:limit]

    lines = [
        "╔══════════════════════════╗",
        "║    🏆 宠物等级排行榜     ║",
        "╠══════════════════════════╣",
    ]

    for idx, (pet_uid, pet_data) in enumerate(top_pets, 1):
        type_config = _get_pet_type_info(pet_data["pet_type"])
        emoji = type_config.emoji if type_config else "🐾"
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        medal = medals.get(idx, f"{idx:>2}.")
        lines.append(
            f"║ {medal} {emoji} {pet_data['name']}  \n"
            f"║    Lv.{pet_data['level']} | {pet_data['wins']}胜{pet_data['losses']}败"
        )

    lines.append("╚══════════════════════════╝")
    await rank_cmd.finish("\n".join(lines))


# -------- 宠物系统帮助 --------
pet_help_cmd = on_command(
    "pet_help", aliases={"宠物帮助", "宠物系统"}, priority=5, block=True
)


@pet_help_cmd.handle()
async def handle_pet_help():
    """宠物系统帮助页面"""
    # 从配置中读取当前类型列表及价格
    type_lines = []
    for tname, tconf in pet_config.pet_types.items():
        type_lines.append(f"  {tconf.emoji} {tname} - {tconf.cost}银币")

    help_text = (
        f"╔══════════════════════════╗\n"
        f"║     🐾 宠物系统帮助      ║\n"
        f"╠══════════════════════════╣\n"
        f"║ 📖 基础命令              ║\n"
        f"║  /pet_help    本帮助页面  ║\n"
        f"║  /pet          查看宠物   ║\n"
        f"║  /adopt <名> [类型] 领养  ║\n"
        f"║  /rename <新名>  改名     ║\n"
        f"║  /release      放生宠物   ║\n"
        f"╠══════════════════════════╣\n"
        f"║ 💰 成长与经济            ║\n"
        f"║  /feed         喂食(25💲) ║\n"
        f"║  /pet_work     打工赚💲   ║\n"
        f"║  /pet_train    训练涨经验 ║\n"
        f"║  /pet_shop     宠物商店   ║\n"
        f"║  /pet_buy <ID> 购买物品   ║\n"
        f"╠══════════════════════════╣\n"
        f"║ ⚔️ 竞技互动              ║\n"
        f"║  /pet_attack @用户 对战   ║\n"
        f"║  /pet_rank     宠物排行   ║\n"
        f"╠══════════════════════════╣\n"
        f"║ 🐣 可领养类型：          ║\n"
        + "\n".join(f"║  {l}" for l in type_lines) + "\n"
        f"╚══════════════════════════╝"
    )
    await pet_help_cmd.finish(help_text)
