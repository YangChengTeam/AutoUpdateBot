import sys
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# 将项目根目录添加到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.routes import tasks

app = FastAPI(
    title="AutoUpdateBot API",
    description="用于管理应用自动更新任务的 REST API",
    version="1.0.0"
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源，生产环境应限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 包含路由
app.include_router(tasks.router)

@app.get("/")
async def root():
    return {"message": "Welcome to AutoUpdateBot API", "docs": "/docs"}

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=10000, reload=True)
