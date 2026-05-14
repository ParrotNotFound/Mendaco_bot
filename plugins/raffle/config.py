from pydantic import BaseModel, Field
from typing import Dict, List, Tuple, Optional

class RecordConfig(BaseModel):
    """唱片抽取插件配置"""
    
    # 抽取消耗的银币数量
    draw_cost: int = Field(1, description="每次抽取消耗的银币数")
    
    # 唱片等级和概率配置
    record_rarity_prob: Dict[str, float] = Field(
        default_factory=lambda: {
            "B": 0.4,    # 40% 概率
            "A": 0.38,    # 25% 概率
            "S": 0.13,    # 15% 概率
            "SS": 0.06,   # 10% 概率
            "SSS": 0.029,  # 7% 概率
            "LEGEND": 0.001  # 3% 概率
        },
        description="唱片等级概率分布（总和应为1.0）"
    )
    
    # 每个等级对应的难度区间（DS值范围）
    record_ds_ranges: Dict[str, Tuple[float, float]] = Field(
        default_factory=lambda: {
            "B": (0, 13.0),      # 简单难度
            "A": (13.0, 13.5),      # 中等难度
            "S": (13.6, 13.9),      # 困难难度
            "SS": (14.0, 14.6),    # 专家难度
            "SSS": (14.7, 14.9),  # 大师难度
            "LEGEND": (15.0, 15.1)  # 传奇难度
        },
        description="每个等级对应的DS难度值范围"
    )
    
    # 每次抽取获得的经验倍数
    exp_multiple: float = Field(0, description="抽取获得经验的倍数")
    
    # 用户数据存储限制
    max_records_per_user: int = Field(100000, description="每个用户最多保存的唱片数量")
    
    # 每日抽取限制
    daily_draw_limit: int = Field(10000, description="每日最多抽取次数")
    
    # 是否允许重复获得同一首曲目
    allow_duplicates: bool = Field(True, description="是否允许获得重复曲目")