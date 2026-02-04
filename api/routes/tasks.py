from fastapi import APIRouter, HTTPException, Request
from services.queue import QueueService
from utils.utils import load_config
import logging
from typing import Dict, Any, List

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = logging.getLogger("api")

# 加载配置以获取 Redis 连接信息
config = load_config()
# 尝试从 settings.yaml 或 watcher.yaml 加载 redis 配置
redis_config = config.get('redis')
if not redis_config:
    import yaml
    try:
        with open("watcher.yaml", "r", encoding="utf-8") as f:
            watcher_config = yaml.safe_load(f)
            redis_config = watcher_config.get('redis')
    except:
        pass

if not redis_config:
    redis_config = {'host': 'localhost', 'port': 6379, 'db': 0}

queue_service = QueueService(redis_config=redis_config)
QUEUE_NAME = "official_website_update_queue"

@router.post("/official-website")
async def create_official_website_task(task: Dict[str, Any]):
    """
    创建一个新的官网更新检测任务，直接接收原始 JSON
    """
    try:
        # 直接将传入的字典推送到 Redis
        success = queue_service.add_task(QUEUE_NAME, task)
        
        if success:
            package_name = task.get('package', 'unknown')
            logger.info(f"成功添加任务到队列 {QUEUE_NAME}: {package_name}")
            return {"status": "success", "message": f"Task for {package_name} added to queue."}
        else:
            logger.error(f"Redis 写入失败")
            raise HTTPException(status_code=500, detail="Failed to add task to Redis.")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加任务出现异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

@router.post("/official-website/batch")
async def create_official_website_tasks_batch(tasks: List[Dict[str, Any]]):
    """
    批量创建官网更新检测任务
    """
    if not tasks:
        raise HTTPException(status_code=400, detail="Task list cannot be empty.")
    
    results = {"success": 0, "failed": 0, "details": []}
    
    for task in tasks:
        package_name = task.get('package_name', 'unknown')
        try:
            success = queue_service.add_task(QUEUE_NAME, task)
            if success:
                results["success"] += 1
                logger.info(f"批量添加成功: {package_name}")
            else:
                results["failed"] += 1
                logger.error(f"批量添加失败 (Redis 写入失败): {package_name}")
                results["details"].append({"package_name": package_name, "error": "Redis write failure"})
        except Exception as e:
            results["failed"] += 1
            logger.error(f"批量添加出现异常: {package_name}, {str(e)}")
            results["details"].append({"package_name": package_name, "error": str(e)})

    return {
        "status": "completed",
        "message": f"Processed {len(tasks)} tasks. {results['success']} success, {results['failed']} failed.",
        "results": results
    }
