import os
import sys

def get_base_dir():
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # 如果是打包后的环境
        return sys._MEIPASS
    else:
        # 如果是开发环境
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASE_DIR = get_base_dir()
BIN_DIR = os.path.join(BASE_DIR, 'bin')
ADB_PATH = os.path.join(BIN_DIR, 'adb')
AAPT_PATH = os.path.join(BIN_DIR, 'aapt', 'aapt.exe')

def setup_env():
    """将项目内的 ADB 路径加入系统环境变量，优先使用"""
    if os.path.exists(ADB_PATH):
        # 确保路径被加入到 PATH 的最前面
        os.environ["PATH"] = ADB_PATH + os.pathsep + os.environ["PATH"]
        print(f"[Env] 已加载本地 ADB: {ADB_PATH}")
    else:
        print(f"[Env] 警告: 未在 {ADB_PATH} 找到 ADB，尝试使用系统默认...")