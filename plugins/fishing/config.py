from pydantic import BaseModel, Field
from typing import Dict, List, Optional

class Config(BaseModel):
    """钓鱼插件配置"""
    # 钓鱼次数限制
    fishing_limit_per_hour: int = Field(6, description="每小时钓鱼次数限制")
    
    # 概率配置
    probability_air: float = Field(0.5, description="空军的概率")
    probability_trash: float = Field(0.35, description="钓到垃圾的概率")
    probability_fish: float = Field(0.15, description="钓到鱼的概率")
    probability_treasure: float = Field(0.0, description="钓到宝物的概率")
    
    # 物品列表
    trash_items: List[str] = Field(
        default_factory=lambda: [
            "破鞋子", "塑料袋", "易拉罐", "烂渔网", "空瓶子",
            "破轮胎", "旧报纸", "锈铁罐", "烂木头", "海草"
        ],
        description="垃圾物品列表"
    )
    
    fish_items: List[str] = Field(
        default_factory=lambda: [
            "小鲤鱼", "鲫鱼", "草鱼", "鲈鱼", "罗非鱼",
            "鲶鱼", "鳊鱼", "青鱼", "金鱼", "泥鳅"
        ],
        description="鱼类列表"
    )
    
    treasure_items: List[str] = Field(
        default_factory=lambda: [
            "黄金", "珍珠", "古董", "宝箱", "钻石",
            "金币", "银币", "古董瓷器", "名贵手表", "宝石"
        ],
        description="宝物列表"
    )
    
    # 特殊垃圾相关配置
    special_trash_weight: float = Field(0.7, description="钓到垃圾时，特殊垃圾的出现权重（0-1之间）")
    max_special_trash_count: int = Field(500, description="最大特殊垃圾数量限制")