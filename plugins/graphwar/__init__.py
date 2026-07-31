"""
GraphWar 插件 - 用数学函数作为炮弹轨迹的炮兵对战游戏

玩法：
- /graphwar 在群内发起匹配
- /gwgo   发起者立即开始游戏（需满足最低人数）
- /gwjoin 加入匹配
- /gw <函数表达式> 发射函数炮弹
- /gwstatus 查看当前战况
- /gwquit 投降退出
- /gwheelp 显示帮助
"""

from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata
from nonebot import on_command, require
from nonebot.adapters.onebot.v11 import (
    Message, MessageSegment, MessageEvent, GroupMessageEvent, Bot
)
from nonebot.params import CommandArg
from nonebot.log import logger

import random
import math
import time
import asyncio
import io
import re
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="graphwar",
    description="GraphWar - 数学函数炮兵对战",
    usage=(
        "发起匹配: /graphwar [classic|hp]\n"
        "  classic - 经典模式（默认），每方3名士兵\n"
        "  hp      - 血量模式，每方1名士兵100HP\n"
        "立即开始: /gwgo\n"
        "加入匹配: /gwjoin\n"
        "发射炮弹: /gw <函数表达式>\n"
        "查看战况: /gwstatus\n"
        "投降退出: /gwquit\n"
        "帮助: /gwheelp\n\n"
        "血量模式伤害规则:\n"
        "  极值点0个 → 99伤害\n"
        "  极值点1个 → 66伤害\n"
        "  极值点2个 → 33伤害\n"
        "  ...极值点越多伤害越低，最低5点\n"
        "  公式越长伤害越低（最多衰减80%）\n\n"
        "支持的函数语法:\n"
        "  变量: x\n"
        "  运算符: + - * / ^\n"
        "  函数: sin cos tan abs sqrt log ln exp\n"
        "  常量: pi, e\n"
        "示例: /gw sin(x/20)*5\n"
        "      /gw (x^2)/50\n"
        "      /gw sqrt(abs(x))*2"
    ),
    config=Config,
)

config = get_plugin_config(Config)

# 导入文件编辑插件（用于可能的持久化）
require("plugins.file_edit")
from plugins.file_edit import read_file, write_file, safe_path, plugin_dir

# 尝试导入图像库
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    logger.warning("PIL not installed, will use text mode for battlefield display")

# ============================================================
#  数学表达式解析器 (Recursive Descent Parser)
# ============================================================

# Token 类型
TOK_NUM = "NUM"
TOK_VAR = "VAR"
TOK_PLUS = "PLUS"
TOK_MINUS = "MINUS"
TOK_MUL = "MUL"
TOK_DIV = "DIV"
TOK_POW = "POW"
TOK_LPAREN = "LPAREN"
TOK_RPAREN = "RPAREN"
TOK_FUNC = "FUNC"
TOK_EOF = "EOF"


@dataclass
class Token:
    type: str
    value: Any = None
    pos: int = 0


FUNC_NAMES = {
    "sin", "cos", "tan", "abs", "sqrt", "log", "ln", "exp"
}

CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
}


def tokenize(expr: str) -> List[Token]:
    """将表达式字符串转换为 Token 列表"""
    tokens: List[Token] = []
    i = 0
    n = len(expr)

    while i < n:
        ch = expr[i]

        # 跳过空白
        if ch.isspace():
            i += 1
            continue

        # 数字
        if ch.isdigit() or (ch == '.' and i + 1 < n and expr[i + 1].isdigit()):
            start = i
            dots = 0
            while i < n and (expr[i].isdigit() or expr[i] == '.'):
                if expr[i] == '.':
                    dots += 1
                    if dots > 1:
                        break
                i += 1
            num_str = expr[start:i]
            try:
                tokens.append(Token(TOK_NUM, float(num_str), start))
            except ValueError:
                pass
            continue

        # 标识符（函数名、常量或变量 x）
        if ch.isalpha() or ch == '_':
            start = i
            while i < n and (expr[i].isalnum() or expr[i] == '_'):
                i += 1
            name = expr[start:i]
            if name in FUNC_NAMES:
                tokens.append(Token(TOK_FUNC, name, start))
            elif name in CONSTANTS:
                tokens.append(Token(TOK_NUM, CONSTANTS[name], start))
            elif name == 'x':
                tokens.append(Token(TOK_VAR, 'x', start))
            else:
                # 未知标识符 — 保留为变量名供后续处理（或报错）
                tokens.append(Token(TOK_VAR, name, start))
            continue

        # 运算符和括号
        if ch == '+':
            tokens.append(Token(TOK_PLUS, '+', i))
        elif ch == '-':
            tokens.append(Token(TOK_MINUS, '-', i))
        elif ch == '*':
            tokens.append(Token(TOK_MUL, '*', i))
        elif ch == '/':
            tokens.append(Token(TOK_DIV, '/', i))
        elif ch == '^':
            tokens.append(Token(TOK_POW, '^', i))
        elif ch == '(':
            tokens.append(Token(TOK_LPAREN, '(', i))
        elif ch == ')':
            tokens.append(Token(TOK_RPAREN, ')', i))
        else:
            # 非法字符，跳过
            pass
        i += 1

    tokens.append(Token(TOK_EOF, None, n))

    # 插入隐式乘号（如 0.15x → 0.15*x, 2(x+1) → 2*(x+1)）
    tokens = _insert_implicit_mul(tokens)

    return tokens


def _insert_implicit_mul(tokens: List[Token]) -> List[Token]:
    """在 token 流中插入隐式乘号"""
    result: List[Token] = []
    for i, tok in enumerate(tokens):
        result.append(tok)
        if i + 1 >= len(tokens):
            break
        nxt = tokens[i + 1]
        should_insert = False
        # NUM 后跟 VAR、FUNC 或 LPAREN → 2x, 2sin(x), 2(x+1)
        if tok.type == TOK_NUM and nxt.type in (TOK_VAR, TOK_FUNC, TOK_LPAREN):
            should_insert = True
        # RPAREN 后跟 VAR、FUNC、LPAREN 或 NUM → )x, )sin(x, )(, )2
        elif tok.type == TOK_RPAREN and nxt.type in (TOK_VAR, TOK_FUNC, TOK_LPAREN, TOK_NUM):
            should_insert = True
        # VAR(即 'x') 后跟 LPAREN → x(
        elif tok.type == TOK_VAR and nxt.type == TOK_LPAREN:
            should_insert = True
        if should_insert:
            result.append(Token(TOK_MUL, '*', tok.pos))
    return result


