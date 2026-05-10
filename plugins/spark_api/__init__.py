from nonebot import get_plugin_config, get_driver
from nonebot.plugin import PluginMetadata
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import asyncio

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="spark_api",
    description="讯飞星火大模型API集成，支持上下文记忆功能",
    usage="使用命令: ask [问题] 与AI对话，支持多轮对话",
    config=Config,
)

config = get_plugin_config(Config)

# 上下文管理器类
class ConversationContext:
    def __init__(self, max_turns: int = 10, timeout_minutes: int = 30):
        """
        初始化对话上下文管理器
        
        Args:
            max_turns: 最大对话轮次，默认为10轮
            timeout_minutes: 上下文超时时间（分钟），默认为30分钟
        """
        self.contexts: Dict[str, List[dict]] = defaultdict(list)
        self.max_turns = max_turns
        self.timeout_minutes = timeout_minutes
        self.last_active: Dict[str, datetime] = {}
        self.lock = asyncio.Lock()
    
    def _get_session_key(self, session_id: str) -> str:
        """生成会话键"""
        return f"session_{session_id}"
    
    async def get_context(self, session_id: str) -> List[dict]:
        """
        获取指定会话的上下文
        
        Args:
            session_id: 会话ID，如群聊ID或私聊用户ID
            
        Returns:
            上下文消息列表
        """
        session_key = self._get_session_key(session_id)
        
        # 检查上下文是否过期
        async with self.lock:
            if session_key in self.last_active:
                last_time = self.last_active[session_key]
                if datetime.now() - last_time > timedelta(minutes=self.timeout_minutes):
                    # 上下文已过期，清空
                    if session_key in self.contexts:
                        del self.contexts[session_key]
                    if session_key in self.last_active:
                        del self.last_active[session_key]
            
            # 更新最后活跃时间
            self.last_active[session_key] = datetime.now()
            
            return self.contexts.get(session_key, [])
    
    async def add_to_context(self, session_id: str, role: str, content: str):
        """
        添加消息到上下文
        
        Args:
            session_id: 会话ID
            role: 角色，'user' 或 'assistant'
            content: 消息内容
        """
        session_key = self._get_session_key(session_id)
        
        async with self.lock:
            if session_key not in self.contexts:
                self.contexts[session_key] = []
            
            # 添加新消息
            self.contexts[session_key].append({
                "role": role,
                "content": content
            })
            
            # 限制上下文长度
            if len(self.contexts[session_key]) > self.max_turns * 2:  # 乘以2因为每轮包含user和assistant
                # 保留最近的消息，移除最旧的消息
                self.contexts[session_key] = self.contexts[session_key][-self.max_turns * 2:]
            
            # 更新最后活跃时间
            self.last_active[session_key] = datetime.now()
    
    async def clear_context(self, session_id: str):
        """清除指定会话的上下文"""
        session_key = self._get_session_key(session_id)
        
        async with self.lock:
            if session_key in self.contexts:
                del self.contexts[session_key]
            if session_key in self.last_active:
                del self.last_active[session_key]
    
    async def get_context_count(self, session_id: str) -> int:
        """获取指定会话的上下文消息数量"""
        session_key = self._get_session_key(session_id)
        return len(self.contexts.get(session_key, [])) // 2  # 除以2得到对话轮数

# 初始化上下文管理器
context_manager = ConversationContext()

# 获取驱动器配置
driver = get_driver()

# 配置项
# 初始化上下文管理器
# 从配置中读取参数，如果没有设置则使用默认值
context_manager = ConversationContext(
    max_turns=config.spark_max_turns,
    timeout_minutes=config.spark_timeout_minutes
)

# 直接从 config 对象获取配置项
# 注意：这里不再有硬编码的默认值，所有值都应来自 .env 文件
SPARK_APP_ID = config.spark_app_id
SPARK_API_KEY = config.spark_api_key
SPARK_API_SECRET = config.spark_api_secret
SPARK_API_HOST = config.spark_api_host
# 导入其他必要的模块
from nonebot import on_command
from nonebot.adapters import Event
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Message, MessageEvent, GroupMessageEvent, PrivateMessageEvent
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.log import logger
import aiohttp
import json
import hashlib
import hmac
import base64
from urllib.parse import urlparse
from time import mktime
from wsgiref.handlers import format_date_time

# 创建命令处理器
spark = on_command("ask", aliases={"问答", "提问"}, priority=5, block=True)
clear_context = on_command("clear_context", aliases={"清除上下文", "新对话"}, priority=5, block=True)

