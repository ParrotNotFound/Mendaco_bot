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

from .config import Config, PetTypeConfig, ShopItemConfig, SkillConfig

# ===================================================================
#  导入 image.py 图片渲染工具
# ===================================================================
try:
    from plugins.image import text_to_image, image_to_base64
    _HAS_IMAGE = True
except ImportError:
    _HAS_IMAGE = False
    text_to_image = None
    image_to_base64 = None


def _make_image_segment(text: str) -> Optional[MessageSegment]:
    """将文本渲染为图片 MessageSegment，失败返回 None"""
    if not _HAS_IMAGE or not text_to_image or not image_to_base64:
        return None
    try:
        img = text_to_image(text)
        b64 = image_to_base64(img).decode()
        return MessageSegment.image(f"base64://{b64}")
    except Exception as e:
        logger.warning(f"[宠物系统] 图片渲染失败: {e}")
        return None


# ===================================================================
#  插件元信息
# ===================================================================
__plugin_meta__ = PluginMetadata(
    name="宠物系统",
    description="简易宠物系统，支持领养、打工、训练、对战、商店等功能",
    usage="""
    /pet_help                   - 宠物系统帮助（本页面）
    /adopt <名字> [类型]       - 领养宠物（类型：猫/狗/龙/兔/狐）
    /pet [序号]                 - 查看宠物状态（默认宠物）
    /pet_list                   - 查看所有宠物列表
    /pet_default <序号>         - 设置默认迎战宠物
    /feed                       - 喂食默认宠物（消耗25银币）
    /pet_work                   - 默认宠物打工赚银币
    /pet_train                  - 默认宠物训练涨经验（消耗15银币）
    /pet_attack @用户           - 默认宠物对战（押金20银币）
    /pet_shop                   - 宠物商店
    /pet_buy <物品ID>           - 购买物品
    /rename <新名字>            - 给默认宠物改名
    /skill_rename <序号> <名>   - 给默认宠物的技能改名
    /release                    - 放生默认宠物（需二次确认）
    /pet_rank                   - 宠物等级排行榜
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
#  核心数据函数：宠物数据加载/保存（多宠物版）
# ===================================================================
#  全局ID计数器（持久化到 global.json，重启不丢失）
# ===================================================================
def _get_global_counter() -> int:
    """读取当前最大ID计数器"""
    try:
        data_str = read_file(PETS_DIRS["global"])
        if data_str:
            data = json.loads(data_str)
            return data.get("max_pet_id", 0)
    except Exception:
        pass
    return 0


def _save_global_counter(max_id: int):
    """保存最大ID计数器"""
    try:
        data_str = read_file(PETS_DIRS["global"])
        if data_str:
            data = json.loads(data_str)
        else:
            data = {}
        data["max_pet_id"] = max_id
        write_file(PETS_DIRS["global"], json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.warning(f"[宠物系统] 保存ID计数器失败: {e}")


def _gen_pet_id(existing_pets: Optional[List[Dict[str, Any]]] = None) -> int:
    """
    生成全局唯一宠物ID（持久化计数器，重启不丢失）。
    优先使用持久的全局计数器，同时确保不低于现有宠物的 max(id)。
    """
    counter = _get_global_counter()
    existing_max = max([p.get("id", 0) for p in (existing_pets or [])], default=0)
    new_id = max(counter, existing_max) + 1
    _save_global_counter(new_id)
    return new_id


def _new_pet_obj(name: str, pet_type: str, existing_pets: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """创建一个新的宠物数据对象（类型特有基础值）"""
    tc = pet_config.pet_types.get(pet_type)
    now = datetime.now().isoformat()

    def _b(field: str, default: int) -> int:
        return getattr(tc, field, default) if tc else default

    return {
        "id": _gen_pet_id(existing_pets),
        "name": name,
        "pet_type": pet_type,
        "level": 1,
        "exp": 0,
        "hp": _b("base_hp", 100),
        "atk": _b("base_atk", 10),
        "defense": _b("base_defense", pet_config.base_defense),
        "magic_atk": _b("base_magic_atk", pet_config.base_magic_atk),
        "magic_def": _b("base_magic_def", pet_config.base_magic_def),
        "speed": _b("base_speed", pet_config.base_speed),
        "skills": [],
        "trophies": pet_config.initial_trophies,
        "mood": pet_config.initial_mood,
        "fullness": pet_config.initial_fullness,
        "wins": 0,
        "losses": 0,
        "last_work_time": 0.0,
        "adopt_time": now,
        "last_interact": now,
    }


def _get_default_user_data() -> Dict[str, Any]:
    """获取默认用户数据（多宠物容器）"""
    return {
        "pets": [],
        "default_pet_id": None,
    }


def _load_pet_data(uid: str) -> Dict[str, Any]:
    """
    加载用户宠物数据。
    自动识别并迁移旧版单宠物格式到新版多宠物格式。
    """
    file_path = _get_pet_file_path(uid)
    try:
        data_str = read_file(file_path)
        if data_str:
            raw = json.loads(data_str)

            # ---- 迁移：旧版单宠物格式 -> 新版多宠物格式 ----
            if "has_pet" in raw:
                logger.info(f"[宠物系统] 正在迁移用户 {uid} 的宠物数据到新版格式")
                new_data = _get_default_user_data()
                if raw.get("has_pet"):
                    pet = _new_pet_obj(raw.get("name", "无名"), raw.get("pet_type", "猫"), existing_pets=[])
                    # 【修复】只保留旧数据的非属性字段，HP/ATK等由 _new_pet_obj 用当前配置创建
                    for key in ("level", "exp", "mood", "fullness",
                                "wins", "losses", "adopt_time", "last_interact"):
                        if key in raw:
                            pet[key] = raw[key]
                    # 按当前等级重新计算属性（兼容配置变更）
                    _migrate_pet_fields(pet)
                    new_data["pets"].append(pet)
                    new_data["default_pet_id"] = pet["id"]
                # 写回新版
                _save_pet_data(uid, new_data)
                return new_data

            # ---- 新版多宠物格式 ----
            if "pets" in raw:
                # 【修复】加载时修复重复ID
                seen_ids = set()
                for p in raw["pets"]:
                    pid = p.get("id")
                    if pid is None or pid in seen_ids:
                        # ID 为空或重复，重新分配
                        pid = _gen_pet_id(raw["pets"])
                        p["id"] = pid
                    seen_ids.add(pid)
                    # 刷新属性
                    _migrate_pet_fields(p)
                # 如果 default_pet_id 指向了已被修复的宠物，自动修正
                default_id = raw.get("default_pet_id")
                if default_id is not None and default_id not in seen_ids:
                    if raw["pets"]:
                        raw["default_pet_id"] = raw["pets"][0]["id"]
                    else:
                        raw["default_pet_id"] = None
                return raw

    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        logger.debug(f"[宠物系统] 读取宠物数据失败({uid}): {e}")
    except Exception as e:
        logger.warning(f"[宠物系统] 读取宠物数据异常({uid}): {e}")

    return _get_default_user_data()


def _save_pet_data(uid: str, data: Dict[str, Any]) -> bool:
    """保存用户宠物数据"""
    try:
        file_path = _get_pet_file_path(uid)
        write_file(file_path, json.dumps(data, ensure_ascii=False, indent=2))
        return True
    except Exception as e:
        logger.error(f"[宠物系统] 保存宠物数据失败({uid}): {e}")
        return False


def _migrate_pet_fields(pet: Dict[str, Any]) -> Dict[str, Any]:
    """
    确保单个宠物数据包含所有新版本字段（类型特有基础值）。
    每次加载时根据当前配置**重新计算所有属性**，保证配置变更后数据一致。
    """
    import math
    level = pet.get("level", 1)
    pet_type = pet.get("pet_type", "猫")
    tc = pet_config.pet_types.get(pet_type)
    lv_log = math.log2(max(1, level))

    def _type_base(field: str, default: int) -> int:
        return getattr(tc, field, default) if tc else default

    def _type_mult(field: str, default: float = 1.0) -> float:
        return getattr(tc, field, default) if tc else default

    # === 【关键修复】每次都按当前配置重新计算 HP 和 ATK ===
    base_hp = _type_base("base_hp", 100)
    base_atk = _type_base("base_atk", 10)
    pet["hp"] = base_hp + int(pet_config.hp_growth * _type_mult("hp_growth_mult") * lv_log)
    pet["atk"] = base_atk + int(pet_config.atk_growth * _type_mult("atk_growth_mult") * lv_log)

    # === 其他属性（同样覆盖，保证一致性） ===
    pet["defense"] = (
        _type_base("base_defense", pet_config.base_defense)
        + int(pet_config.defense_growth * _type_mult("def_growth_mult") * lv_log))
    pet["magic_atk"] = (
        _type_base("base_magic_atk", pet_config.base_magic_atk)
        + int(pet_config.magic_atk_growth * _type_mult("matk_growth_mult") * lv_log))
    pet["magic_def"] = (
        _type_base("base_magic_def", pet_config.base_magic_def)
        + int(pet_config.magic_def_growth * _type_mult("mdef_growth_mult") * lv_log))
    pet["speed"] = (
        _type_base("base_speed", pet_config.base_speed)
        + int(pet_config.speed_growth * _type_mult("spd_growth_mult") * lv_log))
    pet.setdefault("trophies", pet_config.initial_trophies)
    pet.setdefault("skills", [])
    pet.setdefault("skill_names", {})
    pet.setdefault("last_work_time", 0.0)
    return pet


def _get_skill_display_name(pet: Dict[str, Any], skill_id: int) -> str:
    """获取技能显示名（优先使用自定义名）"""
    custom = pet.get("skill_names", {}).get(str(skill_id))
    if custom:
        return custom
    sc = pet_config.skills.get(skill_id)
    return sc.name if sc else f"未知技能"


def _resolve_default_pet(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    获取用户的默认宠物。
    如果 default_pet_id 无效或未设置，自动选第一个。
    如果没有宠物，返回 None。
    """
    pets = data.get("pets", [])
    if not pets:
        return None

    default_id = data.get("default_pet_id")
    # 尝试按 ID 找
    if default_id is not None:
        for p in pets:
            _migrate_pet_fields(p)
            if p["id"] == default_id:
                return p

    # 回退到第一个
    _migrate_pet_fields(pets[0])
    data["default_pet_id"] = pets[0]["id"]
    return pets[0]


# ===================================================================
#  奖杯变化计算（ELO + 分界线调节）
# ===================================================================
def _calc_trophy_change(r_winner: int, r_loser: int) -> Tuple[int, int]:
    """
    基于ELO算法计算奖杯变化。
    返回: (胜者获得, 败者扣除)
    """
    import math
    avg = (r_winner + r_loser) / 2.0
    # ELO期望值
    E = 1.0 / (1.0 + math.pow(10, (r_loser - r_winner) / 400.0))
    # K值随平均奖杯增长
    K = pet_config.trophy_k_base + int(avg * pet_config.trophy_k_scale)
    # 偏离分界线的距离
    offset = avg - pet_config.trophy_threshold
    # 非对称倍率
    gain_mult = 1.0 - offset * pet_config.trophy_gain_slope
    loss_mult = 1.0 + offset * pet_config.trophy_loss_slope
    # 计算
    gain = max(1, int(K * (1.0 - E) * gain_mult))
    loss = max(1, min(pet_config.trophy_max_loss, int(K * E * loss_mult)))
    return gain, loss


# ===================================================================
#  核心逻辑：宠物属性计算
# ===================================================================
def _calc_level_up_exp(level: int) -> int:
    """计算升级所需经验"""
    return level * pet_config.base_exp_per_level


def _calc_pet_hp(pet_type: str, level: int) -> int:
    """计算宠物当前等级下的生命值（对数成长，类型倍率）"""
    type_config = pet_config.pet_types.get(pet_type)
    base_hp = type_config.base_hp if type_config else 100
    mult = type_config.hp_growth_mult if type_config else 1.0
    import math
    return base_hp + int(pet_config.hp_growth * mult * math.log2(max(1, level)))


def _calc_pet_atk(pet_type: str, level: int) -> int:
    """计算宠物当前等级下的攻击力（对数成长，类型倍率）"""
    type_config = pet_config.pet_types.get(pet_type)
    base_atk = type_config.base_atk if type_config else 10
    mult = type_config.atk_growth_mult if type_config else 1.0
    import math
    return base_atk + int(pet_config.atk_growth * mult * math.log2(max(1, level)))


def _calc_pet_defense(pet_type: str, level: int) -> int:
    """计算宠物当前等级下的物理防御（对数成长，类型倍率）"""
    type_config = pet_config.pet_types.get(pet_type)
    base = type_config.base_defense if type_config else pet_config.base_defense
    mult = type_config.def_growth_mult if type_config else 1.0
    import math
    return base + int(pet_config.defense_growth * mult * math.log2(max(1, level)))


def _calc_pet_magic_atk(pet_type: str, level: int) -> int:
    """计算宠物当前等级下的法术攻击（对数成长，类型倍率）"""
    type_config = pet_config.pet_types.get(pet_type)
    base = type_config.base_magic_atk if type_config else pet_config.base_magic_atk
    mult = type_config.matk_growth_mult if type_config else 1.0
    import math
    return base + int(pet_config.magic_atk_growth * mult * math.log2(max(1, level)))


def _calc_pet_magic_def(pet_type: str, level: int) -> int:
    """计算宠物当前等级下的法术防御（法抗，对数成长，类型倍率）"""
    type_config = pet_config.pet_types.get(pet_type)
    base = type_config.base_magic_def if type_config else pet_config.base_magic_def
    mult = type_config.mdef_growth_mult if type_config else 1.0
    import math
    return base + int(pet_config.magic_def_growth * mult * math.log2(max(1, level)))


def _calc_pet_speed(pet_type: str, level: int) -> int:
    """计算宠物当前等级下的速度（对数成长，类型倍率）"""
    type_config = pet_config.pet_types.get(pet_type)
    base = type_config.base_speed if type_config else pet_config.base_speed
    mult = type_config.spd_growth_mult if type_config else 1.0
    import math
    return base + int(pet_config.speed_growth * mult * math.log2(max(1, level)))


def _check_skill_unlock(pet: Dict[str, Any], old_level: int, new_level: int) -> List[int]:
    """
    检查升级过程中是否有新技能解锁。
    返回新解锁的技能ID列表。
    """
    unlocked = []
    for unlock_lv in sorted(pet_config.skill_unlock_levels):
        if old_level < unlock_lv <= new_level:
            skill_ids = pet_config.skill_unlock_map.get(unlock_lv, [])
            for sid in skill_ids:
                if sid not in pet.get("skills", []):
                    unlocked.append(sid)
    return unlocked


def _try_level_up(data: Dict[str, Any]) -> Tuple[bool, int, List[int]]:
    """
    尝试升级宠物，更新所有属性并检查技能解锁。
    返回: (是否升级, 新等级, 新解锁技能ID列表)
    """
    old_level = data["level"]
    new_skills = []
    while data["level"] < pet_config.max_level:
        needed = _calc_level_up_exp(data["level"])
        if data["exp"] >= needed:
            data["exp"] -= needed
            old_lv = data["level"]
            data["level"] += 1
            # 更新所有属性
            pet_type = data["pet_type"]
            data["hp"] = _calc_pet_hp(pet_type, data["level"])
            data["atk"] = _calc_pet_atk(pet_type, data["level"])
            data["defense"] = _calc_pet_defense(pet_type, data["level"])
            data["magic_atk"] = _calc_pet_magic_atk(pet_type, data["level"])
            data["magic_def"] = _calc_pet_magic_def(pet_type, data["level"])
            data["speed"] = _calc_pet_speed(pet_type, data["level"])
            # 检查技能解锁
            for sid in _check_skill_unlock(data, old_lv, data["level"]):
                if sid not in data["skills"]:
                    data["skills"].append(sid)
                    new_skills.append(sid)
        else:
            break
    leveled_up = data["level"] > old_level
    return leveled_up, data["level"], new_skills


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
#  核心逻辑：打工休息加成函数（连续可导）
# ===================================================================
def _calc_rest_bonus(hours_since: float) -> float:
    """
    休息加成函数，连续可导。
    u = hours_since / 24
    f(u) = 1 + A · u · e^(1-u) · (1-u)
    
    性质：
    - u=0 (刚打完) → f=1
    - 0<u<1 (24h内) → f>1 正收益
    - u=1 (刚好24h) → f=1 中性
    - u>1 (超过24h) → f<1 负收益（惩罚懒惰）
    - u→∞ → f→1
    - 峰值在 u=(3-√5)/2 ≈ 9.2h
    - 谷值在 u=(3+√5)/2 ≈ 62.8h
    """
    import math
    A = pet_config.work_rest_amplitude
    u = hours_since / 24.0
    bonus = 1.0 + A * u * math.exp(1.0 - u) * (1.0 - u)
    return bonus


# ===================================================================
#  核心逻辑：打工收益计算
# ===================================================================
def _calc_work_reward(pet: Dict[str, Any]) -> Tuple[int, int, int]:
    """
    计算打工获得的银币和消耗
    收益 = log2(等级+1) × 基数 × 心情系数 × 休息加成 × 随机波动
    返回: (银币收益, 饱腹消耗, 心情消耗)
    """
    level = pet["level"]
    mood = pet["mood"]

    # 心情系数
    mood_ratio = pet_config.work_mood_multiplier + (mood / 100) * 0.5

    # 休息加成（连续可导函数，24h内正收益，超过24h负收益）
    last_work = pet.get("last_work_time", 0.0)
    hours_since = (time.time() - last_work) / 3600 if last_work > 0 else 0
    rest_bonus = _calc_rest_bonus(hours_since)

    # 银币收益：等级对数 + 各项系数
    import math
    log_level = math.log2(level + 1)
    base_reward = log_level * pet_config.work_coin_base * mood_ratio * rest_bonus
    random_factor = random.uniform(
        pet_config.work_random_min, pet_config.work_random_max
    )
    coin_reward = max(1, int(base_reward * random_factor))

    # 饱腹消耗（纯随机）
    fullness_cost = random.randint(
        pet_config.work_fullness_cost_min, pet_config.work_fullness_cost_max
    )

    # 心情消耗：休息越短消耗越高（指数衰减）
    # mood = min + (max - min) * exp(-hours / decay)
    mood_range = pet_config.work_mood_cost_max - pet_config.work_mood_cost_min
    mood_cost = pet_config.work_mood_cost_min + int(
        mood_range * math.exp(-hours_since / pet_config.work_mood_decay_hours)
    )
    mood_cost = min(mood_cost, pet_config.work_mood_cost_max)

    return coin_reward, fullness_cost, mood_cost


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
# ===================================================================
#  战斗系统：回合制 + 技能（技能触发由调用方处理）
# ===================================================================
def _apply_buffs(base: Dict[str, Any], buffs: Dict[str, float]) -> Dict[str, Any]:
    """将增益/减益效果应用到属性副本上"""
    eff = dict(base)
    for stat, mult in buffs.items():
        if stat in eff:
            eff[stat] = max(1, int(eff[stat] * mult))
    return eff


def _calc_phys_damage(atk: int, target_def: int) -> int:
    """物理伤害：max(攻击×5%, 攻击-防御)，最低1"""
    return max(1, max(int(atk * 0.05), atk - target_def))


def _calc_magic_damage(matk: int, target_mdef: int) -> int:
    """法术伤害：法伤 × max(5%, 1-法抗/100)，最低1"""
    return max(1, int(matk * max(0.05, 1.0 - target_mdef / 100.0)))


def _try_trigger_skill_on(
    caster: Dict[str, Any],
    caster_buffs: Dict[str, float],
    target_buffs: Dict[str, float],
    caster_hp: int,
    target_hp: int,
    target_combatant: Optional[Dict[str, Any]] = None,
    target_eff_buffs: Optional[Dict[str, float]] = None,
) -> Tuple[Optional[str], int]:
    """
    尝试触发技能。遍历宠物的已学技能，按概率触发。
    buffs 字典内同时记录倍率，持续回合由调用方维护。
    返回: (触发的技能名, 造成的伤害/治疗量) 或 (None, 0)
    约定：返回负数表示治疗，正数表示伤害，0表示增益/减益/控制
    
    magic_strike 类型会利用 target_combatant 和 target_eff_buffs
    直接结算法伤减免。
    """
    for sid in caster.get("skills", []):
        skill_cfg = pet_config.skills.get(sid)
        if not skill_cfg:
            continue
        if random.random() > skill_cfg.trigger_prob:
            continue

        params = skill_cfg.params
        stype = skill_cfg.skill_type

        if stype == "buff_defense":
            ratio = params.get("ratio", 0.5)
            caster_buffs["defense"] = 1.0 + ratio
            return skill_cfg.name, 0

        elif stype == "heal":
            ratio = params.get("ratio", 0.3)
            heal = int(caster["hp"] * ratio)
            return skill_cfg.name, -heal  # 负值=治疗

        elif stype == "debuff_defense":
            ratio = params.get("ratio", 0.5)
            target_buffs["defense"] = 1.0 - ratio
            return skill_cfg.name, 0

        elif stype == "debuff_atk":
            ratio = params.get("ratio", 0.3)
            target_buffs["atk"] = 1.0 - ratio
            return skill_cfg.name, 0

        elif stype == "power_strike":
            multiplier = params.get("multiplier", 3.0)
            dmg = max(1, int(caster["atk"] * multiplier))
            return skill_cfg.name, dmg

        elif stype == "true_strike":
            # 给自身附加"真实打击"buff，下次普攻无视一切防御
            caster_buffs["true_strike"] = 1.0
            return skill_cfg.name, 0

        elif stype == "magic_strike":
            # 火球术：法伤强力击，受目标法抗减免
            multiplier = params.get("multiplier", 3.0)
            raw = int(caster["magic_atk"] * multiplier)
            if target_combatant and target_eff_buffs is not None:
                eff_target = _apply_buffs(target_combatant, target_eff_buffs)
                dmg = _calc_magic_damage(raw, eff_target["magic_def"])
                dmg = int(dmg * random.uniform(
                    pet_config.battle_magic_random_min, pet_config.battle_magic_random_max
                ))
                return skill_cfg.name, max(1, dmg)
            return skill_cfg.name, max(1, raw)

        elif stype == "speed_up":
            ratio = params.get("ratio", 0.5)
            caster_buffs["speed"] = 1.0 + ratio
            return skill_cfg.name, 0

        elif stype == "freeze":
            dur = int(params.get("duration", 1))
            target_buffs["freeze"] = float(dur)
            return skill_cfg.name, 0

    return None, 0


def _calc_battle(
    attacker: Dict[str, Any], defender: Dict[str, Any]
) -> Tuple[bool, int, int, str]:
    """
    回合制对战（含技能系统）。
    返回: (攻击方是否获胜, 攻击方剩余HP, 防守方剩余HP, 战斗日志)
    """
    # 最大HP
    a_max = attacker["hp"]
    d_max = defender["hp"]
    a_cur = a_max
    d_cur = d_max

    # 增益/减益 {stat: multiplier}，内含"freeze"键表示冻结
    a_buffs: Dict[str, float] = {}
    d_buffs: Dict[str, float] = {}
    # 持续回合 {stat: remaining}
    a_dur: Dict[str, int] = {}
    d_dur: Dict[str, int] = {}

    # 行动点
    ap = [0.0, 0.0]

    log: List[str] = []
    max_turns = pet_config.battle_max_turns

    def _tick_buffs(buffs: Dict[str, float], durs: Dict[str, int]):
        """递减buff回合，过期移除"""
        expired = []
        for stat in list(durs.keys()):
            durs[stat] -= 1
            if durs[stat] <= 0:
                expired.append(stat)
        for s in expired:
            buffs.pop(s, None)
            durs.pop(s, None)

    for turn in range(max_turns):
        # 累计行动点
        a_speed = _apply_buffs(attacker, a_buffs)["speed"]
        d_speed = _apply_buffs(defender, d_buffs)["speed"]
        ap[0] += a_speed / 10.0
        ap[1] += d_speed / 10.0

        # 确定当前行动者
        actor = 0 if ap[0] >= ap[1] else 1
        ap[actor] -= 1.0
        other = 1 - actor

        cur = attacker if actor == 0 else defender
        cur_name = cur["name"]
        cur_buffs = a_buffs if actor == 0 else d_buffs
        cur_dur = a_dur if actor == 0 else d_dur
        other_buffs = d_buffs if actor == 0 else a_buffs
        other_dur = d_dur if actor == 0 else a_dur
        other_name = defender["name"] if actor == 0 else attacker["name"]

        # 冻结检查
        if cur_buffs.get("freeze", 0) > 0:
            cur_buffs["freeze"] -= 0.5  # 每半回合消耗0.5，持续1回合=消耗到0
            if cur_buffs["freeze"] <= 0:
                del cur_buffs["freeze"]
                cur_dur.pop("freeze", None)
            log.append(f"❄️ {cur_name}被冻结，无法行动！")
            _tick_buffs(a_buffs, a_dur)
            _tick_buffs(d_buffs, d_dur)
            continue

        # 技能判定（传入目标信息供火球术结算法抗）
        other_combatant = defender if actor == 0 else attacker
        skill_name, skill_damage = _try_trigger_skill_on(
            cur, cur_buffs, other_buffs,
            a_cur if actor == 0 else d_cur,
            d_cur if actor == 0 else a_cur,
            other_combatant, other_buffs,
        )

        if skill_name:
            eff_self = _apply_buffs(cur, cur_buffs)
            if skill_damage < 0:
                heal = -skill_damage
                if actor == 0:
                    a_cur = min(a_max, a_cur + heal)
                else:
                    d_cur = min(d_max, d_cur + heal)
                log.append(f"💚 {cur_name}发动【{skill_name}】，回复{heal}HP！")
            elif skill_damage > 0:
                if actor == 0:
                    d_cur -= skill_damage
                else:
                    a_cur -= skill_damage
                log.append(f"🔥 {cur_name}发动【{skill_name}】，造成{skill_damage}点伤害！")
            else:
                # 检测具体触发了什么效果
                if "freeze" in other_buffs:
                    dur = int(other_buffs.get("freeze", 1))
                    other_dur["freeze"] = dur
                    log.append(f"❄️ {cur_name}发动【{skill_name}】，{other_name}被冻结{dur}回合！")
                elif "true_strike" in cur_buffs:
                    log.append(f"⚡ {cur_name}发动【{skill_name}】，下次攻击变为真实伤害！")
                elif "defense" in cur_buffs:
                    log.append(f"🛡️ {cur_name}发动【{skill_name}】，防御提升！")
                elif "defense" in other_buffs and other_buffs["defense"] < 1.0:
                    log.append(f"🔨 {cur_name}发动【{skill_name}】，{other_name}防御降低！")
                elif "atk" in other_buffs and other_buffs["atk"] < 1.0:
                    log.append(f"💫 {cur_name}发动【{skill_name}】，{other_name}攻击降低！")
                elif "speed" in cur_buffs:
                    log.append(f"💨 {cur_name}发动【{skill_name}]，速度提升！")
                else:
                    log.append(f"✨ {cur_name}发动【{skill_name}】！")
        else:
            # 普攻（检查真实打击buff）
            eff_self = _apply_buffs(cur, cur_buffs)
            eff_other = _apply_buffs(other_combatant, other_buffs)
            is_true = cur_buffs.pop("true_strike", None) is not None

            if is_true:
                # 真实伤害普攻：无视一切防御法抗
                dmg = eff_self["atk"] if eff_self["atk"] >= eff_self.get("magic_atk", 0) else eff_self["magic_atk"]
                dmg = max(1, int(dmg * random.uniform(0.9, 1.1)))
                log.append(f"⚡ {cur_name}真实攻击，造成{dmg}点真实伤害！")
            elif eff_self.get("magic_atk", 0) > 0 and random.random() < 0.5:
                dmg = _calc_magic_damage(eff_self["magic_atk"], eff_other["magic_def"])
                dmg = int(dmg * random.uniform(
                    pet_config.battle_magic_random_min, pet_config.battle_magic_random_max
                ))
                dmg = max(1, dmg)
                log.append(f"⚡ {cur_name}施法，造成{dmg}点法术伤害！")
            else:
                dmg = _calc_phys_damage(eff_self["atk"], eff_other["defense"])
                dmg = int(dmg * random.uniform(
                    pet_config.battle_atk_random_min, pet_config.battle_atk_random_max
                ))
                dmg = max(1, dmg)
                log.append(f"⚔️ {cur_name}攻击，造成{dmg}点物理伤害！")

            if actor == 0:
                d_cur -= dmg
            else:
                a_cur -= dmg

        # Buff持续回合递减
        _tick_buffs(a_buffs, a_dur)
        _tick_buffs(d_buffs, d_dur)

        # 胜负判定
        a_cur = max(0, a_cur)
        d_cur = max(0, d_cur)
        if d_cur <= 0:
            log.append(f"💀 {defender['name']}倒下了！{attacker['name']}获胜！")
            break
        if a_cur <= 0:
            log.append(f"💀 {attacker['name']}倒下了！{defender['name']}获胜！")
            break

    # 判定胜负
    if a_cur <= 0:
        attacker_wins = False
    elif d_cur <= 0:
        attacker_wins = True
    else:
        # 超时，防守方胜
        attacker_wins = False
        log.append(f"⏰ 战斗超时（{max_turns}回合），{defender['name']}获胜！")

    # 生成日志摘要（最多保留最近8条）
    log_text = "\n".join(log[-8:])
    return attacker_wins, a_cur, d_cur, log_text


# ===================================================================
#  获取宠物类型信息文本
# ===================================================================
def _get_pet_type_info(pet_type: str) -> Optional[PetTypeConfig]:
    """获取宠物类型配置"""
    return pet_config.pet_types.get(pet_type)


# ===================================================================
#  生成宠物状态文本
# ===================================================================
def _format_pet_status(pet: Dict[str, Any], is_default: bool = False) -> str:
    """格式化单只宠物状态显示文本"""
    type_config = _get_pet_type_info(pet["pet_type"])
    emoji = type_config.emoji if type_config else "🐾"

    # 进度条
    def progress_bar(value: int, max_val: int, length: int = 10) -> str:
        filled = int(value / max_val * length)
        filled = max(0, min(length, filled))
        return "█" * filled + "░" * (length - filled)

    # 当前等级经验进度
    if pet["level"] >= pet_config.max_level:
        exp_bar = "MAX"
        exp_text = "已满级"
    else:
        needed = _calc_level_up_exp(pet["level"])
        exp_bar = progress_bar(pet["exp"], needed)
        exp_text = f"{pet['exp']}/{needed}"

    mood_bar = progress_bar(pet["mood"], pet_config.max_mood)
    fullness_bar = progress_bar(pet["fullness"], pet_config.max_fullness)
    tag = " ⭐默认" if is_default else ""

    # 属性行
    def_stat = pet.get("defense", 0)
    mdef_stat = pet.get("magic_def", 0)
    matk_stat = pet.get("magic_atk", 0)
    spd_stat = pet.get("speed", 10)
    stat_line = f"ATK:{pet['atk']} DEF:{def_stat} SPD:{spd_stat}"

    # 技能列表
    skill_ids = pet.get("skills", [])
    if skill_ids:
        display_names = []
        for idx, sid in enumerate(skill_ids, 1):
            sname = _get_skill_display_name(pet, sid)
            display_names.append(f"{idx}.{sname}")
        skill_line = f"技能：{' '.join(display_names)}"
    else:
        skill_line = "技能：无（10级解锁）"

    trophy_count = pet.get("trophies", 0)
    lines = [
        f"╔══════════════════════════╗",
        f"║  {emoji} {pet['name']} [{pet['pet_type']}]{tag}",
        f"║  Lv.{pet['level']}  🏆奖杯:{trophy_count}",
        f"║  HP:{pet['hp']}  {stat_line}",
        f"║  法伤:{matk_stat} 法抗:{mdef_stat}",
        f"║  经验: {exp_bar} {exp_text}",
        f"║  心情: {mood_bar} {pet['mood']}/{pet_config.max_mood}",
        f"║  饱腹: {fullness_bar} {pet['fullness']}/{pet_config.max_fullness}",
        f"║  战绩:{pet['wins']}胜{pet['losses']}败 {skill_line}",
        f"╚══════════════════════════╝",
    ]
    return "\n".join(lines)


def _format_no_pet() -> str:
    """无宠物时的提示"""
    return (
        "你还没有宠物！使用 /adopt <名字> [类型] 领养一只吧~\n"
        f"可选类型：{'、'.join(pet_config.pet_types.keys())}"
    )


# ===================================================================
#  获取所有用户宠物数据（排行榜用）
# ===================================================================
def _get_all_pets() -> List[Tuple[str, Dict[str, Any]]]:
    """获取所有用户的宠物数据（展平所有宠物，用于排行榜）"""
    users_dir = safe_path(PETS_DIRS["users"])
    if not users_dir.exists():
        return []

    entries = []
    for file_path in users_dir.glob("*.json"):
        uid = file_path.stem
        try:
            user_data = _load_pet_data(uid)
            for pet in user_data.get("pets", []):
                _migrate_pet_fields(pet)
                entries.append((uid, pet))
        except Exception:
            continue

    return entries


# ===================================================================
#  命令处理器
# ===================================================================

# -------- 领养宠物 --------
adopt_cmd = on_command(
    "adopt", aliases={"领养"}, priority=5, block=True
)


@adopt_cmd.handle()
async def handle_adopt(event: MessageEvent, args: Message = CommandArg()):
    """处理领养宠物命令（多宠物版）"""
    uid = _get_user_id(event)
    nickname = _get_user_nickname(event)
    text = args.extract_plain_text().strip()

    # 解析参数：/adopt 名字 [类型]
    parts = text.split()
    if not parts:
        await adopt_cmd.finish(
            "格式：/adopt <名字> [类型]\n"
            f"可选类型：{'、'.join(pet_config.pet_types.keys())}（默认随机）"
        )

    pet_name = parts[0]
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

    # 加载用户数据，检查数量上限
    user_data = _load_pet_data(uid)
    pets = user_data.get("pets", [])
    if len(pets) >= pet_config.max_pets_per_user:
        await adopt_cmd.finish(
            f"😅 你已经拥有 {len(pets)} 只宠物了（上限{pet_config.max_pets_per_user}只）！\n"
            "使用 /release 放生后再领养吧~"
        )

    # 创建新宠物（传入现有列表避免ID冲突）
    new_pet = _new_pet_obj(pet_name, chosen_type, existing_pets=pets)
    pets.append(new_pet)

    # 如果是第一只宠物，自动设为默认
    if user_data.get("default_pet_id") is None:
        user_data["default_pet_id"] = new_pet["id"]

    if _save_pet_data(uid, user_data):
        await adopt_cmd.finish(
            f"{type_info.emoji} 恭喜！你领养了一只{chosen_type}「{pet_name}」！\n"
            f"消耗了 {cost} 银币\n"
            f"你现在有 {len(pets)}/{pet_config.max_pets_per_user} 只宠物\n"
            f"快使用 /pet 查看它的状态吧~"
        )
    else:
        await adopt_cmd.finish("😅 保存数据失败了，请稍后再试…")


# -------- 查看宠物状态（支持序号） --------
pet_cmd = on_command("pet", aliases={"宠物", "我的宠物"}, priority=5, block=True)


@pet_cmd.handle()
async def handle_pet(event: MessageEvent, args: Message = CommandArg()):
    """查看自己的宠物状态，格式：/pet [序号]"""
    uid = _get_user_id(event)
    user_data = _load_pet_data(uid)
    pets = user_data.get("pets", [])

    if not pets:
        await pet_cmd.finish(_format_no_pet())

    text = args.extract_plain_text().strip()

    if text and text.isdigit():
        # 指定序号（1-based）
        idx = int(text) - 1
        if idx < 0 or idx >= len(pets):
            await pet_cmd.finish(
                f"序号不正确！你只有 {len(pets)} 只宠物（序号 1~{len(pets)}）"
            )
        pet = pets[idx]
        is_default = (pet["id"] == user_data.get("default_pet_id"))
        await pet_cmd.finish(_format_pet_status(pet, is_default))
    else:
        # 显示默认宠物
        pet = _resolve_default_pet(user_data)
        if not pet:
            await pet_cmd.finish(_format_no_pet())
        await pet_cmd.finish(_format_pet_status(pet, is_default=True))


# -------- 喂食宠物 --------
feed_cmd = on_command("feed", aliases={"喂食"}, priority=5, block=True)


@feed_cmd.handle()
async def handle_feed(event: MessageEvent):
    """喂食默认宠物"""
    uid = _get_user_id(event)
    nickname = _get_user_nickname(event)

    user_data = _load_pet_data(uid)
    pet = _resolve_default_pet(user_data)
    if not pet:
        await feed_cmd.finish(_format_no_pet())

    # 检查冷却
    available, remaining = _check_cooldown(uid, "feed", pet_config.feed_cooldown)
    if not available:
        await feed_cmd.finish(f"⏳ 喂食冷却中，剩余 {remaining} 秒~")

    # 检查是否已满
    if pet["fullness"] >= pet_config.max_fullness:
        await feed_cmd.finish(f"{pet['name']}已经很饱了，不用再喂啦~")

    # 消耗银币
    result = await consume_coins(uid, pet_config.feed_coin_cost, nickname=nickname)
    if result[0] is None:
        await feed_cmd.finish(
            f"😅 银币不够！喂食需要 {pet_config.feed_coin_cost} 银币"
        )

    # 更新状态
    pet["fullness"] = min(
        pet_config.max_fullness, pet["fullness"] + pet_config.feed_fullness_gain
    )
    pet["mood"] = min(
        pet_config.max_mood, pet["mood"] + pet_config.feed_mood_gain
    )
    pet["last_interact"] = datetime.now().isoformat()
    _save_pet_data(uid, user_data)

    await feed_cmd.finish(
        f"🍖 给{pet['name']}喂了食物~\n"
        f"饱腹度 +{pet_config.feed_fullness_gain}，心情 +{pet_config.feed_mood_gain}\n"
        f"消耗了 {pet_config.feed_coin_cost} 银币"
    )


# -------- 宠物打工 --------
work_cmd = on_command("pet_work", aliases={"打工"}, priority=5, block=True)


@work_cmd.handle()
async def handle_work(event: MessageEvent):
    """宠物打工赚银币（含休息加成/惩罚）"""
    uid = _get_user_id(event)
    nickname = _get_user_nickname(event)

    async with _get_user_lock(uid):
        user_data = _load_pet_data(uid)
        pet = _resolve_default_pet(user_data)
        if not pet:
            await work_cmd.finish(_format_no_pet())

        # 检查冷却
        available, remaining = _check_cooldown(
            uid, "work", pet_config.work_cooldown
        )
        if not available:
            await work_cmd.finish(f"⏳ 打工冷却中，剩余 {remaining} 秒~")

        # 检查饱腹度和心情
        if pet["fullness"] <= pet_config.min_fullness:
            await work_cmd.finish(
                f"😅 {pet['name']}饿坏了，没法打工！先喂食吧 /feed"
            )
        if pet["mood"] <= pet_config.min_mood:
            await work_cmd.finish(
                f"😅 {pet['name']}心情不好，不想打工~ 去商店买玩具吧 /pet_shop"
            )

        # 计算收益与消耗（含休息时间加成/惩罚）
        reward, fullness_cost, mood_cost = _calc_work_reward(pet)

        # 更新状态
        pet["fullness"] = max(
            pet_config.min_fullness, pet["fullness"] - fullness_cost
        )
        pet["mood"] = max(pet_config.min_mood, pet["mood"] - mood_cost)
        pet["last_work_time"] = time.time()
        pet["last_interact"] = datetime.now().isoformat()
        _save_pet_data(uid, user_data)

    # 增加银币（移出锁范围避免死锁）
    new_coins, _ = await get_coins(uid, reward, nickname=nickname)

    await work_cmd.finish(
        f"💼 {pet['name']}打工回来了！\n"
        f"赚了 {reward} 银币！(现有 {new_coins} 银币)\n"
        f"消耗了 {fullness_cost} 饱腹度、{mood_cost} 心情值"
    )


# -------- 宠物训练 --------
train_cmd = on_command("pet_train", aliases={"训练"}, priority=5, block=True)


@train_cmd.handle()
async def handle_train(event: MessageEvent, args: Message = CommandArg()):
    """
    宠物训练涨经验。
    格式：/pet_train [小时数]（默认0.5小时）
    收益与消耗按 log2(小时×2+1) 倍率放大。
    训练期间不可进行下一次训练。
    """
    uid = _get_user_id(event)
    nickname = _get_user_nickname(event)
    text = args.extract_plain_text().strip()

    # 解析训练时长
    hours = 0.5  # 默认半小时
    if text:
        try:
            parsed = float(text)
            if parsed <= 0:
                await train_cmd.finish("训练时长必须大于0小时！")
            hours = min(parsed, pet_config.train_max_hours)
        except ValueError:
            await train_cmd.finish(
                "格式：/pet_train [小时数]\n"
                f"例：/pet_train 2（训练2小时，上限{pet_config.train_max_hours}小时）"
            )

    user_data = _load_pet_data(uid)
    pet = _resolve_default_pet(user_data)
    if not pet:
        await train_cmd.finish(_format_no_pet())

    # 检查冷却（动态冷却 = 训练小时数）
    cooldown_sec = int(hours * 3600)
    available, remaining = _check_cooldown(
        uid, "train", cooldown_sec
    )
    if not available:
        rh = remaining // 3600
        rm = (remaining % 3600) // 60
        if rh > 0:
            await train_cmd.finish(f"⏳ 训练中，剩余 {rh} 小时 {rm} 分钟~")
        else:
            await train_cmd.finish(f"⏳ 训练中，剩余 {rm} 分钟~")

    # 计算倍率 multiplier = log2(hours × 2 + 1)
    import math
    multiplier = math.log2(hours * 2 + 1)

    # 检查饱腹度（按倍率放大后的消耗检查）
    total_fullness_cost = min(100, int(multiplier * pet_config.train_fullness_cost))
    if pet["fullness"] < total_fullness_cost:
        await train_cmd.finish(
            f"😅 {pet['name']}太饿了（饱腹{pet['fullness']}），"
            f"训练{hours}小时需要 {total_fullness_cost} 饱腹度！先喂食吧 /feed"
        )

    # 检查是否满级
    if pet["level"] >= pet_config.max_level:
        await train_cmd.finish(f"✨ {pet['name']}已经满级了，不用再训练啦~")

    # 消耗银币（固定，不受时长影响）
    result = await consume_coins(uid, pet_config.train_coin_cost, nickname=nickname)
    if result[0] is None:
        coins, _, _ = await get_user_info(uid)
        await train_cmd.finish(
            f"😅 银币不够！训练需要 {pet_config.train_coin_cost} 银币，你只有 {coins} 银币"
        )

    # 计算基础收益 × 时长倍率
    base_exp = _calc_train_reward(pet)
    exp_gain = int(multiplier * base_exp)

    # 更新状态
    pet["fullness"] = max(
        pet_config.min_fullness, pet["fullness"] - total_fullness_cost
    )
    pet["exp"] += exp_gain
    pet["last_interact"] = datetime.now().isoformat()

    # 尝试升级
    leveled_up, new_level, new_skills = _try_level_up(pet)
    _save_pet_data(uid, user_data)

    msg_parts = [
        f"🏋️ {pet['name']}训练了 {hours} 小时！",
        f"获得 {exp_gain} 经验！",
    ]
    if leveled_up:
        msg_parts.append(f"🎉 升级了！当前等级: Lv.{new_level}")
    if new_skills:
        skill_names = [_get_skill_display_name(pet, sid) for sid in new_skills]
        msg_parts.append(f"✨ 习得新技能：{'、'.join(skill_names)}！")
    else:
        needed = _calc_level_up_exp(pet["level"])
        msg_parts.append(
            f"当前经验 {pet['exp']}/{needed}"
        )

    msg_parts.append(f"消耗了 {total_fullness_cost} 饱腹度")
    msg_parts.append(f"消耗了 {pet_config.train_coin_cost} 银币")
    await train_cmd.finish("\n".join(msg_parts))


# -------- 宠物对战 --------
attack_cmd = on_command(
    "pet_attack", aliases={"攻击", "对战"}, priority=5, block=True
)


@attack_cmd.handle()
async def handle_attack(event: MessageEvent, args: Message = CommandArg()):
    """宠物对战（含押金，双方都用默认宠物）"""
    uid = _get_user_id(event)
    nickname = _get_user_nickname(event)
    # 注意：必须用 str(args) 而非 extract_plain_text()，否则 CQ:at 会被吃掉
    text = str(args).strip()

    user_data = _load_pet_data(uid)
    my_pet = _resolve_default_pet(user_data)
    if not my_pet:
        await attack_cmd.finish(_format_no_pet())

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

    target_user_data = _load_pet_data(target_uid)
    target_pet = _resolve_default_pet(target_user_data)
    if not target_pet:
        await attack_cmd.finish("对方还没有宠物，无法对战~")

    # ========== 押金逻辑：仅攻击方付押金 ==========
    deposit = pet_config.battle_deposit
    atk_result = await consume_coins(uid, deposit, nickname=nickname)
    if atk_result[0] is None:
        coins, _, _ = await get_user_info(uid)
        await attack_cmd.finish(
            f"😅 你的银币不够！对战需要 {deposit} 银币押金，你只有 {coins} 银币"
        )

    # 执行对战（回合制+技能）
    attacker_wins, atk_hp_left, def_hp_left, battle_log = _calc_battle(my_pet, target_pet)

    type_config_self = _get_pet_type_info(my_pet["pet_type"])
    type_config_target = _get_pet_type_info(target_pet["pet_type"])
    emoji_self = type_config_self.emoji if type_config_self else "🐾"
    emoji_target = type_config_target.emoji if type_config_target else "🐾"

    # 双方扣对战消耗（饱腹+心情）
    my_pet["fullness"] = max(pet_config.min_fullness, my_pet.get("fullness", 100) - pet_config.battle_fullness_cost)
    my_pet["mood"] = max(pet_config.min_mood, my_pet["mood"] - pet_config.battle_mood_cost)
    target_pet["fullness"] = max(pet_config.min_fullness, target_pet.get("fullness", 100) - pet_config.battle_fullness_cost)
    target_pet["mood"] = max(pet_config.min_mood, target_pet["mood"] - pet_config.battle_mood_cost)

    bonus = pet_config.battle_win_bonus

    # ========== 奖杯计算 ==========
    my_trophies = my_pet.get("trophies", 0)
    target_trophies = target_pet.get("trophies", 0)
    trophy_gain, trophy_loss = _calc_trophy_change(my_trophies, target_trophies)

    if attacker_wins:
        my_pet["wins"] += 1
        target_pet["losses"] += 1
        my_pet["exp"] += pet_config.battle_win_exp
        target_pet["exp"] += pet_config.battle_lose_exp
        my_pet["trophies"] = my_trophies + trophy_gain
        target_pet["trophies"] = max(0, target_trophies - trophy_loss)
        # 胜者：退回押金 + 1银币奖励
        await get_coins(uid, deposit + bonus, nickname=nickname)
        result_msg = (
            f"⚔️ 战斗结束！\n"
            f"{emoji_self} {my_pet['name']} 战胜了 {emoji_target} {target_pet['name']}！🎉\n"
            f"我方剩余HP: {atk_hp_left}\n"
            f"对方剩余HP: {def_hp_left}\n"
            f"获得 {pet_config.battle_win_exp} 经验！\n"
            f"🏆 奖杯 {my_pet['trophies']} (+{trophy_gain})\n"
            f"💰 退回押金 {deposit} 银币 + 奖励 {bonus} 银币！"
        )
    else:
        my_pet["losses"] += 1
        target_pet["wins"] += 1
        my_pet["exp"] += pet_config.battle_lose_exp
        target_pet["exp"] += pet_config.battle_win_exp
        my_pet["trophies"] = max(0, my_trophies - trophy_loss)
        target_pet["trophies"] = target_trophies + trophy_gain
        # 败者：押金送给对方
        await get_coins(target_uid, deposit)
        result_msg = (
            f"⚔️ 战斗结束！\n"
            f"{emoji_self} {my_pet['name']} 输给了 {emoji_target} {target_pet['name']}...😢\n"
            f"我方剩余HP: {atk_hp_left}\n"
            f"对方剩余HP: {def_hp_left}\n"
            f"获得 {pet_config.battle_lose_exp} 经验（安慰奖）\n"
            f"心情 -{pet_config.battle_mood_cost}，饱腹 -{pet_config.battle_fullness_cost}\n"
            f"🏆 奖杯 {my_pet['trophies']} (-{trophy_loss})\n"
            f"💸 押金 {deposit} 银币被对方赢走了！"
        )

    # 附加战斗日志（完整显示，不截断）
    log_text = battle_log.strip()

    # 尝试升级
    leveled_up_self, new_level_self, new_skills_self = _try_level_up(my_pet)
    leveled_up_target, new_level_target, new_skills_target = _try_level_up(target_pet)

    if leveled_up_self:
        result_msg += f"\n🎉 {my_pet['name']} 升级到 Lv.{new_level_self}！"
        if new_skills_self:
            snames = [_get_skill_display_name(my_pet, sid) for sid in new_skills_self]
            result_msg += f"\n✨ 习得新技能：{'、'.join(snames)}！"
    if leveled_up_target:
        result_msg += f"\n🎉 对方的 {target_pet['name']} 升级到 Lv.{new_level_target}！"
        if new_skills_target:
            snames = [_get_skill_display_name(target_pet, sid) for sid in new_skills_target]
            result_msg += f"\n✨ 对方习得新技能：{'、'.join(snames)}！"

    my_pet["last_interact"] = datetime.now().isoformat()
    target_pet["last_interact"] = datetime.now().isoformat()
    _save_pet_data(uid, user_data)
    _save_pet_data(target_uid, target_user_data)

    # ---- 输出：文字或图片 ----
    if log_text:
        result_msg += "\n\n📜 战斗回放：\n" + log_text

    if pet_config.battle_use_image:
        img_seg = _make_image_segment(result_msg)
        if img_seg:
            await attack_cmd.finish(img_seg)

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
    """购买宠物商店物品（作用于默认宠物）"""
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
    user_data = _load_pet_data(uid)
    pet = _resolve_default_pet(user_data)
    if not pet:
        await buy_cmd.finish(_format_no_pet())

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
            old = pet["fullness"]
            pet["fullness"] = min(pet_config.max_fullness, pet["fullness"] + value)
            gained = pet["fullness"] - old
            effect_messages.append(f"饱腹度 +{gained}")
        elif attr == "mood":
            old = pet["mood"]
            pet["mood"] = min(pet_config.max_mood, pet["mood"] + value)
            gained = pet["mood"] - old
            effect_messages.append(f"心情 +{gained}")
        elif attr == "exp":
            pet["exp"] += value
            effect_messages.append(f"经验 +{value}")
            leveled_up, new_level, new_skills = _try_level_up(pet)
            if leveled_up:
                effect_messages.append(f"🎉 升级到 Lv.{new_level}！")
            if new_skills:
                skill_names = [_get_skill_display_name(pet, sid) for sid in new_skills]
                effect_messages.append(f"✨ 习得新技能：{'、'.join(skill_names)}！")

    pet["last_interact"] = datetime.now().isoformat()
    _save_pet_data(uid, user_data)

    await buy_cmd.finish(
        f"✅ 成功购买 {item.name}（{item.price}银币）\n"
        f"{pet['name']}使用了物品：{'，'.join(effect_messages)}"
    )


# -------- 宠物改名 --------
rename_cmd = on_command(
    "rename", aliases={"改名", "重命名"}, priority=5, block=True
)


@rename_cmd.handle()
async def handle_rename(event: MessageEvent, args: Message = CommandArg()):
    """给默认宠物改名"""
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

    user_data = _load_pet_data(uid)
    pet = _resolve_default_pet(user_data)
    if not pet:
        await rename_cmd.finish(_format_no_pet())

    old_name = pet["name"]
    pet["name"] = new_name
    pet["last_interact"] = datetime.now().isoformat()
    _save_pet_data(uid, user_data)

    await rename_cmd.finish(f"✅ {old_name} 改名为 {new_name} 啦~")


# -------- 技能改名 --------
skill_rename_cmd = on_command(
    "skill_rename", aliases={"技能改名"}, priority=5, block=True
)


@skill_rename_cmd.handle()
async def handle_skill_rename(event: MessageEvent, args: Message = CommandArg()):
    """给默认宠物的技能改名"""
    uid = _get_user_id(event)
    nickname = _get_user_nickname(event)
    text = args.extract_plain_text().strip()

    if not text:
        await skill_rename_cmd.finish("格式：/skill_rename <序号> <新名字>\n用 /pet 查看技能序号")

    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        await skill_rename_cmd.finish("格式：/skill_rename <序号> <新名字>\n例：/skill_rename 1 超级铁壁")

    skill_idx = int(parts[0]) - 1  # 转为0-based
    new_name = parts[1].strip()

    if len(new_name) > pet_config.max_pet_name_length:
        await skill_rename_cmd.finish(f"名字过长！最长 {pet_config.max_pet_name_length} 个字符")

    # 名字审查
    is_valid, reason = await _review_pet_name(new_name)
    if not is_valid:
        await skill_rename_cmd.finish(f"😅 技能名「{new_name}」不太合适：{reason}")

    user_data = _load_pet_data(uid)
    pet = _resolve_default_pet(user_data)
    if not pet:
        await skill_rename_cmd.finish(_format_no_pet())

    skill_ids = pet.get("skills", [])
    if skill_idx < 0 or skill_idx >= len(skill_ids):
        await skill_rename_cmd.finish(
            f"序号不正确！{pet['name']}只有 {len(skill_ids)} 个技能"
        )

    sid = skill_ids[skill_idx]
    old_name = _get_skill_display_name(pet, sid)

    # 消耗银币
    result = await consume_coins(uid, pet_config.skill_rename_cost, nickname=nickname)
    if result[0] is None:
        coins, _, _ = await get_user_info(uid)
        await skill_rename_cmd.finish(
            f"😅 银币不够！改名需要 {pet_config.skill_rename_cost} 银币，你只有 {coins} 银币"
        )

    # 保存自定义名
    skill_names = pet.setdefault("skill_names", {})
    skill_names[str(sid)] = new_name
    _save_pet_data(uid, user_data)

    await skill_rename_cmd.finish(
        f"✅ 技能「{old_name}」改名为「{new_name}」！\n"
        f"消耗了 {pet_config.skill_rename_cost} 银币"
    )


# -------- 放生宠物 --------
release_cmd = on_command(
    "release", aliases={"放生"}, priority=5, block=True
)


@release_cmd.handle()
async def handle_release(event: MessageEvent):
    """放生默认宠物（需二次确认）"""
    uid = _get_user_id(event)
    now = time.time()
    _release_key = f"release_{uid}"

    # 检查是否已有确认
    if _release_key in _release_confirm and (now - _release_confirm[_release_key]) < 30:
        user_data = _load_pet_data(uid)
        pet = _resolve_default_pet(user_data)
        if not pet:
            _release_confirm.pop(_release_key, None)
            await release_cmd.finish("你还没有宠物呢~")

        pet_name = pet["name"]
        pet_id = pet["id"]
        pets = user_data.get("pets", [])

        # 从列表中移除
        user_data["pets"] = [p for p in pets if p["id"] != pet_id]

        # 如果移除的是默认宠物，重置默认
        if user_data.get("default_pet_id") == pet_id:
            if user_data["pets"]:
                user_data["default_pet_id"] = user_data["pets"][0]["id"]
            else:
                user_data["default_pet_id"] = None

        if _save_pet_data(uid, user_data):
            _release_confirm.pop(_release_key, None)
            remain = len(user_data["pets"])
            msg = f"🕊️ {pet_name}被放生了…愿你找到更好的归宿~"
            if remain > 0:
                msg += f"\n你还剩 {remain} 只宠物"
            await release_cmd.finish(msg)
        else:
            await release_cmd.finish("😅 放生失败，请稍后再试…")
    else:
        # 初次确认
        user_data = _load_pet_data(uid)
        pet = _resolve_default_pet(user_data)
        if not pet:
            await release_cmd.finish(_format_no_pet())

        _release_confirm[_release_key] = now
        await release_cmd.finish(
            f"⚠️ 确定要放生 {pet['name']} 吗？\n"
            f"再发一次 /release 确认（30秒内有效）\n"
            f"放生后数据将不可恢复！"
        )


# -------- 宠物排行榜 --------
rank_cmd = on_command(
    "pet_rank", aliases={"宠物排行", "宠物排行榜"}, priority=5, block=True
)


@rank_cmd.handle()
async def handle_rank(event: MessageEvent):
    """宠物奖杯排行榜（支持图片输出）"""
    all_pets = _get_all_pets()

    if not all_pets:
        await rank_cmd.finish("目前还没有人领养宠物呢~ 快来领养一只吧 /adopt")

    # 按奖杯降序排序
    all_pets.sort(key=lambda x: x[1].get("trophies", 0), reverse=True)

    limit = pet_config.rank_limit
    top_pets = all_pets[:limit]

    lines = [
        "╔══════════════════════════╗",
        "║    🏆 宠物奖杯排行榜     ║",
        "╠══════════════════════════╣",
    ]

    for idx, (pet_uid, pet_data) in enumerate(top_pets, 1):
        type_config = _get_pet_type_info(pet_data["pet_type"])
        emoji = type_config.emoji if type_config else "🐾"
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        medal = medals.get(idx, f"{idx:>2}.")
        trophies = pet_data.get("trophies", 0)
        skill_ids = pet_data.get("skills", [])
        skill_text = ""
        if skill_ids:
            snames = [_get_skill_display_name(pet_data, sid) for sid in skill_ids[:2]]
            skill_text = f" {' '.join(snames)}"
        lines.append(
            f"║ {medal} {emoji} {pet_data['name']}  \n"
            f"║    🏆{trophies} Lv.{pet_data['level']} {pet_data['wins']}胜{pet_data['losses']}败{skill_text}"
        )

    lines.append("╚══════════════════════════╝")
    rank_text = "\n".join(lines)

    if pet_config.rank_use_image:
        img_seg = _make_image_segment(rank_text)
        if img_seg:
            await rank_cmd.finish(img_seg)

    await rank_cmd.finish(rank_text)


# -------- 宠物列表 --------
pet_list_cmd = on_command(
    "pet_list", aliases={"我的宠物们", "宠物列表"}, priority=5, block=True
)


@pet_list_cmd.handle()
async def handle_pet_list(event: MessageEvent):
    """查看用户所有宠物"""
    uid = _get_user_id(event)
    user_data = _load_pet_data(uid)
    pets = user_data.get("pets", [])

    if not pets:
        await pet_list_cmd.finish(_format_no_pet())

    default_id = user_data.get("default_pet_id")
    lines = [
        f"╔══════════════════════════╗",
        f"║   📋 我的宠物们 ({len(pets)}只)  ║",
        f"╠══════════════════════════╣",
    ]

    for idx, p in enumerate(pets, 1):
        type_config = _get_pet_type_info(p["pet_type"])
        emoji = type_config.emoji if type_config else "🐾"
        tag = " ⭐" if p["id"] == default_id else ""
        trophy = p.get("trophies", 0)
        lines.append(
            f"║ {idx}. {emoji} {p['name']}  Lv.{p['level']} 🏆{trophy}{tag}"
        )

    lines.append(f"║ 上限 {pet_config.max_pets_per_user} 只            ║")
    lines.append("╚══════════════════════════╝")
    lines.append("使用 /pet <序号> 查看详情，/pet_default <序号> 设置默认")
    await pet_list_cmd.finish("\n".join(lines))


# -------- 设置默认宠物 --------
pet_default_cmd = on_command(
    "pet_default", aliases={"默认宠物", "设置默认"}, priority=5, block=True
)


@pet_default_cmd.handle()
async def handle_pet_default(event: MessageEvent, args: Message = CommandArg()):
    """设置默认迎战宠物"""
    uid = _get_user_id(event)
    text = args.extract_plain_text().strip()

    if not text or not text.isdigit():
        await pet_default_cmd.finish("格式：/pet_default <序号>\n使用 /pet_list 查看宠物序号")

    idx = int(text) - 1
    user_data = _load_pet_data(uid)
    pets = user_data.get("pets", [])

    if not pets:
        await pet_default_cmd.finish(_format_no_pet())

    if idx < 0 or idx >= len(pets):
        await pet_default_cmd.finish(
            f"序号不正确！你只有 {len(pets)} 只宠物（序号 1~{len(pets)}）"
        )

    pet = pets[idx]
    user_data["default_pet_id"] = pet["id"]
    _save_pet_data(uid, user_data)

    type_config = _get_pet_type_info(pet["pet_type"])
    emoji = type_config.emoji if type_config else "🐾"
    await pet_default_cmd.finish(
        f"✅ 已将 {emoji} {pet['name']}（Lv.{pet['level']}）设为默认宠物！\n"
        f"之后的打工、训练、对战都将使用它~"
    )


# -------- 宠物系统帮助 --------
pet_help_cmd = on_command(
    "pet_help", aliases={"宠物帮助", "宠物系统"}, priority=5, block=True
)


@pet_help_cmd.handle()
async def handle_pet_help():
    """宠物系统帮助页面"""
    type_lines = []
    for tname, tconf in pet_config.pet_types.items():
        type_lines.append(f"  {tconf.emoji} {tname} - {tconf.cost}银币")

    help_text = (
        f"╔══════════════════════════╗\n"
        f"║     🐾 宠物系统帮助      ║\n"
        f"╠══════════════════════════╣\n"
        f"║ 📖 基础命令              ║\n"
        f"║  /pet_help      本帮助页  ║\n"
        f"║  /pet [序号]    查看宠物  ║\n"
        f"║  /pet_list      宠物列表  ║\n"
        f"║  /pet_default <序号> 默认 ║\n"
        f"║  /adopt <名> [类型] 领养  ║\n"
        f"║  /rename <新名>  改名     ║\n"
        f"║  /skill_rename <序> <名>  ║\n"
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
        f"║    每人最多{pet_config.max_pets_per_user}只宠物   ║\n"
        f"╚══════════════════════════╝"
    )
    await pet_help_cmd.finish(help_text)