class Parser:
    """递归下降解析器"""

    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def consume(self) -> Token:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def expect(self, tok_type: str) -> Token:
        token = self.peek()
        if token.type != tok_type:
            raise SyntaxError(
                f"期望 {tok_type}，但遇到了 {token.type}({token.value})"
            )
        return self.consume()

    def parse(self):
        """入口：解析整个表达式"""
        result = self.parse_expr()
        if self.peek().type != TOK_EOF:
            raise SyntaxError(
                f"意外的 token: {self.peek().type}({self.peek().value})"
            )
        return result

    # expr := term (('+' | '-') term)*
    def parse_expr(self):
        left = self.parse_term()
        while self.peek().type in (TOK_PLUS, TOK_MINUS):
            op = self.consume()
            right = self.parse_term()
            if op.type == TOK_PLUS:
                left = ('+', left, right)
            else:
                left = ('-', left, right)
        return left

    # term := unary (('*' | '/') unary)*
    def parse_term(self):
        left = self.parse_unary()
        while self.peek().type in (TOK_MUL, TOK_DIV):
            op = self.consume()
            right = self.parse_unary()
            if op.type == TOK_MUL:
                left = ('*', left, right)
            else:
                left = ('/', left, right)
        return left

    # unary := ('+' | '-') unary | power
    def parse_unary(self):
        if self.peek().type in (TOK_PLUS, TOK_MINUS):
            op = self.consume()
            operand = self.parse_unary()
            if op.type == TOK_MINUS:
                return ('neg', operand)
            return operand
        return self.parse_power()

    # power := atom ('^' unary)?
    def parse_power(self):
        left = self.parse_atom()
        if self.peek().type == TOK_POW:
            self.consume()
            right = self.parse_unary()  # 右结合
            return ('^', left, right)
        return left

    # atom := NUM | VAR | FUNC '(' expr ')' | '(' expr ')'
    def parse_atom(self):
        token = self.peek()

        if token.type == TOK_NUM:
            self.consume()
            return token.value

        if token.type == TOK_VAR:
            self.consume()
            return ('var', token.value)

        if token.type == TOK_FUNC:
            func_name = token.value
            self.consume()
            self.expect(TOK_LPAREN)
            arg = self.parse_expr()
            self.expect(TOK_RPAREN)
            return ('func', func_name, arg)

        if token.type == TOK_LPAREN:
            self.consume()
            expr = self.parse_expr()
            self.expect(TOK_RPAREN)
            return expr

        raise SyntaxError(f"意外的 token: {token.type}({token.value})")


def eval_ast(ast, x_val: float) -> float:
    """对 AST 求值"""
    if isinstance(ast, (int, float)):
        return float(ast)

    if isinstance(ast, tuple):
        op = ast[0]

        if op == '+':
            return eval_ast(ast[1], x_val) + eval_ast(ast[2], x_val)
        elif op == '-':
            return eval_ast(ast[1], x_val) - eval_ast(ast[2], x_val)
        elif op == '*':
            return eval_ast(ast[1], x_val) * eval_ast(ast[2], x_val)
        elif op == '/':
            denom = eval_ast(ast[2], x_val)
            if denom == 0:
                raise ZeroDivisionError("除以零")
            return eval_ast(ast[1], x_val) / denom
        elif op == '^':
            base = eval_ast(ast[1], x_val)
            exp = eval_ast(ast[2], x_val)
            result = base ** exp
            if isinstance(result, complex):
                raise ValueError("产生了复数结果")
            return result
        elif op == 'neg':
            return -eval_ast(ast[1], x_val)

        elif op == 'var':
            return x_val

        elif op == 'func':
            func_name = ast[1]
            arg_val = eval_ast(ast[2], x_val)
            return apply_func(func_name, arg_val)

    raise ValueError(f"未知的 AST 节点: {ast}")


def apply_func(name: str, value: float) -> float:
    """应用数学函数"""
    if name == 'sin':
        return math.sin(value)
    elif name == 'cos':
        return math.cos(value)
    elif name == 'tan':
        result = math.tan(value)
        if abs(result) > 1e10:
            raise ValueError("tan 值过大，函数爆炸了！")
        return result
    elif name == 'abs':
        return abs(value)
    elif name == 'sqrt':
        if value < 0:
            raise ValueError("sqrt 参数为负数")
        return math.sqrt(value)
    elif name == 'log':
        if value <= 0:
            raise ValueError("log 参数必须为正数")
        return math.log10(value)
    elif name == 'ln':
        if value <= 0:
            raise ValueError("ln 参数必须为正数")
        return math.log(value)
    elif name == 'exp':
        result = math.exp(value)
        if abs(result) > 1e10:
            raise ValueError("exp 值过大，函数爆炸了！")
        return result
    raise ValueError(f"未知函数: {name}")


def parse_and_eval(expr_str: str, x_val: float) -> float:
    """解析并求值表达式"""
    try:
        tokens = tokenize(expr_str)
        parser = Parser(tokens)
        ast = parser.parse()
        return eval_ast(ast, x_val)
    except SyntaxError as e:
        raise ValueError(f"语法错误: {e}")
    except (ZeroDivisionError, OverflowError) as e:
        raise ValueError(f"计算错误: {e}")


# ============================================================
#  游戏数据结构
# ============================================================

@dataclass
class Soldier:
    """士兵"""
    x: float
    y: float
    owner_id: str
    alive: bool = True
    hp: int = 100


@dataclass
class Obstacle:
    """圆形障碍物"""
    x: float
    y: float
    radius: float
    craters: List[Tuple[float, float]] = field(default_factory=list)
    hp: int = 3  # 障碍物血量，0 时消失
    max_hp: int = 3


@dataclass
class GameSession:
    """一局游戏"""
    group_id: str
    players: Dict[str, str] = field(default_factory=dict)  # user_id -> nickname
    soldiers: List[Soldier] = field(default_factory=list)
    obstacles: List[Obstacle] = field(default_factory=list)
    current_player_idx: int = 0
    player_order: List[str] = field(default_factory=list)  # 轮流顺序
    started: bool = False
    finished: bool = False
    created_at: float = 0.0
    last_turn_at: float = 0.0
    turn_count: int = 0
    last_shot_traj: Optional[List[Tuple[float, float]]] = None
    last_shot_hit: bool = False
    game_mode: str = "classic"  # "classic" 或 "hp"
    team_mode: bool = True      # True=组队, False=自由对战
    _turn_version: int = 0      # 回合版本号，防止竞态条件导致双倍推进


# 活跃的游戏会话（按群组 ID 索引）
active_games: Dict[str, GameSession] = {}

# 匹配大厅（按群组 ID 索引）
matchmaking_lobbies: Dict[str, Dict] = {}


# ============================================================
#  战场生成
# ============================================================

# 地图常量
MAP_X_MIN, MAP_X_MAX = -25.0, 25.0
MAP_Y_MIN, MAP_Y_MAX = -15.0, 15.0
LEFT_SPAWN_X_RANGE = (-22.0, -5.0)   # 左方出生 x 范围
RIGHT_SPAWN_X_RANGE = (5.0, 22.0)     # 右方出生 x 范围
SPAWN_Y_RANGE = (-12.0, 12.0)         # y 范围
MIN_SOLDIER_DIST = 3.0                # 士兵之间的最小距离


def generate_battlefield(
    player_ids: List[str],
    soldiers_per_player: int,
    team_mode: bool = True,
) -> Tuple[List[Soldier], List[Obstacle]]:
    """随机生成战场，为每个玩家分配士兵位置，并生成障碍物"""
    soldiers: List[Soldier] = []

    # 组队模式：将玩家分配到左右两侧；自由对战：全图随机
    if team_mode:
        random.shuffle(player_ids)  # 随机决定谁在左边

    for i, pid in enumerate(player_ids):
        if team_mode:
            if i % 2 == 0:
                x_range = LEFT_SPAWN_X_RANGE
            else:
                x_range = RIGHT_SPAWN_X_RANGE
        else:
            x_range = (MAP_X_MIN + 3, MAP_X_MAX - 3)

        for _ in range(soldiers_per_player):
            for attempt in range(100):
                x = random.uniform(*x_range)
                y = random.uniform(*SPAWN_Y_RANGE)
                too_close = False
                for s in soldiers:
                    if math.hypot(x - s.x, y - s.y) < MIN_SOLDIER_DIST:
                        too_close = True
                        break
                if not too_close:
                    soldiers.append(Soldier(x=x, y=y, owner_id=pid))
                    break

    # 生成障碍物（避开士兵）
    obstacles: List[Obstacle] = []
    for _ in range(config.obstacle_count):
        for attempt in range(100):
            x = random.uniform(MAP_X_MIN + 5, MAP_X_MAX - 5)
            y = random.uniform(MAP_Y_MIN + 3, MAP_Y_MAX - 3)
            radius = random.uniform(config.obstacle_min_radius, config.obstacle_max_radius)

            too_close = False
            for s in soldiers:
                # 障碍物不能覆盖士兵
                if math.hypot(x - s.x, y - s.y) < radius + MIN_SOLDIER_DIST:
                    too_close = True
                    break
            for o in obstacles:
                # 障碍物之间留间距
                if math.hypot(x - o.x, y - o.y) < radius + o.radius + 2:
                    too_close = True
                    break
            if not too_close:
                obstacles.append(Obstacle(
                    x=x, y=y, radius=radius,
                    hp=config.obstacle_hp,
                    max_hp=config.obstacle_hp,
                ))
                break

    return soldiers, obstacles


