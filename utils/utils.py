import os
import yaml
import hashlib
import shutil
from datetime import datetime


def load_config(config_path):
    """加载 YAML 配置文件"""
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[utils] 加载配置失败 {config_path}: {e}")
        return {}


def get_local_path(package_name, storage_dir):
    """生成 APK 本地存储路径"""
    return os.path.join(storage_dir, f"{package_name}.apk")


def delete_file(file_path):
    """删除文件（如果存在）"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        print(f"[utils] 删除文件失败 {file_path}: {e}")


def rename(src, dst):
    """重命名/移动文件"""
    os.rename(src, dst)


def get_file_md5(file_path, chunk_size=8192):
    """计算文件的 MD5"""
    md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            md5.update(chunk)
    return md5.hexdigest()


def get_file_blake3(file_path, chunk_size=8192):
    """计算文件的 BLAKE3（需要 pip install blake3）"""
    try:
        import blake3
        with open(file_path, 'rb') as f:
            return blake3.blake3(f.read()).hexdigest()
    except ImportError:
        return get_file_md5(file_path)
