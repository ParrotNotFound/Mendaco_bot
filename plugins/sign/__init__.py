from nonebot import get_plugin_config, on_command, get_driver
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Message, MessageEvent, GroupMessageEvent, PrivateMessageEvent, MessageSegment
from nonebot.params import CommandArg
from nonebot.log import logger
import random
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
import calendar
from pathlib import Path

from .config import SignConfig

__plugin_meta__ = PluginMetadata(
    name="每日签到",
    description="每日签到获取银币奖励",
    usage="""
每日签到: /sign
签到记录: /sign_record
月度统计: /sign_month
签到帮助: /sign_help
管理员补偿: /compensate <额度> [理由]  (仅管理员1287428141)
""",
    config=SignConfig,
)

config = get_plugin_config(SignConfig)
driver = get_driver()
# 导入coin插件
from nonebot import require
require("plugins.coin")
from plugins.coin import get_coins, get_user_info, get_exp_rank

# 导入文件编辑器插件
require("plugins.file_edit")
from plugins.file_edit import (
    read_file,
    write_file,
    safe_path,
    plugin_dir
)

# 文件路径定义
SIGN_ROOT = "sign"
DATA_FILES = {
    "users": f"{SIGN_ROOT}/users",  # 用户签到数据目录
    "global": f"{SIGN_ROOT}/global.json",  # 全局统计数据文件
    "compensations": f"{SIGN_ROOT}/compensations.json",  # 补偿记录文件
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
    """获取用户签到数据文件路径"""
    return f"{DATA_FILES['users']}/{user_id}.json"

def load_user_data(user_id: str) -> Dict:
    """加载用户签到数据"""
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
        "total_sign_days": 0,  # 总签到天数
        "consecutive_days": 0,  # 连续签到天数
        "last_sign_date": None,  # 最后签到日期
        "sign_history": {},  # 签到历史记录，格式：YYYY-MM: [日期列表]
        "total_coins_earned": 0,  # 通过签到获得的总银币
        "special_bonus_count": 0,  # 获得特殊奖励的次数
        "claimed_compensations": [],  # 已领取的补偿ID列表
    }

def save_user_data(user_id: str, data: Dict) -> bool:
    """保存用户签到数据"""
    try:
        user_file = get_user_file_path(user_id)
        write_file(user_file, json.dumps(data, ensure_ascii=False, indent=2))
        return True
    except Exception as e:
        logger.error(f"保存用户签到数据失败: {e}")
        return False

def get_global_data() -> Dict:
    """获取全局统计数据"""
    try:
        data = read_file(DATA_FILES["global"])
        if data:
            return json.loads(data)
    except:
        pass
    
    # 返回默认数据
    return {
        "total_sign_count": 0,  # 全服总签到次数
        "today_sign_count": 0,  # 今日签到人数
        "today_sign_users": [],  # 今日签到用户列表
        "last_update_date": datetime.now().strftime("%Y-%m-%d")  # 最后更新日期
    }

def save_global_data(data: Dict) -> bool:
    """保存全局统计数据"""
    try:
        write_file(DATA_FILES["global"], json.dumps(data, ensure_ascii=False, indent=2))
        return True
    except Exception as e:
        logger.error(f"保存全局数据失败: {e}")
        return False

# ==================== 补偿系统相关函数 ====================
def load_compensations() -> Dict:
    """加载所有补偿记录"""
    try:
        data = read_file(DATA_FILES["compensations"])
        if data:
            comp_data = json.loads(data)
            # 兼容旧数据格式
            if "compensations" not in comp_data:
                comp_data = {"compensations": comp_data if isinstance(comp_data, list) else [], "next_id": 1}
            if "next_id" not in comp_data:
                comp_data["next_id"] = max([c["id"] for c in comp_data["compensations"]], default=0) + 1
            return comp_data
    except:
        pass
    return {"compensations": [], "next_id": 1}

def save_compensations(comp_data: Dict) -> bool:
    """保存补偿记录"""
    try:
        write_file(DATA_FILES["compensations"], json.dumps(comp_data, ensure_ascii=False, indent=2))
        return True
    except Exception as e:
        logger.error(f"保存补偿数据失败: {e}")
        return False