def get_player_soldiers(session: GameSession, player_id: str) -> List[Soldier]:
    """获取某玩家的所有士兵"""
    return [s for s in session.soldiers if s.owner_id == player_id]


def _spawn_single_obstacle(
    soldiers: List[Soldier],
    existing_obstacles: List[Obstacle],
) -> Optional[Obstacle]:
    """尝试在战场中生成一个障碍物，避开士兵和现有障碍物"""
    for _ in range(50):
        x = random.uniform(MAP_X_MIN + 5, MAP_X_MAX - 5)
        y = random.uniform(MAP_Y_MIN + 3, MAP_Y_MAX - 3)
        radius = random.uniform(config.obstacle_min_radius, config.obstacle_max_radius)

        too_close = False
        for s in soldiers:
            if math.hypot(x - s.x, y - s.y) < radius + MIN_SOLDIER_DIST:
                too_close = True
                break
        for o in existing_obstacles:
            if o.hp <= 0:
                continue
            if math.hypot(x - o.x, y - o.y) < radius + o.radius + 2:
                too_close = True
                break
        if not too_close:
            return Obstacle(
                x=x, y=y, radius=radius,
                hp=config.obstacle_hp,
                max_hp=config.obstacle_hp,
            )
    return None


def _update_obstacles(session: GameSession):
    """清理已毁障碍物，并按配置间隔生成新障碍物"""
    # 移除血量归零的障碍物
    dead_count = sum(1 for o in session.obstacles if o.hp <= 0)
    if dead_count > 0:
        session.obstacles = [o for o in session.obstacles if o.hp > 0]

    # 按间隔生成新障碍物
    if config.obstacle_respawn_interval > 0 and session.turn_count > 0:
        if session.turn_count % config.obstacle_respawn_interval == 0:
            alive_count = len([o for o in session.obstacles if o.hp > 0])
            if alive_count < config.obstacle_max_count:
                new_obs = _spawn_single_obstacle(session.soldiers, session.obstacles)
                if new_obs is not None:
                    session.obstacles.append(new_obs)


def get_alive_soldiers(session: GameSession, player_id: str) -> List[Soldier]:
    """获取某玩家存活的士兵"""
    return [s for s in session.soldiers
            if s.owner_id == player_id and s.alive]


def get_player_side(session: GameSession, player_id: str) -> int:
    """获取玩家所在侧：0=左, 1=右（取第一个士兵的 x 坐标判断）"""
    for s in session.soldiers:
        if s.owner_id == player_id:
            return 0 if s.x < 0 else 1
    return 0


def get_enemy_soldiers(session: GameSession, player_id: str) -> List[Soldier]:
    """
    获取某玩家的敌方士兵。
    组队模式：敌方=对侧玩家；若开启友伤则同侧非己方也算
    自由对战：所有非己方士兵均为敌方
    """
    if session.team_mode:
        my_side = get_player_side(session, player_id)
        result = []
        for s in session.soldiers:
            if not s.alive:
                continue
            if s.owner_id == player_id:
                continue
            s_side = 0 if s.x < 0 else 1
            if s_side != my_side:
                result.append(s)  # 对侧 = 敌人
            elif config.friendly_fire:
                result.append(s)  # 同侧但开启友伤
        return result
    else:
        # 自由对战：所有其他玩家都是敌人
        return [s for s in session.soldiers
                if s.owner_id != player_id and s.alive]


def get_shooting_soldier(session: GameSession, player_id: str) -> Optional[Soldier]:
    """获取当前玩家用于射击的士兵（第一个存活的士兵）"""
    alive = get_alive_soldiers(session, player_id)
    return alive[0] if alive else None


# ============================================================
#  函数轨迹追踪与命中判定
# ============================================================

