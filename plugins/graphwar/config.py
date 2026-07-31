from pydantic import BaseModel, Field


class Config(BaseModel):
    """GraphWar 插件配置"""

    # 匹配超时（秒）
    matchmaking_timeout: int = Field(120, description="匹配等待时间（秒）")

    # 每方士兵数量
    soldiers_per_player: int = Field(3, description="每方士兵数量")

    # 命中判定容差（坐标距离）
    hit_tolerance: float = Field(1, description="命中判定容差")

    # 函数最大长度（字符数）
    max_function_length: int = Field(200, description="函数表达式最大长度")

    # 函数追踪步长（用于碰撞检测）
    trace_step: float = Field(0.1, description="函数追踪步长")

    # 函数最大追踪点数（防止死循环/过长函数）
    max_trace_points: int = Field(2000, description="最大追踪点数")

    # 是否以图片形式发送战场
    send_photo: bool = Field(True, description="是否将战场以图片形式发送")

    # 每回合超时（秒）
    turn_timeout: int = Field(60, description="每回合超时时间（秒）")

    # 回合超时提醒提前时间（秒）
    turn_warning_time: int = Field(15, description="超时前多少秒发出提醒")

    # 最小玩家数
    min_players: int = Field(2, description="最少玩家数量")

    # 血量模式 - 士兵初始血量
    soldier_hp: int = Field(100, description="血量模式下士兵初始血量")

    # 血量模式 - 最小伤害
    hp_min_damage: int = Field(5, description="血量模式下最低伤害")

    # 是否开启友方伤害（组队模式下，同侧队友是否可被误伤）
    friendly_fire: bool = Field(True, description="组队模式下是否开启友方伤害")

    # 障碍物数量
    obstacle_count: int = Field(5, description="战场中圆形障碍物数量")

    # 障碍物半径范围
    obstacle_min_radius: float = Field(1.5, description="障碍物最小半径")
    obstacle_max_radius: float = Field(4.0, description="障碍物最大半径")

    # 障碍物血量（被击中多少次后消失，0=永不消失）
    obstacle_hp: int = Field(3, description="障碍物血量，被命中次数上限")

    # 障碍物重生间隔（回合数，0=不重生）
    obstacle_respawn_interval: int = Field(5, description="每隔多少回合生成一个新障碍物")

    # 障碍物最大数量上限
    obstacle_max_count: int = Field(8, description="同一时间最多障碍物数量")
