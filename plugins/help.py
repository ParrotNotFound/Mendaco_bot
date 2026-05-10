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
    msg = '''Mendaco_bot v0.1.0
    最初版本的bot。
    借用“银币怎么看”功能；
    加入智能聊天功能
    '''
    await version.send(msg)
