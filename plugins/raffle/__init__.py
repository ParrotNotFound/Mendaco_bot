from nonebot import get_plugin_config, on_command, get_driver
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Message, MessageEvent, GroupMessageEvent, PrivateMessageEvent, MessageSegment
from nonebot.params import CommandArg
from nonebot.log import logger
import random
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any, Set
from pathlib import Path
from copy import deepcopy

from .config import RecordConfig
driver = get_driver()
__plugin_meta__ = PluginMetadata(
    name="唱片抽取",
    description="使用银币抽取maimai唱片的插件",
    usage="""
单抽唱片: /draw_record
十连唱片: /draw_10
我的唱片: /my_records
查看唱片详情: /record_info 序号
唱片统计: /record_stats
唱片帮助: /record_help
""",
    config=RecordConfig,
)

config = get_plugin_config(RecordConfig)

# 导入coin插件
from nonebot import require
require("plugins.coin")
from plugins.coin import consume_coins, get_user_info, get_coins
require("plugins.maimaidx_music")
require("plugins.image")
from plugins.image import text_to_image2,image_to_base64
# 导入maimaidx_music插件
try:
    from plugins.maimaidx_music import total_list, Music, MusicList
    MAIMAI_MUSIC_AVAILABLE = True
except ImportError:
    logger.warning("无法导入maimaidx_music插件，唱片抽取功能将不可用")
    MAIMAI_MUSIC_AVAILABLE = False
    total_list = None
    Music = None
    MusicList = None

# 导入文件编辑器插件
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
RECORD_ROOT = "record_draw"
DATA_FILES = {
    "users": f"{RECORD_ROOT}/users",  # 用户数据目录
    "global": f"{RECORD_ROOT}/global.json",  # 全局数据文件
    "temp": f"{RECORD_ROOT}/temp"  # 临时数据目录
}

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

init_directories()

# 辅助函数
def get_user_id(event: MessageEvent) -> str:
    """获取用户ID"""
    return str(event.get_user_id())

def get_user_nickname(event: MessageEvent) -> str:
    """获取用户昵称"""
    try:
        if hasattr(event, 'sender') and hasattr(event.sender, 'nickname'):
            return event.sender.nickname
        return get_user_id(event)
    except:
        return get_user_id(event)

def get_user_file_path(user_id: str) -> str:
    """获取用户数据文件路径"""
    return f"{DATA_FILES['users']}/{user_id}.json"

def load_user_data(user_id: str) -> Dict:
    """加载用户唱片数据"""
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
        "total_draws": 0,  # 总抽取次数
        "today_draws": 0,  # 今日抽取次数
        "last_draw_date": None,  # 上次抽取日期
        "records": [],  # 拥有的唱片列表
        "record_stats": {  # 按唯一标识统计
            "total_unique": 0,  # 唯一唱片数量
            "by_rarity": {}  # 按稀有度统计的唯一唱片
        },
        "total_spent": 0  # 总消费银币
    }

def save_user_data(user_id: str, data: Dict) -> bool:
    """保存用户唱片数据"""
    try:
        user_file = get_user_file_path(user_id)
        write_file(user_file, json.dumps(data, ensure_ascii=False, indent=2))
        return True
    except Exception as e:
        logger.error(f"保存用户数据失败: {e}")
        return False

