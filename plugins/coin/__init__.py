from pathlib import Path
import nonebot
from nonebot import require, get_driver, on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent, GroupMessageEvent, PrivateMessageEvent
# from nonebot.adapters.console import Message, MessageEvent
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
import asyncio
import csv
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import aiofiles
import aiofiles.os

# 导入文件编辑器插件的安全路径功能
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

__plugin_meta__ = PluginMetadata(
    name="货币系统",
    description="银币与经验系统，提供货币获取、消费和排行榜功能",
    usage="""
    可用命令：
    /user - 查询当前用户的银币和经验
    /user_rank - 查询经验排行榜
    """,
    extra={"unique_name": "coin_system", "permissions": ["文件读写"]},
)

# 获取驱动器和配置
driver = get_driver()

# 配置项
COIN_DIR_NAME = "coin"  # 修改为coin目录
DEFAULT_COIN_NAME = "银币"
INITIAL_COINS = 30  # 初始银币数
INITIAL_EXP = 0      # 初始经验值

# 用户昵称缓存，避免频繁读取文件
_user_nicknames: Dict[str, str] = {}

# 创建锁字典，用于防止并发操作同一用户文件时的数据竞争
_user_locks: Dict[str, asyncio.Lock] = {}

def _get_user_lock(uid: str) -> asyncio.Lock:
    """获取或创建用户的锁"""
    if uid not in _user_locks:
        _user_locks[uid] = asyncio.Lock()
    return _user_locks[uid]

def _get_user_nickname_from_event(event: MessageEvent) -> str:
    """从事件中获取用户昵称"""
    if hasattr(event, 'sender') and hasattr(event.sender, 'nickname'):
        return event.sender.nickname
    elif hasattr(event, 'sender') and hasattr(event.sender, 'card'):
        card_name = event.sender.card
        if card_name and card_name.strip():
            return card_name.strip()
    return str(event.get_user_id())

def _get_user_file_path(uid: str) -> str:
    """获取用户数据文件路径（在coin目录下）"""
    return f"{COIN_DIR_NAME}/{uid}.csv"

async def _ensure_user_file(uid: str, nickname: str = "") -> bool:
    """确保用户数据文件存在，如果不存在则创建"""
    filename = _get_user_file_path(uid)
    file_path = safe_path(filename)
    
    # 确保父目录存在
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    if not file_path.exists():
        # 创建初始数据：银币,经验,最后更新时间,昵称
        initial_data = [[str(INITIAL_COINS), str(INITIAL_EXP), datetime.now().isoformat(), nickname]]
        return write_csv_file(filename, initial_data)
    
    # 如果文件已存在，检查是否需要更新昵称
    if nickname:
        data = read_csv_file(filename)
        if data and len(data) > 0 and len(data[0]) >= 4:
            # 更新昵称
            data[0][3] = nickname
            return write_csv_file(filename, data)
    
    return True

async def _get_user_data(uid: str) -> Tuple[int, int, str, str]:
    """
    获取用户数据
    
    返回: (银币数, 经验值, 最后更新时间, 昵称)
    """
    filename = _get_user_file_path(uid)
    
    # 确保文件存在
    await _ensure_user_file(uid)
    
    # 读取数据
    data = read_csv_file(filename)
    
    if not data or len(data) < 1 or len(data[0]) < 3:
        # 如果文件为空或格式错误，返回初始值
        return INITIAL_COINS, INITIAL_EXP, datetime.now().isoformat(), ""
    
    try:
        coins = int(data[0][0]) if data[0][0] else INITIAL_COINS
        exp = int(data[0][1]) if data[0][1] else INITIAL_EXP
        last_update = data[0][2] if len(data[0]) > 2 and data[0][2] else datetime.now().isoformat()
        nickname = data[0][3] if len(data[0]) > 3 and data[0][3] else ""
        
        # 更新昵称缓存
        if nickname and nickname not in _user_nicknames:
            _user_nicknames[uid] = nickname
            
        return coins, exp, last_update, nickname
    except (ValueError, IndexError):
        return INITIAL_COINS, INITIAL_EXP, datetime.now().isoformat(), ""