def add_compensation(amount: int, reason: str) -> Tuple[bool, int, str]:
    """添加新的补偿记录，返回(是否成功, 补偿ID, 错误信息)"""
    if amount <= 0:
        return False, 0, "补偿额度必须为正整数"
    
    comp_data = load_compensations()
    now = datetime.now()
    compensation = {
        "id": comp_data["next_id"],
        "amount": amount,
        "reason": reason,
        "start_time": now.isoformat(),
        "end_time": (now + timedelta(days=5)).isoformat()
    }
    comp_data["compensations"].append(compensation)
    comp_data["next_id"] += 1
    if save_compensations(comp_data):
        return True, compensation["id"], ""
    return False, 0, "保存补偿记录失败"

def get_active_compensations() -> List[Dict]:
    """获取所有有效的补偿（当前时间在有效期内）"""
    comp_data = load_compensations()
    now = datetime.now()
    active = []
    for comp in comp_data["compensations"]:
        try:
            end_time = datetime.fromisoformat(comp["end_time"])
            if now <= end_time:
                active.append(comp)
        except:
            continue
    return active

# ==================== 签到核心函数 ====================
def check_special_date() -> Tuple[bool, Dict]:
    """检查今天是否是特殊日期"""
    today_str = datetime.now().strftime("%m-%d")
    special_date_info = config.special_dates.get(today_str)
    
    if special_date_info:
        return True, special_date_info
    return False, {}

def get_month_sign_days(user_data: Dict, year: int, month: int) -> List[int]:
    """获取用户指定月份的签到日期列表"""
    month_key = f"{year:04d}-{month:02d}"
    
    if "sign_history" not in user_data:
        user_data["sign_history"] = {}
    
    if month_key not in user_data["sign_history"]:
        user_data["sign_history"][month_key] = []
    
    return user_data["sign_history"][month_key]

def calculate_consecutive_multiplier(consecutive_days: int) -> float:
    """计算连续签到奖励倍数"""
    if not config.consecutive_bonus:
        return 1.0
    
    multipliers = config.consecutive_multipliers
    if not multipliers:
        return 1.0
    
    # 如果连续天数超过倍数列表长度，取最后一个倍数
    index = min(consecutive_days - 1, len(multipliers) - 1)
    if index < 0:
        return 1.0
    
    return multipliers[index]

def generate_month_calendar(year: int, month: int, sign_days: List[int]) -> str:
    """生成月度签到日历"""
    # 获取日历
    cal = calendar.monthcalendar(year, month)
    month_names = ["一月", "二月", "三月", "四月", "五月", "六月", 
                   "七月", "八月", "九月", "十月", "十一月", "十二月"]
    
    # 星期标题
    week_days = ["一", "二", "三", "四", "五", "六", "日"]
    
    # 构建日历
    today = datetime.now().day
    result = f"{year}年 {month_names[month-1]}\n"
    result += " ".join(week_days) + "\n"
    
    for week in cal:
        line = ""
        for day in week:
            if day == 0:
                line += "   "
            else:
                if day in sign_days:
                    if day == today and datetime.now().month == month and datetime.now().year == year:
                        line += "✓ "
                    else:
                        line += "✓ "
                else:
                    if day == today and datetime.now().month == month and datetime.now().year == year:
                        line += f"{day:2d}*"
                    else:
                        line += f"{day:2d} "
        result += line + "\n"
    
    return result

# 命令处理器
sign_cmd = on_command("sign", aliases={"签到", "打卡", "checkin"}, priority=5, block=True)
sign_record_cmd = on_command("sign_record", aliases={"签到记录", "我的签到"}, priority=5, block=True)
sign_month_cmd = on_command("sign_month", aliases={"月度签到", "月签到统计"}, priority=5, block=True)
sign_help_cmd = on_command("sign_help", aliases={"签到帮助"}, priority=5, block=True)
compensate_cmd = on_command("compensate", aliases={"补偿", "系统补偿"}, priority=5, block=True)

