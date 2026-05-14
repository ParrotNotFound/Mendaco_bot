from pathlib import Path
import nonebot
from nonebot import require, get_driver, on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent, GroupMessageEvent, PrivateMessageEvent
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
import asyncio
import csv
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import aiofiles
import aiofiles.os

# 导入文件编辑器插件的安全路径功能
# 注意：这里假设文件编辑器插件已正确安装并可导入
# 如果导入失败，您可能需要调整导入路径或使用相对导入
try:
    from ..file_edit import safe_path, read_csv_file, write_csv_file
except ImportError:
    # 如果导入失败，定义替代函数
    from nonebot.log import logger
    logger.warning("无法导入file_edit插件函数，将使用简化版本")

    def safe_path(filename: str) -> Path:
        """简化版安全路径函数"""
        from pathlib import Path
        driver = nonebot.get_driver()
        data_dir = Path(getattr(driver.config, 'data_dir', 'data'))
        file_edit_dir = getattr(driver.config, 'file_edit_dir', 'file_editor')
        coins_dir = data_dir / file_edit_dir / "coins"
        coins_dir.mkdir(parents=True, exist_ok=True)
        return coins_dir / filename

    async def read_csv_file(filename: str) -> List[List[str]]:
        """异步读取CSV文件"""
        file_path = safe_path(filename)
        if not file_path.exists():
            return []
        async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
            content = await f.read()
            reader = csv.reader(content.splitlines())
            return [row for row in reader]

    async def write_csv_file(filename: str, data: List[List[str]]) -> bool:
        """异步写入CSV文件"""
        file_path = safe_path(filename)
        async with aiofiles.open(file_path, mode='w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            for row in data:
                await f.write(','.join(map(str, row)) + '\n')
        return True

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
COINS_DIR_NAME = "coins"
DEFAULT_COIN_NAME = "银币"
INITIAL_COINS = 0  # 初始银币数
INITIAL_EXP = 0      # 初始经验值

# 创建锁字典，用于防止并发操作同一用户文件时的数据竞争
_user_locks: Dict[str, asyncio.Lock] = {}

def _get_user_lock(uid: str) -> asyncio.Lock:
    """获取或创建用户的锁"""
    if uid not in _user_locks:
        _user_locks[uid] = asyncio.Lock()
    return _user_locks[uid]

async def _ensure_user_file(uid: str) -> bool:
    """确保用户数据文件存在，如果不存在则创建"""
    filename = f"{uid}.csv"
    file_path = safe_path(filename)
    
    if not file_path.exists():
        # 创建初始数据：银币,经验,最后更新时间
        initial_data = [[str(INITIAL_COINS), str(INITIAL_EXP), datetime.now().isoformat()]]
        return await write_csv_file(filename, initial_data)
    return True

async def _get_user_data(uid: str) -> Tuple[int, int, str]:
    """
    获取用户数据
    
    返回: (银币数, 经验值, 最后更新时间)
    """
    filename = f"{uid}.csv"
    
    # 确保文件存在
    await _ensure_user_file(uid)
    
    # 读取数据
    data = await read_csv_file(filename)
    
    if not data or len(data) < 1 or len(data[0]) < 3:
        # 如果文件为空或格式错误，返回初始值
        return INITIAL_COINS, INITIAL_EXP, datetime.now().isoformat()
    
    try:
        coins = int(data[0][0]) if data[0][0] else INITIAL_COINS
        exp = int(data[0][1]) if data[0][1] else INITIAL_EXP
        last_update = data[0][2] if len(data[0]) > 2 and data[0][2] else datetime.now().isoformat()
        return coins, exp, last_update
    except (ValueError, IndexError):
        return INITIAL_COINS, INITIAL_EXP, datetime.now().isoformat()

async def _save_user_data(uid: str, coins: int, exp: int) -> bool:
    """保存用户数据"""
    filename = f"{uid}.csv"
    last_update = datetime.now().isoformat()
    data = [[str(coins), str(exp), last_update]]
    return await write_csv_file(filename, data)

# ========== 供其他插件调用的API函数 ==========

async def get_coins(uid: str, amount: int, exp_multiple: float = 1.0) -> Tuple[int, int]:
    """
    为用户增加银币和经验（供其他插件调用）
    
    参数:
        uid: 用户ID
        amount: 增加的银币数量
        exp_multiple: 经验倍数，每增加1银币获得exp_multiple经验
        
    返回:
        (新的银币数, 新的经验值)
    """
    async with _get_user_lock(uid):
        coins, exp, _ = await _get_user_data(uid)
        
        # 计算经验增加
        exp_gain = int(amount * exp_multiple)
        
        # 更新数据
        coins += amount
        exp += exp_gain
        
        # 保存
        await _save_user_data(uid, coins, exp)
        
        return coins, exp

async def consume_coins(uid: str, amount: int, exp_multiple: float = 0.0) -> Tuple[Optional[int], Optional[int]]:
    """
    消费用户的银币，并增加经验（供其他插件调用）
    
    参数:
        uid: 用户ID
        amount: 消费的银币数量
        exp_multiple: 经验倍数，每消费1银币获得exp_multiple经验
        
    返回:
        成功: (新的银币数, 新的经验值)
        失败（银币不足）: (None, None)
    """
    async with _get_user_lock(uid):
        coins, exp, _ = await _get_user_data(uid)
        
        # 检查银币是否足够
        if coins < amount:
            return None, None
        
        # 计算经验增加
        exp_gain = int(amount * exp_multiple)
        
        # 更新数据
        coins -= amount
        exp += exp_gain
        
        # 保存
        await _save_user_data(uid, coins, exp)
        
        return coins, exp

async def get_user_info(uid: str) -> Tuple[int, int]:
    """获取用户信息（银币和经验）"""
    coins, exp, _ = await _get_user_data(uid)
    return coins, exp

# ========== 排行榜相关函数 ==========

async def _get_all_users() -> List[Tuple[str, int, int]]:
    """获取所有用户数据（用于排行榜）"""
    from pathlib import Path
    
    # 获取coins目录
    coins_dir = safe_path("").parent  # safe_path返回的是文件路径，其父目录是coins目录
    
    if not coins_dir.exists():
        return []
    
    users_data = []
    
    # 遍历所有CSV文件
    for file_path in coins_dir.glob("*.csv"):
        uid = file_path.stem  # 去掉扩展名
        
        try:
            coins, exp, _ = await _get_user_data(uid)
            users_data.append((uid, coins, exp))
        except Exception:
            continue
    
    return users_data

async def get_exp_rank(limit: int = 10) -> List[Tuple[str, int, int]]:
    """
    获取经验排行榜
    
    参数:
        limit: 返回的排名数量
        
    返回:
        按经验值降序排列的用户列表，每个元素为(uid, coins, exp)
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
    
    # 获取用户数据
    coins, exp = await get_user_info(uid)
    
    # 发送回复
    await user_cmd.finish(f"💰 你的{DEFAULT_COIN_NAME}: {coins}枚\n🌟 你的经验值: {exp}点")

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
    
    for i, (uid, coins, exp) in enumerate(rank_list, 1):
        # 这里uid是QQ号，可以根据需要显示昵称
        # 为了隐私，通常只显示部分ID
        display_uid = f"用户{uid[-4:]}" if len(uid) > 4 else f"用户{uid}"
        rank_msg += f"{i}. {display_uid} - 经验: {exp}点 (银币: {coins}枚)\n"
    
    await rank_cmd.finish(rank_msg.strip())

# ========== 插件启动时的初始化 ==========

@driver.on_startup
async def init_coin_system():
    """初始化货币系统"""
    # 确保coins目录存在
    coins_dir = safe_path("").parent
    coins_dir.mkdir(parents=True, exist_ok=True)
    
    nonebot.logger.info(f"货币系统初始化完成，数据目录: {coins_dir}")

# ========== 测试函数（可选，用于调试） ==========

async def test_coin_system():
    """测试货币系统功能"""
    test_uid = "10001"
    
    # 测试获取银币
    new_coins, new_exp = await get_coins(test_uid, 50, 2.0)
    print(f"测试获取银币: 用户{test_uid} 现在有{new_coins}银币, {new_exp}经验")
    
    # 测试消费银币
    result = await consume_coins(test_uid, 30, 1.5)
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