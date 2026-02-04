import os
import time
import yaml
from core.device.device import DeviceManager
from services.queue import QueueService
from core.env_loader import BASE_DIR

class WorkerService:
    def __init__(self, device):
        self.device = device
        self.serial = device.serial
        self.watcher_cfg = self._load_watcher_config()
        self.redis_config = self.watcher_cfg.get('redis', {'host': 'localhost', 'port': 6379, 'db': 0})
        self.queue_service = QueueService(self.redis_config)
        
        port = self.serial.split(':')[-1] if ':' in self.serial else self.serial
        base_queue_name = self.watcher_cfg.get('watcher', {}).get('queue_name', 'apk_task_queue')
        self.queue_name = f"{base_queue_name}_{port}"

    def _load_watcher_config(self):
        path = os.path.join(BASE_DIR, 'watcher.yaml')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        return {}

    def start(self):
        """启动监听循环"""
        print(f"--> [WorkerService] 启动，监听设备: {self.serial}, 队列: {self.queue_name}")
        while True:
            try:
                task = self.queue_service.get_task(self.queue_name)
                if task:
                    print(f"--> [WorkerService] 收到任务: {task}")
                    apk_path = task.get('path')
                    is_remote = task.get('is_remote', True)
                    
                    if not is_remote and apk_path and os.path.exists(apk_path):
                        print(f"--> [WorkerService] 正在执行安装: {apk_path}")
                        self.device.app_install(apk_path)
                    else:
                        print(f"--> [WorkerService] 跳过无效或远程任务")
                time.sleep(1)
            except Exception as e:
                print(f"--> [WorkerService] 运行异常: {e}")
                time.sleep(5)
