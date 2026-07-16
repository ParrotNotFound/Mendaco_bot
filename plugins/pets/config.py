from pydantic import BaseModel, Field
from typing import Dict, List


class PetTypeConfig(BaseModel):
    """宠物类型配置（含各属性基础值与成长倍率）"""
    name: str                     # 类型名称
    cost: int                     # 领养消耗银币
    base_hp: int                  # 基础生命值
    base_atk: int                 # 基础攻击力
    emoji: str                    # 显示表情
    # ---- 各类型额外基础属性 ----
    base_defense: int = 5
    base_magic_atk: int = 0
    base_magic_def: int = 5
    base_speed: int = 10
    # ---- 成长倍率（×全局growth） ----
    hp_growth_mult: float = 1.0
    atk_growth_mult: float = 1.0
    def_growth_mult: float = 1.0
    matk_growth_mult: float = 1.0
    mdef_growth_mult: float = 1.0
    spd_growth_mult: float = 1.0


class SkillConfig(BaseModel):
    """技能配置"""
    id: int
    name: str                     # 技能名
    skill_type: str               # 技能类型
    description: str              # 描述
    trigger_prob: float           # 触发概率 (0~1)
    params: Dict[str, float]      # 技能参数

    # skill_type 说明及 params 字段:
    #   "buff_defense"  : {"ratio": 0.5, "duration": 2}     → 加防御 ratio%，持续 duration 回合
    #   "heal"          : {"ratio": 0.3}                     → 回复 HP ratio% 的血量
    #   "debuff_defense": {"ratio": 0.5, "duration": 2}     → 减对方防御 ratio%，持续 duration 回合
    #   "debuff_atk"    : {"ratio": 0.3, "duration": 2}     → 减对方攻击 ratio%，持续 duration 回合
    #   "power_strike"  : {"multiplier": 3.0}                → 造成 ATK × multiplier 的物理伤害
    #   "true_damage"   : {"ratio": 0.2}                     → 造成最大 HP × ratio 的真实伤害（无视防御法抗）
    #   "speed_up"      : {"ratio": 0.5, "duration": 3}     → 加自己速度 ratio%，持续 duration 回合
    #   "freeze"        : {"duration": 1}                    → 使对方冻结 duration 回合（无法行动）


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
    max_pets_per_user: int = Field(
        default=5,
        description="每个用户最多可拥有的宠物数量"
    )

    # ===================================================================
    #  领养配置
    # ===================================================================
    # 宠物类型列表，每种类型有不同的初始属性和领养费用
    pet_types: Dict[str, PetTypeConfig] = Field(
        default={
            "猫": PetTypeConfig(
                name="猫", cost=50, base_hp=100, base_atk=12, emoji="🐱",
                base_defense=4, base_magic_atk=2, base_magic_def=4, base_speed=12,
                hp_growth_mult=0.9, atk_growth_mult=1.2, def_growth_mult=0.8,
                matk_growth_mult=1.0, mdef_growth_mult=0.8, spd_growth_mult=1.2,
            ),
            "狗": PetTypeConfig(
                name="狗", cost=60, base_hp=120, base_atk=10, emoji="🐶",
                base_defense=7, base_magic_atk=0, base_magic_def=6, base_speed=10,
                hp_growth_mult=1.2, atk_growth_mult=0.9, def_growth_mult=1.5,
                matk_growth_mult=0.5, mdef_growth_mult=1.1, spd_growth_mult=0.9,
            ),
            "龙": PetTypeConfig(
                name="龙", cost=200, base_hp=150, base_atk=12, emoji="🐉",
                base_defense=6, base_magic_atk=5, base_magic_def=7, base_speed=9,
                hp_growth_mult=1.2, atk_growth_mult=0.9, def_growth_mult=1.0,
                matk_growth_mult=1.4, mdef_growth_mult=1.2, spd_growth_mult=1.0,
            ),
            "兔": PetTypeConfig(
                name="兔", cost=40, base_hp=80, base_atk=8, emoji="🐰",
                base_defense=3, base_magic_atk=3, base_magic_def=3, base_speed=14,
                hp_growth_mult=0.7, atk_growth_mult=0.8, def_growth_mult=0.6,
                matk_growth_mult=1.1, mdef_growth_mult=0.7, spd_growth_mult=1.4,
            ),
            "狐": PetTypeConfig(
                name="狐", cost=100, base_hp=110, base_atk=15, emoji="🦊",
                base_defense=5, base_magic_atk=8, base_magic_def=6, base_speed=11,
                hp_growth_mult=0.9, atk_growth_mult=1.0, def_growth_mult=0.8,
                matk_growth_mult=1.8, mdef_growth_mult=1.3, spd_growth_mult=1.1,
            ),
        },
        description="宠物类型配置，不同类型消耗不同银币，基础属性与成长速度各异"
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
    hp_growth: int = Field(
        default=120,
        description="HP对数成长基数，实际HP = 基础HP + 该值 × log2(等级)"
    )
    atk_growth: int = Field(
        default=30,
        description="ATK对数成长基数"
    )
    defense_growth: int = Field(
        default=12,
        description="DEF对数成长基数"
    )
    magic_atk_growth: int = Field(
        default=6,
        description="法伤对数成长基数"
    )
    magic_def_growth: int = Field(
        default=6,
        description="法抗对数成长基数"
    )
    speed_growth: int = Field(
        default=0,
        description="速度对数成长基数（0表示不成长）"
    )
    max_level: int = Field(
        default=100,
        description="宠物最高等级"
    )
    base_defense: int = Field(
        default=5,
        description="宠物1级时的基础物理防御"
    )
    base_magic_atk: int = Field(
        default=0,
        description="宠物1级时的基础法术攻击"
    )
    base_magic_def: int = Field(
        default=5,
        description="宠物1级时的基础法术防御（法抗）"
    )
    base_speed: int = Field(
        default=10,
        description="宠物1级时的基础速度（影响出手顺序）"
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
        default=50,
        description="打工消耗心情最大值（休息时间=0时的消耗）"
    )
    work_mood_decay_hours: float = Field(
        default=12,
        description="心情消耗随休息时间衰减的特征时间（小时），休息越久消耗越低"
    )
    work_coin_base: int = Field(
        default=2,
        description="打工银币基数，收入 = 等级 × 该值 × 心情倍率 × 随机 × 休息加成"
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
    work_rest_amplitude: float = Field(
        default=0.3,
        description="打工休息加成幅度 A。f(u)=1+A·u·e^(1-u)·(1-u)，u=小时/24。"
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
        description="每次训练消耗银币（固定，不受时长影响）"
    )
    train_max_hours: float = Field(
        default=8,
        description="单次训练最大时长（小时）"
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
    #  对战配置（/pet_attack）—— 回合制 + 技能系统
    # ===================================================================
    battle_cooldown: int = Field(
        default=180,
        description="对战冷却时间（秒），默认3分钟"
    )
    battle_atk_random_min: float = Field(
        default=0.85,
        description="普攻物伤随机波动最小值"
    )
    battle_atk_random_max: float = Field(
        default=1.15,
        description="普攻物伤随机波动最大值"
    )
    battle_magic_random_min: float = Field(
        default=0.9,
        description="普攻法伤随机波动最小值"
    )
    battle_magic_random_max: float = Field(
        default=1.1,
        description="普攻法伤随机波动最大值"
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
        default=10,
        description="对战押金，发起方支付，输了给对方，赢了退押金+1"
    )
    battle_win_bonus: int = Field(
        default=1,
        description="战胜后额外获得的银币奖励（不含退还的押金）"
    )
    battle_fullness_cost: int = Field(
        default=10,
        description="每次对战消耗的饱腹度（双方都扣）"
    )
    battle_mood_cost: int = Field(
        default=5,
        description="每次对战消耗的心情值（双方都扣）"
    )
    battle_max_turns: int = Field(
        default=50,
        description="对战最大回合数，超出则防守方获胜"
    )
    battle_use_image: bool = Field(
        default=False,
        description="战斗日志是否使用图片输出（需安装Pillow）"
    )
    rank_use_image: bool = Field(
        default=False,
        description="排行榜是否使用图片输出（需安装Pillow）"
    )

    # ===================================================================
    #  奖杯配置（/pet_attack 排行榜）
    # ===================================================================
    trophy_k_base: int = Field(
        default=30,
        description="奖杯ELO基础K值"
    )
    trophy_k_scale: float = Field(
        default=0.005,
        description="奖杯K值随平均奖杯的增长斜率"
    )
    trophy_threshold: int = Field(
        default=4000,
        description="奖杯分界线，以上通缩以下通胀"
    )
    trophy_max_loss: int = Field(
        default=100,
        description="单次对战最多扣除奖杯数"
    )
    trophy_gain_slope: float = Field(
        default=1/12000,
        description="赢家倍率随偏移的变化率"
    )
    trophy_loss_slope: float = Field(
        default=1/6000,
        description="输家倍率随偏移的变化率"
    )
    initial_trophies: int = Field(
        default=0,
        description="新宠物初始奖杯数"
    )

    # ===================================================================
    #  技能配置
    # ===================================================================
    skill_rename_cost: int = Field(
        default=30,
        description="技能改名消耗的银币"
    )
    skill_unlock_levels: List[int] = Field(
        default=[10, 30, 60],
        description="宠物技能解锁等级"
    )
    # 每个解锁档位可习得的技能ID列表
    skill_unlock_map: Dict[int, List[int]] = Field(
        default={
            10: [1, 5, 9],
            30: [2, 3, 4, 6, 7, 8],
            60: [2, 3, 4, 6, 7, 8],
        },
        description="技能解锁映射 {等级: [技能ID列表]}"
    )
    skills: Dict[int, SkillConfig] = Field(
        default={
            1: SkillConfig(
                id=1, name="铁壁", skill_type="buff_defense",
                description="提升自身50%防御，持续2回合",
                trigger_prob=0.25,
                params={"ratio": 0.5, "duration": 2},
            ),
            2: SkillConfig(
                id=2, name="治愈", skill_type="heal",
                description="回复30%生命值",
                trigger_prob=0.20,
                params={"ratio": 0.3},
            ),
            3: SkillConfig(
                id=3, name="破甲", skill_type="debuff_defense",
                description="降低对方50%防御，持续2回合",
                trigger_prob=0.20,
                params={"ratio": 0.5, "duration": 2},
            ),
            4: SkillConfig(
                id=4, name="弱化", skill_type="debuff_atk",
                description="降低对方30%攻击，持续2回合",
                trigger_prob=0.20,
                params={"ratio": 0.3, "duration": 2},
            ),
            5: SkillConfig(
                id=5, name="强力击", skill_type="power_strike",
                description="造成3倍攻击力的物理伤害",
                trigger_prob=0.15,
                params={"multiplier": 3.0},
            ),
            6: SkillConfig(
                id=6, name="真实伤害", skill_type="true_strike",
                description="下次普攻变为真实伤害，无视一切防御法抗",
                trigger_prob=0.15,
                params={"duration": 1},
            ),
            7: SkillConfig(
                id=7, name="加速术", skill_type="speed_up",
                description="提升自身50%速度，持续3回合",
                trigger_prob=0.15,
                params={"ratio": 0.5, "duration": 3},
            ),
            8: SkillConfig(
                id=8, name="冰冻术", skill_type="freeze",
                description="使对手冻结1回合，无法行动",
                trigger_prob=0.10,
                params={"duration": 1},
            ),
            9: SkillConfig(
                id=9, name="火球术", skill_type="magic_strike",
                description="造成3倍法伤的法术伤害",
                trigger_prob=0.15,
                params={"multiplier": 3.0},
            ),
        },
        description="所有技能定义"
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
            1: ShopItemConfig(id=1, name="高级宠物粮", price=20,
                              description="饱腹度+40", effect={"fullness": 40}),
            2: ShopItemConfig(id=2, name="玩具球", price=20,
                              description="心情+50", effect={"mood": 50}),
            3: ShopItemConfig(id=3, name="经验药水", price=50,
                              description="经验+100", effect={"exp": 100}),
            4: ShopItemConfig(id=4, name="复活药水", price=100,
                              description="心情+100，饱腹+100",
                              effect={"mood": 100, "fullness": 100}),
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