def check_daily_limit(user_id: str, draw_count: int = 1) -> Tuple[bool, str]:
    """检查每日抽取限制"""
    data = load_user_data(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 如果日期变化，重置今日抽取次数
    if data.get("last_draw_date") != today:
        data["today_draws"] = 0
        data["last_draw_date"] = today
        save_user_data(user_id, data)
    
    # 检查是否超过限制
    remaining = config.daily_draw_limit - data["today_draws"]
    if remaining < draw_count:
        return False, f"今日抽取次数不足，剩余{remaining}次，需要{draw_count}次"
    
    return True, ""

def get_record_unique_key(record: Dict) -> str:
    """生成唱片的唯一标识符"""
    # 两唱片被视作相同，当且仅当其所有信息完全一致
    # 我们使用JSON序列化来确保所有字段都参与比较
    return json.dumps({
        "music_id": record.get("music_id"),
        "diff_index": record.get("diff_index"),
        "rarity": record.get("rarity"),
        "title": record.get("title"),
        "artist": record.get("artist"),
        "genre": record.get("genre"),
        "version": record.get("version"),
        "ds": record.get("ds"),
        "level": record.get("level")
    }, sort_keys=True)

def get_random_rarity() -> str:
    """根据概率随机获取唱片等级"""
    rand = random.random()
    cumulative = 0.0
    
    for rarity, prob in config.record_rarity_prob.items():
        cumulative += prob
        if rand <= cumulative:
            return rarity
    
    # 如果概率总和不为1，返回最低等级
    return "B"

def get_random_music_by_rarity(rarity: str) -> Optional[Dict]:
    """根据等级获取随机曲目"""
    if not MAIMAI_MUSIC_AVAILABLE or not total_list:
        return None
    
    # 获取该等级对应的难度范围
    ds_range = config.record_ds_ranges.get(rarity, (1.0, 5.0))
    
    # 使用filter方法筛选符合条件的曲目
    # 注意：我们只考虑第4个和可能存在的第5个难度，即diff=[3,4]
    filtered_music = total_list.filter(ds=ds_range, diff=[3,4])
    
    if not filtered_music:
        # 如果没有符合条件的曲目，尝试放宽条件
        filtered_music = total_list.filter(ds=(ds_range[0]-1, ds_range[1]+1), diff=[3,4])
    
    if not filtered_music:
        logger.error(f"没有找到符合条件的曲目，等级: {rarity}, DS范围: {ds_range}")
        return None
    
    # 随机选择一首曲目
    music = random.choice(filtered_music)
    
    # 获取第4个或第5个难度的详细信息
    # music.diff包含了筛选出的难度索引列表，我们取第一个
    if hasattr(music, 'diff') and music.diff:
        diff_index = music.diff[0]
    else:
        # 如果没有diff信息，默认取第4个难度（索引3）
        diff_index = 3 if len(music.ds) >= 4 else 0
    
    # 获取该难度的详细信息
    ds_value = music.ds[diff_index] if diff_index < len(music.ds) else 0
    level_value = music.level[diff_index] if diff_index < len(music.level) else "?"
    
    return {
        "music_id": music.id,
        "title": music.title,
        "artist": music.artist,
        "genre": music.genre,
        "version": music.version,
        "ds": ds_value,
        "level": level_value,
        "diff_index": diff_index,  # 难度索引（3=4级，4=5级）
        "actual_level": diff_index + 1,  # 实际显示等级
        "chart_data": music.charts[diff_index] if diff_index < len(music.charts) else {}
    }

def get_record_display_name(record: Dict, is_new: bool = False) -> str:
    """获取唱片的显示名称"""
    rarity = record.get("rarity", "B")
    title = record.get("title", "未知曲目")
    count = record.get("count", 1)
    
    # 格式化显示：[稀有度]「曲名」
    display_name = f"[{rarity}]「{title}」"
    
    # 如果是新的，加*NEW*
    if is_new:
        display_name += " *NEW*"
    
    return display_name

def get_record_detailed_info(record: Dict) -> str:
    """获取唱片的详细信息"""
    rarity = record.get("rarity", "B")
    title = record.get("title", "未知曲目")
    artist = record.get("artist", "未知艺术家")
    level = record.get("level", "?")
    ds = record.get("ds", 0)
    genre = record.get("genre", "未知流派")
    version = record.get("version", "未知版本")
    draw_time = record.get("draw_time", "")
    actual_level = record.get("actual_level", 4)  # 默认为4级
    count = record.get("count", 1)  # 获得次数
    
    info = f"[{rarity}]「{title}」\n"
    info += f"获得次数: {count}次\n"
    info += f"艺术家: {artist}\n"
    info += f"难度: {actual_level} ({ds:.1f})\n"
    info += f"等级: {level}\n"
    info += f"流派: {genre}\n"
    info += f"版本: {version}\n"
    if draw_time:
        info += f"首次获得时间: {draw_time}"
    
    return info

def process_single_draw(user_data: Dict) -> Dict:
    """处理单次抽取，返回抽取结果和是否为新唱片"""
    if not MAIMAI_MUSIC_AVAILABLE:
        return None
    
    # 随机抽取唱片等级
    rarity = get_random_rarity()
    
    # 根据等级获取随机曲目
    music_data = get_random_music_by_rarity(rarity)
    
    if not music_data:
        return None
    
    # 创建唱片记录
    draw_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    new_record = {
        "music_id": music_data["music_id"],
        "title": music_data["title"],
        "artist": music_data["artist"],
        "genre": music_data["genre"],
        "version": music_data["version"],
        "ds": music_data["ds"],
        "level": music_data["level"],
        "diff_index": music_data["diff_index"],
        "actual_level": music_data["actual_level"],
        "rarity": rarity,
        "first_draw_time": draw_time,
        "last_draw_time": draw_time,
        "count": 1
    }
    
    # 检查是否已拥有相同的唱片
    record_key = get_record_unique_key(new_record)
    is_new = True
    
    # 在用户记录中查找相同的唱片
    for existing_record in user_data["records"]:
        existing_key = get_record_unique_key(existing_record)
        if existing_key == record_key:
            # 相同的唱片，增加计数
            existing_record["count"] += 1
            existing_record["last_draw_time"] = draw_time
            new_record = existing_record
            is_new = False
            break
    
    if is_new:
        # 新唱片，添加到列表
        user_data["records"].append(new_record)
    
    return {"record": new_record, "is_new": is_new}

def update_user_stats_after_draws(user_data: Dict, draw_count: int) -> Dict:
    """抽取后更新用户统计信息"""
    # 更新总抽取次数
    user_data["total_draws"] = user_data.get("total_draws", 0) + draw_count
    
    # 更新今日抽取次数
    user_data["today_draws"] = user_data.get("today_draws", 0) + draw_count
    user_data["last_draw_date"] = datetime.now().strftime("%Y-%m-%d")
    
    # 更新总消费银币
    user_data["total_spent"] = user_data.get("total_spent", 0) + (draw_count * config.draw_cost)
    
    # 重新计算唯一唱片数量和稀有度统计
    unique_records = {}
    for record in user_data["records"]:
        record_key = get_record_unique_key(record)
        if record_key not in unique_records:
            unique_records[record_key] = {
                "record": record,
                "count": record.get("count", 1)
            }
    
    # 按稀有度统计唯一唱片
    rarity_stats = {}
    for data in unique_records.values():
        rarity = data["record"].get("rarity", "B")
        if rarity not in rarity_stats:
            rarity_stats[rarity] = 0
        rarity_stats[rarity] += 1
    
    user_data["record_stats"] = {
        "total_unique": len(unique_records),
        "by_rarity": rarity_stats
    }
    
    return user_data

# 命令处理器
draw_record = on_command("draw_record", aliases={"draw","pick","抽唱片", "唱片抽取", "单抽"}, priority=5, block=True)
draw_10 = on_command("draw_10", aliases={"十连", "十连抽", "pick_10", "唱片十连"}, priority=5, block=True)
my_records = on_command("my_records", aliases={"我的唱片", "唱片列表"}, priority=5, block=True)
record_info = on_command("record_info", aliases={"唱片详情", "查看唱片"}, priority=5, block=True)
record_stats = on_command("record_stats", aliases={"唱片统计", "唱片信息"}, priority=5, block=True)
record_help = on_command("record_help", aliases={"唱片帮助"}, priority=5, block=True)

@draw_record.handle()
async def handle_draw_record(event: MessageEvent):
    """处理单抽唱片命令"""
    if not MAIMAI_MUSIC_AVAILABLE:
        await draw_record.finish("❌ 唱片系统暂不可用，maimai音乐数据未加载")
    
    user_id = get_user_id(event)
    nickname = get_user_nickname(event)
    
    # 检查每日限制
    can_draw, limit_msg = check_daily_limit(user_id, 1)
    if not can_draw:
        await draw_record.finish(f"❌ {limit_msg}")
    
    # 检查银币是否足够
    coin_balance, exp, _ = await get_user_info(user_id)
    if coin_balance < config.draw_cost:
        await draw_record.finish(f"❌ 银币不足，需要{config.draw_cost}银币，当前只有{coin_balance}银币")
    
    # 检查唱片数量限制
    user_data = load_user_data(user_id)
    if len(user_data["records"]) >= config.max_records_per_user:
        await draw_record.finish(f"❌ 唱片数量已达上限（{config.max_records_per_user}张）")
    
    # 消耗银币
    result = await consume_coins(user_id, config.draw_cost, config.exp_multiple, nickname)
    if result[0] is None:
        await draw_record.finish("❌ 银币消费失败，请稍后重试")
    
    new_coins, new_exp = result
    
    # 处理抽取
    draw_result = process_single_draw(user_data)
    
    if not draw_result:
        # 抽取失败，返还银币
        await get_coins(user_id, config.draw_cost, 0, nickname)
        await draw_record.finish("❌ 抽取失败，没有找到符合条件的曲目，银币已返还")
    
    # 更新用户统计
    user_data = update_user_stats_after_draws(user_data, 1)
    
    # 保存数据
    if not save_user_data(user_id, user_data):
        # 保存失败，返还银币
        await get_coins(user_id, config.draw_cost, 0, nickname)
        await draw_record.finish("❌ 保存唱片数据失败，银币已返还")
    
    # 构建回复消息
    record_name = get_record_display_name(
        draw_result["record"], 
        draw_result["is_new"]
    )
    
    # 只回复获得的唱片
    message_id = event.message_id if hasattr(event, 'message_id') else None
    if message_id:
        await draw_record.finish(MessageSegment.reply(message_id)+record_name)
    else:
        await draw_record.finish(record_name)

@draw_10.handle()
async def handle_draw_10(event: MessageEvent):
    """处理十连抽命令"""
    if not MAIMAI_MUSIC_AVAILABLE:
        await draw_10.finish("❌ 唱片系统暂不可用，maimai音乐数据未加载")
    
    user_id = get_user_id(event)
    nickname = get_user_nickname(event)
    draw_count = 10
    
    # 检查每日限制
    can_draw, limit_msg = check_daily_limit(user_id, draw_count)
    if not can_draw:
        await draw_10.finish(f"❌ {limit_msg}")
    
    # 检查银币是否足够
    total_cost = config.draw_cost * draw_count
    coin_balance, exp, _ = await get_user_info(user_id)
    if coin_balance < total_cost:
        await draw_10.finish(f"❌ 银币不足，需要{total_cost}银币，当前只有{coin_balance}银币")
    
    # 检查唱片数量限制
    user_data = load_user_data(user_id)
    remaining_slots = config.max_records_per_user - len(user_data["records"])
    if remaining_slots <= 0:
        await draw_10.finish(f"❌ 唱片数量已达上限（{config.max_records_per_user}张）")
    
    # 如果剩余槽位不足10个，只抽取剩余槽位数量
    actual_draw_count = min(draw_count, remaining_slots)
    if actual_draw_count < draw_count:
        await draw_10.send(f"⚠️ 唱片槽位不足，将只抽取{actual_draw_count}次（剩余槽位{remaining_slots}个）")
    
    # 消耗银币
    actual_cost = config.draw_cost * actual_draw_count
    result = await consume_coins(user_id, actual_cost, config.exp_multiple, nickname)
    if result[0] is None:
        await draw_10.finish("❌ 银币消费失败，请稍后重试")
    
    new_coins, new_exp = result
    
    # 处理十连抽
    draw_results = []
    successful_draws = 0
    
    for i in range(actual_draw_count):
        draw_result = process_single_draw(user_data)
        if draw_result:
            draw_results.append(draw_result)
            successful_draws += 1
    
    if successful_draws == 0:
        # 抽取全部失败，返还银币
        await get_coins(user_id, actual_cost, 0, nickname)
        await draw_10.finish("❌ 抽取失败，没有找到符合条件的曲目，银币已返还")
    
    # 更新用户统计
    user_data = update_user_stats_after_draws(user_data, successful_draws)
    
    # 保存数据
    if not save_user_data(user_id, user_data):
        # 保存失败，返还银币
        await get_coins(user_id, actual_cost, 0, nickname)
        await draw_10.finish("❌ 保存唱片数据失败，银币已返还")
    
    # 构建回复消息
    reply_msg = f"十连抽结果:\n"
    reply_msg += "=" * 20 + "\n"
    
    for i, result in enumerate(draw_results, 1):
        record_name = get_record_display_name(
            result["record"], 
            result["is_new"]
        )
        reply_msg += f"{record_name}\n"
    
    # 统计新唱片数量
    new_records = sum(1 for r in draw_results if r["is_new"])
    duplicate_records = len(draw_results) - new_records
    
    #reply_msg += f"\n📊 统计: 新唱片{new_records}张，重复唱片{duplicate_records}张"
    img = image_to_base64(text_to_image2(reply_msg))
    message_id = event.message_id if hasattr(event, 'message_id') else None
    if message_id:
        await draw_10.send(MessageSegment.reply(message_id) + Message([
                        MessageSegment("image", {
                            "file": f"base64://{str(image_to_base64(text_to_image2(reply_msg)), encoding='utf-8')}"
                        })
                    ]))
    else:
        await draw_10.finish(Message([
                        MessageSegment("image", {
                            "file": f"base64://{str(image_to_base64(text_to_image2(reply_msg)), encoding='utf-8')}"
                        })
                    ]))

@my_records.handle()
async def handle_my_records(event: MessageEvent, args: Message = CommandArg()):
    """处理我的唱片命令"""
    user_id = get_user_id(event)
    nickname = get_user_nickname(event)
    
    # 解析页码参数
    arg_text = args.extract_plain_text().strip()
    page = 1
    if arg_text and arg_text.isdigit():
        page = int(arg_text)
    
    # 加载用户数据
    user_data = load_user_data(user_id)
    records = user_data.get("records", [])
    
    if not records:
        await my_records.finish(f"🎵 {nickname}还没有任何唱片，快来抽取第一张唱片吧！")
    
    # 获取唯一唱片列表
    unique_records = []
    seen_keys = set()
    
    for record in records:
        record_key = get_record_unique_key(record)
        if record_key not in seen_keys:
            seen_keys.add(record_key)
            unique_records.append(record)
    
    # 分页设置
    records_per_page = 10
    total_pages = (len(unique_records) + records_per_page - 1) // records_per_page
    page = max(1, min(page, total_pages))
    
    # 计算起始和结束索引
    start_idx = (page - 1) * records_per_page
    end_idx = min(start_idx + records_per_page, len(unique_records))
    
    # 构建消息
    reply_msg = f"🎵 {nickname}的唱片收藏 (第{page}/{total_pages}页)\n"
    reply_msg += f"总计: {len(records)}张唱片 ({len(unique_records)}种)\n\n"
    
    # 按稀有度统计
    rarity_stats = user_data.get("record_stats", {}).get("by_rarity", {})
    if rarity_stats:
        reply_msg += "📊 稀有度统计:\n"
        for rarity in ["B", "A", "S", "SS", "SSS", "LEGEND"]:
            count = rarity_stats.get(rarity, 0)
            if count > 0:
                reply_msg += f"  {rarity}: {count}种\n"
    
    reply_msg += f"\n📁 唱片列表:\n"
    
    for i in range(start_idx, end_idx):
        record = unique_records[i]
        record_name = get_record_display_name(record, False)
        count = record.get("count", 1)
        
        # 显示获得次数
        if count > 1:
            record_name += f" (x{count})"
        
        reply_msg += f"{i+1}. {record_name}\n"
    
    reply_msg += f"\n使用 /record_info 序号 查看唱片详情\n"
    reply_msg += f"使用 /my_records 页码 查看其他页"
    
    await my_records.finish(reply_msg)

@record_info.handle()
async def handle_record_info(event: MessageEvent, args: Message = CommandArg()):
    """查看唱片详情"""
    arg_text = args.extract_plain_text().strip()
    
    if not arg_text or not arg_text.isdigit():
        await record_info.finish("请提供唱片序号，例如: /record_info 1")
    
    record_idx = int(arg_text) - 1
    user_id = get_user_id(event)
    
    # 加载用户数据
    user_data = load_user_data(user_id)
    records = user_data.get("records", [])
    
    if not records:
        await record_info.finish("您还没有任何唱片")
    
    # 获取唯一唱片列表
    unique_records = []
    seen_keys = set()
    
    for record in records:
        record_key = get_record_unique_key(record)
        if record_key not in seen_keys:
            seen_keys.add(record_key)
            unique_records.append(record)
    
    if record_idx < 0 or record_idx >= len(unique_records):
        await record_info.finish(f"唱片序号无效，请输入1-{len(unique_records)}之间的数字")
    
    record = unique_records[record_idx]
    record_details = get_record_detailed_info(record)
    
    reply_msg = f"📀 唱片详情 (第{record_idx+1}/{len(unique_records)}种)\n"
    reply_msg += "=" * 20 + "\n"
    reply_msg += record_details
    
    await record_info.finish(reply_msg)

@record_stats.handle()
async def handle_record_stats(event: MessageEvent):
    """查看唱片统计信息"""
    user_id = get_user_id(event)
    nickname = get_user_nickname(event)
    
    # 加载用户数据
    user_data = load_user_data(user_id)
    
    reply_msg = f"📊 {nickname}的唱片统计\n"
    reply_msg += "=" * 20 + "\n"
    
    # 基本信息
    reply_msg += f"总抽取次数: {user_data.get('total_draws', 0)}次\n"
    reply_msg += f"今日抽取: {user_data.get('today_draws', 0)}/{config.daily_draw_limit}次\n"
    
    # 唱片统计
    total_records = len(user_data.get("records", []))
    unique_stats = user_data.get("record_stats", {})
    total_unique = unique_stats.get("total_unique", 0)
    
    reply_msg += f"拥有唱片: {total_records}张\n"
    reply_msg += f"唯一唱片: {total_unique}种\n"
    reply_msg += f"总消费银币: {user_data.get('total_spent', 0)}枚\n\n"
    
    # 稀有度统计
    rarity_stats = unique_stats.get("by_rarity", {})
    if rarity_stats:
        reply_msg += "📈 稀有度分布:\n"
        for rarity, prob in config.record_rarity_prob.items():
            count = rarity_stats.get(rarity, 0)
            if total_unique > 0:
                actual_rate = count / total_unique
            else:
                actual_rate = 0
            reply_msg += f"  {rarity}: {count}种 ({actual_rate*100:.1f}%，理论{prob*100:.0f}%)\n"
    
    # 获取银币余额
    coin_balance, exp, _ = await get_user_info(user_id)
    reply_msg += f"\n💰 当前银币: {coin_balance}枚\n"
    reply_msg += f"🌟 当前经验: {exp}点\n"
    reply_msg += f"🎯 单次抽取: {config.draw_cost}银币"
    
    await record_stats.finish(reply_msg)

@record_help.handle()
async def handle_record_help():
    """显示唱片帮助"""
    reply_msg = "🎵 唱片抽取系统帮助\n"
    reply_msg += "=" * 20 + "\n"
    reply_msg += f"💰 单抽消耗: {config.draw_cost}银币\n"
    reply_msg += f"💰 十连消耗: {config.draw_cost * 10}银币\n"
    reply_msg += f"📅 每日抽取限制: {config.daily_draw_limit}次\n"
    reply_msg += f"🎴 唱片存储上限: {config.max_records_per_user}张\n"
    reply_msg += f"🔄 允许重复: {'是' if config.allow_duplicates else '否'}\n\n"
    
    reply_msg += "📊 唱片等级概率:\n"
    for rarity, prob in config.record_rarity_prob.items():
        ds_range = config.record_ds_ranges.get(rarity, (1.0, 5.0))
        reply_msg += f"  {rarity}: {prob*100:.0f}% (DS: {ds_range[0]}-{ds_range[1]})\n"
    
    reply_msg += "\n🎯 可用命令:\n"
    reply_msg += "  /draw_record - 单抽一张唱片\n"
    reply_msg += "  /draw_10 - 十连抽唱片\n"
    reply_msg += "  /my_records - 查看我的唱片收藏\n"
    reply_msg += "  /record_info 序号 - 查看唱片详情\n"
    reply_msg += "  /record_stats - 查看唱片统计\n"
    reply_msg += "  /record_help - 显示此帮助\n"
    reply_msg += "\n📝 显示说明:\n"
    reply_msg += "  *NEW* - 首次获得的唱片\n"
    reply_msg += "  (xN) - 已获得N次的唱片\n"
    
    await record_help.finish(reply_msg)

# 插件启动时的初始化
@driver.on_startup
async def init_record_system():
    """初始化唱片系统"""
    if not MAIMAI_MUSIC_AVAILABLE:
        logger.warning("唱片系统初始化失败：maimai音乐数据未加载")
    else:
        logger.info(f"唱片系统初始化完成，已加载{len(total_list) if total_list else 0}首曲目")