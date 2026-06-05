from pydantic import BaseModel, Field
from typing import Tuple, Dict, Any
from pathlib import Path

class TankConfig(BaseModel):
    """鱼缸插件配置"""
    tank_open: bool = Field(
        False,  # 默认关闭
        description="是否开启鱼缸功能"
    )
    # 鱼的价值范围
    fish_value_range: Tuple[int, int] = Field(
        (3, 50),  # 每条鱼的价值范围
        description="单条鱼的价值范围（最小值，最大值）"
    )
    
    # 单次加入数量限制
    max_fish_per_add: int = Field(
        20,  # 单次最多加入20条
        description="单次最多可加入的鱼数量"
    )
    
    # 鱼缸背景配置
    default_tank_color: Tuple[int, int, int] = Field(
        (173, 216, 230),  # 淡蓝色
        description="默认鱼缸背景颜色 (R, G, B)"
    )
    
    default_tank_size: Tuple[int, int] = Field(
        (800, 600),  # 默认鱼缸尺寸 (宽, 高)
        description="默认鱼缸背景尺寸"
    )
    
    # 图片处理配置
    image_wait_timeout: int = Field(
        60,  # 60秒
        description="等待用户发送图片的超时时间（秒）"
    )
    
    background_remove_model: str = Field(
        "u2net",  # 抠图模型
        description="背景移除模型 (u2net, u2netp, u2net_human_seg)"
    )
    
    # 鱼缸存储配置
    tank_data_dir: str = Field(
        "data/tanks",  # 鱼缸数据目录
        description="鱼缸数据存储目录"
    )
    
    fish_images_dir: str = Field(
        "data/tanks/images",  # 鱼图片存储目录
        description="鱼图片存储目录"
    )
    
    # 鱼缸渲染配置
    max_fish_in_tank: int = Field(
        100,  # 鱼缸最多显示100条鱼
        description="鱼缸最多显示的鱼数量"
    )
    
    # 鱼的大小计算系数
    fish_size_multiplier: float = Field(
        0.075,  # 基础倍数
        description="鱼大小的基础倍数"
    )
    
    # 鱼的旋转角度范围
    max_rotation_angle: int = Field(
        10,  # ±10度
        description="鱼的最大旋转角度（正负）"
    )