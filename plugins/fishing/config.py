from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Set

class Config(BaseModel):
    """钓鱼插件配置"""
    # 钓鱼次数限制
    fishing_limit_per_hour: int = Field(6, description="每小时钓鱼次数限制")
    
    # 概率配置
    probability_air: float = Field(0.6, description="空军的概率")
    probability_trash: float = Field(0.2, description="钓到垃圾的概率")
    probability_fish: float = Field(0.15, description="钓到鱼的概率")
    probability_treasure: float = Field(0.05, description="钓到宝物的概率")
    
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
    
    # 管理员配置
    admin_users: Set[str] = Field(
        default_factory=set,
        description="管理员用户ID列表"
    )
    
    # 指令权限配置
    require_admin_for_add_fish: bool = Field(True, description="添加鱼种是否需要管理员权限")
    require_admin_for_add_trash: bool = Field(True, description="添加垃圾是否需要管理员权限")
    require_admin_for_add_treasure: bool = Field(True, description="添加宝物是否需要管理员权限")
    require_admin_for_remove_item: bool = Field(True, description="移除物品是否需要管理员权限")
    require_admin_for_list_items: bool = Field(False, description="查看物品列表是否需要管理员权限")