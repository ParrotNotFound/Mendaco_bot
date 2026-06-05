from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata
from nonebot import require
from nonebot.rule import to_me, startswith
from nonebot.plugin import on_command,on_message
from nonebot.params import CommandArg, EventMessage
from nonebot.adapters.console import Message
from nonebot.adapters import Event
from nonebot.log import logger

import time
import random as rand

version = on_command('about')

@version.handle()
async def handle_function(event: Event):
    msg = '''Mendaco_bot v0.5.1
    钓鱼功能大改，新增季节与海钓机制；
    新增鱼缸功能（默认关闭，需管理员手动开启）
    新增一次多钓功能'''
    await version.send(msg)

helps = on_command('help')

@helps.handle()
async def handle_function(event: Event):
    msg = '''功能一览：
    漂流瓶->/throw /bottle /comment
    小助手->/ask
    钓鱼->/fish_help
    鱼缸->/tank
    抽卡->/record_help
    查询个人货币->/user
    等待后续更新中'''
    await helps.send(msg)