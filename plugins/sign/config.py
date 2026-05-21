from pydantic import BaseModel, Field
from typing import Tuple

class SignConfig(BaseModel):
    """签到插件配置"""
    
    # 银币奖励范围
    coin_range: Tuple[int, int] = Field(
        (10, 20),  # 默认10-20银币
        description="签到获得的银币范围（最小值，最大值）"
    )
    
    # 连续签到额外奖励
    consecutive_bonus: bool = Field(
        True,
        description="是否开启连续签到额外奖励"
    )
    
    # 连续签到奖励倍数
    consecutive_multipliers: Tuple[float, ...] = Field(
        (1.0, 1.1, 1.1, 1.2, 1.2, 1.3, 1.5),  # 7天周期
        description="连续签到奖励倍数（第1天到第7天）"
    )
    
    # 经验倍数
    exp_multiple: float = Field(
        1.0,
        description="签到获得经验的倍数"
    )
    
    # 每月签到奖励
    monthly_full_sign_bonus: int = Field(
        50,
        description="每月全勤签到额外奖励（银币）"
    )
    
    # 特殊日期额外奖励
    special_dates: dict = Field(
        default_factory=lambda: {
            "01-01": {"name": "元旦", "bonus": 227},  # 元旦
            
            "05-01": {"name": "劳动节", "bonus": 150},  # 情人节
            "06-01": {"name": "儿童节", "bonus": 160},  # 
            "07-27": {"name": "When you see it", "bonus": 72},  # 世界旅游日
            "10-01": {"name": "国庆节", "bonus": 200},  # 国庆节
            "12-25": {"name": "圣诞节", "bonus": 125},  # 圣诞节
        },
        description="特殊日期额外奖励"
    )