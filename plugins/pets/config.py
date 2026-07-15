from pydantic import BaseModel, Field
from typing import Dict


class PetTypeConfig(BaseModel):
    """宠物类型配置"""
    name: str          # 类型名称
    cost: int          # 领养消耗银币
    base_hp: int       # 基础生命值
    base_atk: int      # 基础攻击力
    emoji: str         # 显示表情


class ShopItemConfig(BaseModel):
    """商店物品配置"""
    id: int
    name: str
    price: int
    description: str
    # 效果：{"fullness": 40} 或 {"mood": 30} 或 {"exp": 100}
    effect: Dict[str, int]


class Config(BaseModel):
    """Plugin Config Here"""

    # ===================================================================
    #  基础配置
    # ===================================================================
    pets_data_dir: str = Field(
        default="pets",
        description="宠物数据存储目录（相对 file_edit 插件目录）"
    )

    # ===================================================================
    #  领养配置
    # ===================================================================
    # 宠物类型列表，每种类型有不同的初始属性和领养费用
    pet_types: Dict[str, PetTypeConfig] = Field(
        default={
            "猫": PetTypeConfig(name="猫", cost=50, base_hp=100, base_atk=12, emoji="🐱"),
            "狗": PetTypeConfig(name="狗", cost=60, base_hp=120, base_atk=10, emoji="🐶"),
            "龙": PetTypeConfig(name="龙", cost=200, base_hp=150, base_atk=18, emoji="🐉"),
            "兔": PetTypeConfig(name="兔", cost=40, base_hp=80, base_atk=8, emoji="🐰"),
            "狐": PetTypeConfig(name="狐", cost=150, base_hp=110, base_atk=15, emoji="🦊"),
        },
        description="宠物类型配置，不同类型消耗不同银币"
    )
    max_pet_name_length: int = Field(
        default=10,
        description="宠物名字最大长度"
    )

    # ===================================================================
    #  成长配置
    # ===================================================================
    base_exp_per_level: int = Field(
        default=50,
        description="每级所需经验基数，升级所需经验 = 等级 × 该值"
    )
    hp_per_level: int = Field(
        default=20,
        description="每升一级增加的生命值"
    )
    atk_per_level: int = Field(
        default=5,
        description="每升一级增加的攻击力"
    )
    max_level: int = Field(
        default=100,
        description="宠物最高等级"
    )

    # ===================================================================
    #  初始状态值
    # ===================================================================
    initial_mood: int = Field(default=100, description="领养时初始心情值")
    initial_fullness: int = Field(default=100, description="领养时初始饱腹度")
    max_mood: int = Field(default=100, description="心情值上限")
    max_fullness: int = Field(default=100, description="饱腹度上限")
    min_mood: int = Field(default=0, description="心情值下限")
    min_fullness: int = Field(default=0, description="饱腹度下限")

    # ===================================================================
    #  打工配置（/pet_work）
    # ===================================================================
    work_cooldown: int = Field(
        default=300,
        description="打工冷却时间（秒），默认5分钟"
    )
    work_fullness_cost_min: int = Field(
        default=10,
        description="打工消耗饱腹度最小值"
    )
    work_fullness_cost_max: int = Field(
        default=20,
        description="打工消耗饱腹度最大值"
    )
    work_mood_cost_min: int = Field(
        default=5,
        description="打工消耗心情最小值"
    )
    work_mood_cost_max: int = Field(
        default=10,
        description="打工消耗心情最大值"
    )
    work_coin_base: int = Field(
        default=1,
        description="打工银币基数，收入 = 等级 × 该值 × 心情倍率 × 随机"
    )
    work_mood_multiplier: float = Field(
        default=0.5,
        description="打工心情系数，收入 × (0.5 + 心情/100 × 0.5)"
    )
    work_random_min: float = Field(
        default=0.8,
        description="打工随机波动最小值"
    )
    work_random_max: float = Field(
        default=1.2,
        description="打工随机波动最大值"
    )

    # ===================================================================
    #  训练配置（/pet_train）
    # ===================================================================
    train_cooldown: int = Field(
        default=60,
        description="训练冷却时间（秒），默认1分钟"
    )
    train_fullness_cost: int = Field(
        default=15,
        description="每次训练消耗饱腹度"
    )
    train_coin_cost: int = Field(
        default=15,
        description="每次训练消耗银币"
    )
    train_exp_min: int = Field(
        default=10,
        description="训练获得经验最小值"
    )
    train_exp_max: int = Field(
        default=30,
        description="训练获得经验最大值"
    )
    train_exp_level_multiplier: int = Field(
        default=2,
        description="训练经验等级加成，获得经验 += 等级 × 该值"
    )

    # ===================================================================
    #  对战配置（/pet_attack）
    # ===================================================================
    battle_cooldown: int = Field(
        default=180,
        description="对战冷却时间（秒），默认3分钟"
    )
    battle_atk_random_min: float = Field(
        default=0.8,
        description="对战攻击随机波动最小值"
    )
    battle_atk_random_max: float = Field(
        default=1.2,
        description="对战攻击随机波动最大值"
    )
    battle_defense_multiplier: float = Field(
        default=0.5,
        description="防御系数，受伤 = 对方攻击 × 该值"
    )
    battle_win_exp: int = Field(
        default=30,
        description="战胜获得经验"
    )
    battle_lose_exp: int = Field(
        default=10,
        description="战败获得经验"
    )
    battle_lose_mood_cost: int = Field(
        default=10,
        description="战败损失心情值"
    )
    battle_deposit: int = Field(
        default=20,
        description="对战押金，胜者赢走双方的押金"
    )

    # ===================================================================
    #  喂食配置（/feed）
    # ===================================================================
    feed_fullness_gain: int = Field(
        default=30,
        description="每次喂食增加饱腹度"
    )
    feed_mood_gain: int = Field(
        default=25,
        description="每次喂食增加心情"
    )
    feed_coin_cost: int = Field(
        default=10,
        description="每次喂食消耗银币"
    )
    feed_cooldown: int = Field(
        default=120,
        description="喂食冷却时间（秒），默认2分钟"
    )

    # ===================================================================
    #  商店配置（/pet_shop）
    # ===================================================================
    shop_items: Dict[int, ShopItemConfig] = Field(
        default={
            1: ShopItemConfig(id=1, name="高级宠物粮", price=50,
                              description="饱腹度+40", effect={"fullness": 40}),
            2: ShopItemConfig(id=2, name="玩具球", price=80,
                              description="心情+30", effect={"mood": 30}),
            3: ShopItemConfig(id=3, name="经验药水", price=150,
                              description="经验+100", effect={"exp": 100}),
            4: ShopItemConfig(id=4, name="复活药水", price=250,
                              description="心情+50，饱腹+30",
                              effect={"mood": 50, "fullness": 30}),
        },
        description="宠物商店物品列表"
    )

    # ===================================================================
    #  排行榜配置
    # ===================================================================
    rank_limit: int = Field(
        default=10,
        description="排行榜显示人数"
    )

    # ===================================================================
    #  DeepSeek 配置（用于宠物名字审查）
    # ===================================================================
    deepseek_api_key: str = Field(
        default="",
        description="DeepSeek API 密钥，留空则跳过名字审查"
    )
    deepseek_api_url: str = Field(
        default="https://api.deepseek.com/v1/chat/completions",
        description="DeepSeek API 地址"
    )
    deepseek_model: str = Field(
        default="deepseek-v4-flash",
        description="DeepSeek 模型名称"
    )
    enable_name_review: bool = Field(
        default=True,
        description="是否启用 DeepSeek 名字审查（需配置 API 密钥）"
    )