def compute_trajectory(
    expr_str: str,
    soldier: Soldier,
    trace_step: float,
    max_points: int,
    bidirectional: bool = False,
    obstacles: Optional[List[Obstacle]] = None,
) -> Tuple[List[Tuple[float, float]], Optional[str], List[Tuple[Obstacle, Tuple[float, float]]]]:
    """
    计算函数轨迹，遇到障碍物时停止。
    返回 (轨迹点列表, 错误信息, [(障碍物, 命中点), ...])
    """
    if obstacles is None:
        obstacles = []

    # 先检查 soldier.x 处函数是否有效
    try:
        f_at_sx = parse_and_eval(expr_str, soldier.x)
    except ValueError as e:
        return [], f"函数在士兵位置 (x={soldier.x:.1f}) 处无效: {e}", []

    # 检查是否发散（inf / nan）
    if math.isinf(f_at_sx) or math.isnan(f_at_sx):
        return [], (
            f"函数在士兵位置 (x={soldier.x:.1f}) 处发散 "
            f"(值={f_at_sx})，请换一个温和的函数！"
        ), []

    c = soldier.y - f_at_sx
    obstacle_hits: List[Tuple[Obstacle, Tuple[float, float]]] = []

    # 检查障碍物碰撞
    def check_obstacle_collision(px: float, py: float) -> Optional[Obstacle]:
        """检查点是否在某个障碍物内"""
        for obs in obstacles:
            if obs.hp <= 0:
                continue
            if math.hypot(px - obs.x, py - obs.y) <= obs.radius:
                return obs
        return None

    def trace_one_direction(direction: int) -> List[Tuple[float, float]]:
        pts: List[Tuple[float, float]] = []
        x = soldier.x
        x_end = MAP_X_MAX if direction > 0 else MAP_X_MIN

        for _ in range(max_points // 2):
            try:
                y = parse_and_eval(expr_str, x) + c
            except (ValueError, ZeroDivisionError, OverflowError):
                break

            if y > MAP_Y_MAX * 1.5 or y < MAP_Y_MIN * 1.5:
                break

            # 障碍物碰撞检测
            hit_obs = check_obstacle_collision(x, y)
            if hit_obs is not None:
                pts.append((x, y))
                hit_obs.craters.append((x, y))
                hit_obs.hp -= 1
                obstacle_hits.append((hit_obs, (x, y)))
                break

            pts.append((x, y))

            if (direction > 0 and x >= x_end) or (direction < 0 and x <= x_end):
                break

            x += direction * trace_step

        return pts

    if bidirectional:
        # 自由对战：双向追踪
        left_points = trace_one_direction(-1)
        right_points = trace_one_direction(1)
        left_points.reverse()
        if left_points and right_points and left_points[-1] == right_points[0]:
            left_points.pop()
        points = left_points + right_points
    else:
        # 组队模式：仅向敌方侧追踪
        if soldier.x < 0:
            points = trace_one_direction(1)  # 左→右
        else:
            points = trace_one_direction(-1) # 右→左

    if len(points) == 0:
        return [], "函数无法生成有效轨迹", obstacle_hits

    if len(points) >= max_points:
        return points, "函数轨迹过长，可能发生了爆炸！", obstacle_hits

    return points, None, obstacle_hits


def check_hits(
    trajectory: List[Tuple[float, float]],
    enemies: List[Soldier],
    tolerance: float,
) -> List[Soldier]:
    """
    检查轨迹是否命中敌方士兵。
    返回被命中的士兵列表。
    """
    hit_soldiers: List[Soldier] = []
    hit_ids: List[int] = []  # 用 id() 追踪已命中的士兵

    for tx, ty in trajectory:
        for enemy in enemies:
            if not enemy.alive:
                continue
            if id(enemy) in hit_ids:
                continue

            dist = math.hypot(tx - enemy.x, ty - enemy.y)
            if dist < tolerance:
                hit_soldiers.append(enemy)
                hit_ids.append(id(enemy))

    return hit_soldiers


def count_extrema(trajectory: List[Tuple[float, float]]) -> int:
    """统计轨迹中极值点的数量（导数变号次数）"""
    if len(trajectory) < 3:
        return 0

    extrema = 0
    prev_sign = 0  # 0=平坦, 1=递增, -1=递减

    for i in range(1, len(trajectory)):
        dy = trajectory[i][1] - trajectory[i - 1][1]
        if abs(dy) < 1e-8:
            sign = 0
        elif dy > 0:
            sign = 1
        else:
            sign = -1

        if prev_sign != 0 and sign != 0 and sign != prev_sign:
            extrema += 1

        if sign != 0:
            prev_sign = sign

    return extrema


def calculate_damage(extrema_count: int, max_hp: int = 100, min_damage: int = 5) -> int:
    """
    根据极值点数量计算伤害。
    公式: 0→99, 1→66, n≥2→99/(n+1)
    """
    if extrema_count == 0:
        return max_hp - 1  # 99
    if extrema_count == 1:
        return (max_hp * 2) // 3  # 66
    damage = (max_hp - 1) // (extrema_count + 1)
    return max(damage, min_damage)


# ============================================================
#  战场渲染（图片）
# ============================================================

# 战场图片尺寸
IMG_WIDTH = 600
IMG_HEIGHT = 400
IMG_MARGIN = 40  # 边距

# 颜色
COLOR_BG = (30, 30, 30)
COLOR_GRID = (50, 50, 50)
COLOR_AXIS = (100, 100, 100)
COLOR_TEXT = (200, 200, 200)
COLOR_LEFT_TEAM = (70, 130, 250)     # 蓝色
COLOR_RIGHT_TEAM = (250, 70, 70)     # 红色
COLOR_HIT = (255, 50, 50)
COLOR_TRAJECTORY = (255, 200, 50)    # 金色轨迹
COLOR_DEAD = (80, 80, 80)

# 自由对战模式下每名玩家的专属颜色（轮转使用）
FFA_PLAYER_COLORS = [
    (70, 130, 250),    # 蓝
    (250, 70, 70),     # 红
    (70, 220, 120),    # 绿
    (240, 180, 60),    # 橙
    (180, 100, 240),   # 紫
    (60, 200, 220),    # 青
    (240, 120, 180),   # 粉
    (200, 200, 80),    # 黄
]


def get_player_color(player_id: str, session: GameSession) -> Tuple[int, int, int]:
    """获取某玩家在战场上的显示颜色"""
    if not session.team_mode:
        # 自由对战：按玩家在 player_order 中的索引分配颜色
        try:
            idx = session.player_order.index(player_id)
        except ValueError:
            idx = hash(player_id) % len(FFA_PLAYER_COLORS)
        return FFA_PLAYER_COLORS[idx % len(FFA_PLAYER_COLORS)]
    # 组队模式：按侧分
    soldiers = [s for s in session.soldiers if s.owner_id == player_id]
    if soldiers and soldiers[0].x < 0:
        return COLOR_LEFT_TEAM
    return COLOR_RIGHT_TEAM


def coord_to_pixel(x: float, y: float) -> Tuple[int, int]:
    """将游戏坐标转换为像素坐标"""
    px = IMG_MARGIN + int((x - MAP_X_MIN) / (MAP_X_MAX - MAP_X_MIN) * (IMG_WIDTH - 2 * IMG_MARGIN))
    py = IMG_MARGIN + int((MAP_Y_MAX - y) / (MAP_Y_MAX - MAP_Y_MIN) * (IMG_HEIGHT - 2 * IMG_MARGIN))
    return px, py


def render_battlefield(session: GameSession, highlight_player_id: Optional[str] = None) -> bytes:
    """将战场渲染为 PNG 图像并返回 bytes"""
    img = Image.new('RGB', (IMG_WIDTH, IMG_HEIGHT), COLOR_BG)
    draw = ImageDraw.Draw(img)

    # 尝试加载字体
    font_path = str(plugin_dir.parent.parent / "src" / "static" / "msyh.ttc")
    try:
        font_small = ImageFont.truetype(font_path, 12)
        font_normal = ImageFont.truetype(font_path, 14)
    except Exception:
        font_small = ImageFont.load_default()
        font_normal = ImageFont.load_default()

    # 绘制网格
    for x in range(int(MAP_X_MIN), int(MAP_X_MAX) + 1, 5):
        px, py1 = coord_to_pixel(x, MAP_Y_MIN)
        _, py2 = coord_to_pixel(x, MAP_Y_MAX)
        color = COLOR_AXIS if x == 0 else COLOR_GRID
        draw.line([(px, py1), (px, py2)], fill=color, width=1)

    for y in range(int(MAP_Y_MIN), int(MAP_Y_MAX) + 1, 5):
        px1, py = coord_to_pixel(MAP_X_MIN, y)
        px2, _ = coord_to_pixel(MAP_X_MAX, y)
        color = COLOR_AXIS if y == 0 else COLOR_GRID
        draw.line([(px1, py), (px2, py)], fill=color, width=1)

    # 绘制坐标轴标签
    px0, py0 = coord_to_pixel(0, 0)
    draw.text((px0 + 3, py0 + 3), "O", fill=COLOR_TEXT, font=font_small)

    # 绘制轨迹
    if session.last_shot_traj:
        pixel_traj = [coord_to_pixel(x, y) for x, y in session.last_shot_traj]
        if len(pixel_traj) > 1:
            # 将轨迹分段绘制为折线
            for i in range(len(pixel_traj) - 1):
                draw.line(
                    [pixel_traj[i], pixel_traj[i + 1]],
                    fill=COLOR_TRAJECTORY,
                    width=2
                )

    # 绘制障碍物
    for obs in session.obstacles:
        if obs.hp <= 0:
            continue
        px, py = coord_to_pixel(obs.x, obs.y)
        obs_px_radius = int(obs.radius / (MAP_X_MAX - MAP_X_MIN) * (IMG_WIDTH - 2 * IMG_MARGIN))

        # 障碍物本体：颜色随血量变暗
        if obs.max_hp > 0 and obs.hp > 0:
            ratio = obs.hp / obs.max_hp
            base = int(60 + 40 * ratio)
            obs_fill = (base - 20, base - 20, base)
            obs_outline = (base + 20, base + 20, base + 30)
        else:
            obs_fill = (80, 80, 90)
            obs_outline = (120, 120, 130)
        draw.ellipse(
            [px - obs_px_radius, py - obs_px_radius,
             px + obs_px_radius, py + obs_px_radius],
            fill=obs_fill,
            outline=obs_outline,
            width=1
        )
        # 血量标签
        if obs.max_hp > 0 and obs.hp > 0:
            draw.text((px - 8, py - 8), f"{obs.hp}", fill=(220, 220, 220), font=font_small)

        # 弹坑（更深的凹陷标记）
        for cx, cy in obs.craters:
            cpx, cpy = coord_to_pixel(cx, cy)
            crater_r = max(2, obs_px_radius // 6)
            draw.ellipse(
                [cpx - crater_r, cpy - crater_r,
                 cpx + crater_r, cpy + crater_r],
                fill=(40, 40, 45),
                outline=(60, 60, 65),
                width=1
            )

    # 绘制士兵
    soldier_radius = 6
    highlighted_players: set = set()  # 只高亮每个当前玩家的第一个存活士兵
    for s in session.soldiers:
        px, py = coord_to_pixel(s.x, s.y)

        if s.alive:
            color = get_player_color(s.owner_id, session)
        else:
            color = COLOR_DEAD

        # 绘制士兵圆点
        draw.ellipse(
            [px - soldier_radius, py - soldier_radius,
             px + soldier_radius, py + soldier_radius],
            fill=color,
            outline=(255, 255, 255),
            width=1
        )

        # 高亮当前玩家即将发射的第一个存活士兵
        if (highlight_player_id
                and s.owner_id == highlight_player_id
                and s.alive
                and s.owner_id not in highlighted_players):
            highlighted_players.add(s.owner_id)
            draw.ellipse(
                [px - soldier_radius - 2, py - soldier_radius - 2,
                 px + soldier_radius + 2, py + soldier_radius + 2],
                outline=(255, 255, 0),
                width=2
            )

        # 显示玩家简称和血量
        nickname = session.players.get(s.owner_id, s.owner_id)[:4]
        if s.alive:
            label = nickname
            if session.game_mode == "hp":
                label += f" {s.hp}HP"
            draw.text((px + 8, py - 8), label, fill=color, font=font_small)

    # 绘制图例
    legend_y = IMG_HEIGHT - 25
    draw.ellipse([10, legend_y - 4, 18, legend_y + 4], fill=COLOR_LEFT_TEAM, outline=(255, 255, 255))
    draw.text((22, legend_y - 8), "左方", fill=COLOR_LEFT_TEAM, font=font_small)
    draw.ellipse([70, legend_y - 4, 78, legend_y + 4], fill=COLOR_RIGHT_TEAM, outline=(255, 255, 255))
    draw.text((82, legend_y - 8), "右方", fill=COLOR_RIGHT_TEAM, font=font_small)
    draw.ellipse([130, legend_y - 4, 138, legend_y + 4], fill=COLOR_DEAD, outline=(255, 255, 255))
    draw.text((142, legend_y - 8), "阵亡", fill=COLOR_DEAD, font=font_small)

    # 保存为 bytes
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def render_text_battlefield(session: GameSession) -> str:
    """将战场渲染为文本（备用方案）"""
    lines = []
    lines.append("═" * 30 + " GraphWar 战场 " + "═" * 30)
    lines.append(f"回合: {session.turn_count}")

    for pid in session.player_order:
        nickname = session.players.get(pid, pid)
        alive = get_alive_soldiers(session, pid)
        total = len(get_player_soldiers(session, pid))
        status = "🟢" if alive else "💀"
        hp_info = ""
        if session.game_mode == "hp" and alive:
            hp_info = f" ({alive[0].hp}HP)"
        lines.append(f"  {status} {nickname}{hp_info}: {len(alive)}/{total} 存活")

    lines.append("")
    lines.append("士兵位置:")
    for s in session.soldiers:
        icon = "🟦" if s.x < 0 else "🟥"
        if not s.alive:
            icon = "💀"
        nickname = session.players.get(s.owner_id, s.owner_id)
        lines.append(f"  {icon} [{nickname}] ({s.x:.1f}, {s.y:.1f})")

    if session.obstacles:
        lines.append("")
        lines.append("障碍物:")
        for i, obs in enumerate(session.obstacles):
            if obs.hp <= 0:
                continue
            craters = f" (弹坑x{len(obs.craters)})" if obs.craters else ""
            hp_str = f" HP{obs.hp}/{obs.max_hp}" if config.obstacle_hp > 0 else ""
            lines.append(
                f"  ⬤ [{i+1}] ({obs.x:.1f}, {obs.y:.1f}) "
                f"r={obs.radius:.1f}{hp_str}{craters}"
            )

    return "\n".join(lines)


# ============================================================
#  游戏逻辑
# ============================================================

async def send_group_msg(bot: Bot, group_id: str, text: str):
    """在后台任务中安全地发送群文本消息"""
    await bot.send_group_msg(
        group_id=int(group_id),
        message=Message(MessageSegment.text(text))
    )


async def send_group_msg_full(bot: Bot, group_id: str, msg: Message):
    """在后台任务中安全地发送完整群消息（含图片等）"""
    await bot.send_group_msg(group_id=int(group_id), message=msg)


def get_user_id(event: MessageEvent) -> str:
    """从事件中获取用户 ID"""
    return str(event.user_id)


def get_user_nickname(event: MessageEvent) -> str:
    """从事件中获取用户昵称"""
    try:
        if hasattr(event, 'sender') and hasattr(event.sender, 'nickname'):
            return event.sender.nickname
        return str(event.user_id)
    except Exception:
        return str(event.user_id)


def get_group_id(event: MessageEvent) -> Optional[str]:
    """获取群组 ID"""
    if isinstance(event, GroupMessageEvent):
        return str(event.group_id)
    return None


def can_join_game(group_id: str, user_id: str) -> Tuple[bool, str]:
    """检查用户是否可以加入游戏"""
    if group_id in active_games:
        session = active_games[group_id]
        if user_id in session.players:
            return False, "你已经在这场游戏中！"
        if session.started:
            return False, "游戏已经开始，无法加入"

    if group_id not in matchmaking_lobbies:
        return False, "当前没有匹配中的游戏，请使用 /graphwar 发起"

    lobby = matchmaking_lobbies[group_id]
    if user_id in lobby["players"]:
        return False, "你已经在匹配队列中！"

    return True, ""


# ============================================================
#  命令处理器
# ============================================================

# 帮助信息文本
GW_HELP_TEXT = (
    "🎯 **GraphWar 帮助**\n"
    "用数学函数作为炮弹轨迹的炮兵对战！\n\n"
    "📋 命令列表:\n"
    "  /graphwar [mode] [ffa] - 发起匹配\n"
    "  /gwgo                  - 发起者立即开始游戏\n"
    "  /gwjoin                - 加入匹配\n"
    "  /gw <函数>             - 发射函数炮弹\n"
    "  /gwstatus              - 查看当前战况\n"
    "  /gwquit                - 投降退出\n"
    "  /gwheelp               - 显示本帮助\n\n"
    "🎮 游戏模式 (mode):\n"
    "  classic (经典/默认)    - 每方3名士兵，命中直接击杀\n"
    "  hp (血量)              - 每方1名士兵100HP，\n"
    "                          极值点越少伤害越高，\n"
    "                          公式越长伤害越低\n\n"
    "⚔️ 对战类型:\n"
    "  (默认) 组队模式        - 同侧玩家为队友，单向射击\n"
    "  ffa/自由               - 自由混战，双向射击\n\n"
    "🔥 友方伤害:\n"
    f"  组队模式下{'开启' if config.friendly_fire else '关闭'}，同侧队友可被误伤\n\n"
    "🧱 障碍物:\n"
    f"  战场随机分布 {config.obstacle_count} 个圆形障碍物，\n"
    "  函数命中障碍物后会停止延伸并留下弹坑。\n\n"
    "📐 函数语法:\n"
    "  变量: x\n"
    "  运算符: + - * / ^\n"
    "  函数: sin cos tan abs sqrt log ln exp\n"
    "  常量: pi, e\n\n"
    "📝 示例:\n"
    "  /graphwar hp           - 血量组队模式\n"
    "  /graphwar ffa          - 经典自由对战\n"
    "  /graphwar hp ffa       - 血量自由对战\n"
    "  /gw sin(x/20)*5\n"
    "  /gw (x^2)/50\n"
    "  /gw sqrt(abs(x))*2\n\n"
    "💡 提示: 函数会自动平移使轨迹经过你的士兵位置。"
)


# 帮助命令
gwheelp = on_command("gwheelp", aliases={"graphwar_help", "gw帮助"}, priority=5, block=True)


@gwheelp.handle()
async def handle_gwheelp(event: GroupMessageEvent):
    """显示 GraphWar 帮助"""
    await gwheelp.finish(GW_HELP_TEXT)


# 发起匹配
graphwar = on_command("graphwar", aliases={"gwstart"}, priority=5, block=True)


@graphwar.handle()
async def handle_graphwar(
    event: GroupMessageEvent,
    bot: Bot,
    message: Message = CommandArg()
):
    """发起 GraphWar 匹配"""
    group_id = str(event.group_id)
    user_id = get_user_id(event)
    nickname = get_user_nickname(event)

    # 如果带了额外参数，解析游戏模式和匹配类型
    extra = message.extract_plain_text().strip().lower()
    if extra in ("help", "h"):
        await graphwar.finish(GW_HELP_TEXT)

    parts = extra.split() if extra else []
    game_mode = "classic"
    team_mode = True  # 默认组队

    for p in parts:
        if p in ("hp", "hpmode", "血量"):
            game_mode = "hp"
        elif p in ("classic", "经典"):
            game_mode = "classic"
        elif p in ("ffa", "free", "自由"):
            team_mode = False
        elif p not in ("",):
            await graphwar.finish(
                f"⚠️ 未知参数 '{p}'。\n"
                f"用法: /graphwar [classic|hp] [ffa]\n"
                f"  classic/hp - 游戏模式（经典/血量）\n"
                f"  ffa        - 自由对战（不加则为组队模式）"
            )

    # 检查是否已有活跃游戏
    if group_id in active_games and not active_games[group_id].finished:
        await graphwar.finish("⚠️ 当前群已有一场进行中的 GraphWar 游戏！请等待游戏结束。")

    # 检查是否已有匹配大厅
    if group_id in matchmaking_lobbies:
        await graphwar.finish("⚠️ 当前群已有匹配中的游戏，请使用 /gwjoin 加入")

    # 创建匹配大厅
    lobby = {
        "players": {user_id: nickname},
        "group_id": group_id,
        "created_at": time.time(),
        "creator_id": user_id,
        "creator_nickname": nickname,
        "game_mode": game_mode,
        "team_mode": team_mode,
    }
    matchmaking_lobbies[group_id] = lobby

    mode_tag = "🩸血量模式" if game_mode == "hp" else "🎯经典模式"
    match_tag = "⚔️自由对战" if not team_mode else "🤝组队模式"
    timeout = config.matchmaking_timeout
    await graphwar.send(
        f"{mode_tag} {match_tag} **GraphWar 匹配已发起！**\n"
        f"发起者: {nickname}\n"
        f"等待时间: {timeout} 秒\n"
        f"发送 **/gwjoin** 来加入匹配！\n"
        f"发起者可发送 **/gwgo** 立即开始\n"
        f"当前玩家: {nickname} (1人)"
    )

    # 启动匹配倒计时
    asyncio.create_task(matchmaking_timer(bot, group_id, timeout))


async def matchmaking_timer(bot: Bot, group_id: str, timeout: int):
    """匹配倒计时，超时后自动开始游戏"""
    await asyncio.sleep(timeout)

    lobby = matchmaking_lobbies.pop(group_id, None)
    if lobby is None:
        return  # 已经被处理过了

    if len(lobby["players"]) < config.min_players:
        # 人数不足，取消匹配
        await send_group_msg(
            bot, group_id,
            f"⏰ 匹配超时！当前仅有 {len(lobby['players'])} 人，"
            f"至少需要 {config.min_players} 人才能开始游戏。"
        )
        return

    # 开始游戏
    await start_game(bot, group_id, lobby["players"],
                     lobby.get("game_mode", "classic"),
                     lobby.get("team_mode", True))


async def start_game(bot: Bot, group_id: str, players: Dict[str, str],
                     game_mode: str = "classic", team_mode: bool = True):
    """开始游戏"""
    player_ids = list(players.keys())

    # HP 模式下每方只有 1 名士兵
    sp = 1 if game_mode == "hp" else config.soldiers_per_player

    # 生成战场
    soldiers, obstacles = generate_battlefield(player_ids, sp, team_mode)

    # HP 模式设置血量
    if game_mode == "hp":
        hp_val = config.soldier_hp
        for s in soldiers:
            s.hp = hp_val

    # 创建游戏会话
    session = GameSession(
        group_id=group_id,
        players=players,
        soldiers=soldiers,
        obstacles=obstacles,
        player_order=player_ids,
        current_player_idx=0,
        started=True,
        created_at=time.time(),
        last_turn_at=time.time(),
        game_mode=game_mode,
        team_mode=team_mode,
    )
    active_games[group_id] = session

    # 发送战场信息
    current_pid = session.player_order[0]
    current_nick = session.players[current_pid]

    mode_tag = "🩸血量模式" if game_mode == "hp" else "🎯经典模式"
    match_tag = "⚔️自由对战" if not team_mode else "🤝组队模式"
    dir_hint = "双向轨迹" if not team_mode else ("左→右" if soldiers[0].x < 0 else "右→左")
    if config.send_photo and HAS_PIL:
        img_data = render_battlefield(session, highlight_player_id=current_pid)
        await send_group_msg_full(
            bot, group_id,
            Message(
                MessageSegment.text(
                    f"{mode_tag} {match_tag} **GraphWar 开始！**\n"
                    f"玩家: {', '.join(players.values())}\n"
                    f"每方 {sp} 名士兵 | {dir_hint}\n"
                    f"当前回合: {current_nick}\n"
                    f"发送 **/gw <函数>** 来发射炮弹！"
                ) + MessageSegment.image(img_data)
            )
        )
    else:
        text_map = render_text_battlefield(session)
        await send_group_msg(
            bot, group_id,
            f"{mode_tag} {match_tag} **GraphWar 开始！**\n"
            f"玩家: {', '.join(players.values())}\n"
            f"每方 {sp} 名士兵 | {dir_hint}\n"
            f"当前回合: {current_nick}\n"
            f"\n{text_map}\n"
            f"\n发送 **/gw <函数>** 来发射炮弹！"
        )

    # 启动回合超时计时器
    asyncio.create_task(turn_timeout_timer(bot, group_id, session.turn_count))


async def turn_timeout_timer(bot: Bot, group_id: str, turn_at_start: int):
    """回合超时计时器，剩余 warn_time 秒时发出提醒"""
    total_timeout = config.turn_timeout
    warn_time = config.turn_warning_time

    session = active_games.get(group_id)
    if session is None:
        return
    turn_version_at_start = session._turn_version

    if total_timeout > warn_time:
        # 第一阶段：等待到只剩 warn_time 秒
        await asyncio.sleep(total_timeout - warn_time)

        session = active_games.get(group_id)
        if session is None or session.finished:
            return
        if session._turn_version != turn_version_at_start:
            return

        current_pid = session.player_order[session.current_player_idx]
        current_nick = session.players[current_pid]
        await send_group_msg(
            bot, group_id,
            f"⏳ {current_nick}，还剩 {warn_time} 秒输入公式！超时将自动跳过回合。"
        )

        # 第二阶段：等待最后 warn_time 秒
        await asyncio.sleep(warn_time)
    else:
        # 总超时太短，直接等待
        await asyncio.sleep(total_timeout)

    session = active_games.get(group_id)
    if session is None or session.finished:
        return

    # 检查回合是否已被消费（玩家已经行动或超时已处理）
    if session._turn_version != turn_version_at_start:
        return

    # 超时，跳过当前玩家
    current_pid = session.player_order[session.current_player_idx]
    current_nick = session.players[current_pid]

    await send_group_msg(
        bot, group_id,
        f"⏰ {current_nick} 回合超时，自动跳过！"
    )

    # 切换到下一个玩家
    await next_turn(bot, group_id)


async def next_turn(bot: Bot, group_id: str):
    """切换到下一个玩家回合"""
    session = active_games.get(group_id)
    if session is None or session.finished:
        return

    # 检查游戏结束条件
    winner_id = check_game_over(session)
    if winner_id:
        await end_game(bot, group_id, winner_id)
        return

    # 递增回合版本号（防止竞态条件导致双倍推进）
    session._turn_version += 1

    # 切换玩家
    session.current_player_idx = (session.current_player_idx + 1) % len(session.player_order)
    session.turn_count += 1
    session.last_turn_at = time.time()
    session.last_shot_traj = None
    session.last_shot_hit = False

    # 清理已毁障碍物，并按间隔生成新障碍物
    _update_obstacles(session)

    current_pid = session.player_order[session.current_player_idx]
    current_nick = session.players[current_pid]

    # 检查当前玩家是否还有存活的士兵
    alive = get_alive_soldiers(session, current_pid)
    if not alive:
        # 该玩家已全军覆没，跳过
        await send_group_msg(
            bot, group_id,
            f"💀 {current_nick} 已无存活士兵，跳过回合。"
        )
        await next_turn(bot, group_id)
        return

    # 发送当前战况
    if config.send_photo and HAS_PIL:
        img_data = render_battlefield(session, highlight_player_id=current_pid)
        await send_group_msg_full(
            bot, group_id,
            Message(
                MessageSegment.text(
                    f"🎯 回合 {session.turn_count}: **{current_nick}**\n"
                    f"发送 **/gw <函数>** 来发射炮弹！"
                ) + MessageSegment.image(img_data)
            )
        )
    else:
        text_map = render_text_battlefield(session)
        await send_group_msg(
            bot, group_id,
            f"🎯 回合 {session.turn_count}: **{current_nick}**\n"
            f"\n{text_map}\n"
            f"\n发送 **/gw <函数>** 来发射炮弹！"
        )

    # 启动回合超时
    asyncio.create_task(turn_timeout_timer(bot, group_id, session.turn_count))


def check_game_over(session: GameSession) -> Optional[List[str]]:
    """检查游戏是否结束，返回胜利者 ID 列表"""

    def get_alive_player_ids() -> set:
        if session.game_mode == "hp":
            return {s.owner_id for s in session.soldiers if s.hp > 0}
        return {s.owner_id for s in session.soldiers if s.alive}

    alive_ids = get_alive_player_ids()

    if session.team_mode:
        # 组队模式：检查某一侧是否全灭
        left_alive = {s.owner_id for s in session.soldiers
                      if s.x < 0 and (s.hp > 0 if session.game_mode == "hp" else s.alive)}
        right_alive = {s.owner_id for s in session.soldiers
                       if s.x >= 0 and (s.hp > 0 if session.game_mode == "hp" else s.alive)}
        if not left_alive:
            return list(right_alive)  # 右方队伍获胜
        if not right_alive:
            return list(left_alive)   # 左方队伍获胜
        return None

    # 自由对战 / 单人存活判定
    if len(alive_ids) <= 1:
        return list(alive_ids) if alive_ids else None
    return None


async def end_game(bot: Bot, group_id: str, winner_ids: List[str]):
    """结束游戏"""
    session = active_games.get(group_id)
    if session is None:
        return

    session.finished = True

    if not winner_ids:
        win_msg = f"🤝 **游戏结束！**\n平局！所有士兵均已阵亡。\n总回合数: {session.turn_count}"
    elif session.team_mode and len(winner_ids) > 1:
        # 组队模式：显示队伍胜利
        side = "左方队伍" if any(
            s.owner_id in winner_ids and s.x < 0 for s in session.soldiers
        ) else "右方队伍"
        winner_nicks = [session.players.get(wid, wid) for wid in winner_ids]
        win_msg = f"🏆 **游戏结束！**\n{side}获胜！\n胜利者: {', '.join(winner_nicks)}\n总回合数: {session.turn_count}"
    else:
        winner_nicks = [session.players.get(wid, wid) for wid in winner_ids]
        win_msg = f"🏆 **游戏结束！**\n胜利者: {winner_nicks[0]}\n总回合数: {session.turn_count}"

    if config.send_photo and HAS_PIL:
        img_data = render_battlefield(session)
        await send_group_msg_full(
            bot, group_id,
            Message(MessageSegment.text(win_msg) + MessageSegment.image(img_data))
        )
    else:
        await send_group_msg(bot, group_id, win_msg)

    del active_games[group_id]


# 加入匹配
gwjoin = on_command("gwjoin", aliases={"gw加入"}, priority=5, block=True)


@gwjoin.handle()
async def handle_gwjoin(event: GroupMessageEvent, bot: Bot):
    """加入 GraphWar 匹配"""
    group_id = str(event.group_id)
    user_id = get_user_id(event)
    nickname = get_user_nickname(event)

    can, msg = can_join_game(group_id, user_id)
    if not can:
        await gwjoin.finish(f"⚠️ {msg}")

    lobby = matchmaking_lobbies[group_id]
    lobby["players"][user_id] = nickname

    player_list = ", ".join(lobby["players"].values())
    await gwjoin.send(
        f"✅ {nickname} 加入了匹配！\n"
        f"当前玩家 ({len(lobby['players'])}人): {player_list}"
    )


# 发起者立即开始游戏
gwgo = on_command("gwgo", aliases={"gw开始"}, priority=5, block=True)


@gwgo.handle()
async def handle_gwgo(event: GroupMessageEvent, bot: Bot):
    """发起者立即开始 GraphWar 游戏"""
    group_id = str(event.group_id)
    user_id = get_user_id(event)
    nickname = get_user_nickname(event)

    lobby = matchmaking_lobbies.get(group_id)
    if lobby is None:
        await gwgo.finish("⚠️ 当前群没有匹配中的游戏！使用 /graphwar 发起新游戏。")

    if user_id != lobby["creator_id"]:
        await gwgo.finish(
            f"⚠️ 只有匹配发起者 ({lobby['creator_nickname']}) 可以提前开始游戏！"
        )

    if len(lobby["players"]) < config.min_players:
        await gwgo.finish(
            f"⚠️ 当前仅有 {len(lobby['players'])} 人，"
            f"至少需要 {config.min_players} 人才能开始游戏。"
        )

    lobby_data = matchmaking_lobbies.pop(group_id)
    player_names = ", ".join(lobby_data["players"].values())
    await gwgo.send(
        f"🚀 {nickname} 提前开始了游戏！\n"
        f"参战玩家 ({len(lobby_data['players'])}人): {player_names}"
    )
    await start_game(bot, group_id, lobby_data["players"],
                     lobby_data.get("game_mode", "classic"),
                     lobby_data.get("team_mode", True))


# 发射炮弹
gw = on_command("gw", aliases={"发射"}, priority=5, block=True)


@gw.handle()
async def handle_gw(event: GroupMessageEvent, bot: Bot, message: Message = CommandArg()):
    """发射函数炮弹"""
    group_id = str(event.group_id)
    user_id = get_user_id(event)
    nickname = get_user_nickname(event)

    # 检查是否在游戏中
    session = active_games.get(group_id)
    if session is None or session.finished:
        await gw.finish("⚠️ 当前群没有进行中的 GraphWar 游戏！使用 /graphwar 发起新游戏。")

    if not session.started:
        await gw.finish("⚠️ 游戏尚未开始，请等待匹配完成。")

    # 检查是否是当前玩家的回合
    current_pid = session.player_order[session.current_player_idx]
    if user_id != current_pid:
        current_nick = session.players.get(current_pid, current_pid)
        await gw.finish(f"⚠️ 现在是 {current_nick} 的回合，请等待！")

    # 防止回合超时竞态：标记回合已被消费，使超时计时器失效
    session._turn_version += 1
    # 二次确认：回合是否已被超时推进（极端竞态保护）
    if session.player_order[session.current_player_idx] != current_pid:
        await gw.finish("⚠️ 回合已超时，请等待下一轮。")

    # 获取函数表达式
    expr_str = message.extract_plain_text().strip()

    if not expr_str:
        await gw.finish(
            "⚠️ 请输入函数表达式！\n"
            "示例: /gw sin(x/20)*5\n"
            "      /gw (x^2)/50\n"
            "      /gw sqrt(abs(x))*2"
        )

    if len(expr_str) > config.max_function_length:
        await gw.finish(f"⚠️ 函数表达式过长（最多 {config.max_function_length} 字符）")

    # 获取射击士兵
    soldier = get_shooting_soldier(session, user_id)
    if soldier is None:
        await gw.finish("💀 你的士兵已全部阵亡！")

    # 计算轨迹
    trajectory, error, obstacle_hits = compute_trajectory(
        expr_str, soldier,
        config.trace_step,
        config.max_trace_points,
        bidirectional=not session.team_mode,  # 自由对战=双向
        obstacles=session.obstacles,
    )

    if error:
        await gw.send(f"💥 {nickname} 的函数爆炸了！\n原因: {error}")
        session.last_shot_traj = None
        session.last_shot_hit = False
        await next_turn(bot, group_id)
        return

    # 检查命中
    enemies = get_enemy_soldiers(session, user_id)
    hits = check_hits(trajectory, enemies, config.hit_tolerance)

    session.last_shot_traj = trajectory

    # 血量模式：计算极值点和伤害
    extrema_count = 0
    damage = 0
    length_factor = 1.0
    if session.game_mode == "hp":
        extrema_count = count_extrema(trajectory)
        damage = calculate_damage(extrema_count, config.soldier_hp, config.hp_min_damage)
        # 公式长度惩罚：公式越长伤害越低
        length_ratio = len(expr_str) / max(config.max_function_length, 1)
        length_factor = max(0.2, 1.0 - length_ratio * 0.8)
        damage = max(1, int(damage * length_factor))

    if hits:
        session.last_shot_hit = True

        if session.game_mode == "hp":
            # 血量模式：扣血
            hit_names = []
            for h in hits:
                h.hp -= damage
                hit_owner_nick = session.players.get(h.owner_id, h.owner_id)
                if h.hp <= 0:
                    h.hp = 0
                    h.alive = False
                    hit_names.append(
                        f"  💀 {hit_owner_nick} ({h.x:.1f}, {h.y:.1f}) 被击杀！"
                    )
                else:
                    hit_names.append(
                        f"  💥 {hit_owner_nick} ({h.x:.1f}, {h.y:.1f}) "
                        f"-{damage} HP，剩余 {h.hp} HP"
                    )

            hit_msg = "\n".join(hit_names)
            len_info = (
                f"，长度惩罚: {length_factor:.0%}"
                if length_factor < 0.95 else ""
            )
            ext_info = (
                f"（极值点: {extrema_count} 个，伤害: {damage}{len_info}）"
                if extrema_count > 0 else f"（无极值点，伤害: {damage}{len_info}！）"
            )
            obs_msg = f"\n🧱 击中 {len(obstacle_hits)} 个障碍物。" if obstacle_hits else ""
            await gw.send(
                f"🎯 {nickname} 发射: y = {expr_str}\n"
                f"命中！{ext_info}\n{hit_msg}{obs_msg}"
            )
        else:
            # 经典模式：直接击杀
            hit_names = []
            for h in hits:
                h.alive = False
                hit_owner_nick = session.players.get(h.owner_id, h.owner_id)
                hit_names.append(f"{hit_owner_nick} 的士兵 ({h.x:.1f}, {h.y:.1f})")

            hit_msg = "\n".join(f"  💥 {name}" for name in hit_names)
            obs_msg = f"\n🧱 击中 {len(obstacle_hits)} 个障碍物。" if obstacle_hits else ""
            await gw.send(
                f"🎯 {nickname} 发射: y = {expr_str}\n"
                f"命中！\n{hit_msg}{obs_msg}"
            )

        # 检查是否游戏结束
        winner_id = check_game_over(session)
        if winner_id:
            if config.send_photo and HAS_PIL:
                img_data = render_battlefield(session)
                await gw.send(MessageSegment.image(img_data))

            await end_game(bot, group_id, winner_id)
            return
    else:
        session.last_shot_hit = False
        obs_msg = ""
        if obstacle_hits:
            obs_msg = f"\n🧱 击中 {len(obstacle_hits)} 个障碍物，轨迹停止延伸。"
        await gw.send(
            f"🎯 {nickname} 发射: y = {expr_str}\n"
            f"未命中任何目标...{obs_msg}"
        )

    # 发送战场更新
    if config.send_photo and HAS_PIL:
        img_data = render_battlefield(session)
        await gw.send(MessageSegment.image(img_data))

    # 切换到下一个玩家
    await next_turn(bot, group_id)


# 查看战况
gwstatus = on_command("gwstatus", aliases={"gw状态"}, priority=5, block=True)


@gwstatus.handle()
async def handle_gwstatus(event: GroupMessageEvent):
    """查看当前战况"""
    group_id = str(event.group_id)

    session = active_games.get(group_id)
    if session is None or session.finished:
        await gwstatus.finish("⚠️ 当前群没有进行中的 GraphWar 游戏！")

    current_pid = session.player_order[session.current_player_idx]
    current_nick = session.players.get(current_pid, current_pid)

    if config.send_photo and HAS_PIL:
        img_data = render_battlefield(session, highlight_player_id=current_pid)
        await gwstatus.send(
            MessageSegment.text(
                f"📊 **GraphWar 战况**\n"
                f"回合: {session.turn_count}\n"
                f"当前: {current_nick}\n"
                f"玩家: {', '.join(session.players.values())}"
            ) + MessageSegment.image(img_data)
        )
    else:
        text_map = render_text_battlefield(session)
        await gwstatus.send(text_map)


# 投降退出
gwquit = on_command("gwquit", aliases={"gw退出", "gw投降"}, priority=5, block=True)


@gwquit.handle()
async def handle_gwquit(event: GroupMessageEvent, bot: Bot):
    """投降退出游戏"""
    group_id = str(event.group_id)
    user_id = get_user_id(event)
    nickname = get_user_nickname(event)

    session = active_games.get(group_id)
    if session is None or session.finished:
        await gwquit.finish("⚠️ 当前群没有进行中的 GraphWar 游戏！")

    if user_id not in session.players:
        await gwquit.finish("⚠️ 你不在当前游戏中！")

    # 将该玩家的所有士兵标记为阵亡
    for s in session.soldiers:
        if s.owner_id == user_id:
            s.alive = False

    await gwquit.send(f"🏳️ {nickname} 投降了！")

    # 检查游戏是否结束
    winner_id = check_game_over(session)
    if winner_id:
        await end_game(bot, group_id, winner_id)
    else:
        # 如果是当前玩家的回合，跳过
        current_pid = session.player_order[session.current_player_idx]
        if current_pid == user_id:
            await next_turn(bot, group_id)