# ==================== 补偿处理核心逻辑 ====================
async def process_compensations(user_id: str, user_data: Dict, nickname: str) -> Tuple[str, int]:
    """
    处理用户所有未领取的补偿
    返回 (补偿信息字符串, 总补偿银币数)
    """
    # 获取所有有效补偿
    active_comps = get_active_compensations()
    if not active_comps:
        return "", 0
    
    # 获取已领取的补偿ID集合
    claimed = set(user_data.get("claimed_compensations", []))
    
    # 筛选未领取的补偿
    pending = [comp for comp in active_comps if comp["id"] not in claimed]
    if not pending:
        return "", 0
    
    # 计算总补偿额并生成消息
    total_amount = 0
    comp_details = []
    for comp in pending:
        total_amount += comp["amount"]
        comp_details.append(f"  • {comp['amount']}银币: {comp['reason']}")
    
    # 发放银币（不获得经验）
    if total_amount > 0:
        new_coins, _ = await get_coins(user_id, total_amount, 0, nickname)
        logger.info(f"用户 {user_id}({nickname}) 领取补偿 {total_amount} 银币，补偿列表: {[c['id'] for c in pending]}")
        
        # 更新已领取记录
        if "claimed_compensations" not in user_data:
            user_data["claimed_compensations"] = []
        for comp in pending:
            if comp["id"] not in user_data["claimed_compensations"]:
                user_data["claimed_compensations"].append(comp["id"])
        
        # 保存用户数据
        save_user_data(user_id, user_data)
        
        # 生成补偿信息文本
        info = f"\n\n🎁 【系统补偿】共领取 {total_amount} 银币:\n" + "\n".join(comp_details)
        return info, total_amount
    
    return "", 0

