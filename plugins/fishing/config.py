from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any, Tuple

class FishDetail(BaseModel):
    """鱼的详细配置"""
    name: str = Field(..., description="鱼的名字")
    avg_weight: float = Field(..., description="平均重量（斤）")
    price_per_jin: int = Field(..., description="每斤价格（银币）")
    probability: float = Field(..., description="相对出现概率（0-1之间）")

class Config(BaseModel):
    """钓鱼插件配置"""
    # 钓鱼次数限制
    fishing_limit_per_hour: int = Field(6, description="每小时钓鱼次数限制")
    
    # 概率配置
    probability_air: float = Field(0.495, description="空军的概率")
    probability_trash: float = Field(0.35, description="钓到垃圾的概率")
    probability_fish: float = Field(0.15, description="钓到鱼的概率")
    probability_treasure: float = Field(0.005, description="钓到宝物的概率")
    
    # 物品列表
    trash_items: List[str] = Field(
        default_factory=lambda: [
            "破鞋子", "塑料袋", "易拉罐", "烂渔网", "空瓶子",
            "破轮胎", "旧报纸", "锈铁罐", "烂木头", "海草"
        ],
        description="垃圾物品列表"
    )
    
    # 鱼类详细配置
    fish_details: List[FishDetail] = Field(
        default_factory=lambda: [
            FishDetail(name="小鲤鱼", avg_weight=0.5, price_per_jin=10, probability=0.3),
            FishDetail(name="鲫鱼", avg_weight=0.8, price_per_jin=12, probability=0.2),
            FishDetail(name="草鱼", avg_weight=2.0, price_per_jin=8, probability=0.15),
            FishDetail(name="鲈鱼", avg_weight=1.2, price_per_jin=20, probability=0.1),
            FishDetail(name="罗非鱼", avg_weight=1.0, price_per_jin=9, probability=0.08),
            FishDetail(name="鲶鱼", avg_weight=3.0, price_per_jin=7, probability=0.07),
            FishDetail(name="鳊鱼", avg_weight=0.6, price_per_jin=11, probability=0.05),
            FishDetail(name="青鱼", avg_weight=4.0, price_per_jin=15, probability=0.03),
            FishDetail(name="金鱼", avg_weight=0.1, price_per_jin=50, probability=0.01),
            FishDetail(name="泥鳅", avg_weight=0.2, price_per_jin=5, probability=0.01)
        ],
        description="鱼类详细配置"
    )
    
    # 基础宝藏配置
    base_treasure_items: List[Dict[str, Any]] = Field(
        default_factory=lambda: [
            {"name": "宝箱", "base_value": 40},
        ],
        description="基础宝物列表，每个宝物有一个基础价值（20-100）"
    )
    
    # 特殊垃圾相关配置
    # special_trash_weight: float = Field(0.7, description="钓到垃圾时，特殊垃圾的出现权重（0-1之间）")
    max_special_trash_count: int = Field(500, description="最大特殊垃圾数量限制")
    
    # 钓鱼获得货币数量
    fish_normal_value: int = Field(5, description="鱼的价钱（备用，如果使用详细配置则此字段不生效）")
    trash_normal_value: int = Field(1, description="垃圾的价钱")
    
    # 宝物相关配置
    max_custom_treasure_count: int = Field(100, description="最大自定义宝物数量限制")
    treasure_value_range: Tuple[int, int] = Field((20, 100), description="宝藏价值范围")