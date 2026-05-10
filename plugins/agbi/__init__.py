from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata
from nonebot import require
from .config import Config

require("plugins.file_edit")
from plugins.file_edit import read_file, read_large_file, write_file, delete_file

__plugin_meta__ = PluginMetadata(
    name="agbi",
    description="银币核心功能之银币怎么看",
    usage="银币怎么看",
    config=Config,
)

config = get_plugin_config(Config)

from nonebot.rule import to_me, startswith
from nonebot.plugin import on_command,on_message
from nonebot.params import CommandArg, EventMessage
from nonebot.adapters.console import Message
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.adapters import Event
from nonebot.log import logger

import time
import random as rand
import asyncio
# import aiohttp


agno3 = on_message(
    rule=startswith(("银币怎么", "银币如何", "银币怎样", "银币")),  # 或用 to_me() + startswith() 组合规则
    priority=5
)

@agno3.handle()
async def handle_function(event: Event):
    agno3_saying = agno3_said()
    msg = agno3_saying.split('|')
    message_id = event.message_id if hasattr(event, 'message_id') else None
    for i,m in enumerate(msg):
        this_msg = m
        if message_id and i < 1:
            this_msg = MessageSegment.reply(message_id) + m
        await agno3.send(this_msg)
        await asyncio.sleep(0.1+rand.random()*0.1)
   

agno3_add = on_command('agno3_add')
@agno3_add.handle()
async def _(event: Event, message: Message = CommandArg()):
    u = str(message).strip(' ')
    n = read_file("agno3.txt")
    if rand.random()>0.1:
        await agno3_add.send(f'已添加新的名言"{u}"')
        write_file('agno3.txt',n+'◈'+u)
    else:
        await agno3_add.send('别啥都加没意思')
        write_file('agno3.txt',n+'◈'+u)

def agno3_said():
    n = read_file("agno3.txt")
    agno3_list = n.split('◈')
    ra = rand.randint(0,len(agno3_list)-1)
    return agno3_list[ra]
