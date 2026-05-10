from pathlib import Path
import nonebot
from nonebot.plugin import PluginMetadata
from .config import Config

__plugin_meta__ = PluginMetadata(
    name="文件编辑器",
    description="安全的文件操作插件",
    usage="通过命令管理文件",
    extra={"unique_name": "file_editor", "permissions": ["文件管理"]},
    config=Config,
)


# 获取数据目录
driver = nonebot.get_driver()
data_dir = Path(driver.config.data_dir)  # 对应.env中的DATA_DIR
plugin_dir = data_dir / driver.config.file_edit_dir  # 对应.env中的FILE_EDIT_DIR

# 创建目录（如果不存在）
plugin_dir.mkdir(parents=True, exist_ok=True)

import shutil
from typing import Optional

def safe_path(filename: str) -> Path:
    """防止路径穿越攻击"""
    target_path = (plugin_dir / filename).resolve()
    if plugin_dir.resolve() not in target_path.parents:
        raise ValueError("非法路径")
    return target_path

import csv
from pathlib import Path
from typing import List, Union

def read_csv_file(
    filename: str,
    delimiter: str = ",",
    encoding: str = "utf-8"
) -> Union[List[List[str]], str]:
    """
    安全读取CSV文件（同步版本）
    参数：
    - filename: 文件名（相对路径）
    - delimiter: 分隔符，默认逗号
    - encoding: 文件编码，默认utf-8
    返回：二维数组或错误信息
    """
    try:
        file_path = safe_path(filename)
        
        # 验证扩展名
        if file_path.suffix.lower() != ".csv":
            return "仅支持CSV文件"
        
        # 读取文件内容
        with file_path.open("r", encoding=encoding) as f:
            reader = csv.reader(f, delimiter=delimiter)
            return [row for row in reader]
            
    except FileNotFoundError:
        return "文件不存在"
    except PermissionError:
        return "没有读取权限"
    except csv.Error as e:
        return f"CSV格式错误：{str(e)}"
    except UnicodeDecodeError:
        return f"编码错误，请尝试指定编码（当前使用{encoding}）"
    except Exception as e:
        return f"读取失败：{str(e)}"

def read_file(filename: str) -> str:
    """读取文件内容"""
    file_path = safe_path(filename)
    try:
        return file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError("文件不存在")

# 使用分块读取
def read_large_file(filename: str):
    file_path = safe_path(filename)
    with file_path.open("r", encoding="utf-8") as f:
        while chunk := f.read(4096):
            yield chunk

def write_file(filename: str, content: str) -> None:
    """写入/创建文件"""
    file_path = safe_path(filename)
    file_path.write_text(content, encoding="utf-8")

def write_csv_file(
    filename: str,
    data: List[List[str]],
    delimiter: str = ",",
    encoding: str = "utf-8"
) -> Union[bool, str]:
    """
    安全写入CSV文件（同步版本）
    参数：
    - filename: 文件名（自动添加.csv后缀）
    - data: 二维数组数据
    - delimiter: 分隔符，默认逗号
    - encoding: 文件编码，默认utf-8
    返回：成功返回True，失败返回错误信息
    """
    try:
        # 自动补充文件后缀
        if not filename.lower().endswith(".csv"):
            filename += ".csv"
        
        file_path = safe_path(filename)
        
        # 创建父目录（如果不存在）
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 验证数据格式
        if not all(isinstance(row, list) for row in data):
            return "数据格式错误：需要二维数组"
        
        # 写入文件
        with file_path.open("w", encoding=encoding, newline='') as f:
            writer = csv.writer(f, delimiter=delimiter)
            writer.writerows(data)
            
        return True
        
    except PermissionError:
        return "没有写入权限"
    except csv.Error as e:
        return f"CSV写入失败：{str(e)}"
    except Exception as e:
        return f"操作失败：{str(e)}"