@sign_cmd.handle()
async def handle_sign(event: MessageEvent):
    """处理签到命令"""
    user_id = get_user_id(event)
    nickname = get_user_nickname(event)
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 加载用户数据
    user_data = load_user_data(user_id)
    
    # 先处理补偿（无论今天是否已签到，都可以领取补偿）
    compensation_msg, compensation_coins = await process_compensations(user_id, user_data, nickname)
    
    # 检查今天是否已经签到
    if user_data.get("last_sign_date") == today:
        # 获取银币余额
        coin_balance, exp, _ = await get_user_info(user_id)
        
        # 计算下次可签到时间（明天0点）
        tomorrow = datetime.now() + timedelta(days=1)
        next_sign_time = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0)
        wait_hours = (next_sign_time - datetime.now()).seconds // 3600
        wait_minutes = ((next_sign_time - datetime.now()).seconds % 3600) // 60
        
        reply_msg = f"🎉 今日已签到！\n\n"
        reply_msg += f"💰 当前银币: {coin_balance}枚\n"
        reply_msg += f"🌟 当前经验: {exp}点\n"
        reply_msg += f"📅 已连续签到: {user_data.get('consecutive_days', 0)}天\n"
        reply_msg += f"⏰ 下次可签到: {wait_hours}小时{wait_minutes}分钟后"
        
        if compensation_msg:
            reply_msg += compensation_msg
        
        message_id = event.message_id if hasattr(event, 'message_id') else None
        if message_id:
            await sign_cmd.finish(MessageSegment.reply(message_id) + reply_msg)
        else:
            await sign_cmd.finish(reply_msg)
    
    # 计算连续签到天数
    last_sign_date = user_data.get("last_sign_date")
    if last_sign_date:
        last_date = datetime.strptime(last_sign_date, "%Y-%m-%d")
        today_date = datetime.strptime(today, "%Y-%m-%d")
        
        # 如果昨天签到了，连续天数+1，否则重置为1
        if (today_date - last_date).days == 1:
            user_data["consecutive_days"] = user_data.get("consecutive_days", 0) + 1
        else:
            user_data["consecutive_days"] = 1
    else:
        # 第一次签到
        user_data["consecutive_days"] = 1
    
    # 生成随机银币
    min_coins, max_coins = config.coin_range
    base_coins = random.randint(min_coins, max_coins)
    
    # 计算连续签到奖励倍数
    multiplier = calculate_consecutive_multiplier(user_data["consecutive_days"])
    
    # 检查特殊日期
    is_special, special_info = check_special_date()
    special_bonus = 0
    special_name = ""
    
    if is_special:
        special_bonus = special_info.get("bonus", 0)
        special_name = special_info.get("name", "特殊日期")
    
    # 计算总银币
    total_coins = int(base_coins * multiplier) + special_bonus
    
    # 获取用户信息并增加银币
    _, exp, _ = await get_user_info(user_id)
    new_coins, new_exp = await get_coins(
        user_id, 
        total_coins, 
        config.exp_multiple, 
        nickname
    )
    
    # 更新用户数据
    user_data["last_sign_date"] = today
    user_data["total_sign_days"] = user_data.get("total_sign_days", 0) + 1
    user_data["total_coins_earned"] = user_data.get("total_coins_earned", 0) + total_coins
    
    if is_special:
        user_data["special_bonus_count"] = user_data.get("special_bonus_count", 0) + 1
    
    # 更新月度签到记录
    today_date = datetime.now()
    year_month = today_date.strftime("%Y-%m")
    day = today_date.day
    
    if "sign_history" not in user_data:
        user_data["sign_history"] = {}
    
    if year_month not in user_data["sign_history"]:
        user_data["sign_history"][year_month] = []
    
    if day not in user_data["sign_history"][year_month]:
        user_data["sign_history"][year_month].append(day)
        user_data["sign_history"][year_month].sort()
    
    # 保存用户数据
    save_user_data(user_id, user_data)
    
    # 更新全局数据
    global_data = get_global_data()
    
    # 如果是新的一天，重置今日统计
    if global_data.get("last_update_date") != today:
        global_data["today_sign_count"] = 0
        global_data["today_sign_users"] = []
        global_data["last_update_date"] = today
    
    # 更新今日统计
    global_data["total_sign_count"] = global_data.get("total_sign_count", 0) + 1
    global_data["today_sign_count"] = global_data.get("today_sign_count", 0) + 1
    
    if user_id not in global_data["today_sign_users"]:
        global_data["today_sign_users"].append(user_id)
    
    save_global_data(global_data)
    
    # 构建回复消息
    reply_msg = f"🎉 签到成功！\n\n"
    reply_msg += f"💰 获得银币: {total_coins}枚\n"
    
    if base_coins != total_coins:
        reply_msg += f"   - 基础奖励: {base_coins}枚\n"
        
        if multiplier > 1.0:
            reply_msg += f"   - 连续签到{multiplier}倍: {int(base_coins * multiplier)}枚\n"
        
        if is_special:
            reply_msg += f"   - {special_name}奖励: +{special_bonus}枚\n"
    
    reply_msg += f"\n📅 连续签到: 第{user_data['consecutive_days']}天\n"
    reply_msg += f"📊 总签到天数: {user_data['total_sign_days']}天\n"
    reply_msg += f"💰 累计签到奖励: {user_data['total_coins_earned']}银币\n\n"
    reply_msg += f"💳 当前银币: {new_coins}枚\n"
    reply_msg += f"🌟 当前经验: {new_exp}点"
    
    # 添加补偿信息
    if compensation_msg:
        reply_msg += compensation_msg
    
    # 检查是否是本月最后一天
    today_date = datetime.now()
    last_day = calendar.monthrange(today_date.year, today_date.month)[1]
    if today_date.day == last_day:
        # 检查本月是否全勤
        sign_days = get_month_sign_days(user_data, today_date.year, today_date.month)
        if len(sign_days) == last_day:
            # 发放全勤奖励
            await get_coins(user_id, config.monthly_full_sign_bonus, 0, nickname)
            reply_msg += f"\n\n🎁 恭喜本月全勤！额外获得{config.monthly_full_sign_bonus}银币全勤奖励！"
    
    # 发送回复
    message_id = event.message_id if hasattr(event, 'message_id') else None
    if message_id:
        await sign_cmd.finish(MessageSegment.reply(message_id) + reply_msg)
    else:
        await sign_cmd.finish(reply_msg)

