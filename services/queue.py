from core.queue.redis_queue import RedisClient

class QueueService:
    def __init__(self, redis_config=None):
        if redis_config is None:
            redis_config = {}
        self.redis = RedisClient(**redis_config)
    
    def get_task(self, queue_name):
        """从指定队列获取任务。"""
        return self.redis.lpop(queue_name)
    
    def add_task(self, queue_name, task_data):
        """添加任务到队列 (用于测试或重新入队)。"""
        return self.redis.push(queue_name, task_data)
