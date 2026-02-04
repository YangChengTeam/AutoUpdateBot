import os
import sys
import json
import asyncio
import logging
import yaml
import random
from watchfiles import awatch

# 将项目根目录添加到路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)

from services.queue import QueueService

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("FileWatcher")

def load_watcher_config():
    """加载 watcher.yaml 配置文件"""
    config_paths = [
        os.path.join(BASE_DIR, 'watcher.yaml'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watcher.yaml')
    ]
    
    for path in config_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    logger.info(f"加载配置文件: {path}")
                    return yaml.safe_load(f)
            except Exception as e:
                logger.error(f"解析配置文件 {path} 失败: {e}")
    
    logger.warning("未找到 watcher.yaml，将使用默认配置")
    return {}

async def main():
    # 加载配置
    config = load_watcher_config()

    # Redis 配置
    redis_config = config.get('redis', {'host': 'localhost', 'port': 6379, 'db': 0})
    queue_service = QueueService(redis_config)
    
    # 监听配置
    watcher_cfg = config.get('watcher', {})
    base_queue_name = watcher_cfg.get('queue_name', 'apk_task_queue')
    watch_dir = watcher_cfg.get('watch_dir', os.path.join(BASE_DIR, 'temp'))
    
    # 解析端口列表
    ports_str = str(watcher_cfg.get('ports', ''))
    ports = [p.strip() for p in ports_str.split(',') if p.strip()]
    
    if not ports:
        logger.warning("未配置端口 (ports)，将使用单一队列")
    else:
        logger.info(f"已配置端口列表: {ports}")
    
    # 确保路径是绝对路径
    if not os.path.isabs(watch_dir):
        watch_dir = os.path.abspath(os.path.join(BASE_DIR, watch_dir))
    
    if not os.path.exists(watch_dir):
        try:
            os.makedirs(watch_dir)
            logger.info(f"创建监听目录: {watch_dir}")
        except Exception as e:
            logger.error(f"无法创建监听目录 {watch_dir}: {e}")
            return
    
    logger.info(f"正在监听目录: {watch_dir}")

    # 开始监听
    async for changes in awatch(watch_dir):
        for change_type, file_path in changes:
            # 1 = added
            if change_type == 1:
                abs_path = os.path.abspath(file_path)
                
                # 排除临时文件
                if abs_path.endswith('.aria2') or abs_path.endswith('.tmp'):
                    continue
                
                logger.info(f"检测到新文件: {abs_path}")
                
                # 随机选择一个端口并构造队列名
                if ports:
                    selected_port = random.choice(ports)
                    target_queue = f"{base_queue_name}_{selected_port}"
                else:
                    target_queue = base_queue_name
                
                # 构造任务数据
                task_data = {
                    "path": abs_path,
                    "is_remote": False
                }
                
                # 推送到 Redis
                success = queue_service.add_task(target_queue, task_data)
                if success:
                    logger.info(f"任务已随机分配至端口 [{selected_port if ports else 'default'}]，推送至队列 [{target_queue}]: {json.dumps(task_data, ensure_ascii=False)}")
                else:
                    logger.error(f"任务推送失败 (Redis 连接异常): {abs_path}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("文件监听已停止")
    except Exception as e:
        logger.error(f"运行出错: {e}")