async def _save_user_data(uid: str, coins: int, exp: int, nickname: str = "") -> bool:
    """保存用户数据"""
    filename = _get_user_file_path(uid)
    last_update = datetime.now().isoformat()
    
    # 如果提供了昵称，更新昵称缓存
    if nickname:
        _user_nicknames[uid] = nickname
    
    # 使用提供的昵称，如果没有则从缓存或文件中获取
    if not nickname and uid in _user_nicknames:
        nickname = _user_nicknames[uid]
    
    data = [[str(coins), str(exp), last_update, nickname]]
    return write_csv_file(filename, data)

async def _update_user_nickname(uid: str, nickname: str) -> bool:
    """更新用户昵称"""
    if not nickname:
        return False
    
    # 更新缓存
    _user_nicknames[uid] = nickname
    
    # 获取当前数据
    coins, exp, last_update, _ = await _get_user_data(uid)
    
    # 保存数据，包括更新的昵称
    return await _save_user_data(uid, coins, exp, nickname)

# ========== 供其他插件调用的API函数 ==========

async def get_coins(uid: str, amount: int, exp_multiple: float = 1.0, nickname: str = "") -> Tuple[int, int]:
    """
    为用户增加银币和经验（供其他插件调用）
    
    参数:
        uid: 用户ID
        amount: 增加的银币数量
        exp_multiple: 经验倍数，每增加1银币获得exp_multiple经验
        nickname: 用户昵称（可选）
        
    返回:
        (新的银币数, 新的经验值)
    """
    async with _get_user_lock(uid):
        coins, exp, _, existing_nickname = await _get_user_data(uid)
        
        # 如果提供了昵称，更新昵称
        if nickname and nickname != existing_nickname:
            await _update_user_nickname(uid, nickname)
        
        # 计算经验增加
        exp_gain = int(amount * exp_multiple)
        
        # 更新数据
        coins += amount
        exp += exp_gain
        
        # 保存
        if nickname:
            await _save_user_data(uid, coins, exp, nickname)
        else:
            await _save_user_data(uid, coins, exp)
        
        return coins, exp

async def consume_coins(uid: str, amount: int, exp_multiple: float = 0.0, nickname: str = "") -> Tuple[Optional[int], Optional[int]]:
    """
    消费用户的银币，并增加经验（供其他插件调用）
    
    参数:
        uid: 用户ID
        amount: 消费的银币数量
        exp_multiple: 经验倍数，每消费1银币获得exp_multiple经验
        nickname: 用户昵称（可选）
        
    返回:
        成功: (新的银币数, 新的经验值)
        失败（银币不足）: (None, None)
    """
    async with _get_user_lock(uid):
        coins, exp, _, existing_nickname = await _get_user_data(uid)
        
        # 如果提供了昵称，更新昵称
        if nickname and nickname != existing_nickname:
            await _update_user_nickname(uid, nickname)
        
        # 检查银币是否足够
        if coins < amount:
            return None, None
        
        # 计算经验增加
        exp_gain = int(amount * exp_multiple)
        
        # 更新数据
        coins -= amount
        exp += exp_gain
        
        # 保存
        if nickname:
            await _save_user_data(uid, coins, exp, nickname)
        else:
            await _save_user_data(uid, coins, exp)
        
        return coins, exp

async def get_user_info(uid: str) -> Tuple[int, int, str]:
    """获取用户信息（银币和经验）"""
    coins, exp, _, nickname = await _get_user_data(uid)
    return coins, exp, nickname

# ========== 排行榜相关函数 ==========

async def _get_all_users() -> List[Tuple[str, int, int, str]]:
    """获取所有用户数据（用于排行榜）"""
    from pathlib import Path
    
    # 获取coin目录
    coin_dir = safe_path(COIN_DIR_NAME)
    
    if not coin_dir.exists():
        return []
    
    users_data = []
    
    # 遍历所有CSV文件
    for file_path in coin_dir.glob("*.csv"):
        uid = file_path.stem  # 去掉扩展名
        
        try:
            coins, exp, _, nickname = await _get_user_data(uid)
            users_data.append((uid, coins, exp, nickname))
        except Exception:
            continue
    
    return users_data