@spark.handle()
async def handle_spark(event: Event, message: Message = CommandArg()):
    question = message.extract_plain_text().strip()
    if not question:
        await spark.finish("请输入您的问题")
    
    # 获取会话ID
    session_id = await get_session_id(event)
    
    try:
        # 获取上下文
        context = await context_manager.get_context(session_id)
        
        # 添加用户问题到上下文
        await context_manager.add_to_context(session_id, "user", question)
        
        # 获取星火API响应
        response = await get_spark_response(question, context)
        
        # 添加AI回答到上下文
        await context_manager.add_to_context(session_id, "assistant", response)
        
        # 获取当前对话轮数
        turn_count = await context_manager.get_context_count(session_id)
        
        # 发送响应
        if turn_count > 1:
            await spark.send(f"（已记忆{turn_count-1}轮对话）\n{response}")
        else:
            await spark.send(response)
            
    except Exception as e:
        logger.error(f"讯飞星火API调用失败: {str(e)}")
        await spark.finish("暂时无法回答，请稍后再试")

@clear_context.handle()
async def handle_clear_context(event: Event):
    """清除上下文命令处理器"""
    session_id = await get_session_id(event)
    
    # 获取清除前的上下文轮数
    turn_count = await context_manager.get_context_count(session_id)
    
    if turn_count > 0:
        await context_manager.clear_context(session_id)
        await clear_context.finish(f"已清除{turn_count}轮对话的上下文，开始新的对话")
    else:
        await clear_context.finish("当前没有可清除的对话上下文")

async def get_session_id(event: Event) -> str:
    """
    获取会话ID
    
    Args:
        event: 消息事件
        
    Returns:
        会话ID字符串
    """
    if isinstance(event, GroupMessageEvent):
        # 群聊：使用群号
        return f"group_{event.group_id}"
    elif isinstance(event, PrivateMessageEvent):
        # 私聊：使用用户号
        return f"private_{event.user_id}"
    else:
        # 其他适配器：使用session_id
        return event.get_session_id()

async def get_spark_response(question: str, context: Optional[List[dict]] = None) -> str:
    """
    调用星火API获取响应，支持上下文
    
    Args:
        question: 用户问题
        context: 历史上下文
        
    Returns:
        AI响应文本
    """
    # 构造请求URL
    url = create_spark_url()
    
    # 准备消息列表
    messages = []
    
    # 添加上下文（如果有）
    if context:
        messages.extend(context)
    else:
        messages.append({"role":"system","content":"现在你是Mendaco的智能小助手，名为Mendaco_bot，你要语气轻快地回答所有问题。"})
    # 添加当前问题
    messages.append({"role": "user", "content": question})
    
    # 构造请求数据
    data = {
        "header": {
            "app_id": SPARK_APP_ID,
            "uid": "agbi"
        },
        "parameter": {
            "chat": {
                "domain": "general",
                "temperature": 0.5,
                "max_tokens": 2048
            }
        },
        "payload": {
            "message": {
                "text": messages
            }
        }
    }

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url) as ws:
            await ws.send_str(json.dumps(data))
            result = ""
            
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    response = json.loads(msg.data)
                    if response["header"]["code"] != 0:
                        raise Exception(f"API Error: {response['header']['message']}")
                    
                    # 拼接响应内容
                    choices = response["payload"]["choices"]
                    result += choices["text"][0]["content"]
                    
                    # 判断是否结束
                    if choices["status"] == 2:
                        break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    raise Exception("WebSocket connection closed with error")
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    break
    
    return result

def create_spark_url() -> str:
    """生成星火API的鉴权URL"""
    host = urlparse(SPARK_API_HOST).netloc
    path = urlparse(SPARK_API_HOST).path
    
    # 生成RFC1123格式时间戳
    now = datetime.now()
    date = format_date_time(mktime(now.timetuple()))
    
    # 拼接签名字符串
    signature_origin = f"host: {host}\ndate: {date}\nGET {path} HTTP/1.1"
    
    # 进行hmac-sha256加密
    signature_sha = hmac.new(SPARK_API_SECRET.encode('utf-8'),
                            signature_origin.encode('utf-8'),
                            digestmod=hashlib.sha256).digest()
    
    signature_sha_base64 = base64.b64encode(signature_sha).decode(encoding='utf-8')
    
    # 构造授权参数
    authorization_origin = f'api_key="{SPARK_API_KEY}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature_sha_base64}"'
    authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode(encoding='utf-8')
    
    # 构造请求URL
    return f"{SPARK_API_HOST}?authorization={authorization}&date={date}&host={host}"

# 定时清理过期上下文的定时任务
'''from nonebot import require
require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

@scheduler.scheduled_job("cron", hour="*/1", id="clean_expired_contexts")
async def clean_expired_contexts():
    """每小时清理一次过期的上下文"""
    now = datetime.now()
    expired_keys = []
    
    for session_key, last_time in context_manager.last_active.items():
        if now - last_time > timedelta(minutes=context_manager.timeout_minutes):
            expired_keys.append(session_key)
    
    for session_key in expired_keys:
        session_id = session_key.replace("session_", "")
        await context_manager.clear_context(session_id)
    
    if expired_keys:
        logger.info(f"已清理 {len(expired_keys)} 个过期的对话上下文")'''