def append_csv_rows(
    filename: str,
    header: List[str],
    rows: List[List[str]],
    delimiter: str = ",",
    encoding: str = "utf-8",
    check_header: bool = False  # 可选参数：检查现有表头是否匹配
) -> Union[bool, str]:
    """
    安全追加行到CSV文件（需单独指定表头）
    参数：
    - filename: 文件名
    - header: 表头列表（文件不存在时使用）
    - rows: 数据行二维数组
    - delimiter: 分隔符
    - encoding: 文件编码
    - check_header: 是否校验现有表头一致性
    """
    try:
        file_path = safe_path(filename)
        
        # 基础验证
        if not isinstance(header, list) or not header:
            return "表头必须是非空列表"
        if not all(isinstance(row, list) for row in rows):
            return "数据行必须为二维数组"
        
        file_exists = file_path.exists()
        file_empty = file_exists and file_path.stat().st_size == 0
        
        # 当文件存在且需要检查表头时
        if file_exists and not file_empty and check_header:
            with file_path.open("r", encoding=encoding) as f:
                reader = csv.reader(f, delimiter=delimiter)
                existing_header = next(reader, None)
                
                if existing_header and existing_header != header:
                    return f"表头不匹配（现有：{existing_header} vs 输入：{header}）"
        
        # 写入模式处理
        mode = "a" if file_exists else "w"
        with file_path.open(mode, encoding=encoding, newline='') as f:
            writer = csv.writer(f, delimiter=delimiter)
            
            # 需要写入表头的情况
            if not file_exists or file_empty:
                writer.writerow(header)
                
            # 写入数据行
            writer.writerows(rows)
            
        return True
        
    except PermissionError:
        return "没有写入权限"
    except csv.Error as e:
        return f"CSV操作失败：{str(e)}"
    except Exception as e:
        return f"操作失败：{str(e)}"

def delete_file(filename: str) -> None:
    """删除文件"""
    file_path = safe_path(filename)
    if file_path.is_dir():
        raise ValueError("不能删除目录")
    file_path.unlink()

##from nonebot import on_command
##from nonebot.params import CommandArg
##from nonebot.adapters.onebot.v11 import Message
##
##file_cmd = on_command("文件操作", aliases={"file"}, priority=5)
##
##@file_cmd.handle()
##async def handle_command(args: Message = CommandArg()):
##    cmd_args = str(args).split()
##    
##    try:
##        if cmd_args[0] == "读取":
##            content = await read_file(cmd_args[1])
##            await file_cmd.finish(f"文件内容：\n{content}")
##            
##        elif cmd_args[0] == "写入":
##            await write_file(cmd_args[1], " ".join(cmd_args[2:]))
##            await file_cmd.finish("文件写入成功")
##            
##        elif cmd_args[0] == "删除":
##            await delete_file(cmd_args[1])
##            await file_cmd.finish("文件已删除")
##            
##    except IndexError:
##        await file_cmd.finish("参数不足，正确格式：\n文件操作 [读取/写入/删除] 文件名 [内容]")
##    except Exception as e:
##        await file_cmd.finish(f"操作失败：{str(e)}")
##
##test_cmd = on_command("ping")
##
##@test_cmd.handle()
##async def _():
##    await write_file("test.txt", " ".join("pong"))
##    await test_cmd.send("pong")
##
### 在命令处理函数中添加日志
# 命令处理器更新
'''
@file_cmd.handle()
def handle_command(args: Message = CommandArg()):
    cmd_args = str(args).split()
    
    try:
        if cmd_args[0] == "读取csv":
            if len(cmd_args) < 2:
                return file_cmd.finish("需要指定文件名")
            
            params = {
                "filename": cmd_args[1],
                "delimiter": ",",
                "encoding": "utf-8"
            }
            
            # 解析参数
            for arg in cmd_args[2:]:
                if "=" in arg:
                    key, value = arg.split("=", 1)
                    if key == "分隔符":
                        params["delimiter"] = value
                    elif key == "编码":
                        params["encoding"] = value
            
            result = read_csv_file(**params)
            
            if isinstance(result, str):
                file_cmd.finish(result)
            else:
                response = "CSV内容：\n" + "\n".join([" | ".join(row) for row in result])
                file_cmd.finish(response[:1000])  # 限制输出长度
'''            
    # ...保持原有异常处理逻辑

#前面能用就行！！！


