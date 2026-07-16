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
    msg = '''Mendaco_bot v0.6.1 beta
    宠物系统进行大幅度更新，使用/pet_help查看帮助'''
    await version.send(msg)

helps = on_command('help')

@helps.handle()
async def handle_function(event: Event):
    msg = '''📋 功能一览：
    🎲 漂流瓶  -> /throw /bottle /comment
    🤖 AI对话  -> /ask
    🎣 钓鱼    -> /fish_help
    🐟 鱼缸    -> /tank
    💿 抽卡    -> /record_help
    🐾 宠物    -> /pet_help
    💰 货币    -> /user
    📅 签到    -> /sign_help
    
    使用各功能的帮助命令查看详细用法'''
    await helps.send(msg)