@sign_record_cmd.handle()
async def handle_sign_record(event: MessageEvent):
    """处理签到记录查询"""
    user_id = get_user_id(event)
    nickname = get_user_nickname(event)
    
    # 加载用户数据
    user_data = load_user_data(user_id)
    
    # 获取当前日期
    today = datetime.now()
    year = today.year
    month = today.month
    
    # 获取本月签到天数
    sign_days = get_month_sign_days(user_data, year, month)
    
    # 获取连续签到天数
    consecutive_days = user_data.get("consecutive_days", 0)
    
    # 获取银币余额
    coin_balance, exp, _ = await get_user_info(user_id)
    
    # 构建回复消息
    reply_msg = f"📅 {nickname}的签到记录\n"
    reply_msg += "=" * 20 + "\n\n"
    
    # 基本信息
    reply_msg += f"💰 当前银币: {coin_balance}枚\n"
    reply_msg += f"🌟 当前经验: {exp}点\n"
    reply_msg += f"📅 连续签到: {consecutive_days}天\n"
    reply_msg += f"📊 总签到天数: {user_data.get('total_sign_days', 0)}天\n"
    reply_msg += f"💰 累计签到奖励: {user_data.get('total_coins_earned', 0)}银币\n\n"
    
    # 月度签到统计
    reply_msg += f"📆 {year}年{month}月签到统计:\n"
    reply_msg += f"   本月已签到: {len(sign_days)}天\n"
    
    # 检查今天是否签到
    if user_data.get("last_sign_date") == today.strftime("%Y-%m-%d"):
        reply_msg += f"   今日状态: 已签到\n"
    else:
        reply_msg += f"   今日状态: 未签到\n"
    
    # 显示签到日历
    if sign_days:
        calendar_text = generate_month_calendar(year, month, sign_days)
        reply_msg += f"\n{calendar_text}"
        reply_msg += f"\n✓ 表示已签到  *表示今天"
    else:
        reply_msg += f"\n本月还未签到过，快来签到吧！"
    
    # 发送回复
    message_id = event.message_id if hasattr(event, 'message_id') else None
    if message_id:
        await sign_record_cmd.finish(MessageSegment.reply(message_id) + reply_msg)
    else:
        await sign_record_cmd.finish(reply_msg)

@sign_month_cmd.handle()
async def handle_sign_month(event: MessageEvent, args: Message = CommandArg()):
    """处理月度签到统计"""
    user_id = get_user_id(event)
    nickname = get_user_nickname(event)
    
    # 解析参数
    arg_text = args.extract_plain_text().strip()
    today = datetime.now()
    
    if arg_text:
        # 尝试解析年月，格式：YYYY-MM
        try:
            if "-" in arg_text:
                year_str, month_str = arg_text.split("-", 1)
                year = int(year_str)
                month = int(month_str)
            else:
                # 只输入月份
                month = int(arg_text)
                year = today.year
                
                # 如果输入的月份大于当前月份，则认为是去年
                if month > today.month:
                    year -= 1
        except ValueError:
            year = today.year
            month = today.month
    else:
        year = today.year
        month = today.month
    
    # 确保月份在有效范围内
    if month < 1 or month > 12:
        month = today.month
    
    # 加载用户数据
    user_data = load_user_data(user_id)
    
    # 获取指定月份的签到天数
    sign_days = get_month_sign_days(user_data, year, month)
    
    # 计算当月天数
    _, last_day = calendar.monthrange(year, month)
    all_days = list(range(1, last_day + 1))
    
    # 构建回复消息
    month_names = ["一月", "二月", "三月", "四月", "五月", "六月", 
                   "七月", "八月", "九月", "十月", "十一月", "十二月"]
    
    reply_msg = f"📅 {nickname}的{year}年{month_names[month-1]}签到统计\n"
    reply_msg += "=" * 20 + "\n\n"
    
    # 统计信息
    reply_msg += f"📊 签到情况: {len(sign_days)}/{last_day}天\n"
    reply_msg += f"📈 签到率: {len(sign_days)/last_day*100:.1f}%\n\n"
    
    if len(sign_days) == last_day:
        reply_msg += "🎉 恭喜本月全勤！\n\n"
    
    # 显示签到日历
    calendar_text = generate_month_calendar(year, month, sign_days)
    reply_msg += calendar_text
    reply_msg += f"\n✓ 表示已签到  *表示今天（如果显示）"
    
    # 发送回复
    await sign_month_cmd.finish(reply_msg)