async def get_exp_rank(limit: int = 10) -> List[Tuple[str, int, int, str]]:
    """
    获取经验排行榜
    
    参数:
        limit: 返回的排名数量
        
    返回:
        按经验值降序排列的用户列表，每个元素为(uid, coins, exp, nickname)
    """
    users_data = await _get_all_users()
    
    # 按经验值降序排序
    users_data.sort(key=lambda x: x[2], reverse=True)
    
    return users_data[:limit]

# ========== 命令处理器 ==========

user_cmd = on_command("user", aliases={"我的银币", "查询银币"}, priority=5, block=True)
rank_cmd = on_command("user_rank", aliases={"经验榜", "排行榜"}, priority=5, block=True)

@user_cmd.handle()
async def handle_user(event: MessageEvent):
    """处理/user命令，查询当前用户银币和经验"""
    # 获取用户ID
    if isinstance(event, GroupMessageEvent):
        uid = str(event.user_id)
    elif isinstance(event, PrivateMessageEvent):
        uid = str(event.user_id)
    else:
        uid = str(event.get_user_id())
    
    # 获取用户昵称
    nickname = _get_user_nickname_from_event(event)
    
    # 更新用户昵称
    await _update_user_nickname(uid, nickname)
    
    # 获取用户数据
    coins, exp, stored_nickname = await get_user_info(uid)
    
    # 如果存储的昵称与当前昵称不同，更新昵称
    if stored_nickname != nickname:
        await _update_user_nickname(uid, nickname)
        stored_nickname = nickname
    
    # 发送回复
    await user_cmd.finish(f"👤 用户: {stored_nickname}\n💰 你的{DEFAULT_COIN_NAME}: {coins}枚\n🌟 你的经验值: {exp}点")

@rank_cmd.handle()
async def handle_rank(event: MessageEvent, args: Message = CommandArg()):
    """处理/user_rank命令，查询经验排行榜"""
    # 解析参数，获取排行榜数量
    arg_text = args.extract_plain_text().strip()
    limit = 10
    
    if arg_text and arg_text.isdigit():
        limit = min(int(arg_text), 50)  # 限制最大50名
    
    # 获取排行榜
    rank_list = await get_exp_rank(limit)
    
    if not rank_list:
        await rank_cmd.finish("暂无排行榜数据")
    
    # 构建排行榜消息
    rank_msg = f"🏆 经验排行榜 (前{len(rank_list)}名):\n"
    
    for i, (uid, coins, exp, nickname) in enumerate(rank_list, 1):
        # 使用昵称显示，如果昵称为空则使用用户ID
        if nickname and nickname.strip():
            display_name = nickname
        else:
            # 昵称为空，使用用户ID（部分显示）
            display_name = f"用户{uid[-4:]}" if len(uid) > 4 else f"用户{uid}"
        
        rank_msg += f"{i}. {display_name} - 经验: {exp}点 (银币: {coins}枚)\n"
    
    await rank_cmd.finish(rank_msg.strip())

# ========== 插件启动时的初始化 ==========

@driver.on_startup
async def init_coin_system():
    """初始化货币系统"""
    # 确保coin目录存在
    coin_dir = safe_path(COIN_DIR_NAME)
    coin_dir.mkdir(parents=True, exist_ok=True)
    
    nonebot.logger.info(f"货币系统初始化完成，数据目录: {coin_dir}")

# ========== 测试函数（可选，用于调试） ==========

async def test_coin_system():
    """测试货币系统功能"""
    test_uid = "10001"
    test_nickname = "测试用户"
    
    # 测试获取银币
    new_coins, new_exp = await get_coins(test_uid, 50, 2.0, test_nickname)
    print(f"测试获取银币: 用户{test_uid}({test_nickname}) 现在有{new_coins}银币, {new_exp}经验")
    
    # 测试消费银币
    result = await consume_coins(test_uid, 30, 1.5, test_nickname)
    if result[0] is not None:
        print(f"测试消费银币: 用户{test_uid} 现在有{result[0]}银币, {result[1]}经验")
    else:
        print("银币不足")
    
    # 测试获取排行榜
    rank = await get_exp_rank(5)
    print(f"排行榜: {rank}")

# 如果直接运行此文件，执行测试
if __name__ == "__main__":
    import asyncio
    asyncio.run(test_coin_system())