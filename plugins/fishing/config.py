from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import random
from datetime import datetime
import calendar

class Season(Enum):
    """季节枚举"""
    SPRING = "spring"  # 春季：3-5月
    SUMMER = "summer"  # 夏季：6-8月
    AUTUMN = "autumn"  # 秋季：9-11月
    WINTER = "winter"  # 冬季：12-2月

class FishDetail(BaseModel):
    """鱼的详细配置"""
    name: str = Field(..., description="鱼的名字")
    avg_weight: float = Field(..., description="平均重量（斤）")
    price_per_jin: int = Field(..., description="每斤价格（银币）")
    probability: float = Field(..., description="相对出现概率（0-1之间）")
    habitats: List[str] = Field(default_factory=lambda: ["pond"], description="栖息地：pond(池塘), sea(海洋), river(河流)")
    seasons: List[str] = Field(default_factory=lambda: ["spring", "summer", "autumn", "winter"], 
                              description="出现季节")

class Config(BaseModel):
    """钓鱼插件配置"""
    # 钓鱼次数限制
    fishing_limit_per_hour: int = Field(3, description="每小时钓鱼次数限制")
    
    # 默认钓鱼地点
    default_fishing_spot: str = Field("pond", description="默认钓鱼地点：pond(池塘), sea(海钓), river(河钓)")
      # 是否将文字转为图片发送
    send_photo: bool = Field(True, description="是否将钓鱼结果以图片形式发送（白底，支持emoji）")
    # 获取当前季节
    def get_current_season(self) -> str:
        """根据当前月份获取季节"""
        current_month = datetime.now().month
        if 3 <= current_month <= 5:
            return "spring"
        elif 6 <= current_month <= 8:
            return "summer"
        elif 9 <= current_month <= 11:
            return "autumn"
        else:
            return "winter"
    
    # 不同地点的概率配置
    fishing_spots: Dict[str, Dict[str, float]] = Field(
        default_factory=lambda: {
            "pond": {  # 池塘钓鱼概率
                "probability_air": 0.35,     # 35% 空军
                "probability_trash": 0.25,   # 25% 垃圾
                "probability_fish": 0.39,    # 39% 鱼
                "probability_treasure": 0.01 # 1% 宝藏
            },
            "sea": {   # 海钓概率
                "probability_air": 0.20,     # 20% 空军
                "probability_trash": 0.30,   # 30% 垃圾
                "probability_fish": 0.48,    # 48% 鱼
                "probability_treasure": 0.02  # 2% 宝藏
            },
            "river": { # 河钓概率
                "probability_air": 0.25,     # 25% 空军
                "probability_trash": 0.35,   # 35% 垃圾
                "probability_fish": 0.39,    # 39% 鱼
                "probability_treasure": 0.01  # 1% 宝藏
            }
        },
        description="不同钓鱼地点的概率配置"
    )
    
    # 鱼类详细配置（按栖息地和季节分类）
    fish_details: List[FishDetail] = Field(
        default_factory=lambda: [
            # ==================== 淡水鱼类 - 池塘/河流 (期望值 ≈ 12) ====================
            # 期望值计算：概率 * 平均重量 * 每斤价格
            FishDetail(name="小鲤鱼", avg_weight=0.5, price_per_jin=8, probability=0.15,   # 贡献期望: 0.15 * 0.5 * 8 = 0.6
                      habitats=["pond", "river"], seasons=["spring", "summer", "autumn", "winter"]),
            FishDetail(name="鲫鱼", avg_weight=0.8, price_per_jin=10, probability=0.20,  # 贡献期望: 0.20 * 0.8 * 10 = 1.6
                      habitats=["pond", "river"], seasons=["spring", "summer", "autumn", "winter"]),
            FishDetail(name="草鱼", avg_weight=4.0, price_per_jin=4, probability=0.12,   # 贡献期望: 0.12 * 4.0 * 4 = 1.92
                      habitats=["pond", "river"], seasons=["spring", "summer", "autumn", "winter"]),
            FishDetail(name="鲢鱼", avg_weight=3.5, price_per_jin=4, probability=0.10,   # 贡献期望: 0.10 * 3.5 * 4 = 1.4
                      habitats=["pond"], seasons=["spring", "summer", "autumn", "winter"]),
            FishDetail(name="鳙鱼", avg_weight=4.5, price_per_jin=5, probability=0.08,   # 贡献期望: 0.08 * 4.5 * 5 = 1.8
                      habitats=["pond"], seasons=["spring", "summer", "autumn", "winter"]),
            
            # 春季特有/偏好鱼类
            FishDetail(name="鳊鱼", avg_weight=1.2, price_per_jin=15, probability=0.10,  # 贡献期望: 0.10 * 1.2 * 15 = 1.8
                      habitats=["pond", "river"], seasons=["spring", "summer"]),
            FishDetail(name="鲴鱼", avg_weight=0.6, price_per_jin=40, probability=0.06,  # 贡献期望: 0.06 * 0.6 * 40 = 1.44
                      habitats=["river"], seasons=["spring"]),
            FishDetail(name="马口鱼", avg_weight=0.3, price_per_jin=50, probability=0.05, # 贡献期望: 0.05 * 0.3 * 50 = 0.75
                      habitats=["river"], seasons=["spring", "summer"]),
            
            # 夏季活跃鱼类
            FishDetail(name="黑鱼", avg_weight=3.0, price_per_jin=12, probability=0.08,  # 贡献期望: 0.08 * 3.0 * 12 = 2.88
                      habitats=["pond", "river"], seasons=["summer"]),
            FishDetail(name="鲶鱼", avg_weight=5.0, price_per_jin=9, probability=0.07,    # 贡献期望: 0.07 * 5.0 * 9 = 3.15
                      habitats=["pond", "river"], seasons=["summer", "autumn"]),
            FishDetail(name="黄颡鱼", avg_weight=0.4, price_per_jin=30, probability=0.05, # 贡献期望: 0.05 * 0.4 * 30 = 0.6
                      habitats=["pond", "river"], seasons=["summer"]),
            
            # 秋季肥美鱼类
            FishDetail(name="青鱼", avg_weight=8.0, price_per_jin=8, probability=0.06,   # 贡献期望: 0.06 * 8.0 * 8 = 3.84
                      habitats=["pond", "river"], seasons=["autumn", "winter"]),
            FishDetail(name="鳜鱼", avg_weight=2.0, price_per_jin=25, probability=0.04,  # 贡献期望: 0.04 * 2.0 * 25 = 2.0
                      habitats=["pond", "river"], seasons=["autumn"]),
            
            # 冬季耐寒鱼类
            FishDetail(name="泥鳅", avg_weight=0.2, price_per_jin=20, probability=0.08,  # 贡献期望: 0.08 * 0.2 * 20 = 0.32
                      habitats=["pond"], seasons=["winter"]),
            FishDetail(name="麦穗鱼", avg_weight=0.1, price_per_jin=8, probability=0.12, # 贡献期望: 0.12 * 0.1 * 8 = 0.096
                      habitats=["pond", "river"], seasons=["winter"]),
            
            # 稀有淡水鱼 (价值较高，但概率低，且检查最大值<200)
            FishDetail(name="金鱼", avg_weight=0.3, price_per_jin=60, probability=0.02,  # 贡献期望: 0.02 * 0.3 * 60 = 0.36, 最大: 0.3 * 1.2 * 60=21.6
                      habitats=["pond"], seasons=["spring", "summer", "autumn", "winter"]),
            FishDetail(name="锦鲤", avg_weight=4.0, price_per_jin=25, probability=0.01,  # 贡献期望: 0.01 * 4.0 * 25 = 1.0, 最大: 4.0 * 1.2 * 25=120
                      habitats=["pond"], seasons=["spring", "summer", "autumn", "winter"]),
            FishDetail(name="金龙鱼", avg_weight=4.0, price_per_jin=25, probability=0.01,  # 贡献期望: 0.01 * 4.0 * 25 = 1.0, 最大: 4.0 * 1.2 * 25=120
                      habitats=["river"], seasons=["spring", "summer", "autumn", "winter"]),
            FishDetail(name="胭脂鱼", avg_weight=1.0, price_per_jin=80, probability=0.005, # 贡献期望: 0.005 * 1.0 * 80 = 0.4, 最大: 1.0 * 1.2 * 80=96
                      habitats=["river"], seasons=["summer", "autumn"]),
            
            # ==================== 海水鱼类 (期望值 ≈ 25) ====================
            # 常见海鱼
            FishDetail(name="带鱼", avg_weight=1.5, price_per_jin=10, probability=0.12,  # 贡献期望: 0.12 * 1.5 * 14 = 2.52
                      habitats=["sea"], seasons=["spring", "summer", "autumn", "winter"]),
            FishDetail(name="鲅鱼", avg_weight=2.5, price_per_jin=8, probability=0.10,  # 贡献期望: 0.10 * 2.5 * 8 = 2.0
                      habitats=["sea"], seasons=["spring", "summer", "autumn", "winter"]),
            FishDetail(name="小黄鱼", avg_weight=0.5, price_per_jin=30, probability=0.20, # 贡献期望: 0.20 * 0.5 * 30 = 3.0
                      habitats=["sea"], seasons=["spring", "summer", "autumn", "winter"]),
            FishDetail(name="鲳鱼", avg_weight=1.0, price_per_jin=20, probability=0.08,  # 贡献期望: 0.08 * 1.0 * 40 = 3.2
                      habitats=["sea"], seasons=["spring", "summer", "autumn", "winter"]),
            
            # 春季海鱼
            FishDetail(name="鲈鱼", avg_weight=2.5, price_per_jin=10, probability=0.10,  # 贡献期望: 0.10 * 2.5 * 30 = 7.5
                      habitats=["sea"], seasons=["spring", "autumn"]),
            FishDetail(name="多宝鱼", avg_weight=2.0, price_per_jin=15, probability=0.06, # 贡献期望: 0.06 * 2.0 * 45 = 5.4
                      habitats=["sea"], seasons=["spring"]),
            
            # 夏季海鱼
            FishDetail(name="石斑鱼", avg_weight=4.0, price_per_jin=25, probability=0.05, # 贡献期望: 0.05 * 4.0 * 35 = 7.0
                      habitats=["sea"], seasons=["summer"]),
            FishDetail(name="马鲛鱼", avg_weight=5.0, price_per_jin=15, probability=0.08, # 贡献期望: 0.08 * 5.0 * 20 = 8.0
                      habitats=["sea"], seasons=["summer", "autumn"]),
            
            # 秋季海鱼
            FishDetail(name="秋刀鱼", avg_weight=0.3, price_per_jin=30, probability=0.12, # 贡献期望: 0.12 * 0.3 * 30 = 1.08
                      habitats=["sea"], seasons=["autumn"]),
            FishDetail(name="鳕鱼", avg_weight=8.0, price_per_jin=5, probability=0.07,  # 贡献期望: 0.07 * 8.0 * 18 = 10.08
                      habitats=["sea"], seasons=["autumn", "winter"]),
            
            # 冬季海鱼
            FishDetail(name="大黄鱼", avg_weight=1.5, price_per_jin=30, probability=0.04, # 贡献期望: 0.04 * 1.5 * 60 = 3.6, 最大: 1.5 * 1.2 * 60=108
                      habitats=["sea"], seasons=["winter"]),
            FishDetail(name="鳗鱼", avg_weight=2.0, price_per_jin=20, probability=0.05,  # 贡献期望: 0.05 * 2.0 * 50 = 5.0, 最大: 2.0 * 1.2 * 50=120
                      habitats=["sea"], seasons=["winter"]),
            
            # 深海稀有鱼 (控制单条价值<200)
            FishDetail(name="金枪鱼", avg_weight=50.0, price_per_jin=3, probability=0.01, # 贡献期望: 0.01 * 50.0 * 3 = 1.5, 最大: 50 * 1.2 * 3=180
                      habitats=["sea"], seasons=["summer"]),
            FishDetail(name="三文鱼", avg_weight=6.0, price_per_jin=15, probability=0.02, # 贡献期望: 0.02 * 6.0 * 15 = 1.8, 最大: 6 * 1.2 * 15=108
                      habitats=["sea"], seasons=["spring", "autumn"]),
            FishDetail(name="旗鱼", avg_weight=30.0, price_per_jin=5, probability=0.015,  # 贡献期望: 0.015 * 30.0 * 5 = 2.25, 最大: 30 * 1.2 * 5=180
                      habitats=["sea"], seasons=["summer"]),
            
            # 名贵海产 (控制单条价值<200)
            FishDetail(name="东星斑", avg_weight=3.0, price_per_jin=50, probability=0.008, # 贡献期望: 0.008 * 3.0 * 50 = 1.2, 最大: 3 * 1.2 * 50=180
                      habitats=["sea"], seasons=["autumn", "winter"]),
            FishDetail(name="苏眉鱼", avg_weight=4.0, price_per_jin=40, probability=0.005, # 贡献期望: 0.005 * 4.0 * 40 = 0.8, 最大: 4 * 1.2 * 40=192
                      habitats=["sea"], seasons=["summer", "autumn"]),
            
            # ==================== 洄游性鱼类 ====================
            FishDetail(name="大马哈鱼", avg_weight=6.0, price_per_jin=12, probability=0.04, # 贡献期望: 0.04 * 8.0 * 12 = 3.84
                      habitats=["river", "sea"], seasons=["autumn"]),
            FishDetail(name="香鱼", avg_weight=0.2, price_per_jin=80, probability=0.06,   # 贡献期望: 0.06 * 0.2 * 80 = 0.96
                      habitats=["river", "sea"], seasons=["summer", "autumn"]),
            FishDetail(name="鲥鱼", avg_weight=2.0, price_per_jin=15, probability=0.02,   # 贡献期望: 0.02 * 2.0 * 40 = 1.6, 最大: 2 * 1.2 * 40=96
                      habitats=["river", "sea"], seasons=["spring", "summer"]),
        ],
        description="鱼类详细配置（期望值优化：淡水≈12， 海水≈25， 单条价值<200）"
    )
    
    # 物品列表
    trash_items: List[str] = Field(
        default_factory=lambda: [
            "破鞋子", "塑料袋", "易拉罐", "烂渔网", "空瓶子",
            "破轮胎", "旧报纸", "锈铁罐", "烂木头", "海草"
        ],
        description="垃圾物品列表"
    )
    
    # 基础宝藏配置
    base_treasure_items: List[Dict[str, Any]] = Field(
        default_factory=lambda: [
            {"name": "宝箱", "base_value": 40},
        ],
        description="基础宝物列表，每个宝物有一个基础价值（20-100）"
    )
    
    # 特殊垃圾相关配置
    max_special_trash_count: int = Field(500, description="最大特殊垃圾数量限制")
    
    # 钓鱼获得货币数量
    fish_normal_value: int = Field(5, description="鱼的价钱（备用，如果使用详细配置则此字段不生效）")
    trash_normal_value: int = Field(1, description="垃圾的价钱")
    
    # 宝物相关配置
    max_custom_treasure_count: int = Field(100, description="最大自定义宝物数量限制")
    treasure_value_range: Tuple[int, int] = Field((20, 100), description="宝藏价值范围")
    
    # 海钓额外配置
    sea_fishing_extra_cost: int = Field(7, description="海钓额外消耗银币")
    sea_fishing_exp_multiple: float = Field(1.5, description="海钓经验倍数")
    max_fish_per_command: int = Field(3, description="每次钓鱼最大钓到的鱼数量")