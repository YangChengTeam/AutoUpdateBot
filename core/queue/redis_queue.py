import redis
import json
import logging

class RedisClient:
    def __init__(self, host='localhost', port=6379, db=0, password=None):
        self.client = redis.Redis(host=host, port=port, db=db, password=password, decode_responses=True)
        self.logger = logging.getLogger(__name__)

    def lpop(self, key):
        """从列表左侧弹出一个元素。"""
        try:
            item = self.client.lpop(key)
            return json.loads(item) if item else None
        except Exception as e:
            self.logger.error(f"从 Redis key {key} 弹出时出错: {e}")
            return None

    def push(self, key, item):
        """将元素推入列表右侧。"""
        try:
            self.client.rpush(key, json.dumps(item))
            return True
        except Exception as e:
            self.logger.error(f"推入 Redis key {key} 时出错: {e}")
            return False
