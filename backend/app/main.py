# main.py  
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 👇 导入你的 somark 路由（假设放在 api/somark.py）  
from .api import somark

# 创建 FastAPI 应用  
app = FastAPI(title="AI 课件助手 API", version="1.0")

# 跨域配置（前端可以正常调用）  
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 生产环境建议改为具体域名  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 👇 注册 SoMark 解析接口  
app.include_router(somark.router)

# 测试接口  
@app.get("/")
def root():
    return {"message": "AI 课件助手后端运行成功！"}  