@sign_help_cmd.handle()
async def handle_sign_help():
    """显示签到帮助"""
    min_coins, max_coins = config.coin_range
    
    reply_msg = "📅 每日签到系统帮助\n"
    reply_msg += "=" * 20 + "\n\n"
    
    reply_msg += f"💰 签到奖励: {min_coins}-{max_coins}银币/天\n"
    
    if config.consecutive_bonus:
        multipliers = config.consecutive_multipliers
        reply_msg += f"📈 连续签到奖励: "
        for i, mult in enumerate(multipliers[:7], 1):
            reply_msg += f"第{i}天{mult}倍 "
        reply_msg += "\n"
    
    reply_msg += f"🎁 每月全勤奖励: {config.monthly_full_sign_bonus}银币\n"
    reply_msg += f"🌟 经验倍数: {config.exp_multiple}倍\n\n"
    
    # 特殊日期
    if config.special_dates:
        reply_msg += "🎉 特殊日期额外奖励:\n"
        for date_str, info in config.special_dates.items():
            name = info.get("name", "特殊日")
            bonus = info.get("bonus", 0)
            reply_msg += f"  {date_str} {name}: +{bonus}银币\n"
        reply_msg += "\n"
    
    reply_msg += "🎯 可用命令:\n"
    reply_msg += "  /sign - 每日签到\n"
    reply_msg += "  /sign_record - 查看签到记录\n"
    reply_msg += "  /sign_month [YYYY-MM] - 查看指定月份签到统计\n"
    reply_msg += "  /sign_help - 显示此帮助\n"
    reply_msg += "  /compensate <额度> [理由] - (管理员)发布系统维护补偿\n\n"
    
    reply_msg += "📝 注意事项:\n"
    reply_msg += "  1. 每天只能签到一次\n"
    reply_msg += "  2. 连续签到中断后会重新计算\n"
    reply_msg += "  3. 每月最后一天自动发放全勤奖励\n"
    reply_msg += "  4. 管理员发布的补偿在5天内有效，每次签到自动领取\n"
    
    await sign_help_cmd.finish(reply_msg)

@compensate_cmd.handle()
async def handle_compensate(event: MessageEvent, args: Message = CommandArg()):
    """管理员发布系统维护补偿"""
    # 管理员ID检查
    ADMIN_ID = "1287428141"
    user_id = get_user_id(event)
    if user_id != ADMIN_ID:
        await compensate_cmd.finish("❌ 权限不足，只有管理员可以发布补偿。")
    
    # 解析参数
    arg_text = args.extract_plain_text().strip()
    if not arg_text:
        await compensate_cmd.finish("❌ 用法: /compensate <额度> [理由]\n例如: /compensate 100 服务器维护补偿")
    
    parts = arg_text.split(maxsplit=1)
    try:
        amount = int(parts[0])
    except ValueError:
        await compensate_cmd.finish("❌ 补偿额度必须是正整数")
    
    if amount <= 0:
        await compensate_cmd.finish("❌ 补偿额度必须大于0")
    
    reason = parts[1] if len(parts) > 1 else "系统维护补偿"
    
    # 添加补偿
    success, comp_id, error = add_compensation(amount, reason)
    if not success:
        await compensate_cmd.finish(f"❌ 发布补偿失败: {error}")
    
    # 计算有效期截止时间
    end_time = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    reply_msg = f"✅ 系统补偿已发布！\n"
    reply_msg += f"💰 补偿额度: {amount}银币\n"
    reply_msg += f"📝 补偿理由: {reason}\n"
    reply_msg += f"⏰ 有效期: 5天 (截止 {end_time})\n"
    reply_msg += f"🆔 补偿ID: {comp_id}\n\n"
    reply_msg += f"所有用户在有效期内首次使用 /sign 将自动领取该补偿（每人仅一次）。"
    
    await compensate_cmd.finish(reply_msg)

# 插件启动时的初始化
@driver.on_startup
async def init_sign_system():
    """初始化签到系统"""
    logger.info("每日签到系统初始化完成")