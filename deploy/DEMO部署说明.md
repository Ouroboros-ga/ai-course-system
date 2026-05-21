# 超星AI互动智课系统 - DEMO部署说明

## 📋 系统概述

本系统是基于泛雅平台的AI互动智课生成与实时问答系统，采用前后端分离架构：
- **前端**：Vue 3 + Vite + Element Plus
- **后端**：FastAPI + Python 3.12
- **数据库**：SQLite3（开发环境）/ MySQL（生产环境）
- **AI能力**：豆包/通义千问/文心一言大模型API
- **语音处理**：火山引擎TTS

---

## 🖥️ 环境要求

### 基础环境
| 组件 | 版本要求 | 说明 |
|------|----------|------|
| Python | 3.12+ | 后端运行环境 |
| Node.js | 20.x+ | 前端运行环境 |
| npm | 10.x+ | 前端包管理器 |
| uv | 最新版 | Python包管理器（推荐） |
| Git | 任意版本 | 代码版本控制 |

### 硬件要求
- **CPU**：4核及以上
- **内存**：8GB及以上
- **磁盘**：20GB可用空间
- **GPU**：可选（用于加速文档解析）

---

## 📦 项目获取

```bash
# 克隆项目仓库
git clone https://gitee.com/Ouroboros/ai-smart-course-system.git
cd ai-smart-course-system
```

---

## ⚙️ 后端部署

### 1. 安装uv包管理器

```bash
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Linux/Mac
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 进入后端目录并创建虚拟环境

```bash
cd backend

# 使用uv创建虚拟环境
uv venv --python 3.12

# Windows激活虚拟环境
.venv\Scripts\activate

# Linux/Mac激活虚拟环境
source .venv/bin/activate
```

### 3. 安装依赖

```bash
# 安装项目依赖
uv pip install -e .

# 如需GPU加速文档解析，安装PyTorch（可选）
uv pip install torch torchvision --torch-backend=auto
```

### 4. 配置环境变量

```bash
# 复制环境变量示例文件
cp .env.example .env

# 编辑.env文件，配置以下关键参数
```

**必须配置的环境变量：**

```env
# 签名校验配置
STATIC_KEY=your-static-key-here
SIGN_TIMEOUT_MINUTES=5

# JWT身份认证
JWT_SECRET_KEY=your-jwt-secret-key-very-long-random-string
ACCESS_TOKEN_EXPIRE_MINUTES=120

# 大模型API配置（以豆包为例）
LLM_PROVIDER=doubao
DOUBAO_API_KEY=your-doubao-api-key
DOUBAO_ENDPOINT_ID=your-doubao-endpoint-id

# TTS语音合成配置（以火山引擎为例）
TTS_PROVIDER=volcengine
VOLCENGINE_TTS_APP_ID=your-app-id
VOLCENGINE_TTS_ACCESS_TOKEN=your-access-token
VOLCENGINE_TTS_SECRET_KEY=your-secret-key
```

### 5. 初始化数据库

```bash
# 系统会自动创建SQLite数据库和初始表结构
# 如需创建测试用户，运行
uv run python app/scripts/init_users.py
```

### 6. 启动后端服务

```bash
# 开发模式启动
uv run python run.py

# 或使用uvicorn直接启动
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**启动成功后访问：**
- API文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

---

## 🎨 前端部署

### 1. 进入前端目录

```bash
cd frontend
```

### 2. 安装依赖

```bash
# 使用npm安装依赖
npm install

# 如遇依赖冲突，可尝试
rm -rf node_modules package-lock.json
npm install
```

### 3. 配置环境变量

```bash
# 复制环境变量示例文件
cp .env.example .env

# 编辑.env文件，配置后端API地址
```

**.env配置示例：**

```env
VITE_API_BASE_URL=http://localhost:8000
```

### 4. 启动前端服务

```bash
# 开发模式启动
npm run dev

# 构建生产版本
npm run build

# 预览生产构建
npm run preview
```

**启动成功后访问：**
- 前端地址：http://localhost:5173（具体端口以终端输出为准）

---

## 🐳 Docker部署（推荐生产环境）

### 1. 安装Docker和Docker Compose

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install docker.io docker-compose-plugin

# CentOS/RHEL
sudo yum install docker docker-compose-plugin
```

### 2. 创建Docker Compose配置

创建 `docker-compose.yml` 文件：

```yaml
version: '3.8'

services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - STATIC_KEY=${STATIC_KEY}
      - JWT_SECRET_KEY=${JWT_SECRET_KEY}
      - DOUBAO_API_KEY=${DOUBAO_API_KEY}
      - DOUBAO_ENDPOINT_ID=${DOUBAO_ENDPOINT_ID}
    volumes:
      - ./backend/data:/app/data
    restart: unless-stopped

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "80:80"
    depends_on:
      - backend
    restart: unless-stopped
```

### 3. 构建并启动

```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

---

## 🔧 常见问题排查

### 后端问题

| 问题 | 解决方案 |
|------|----------|
| `ModuleNotFoundError` | 确认虚拟环境已激活，重新运行 `uv pip install -e .` |
| 数据库连接失败 | 检查数据库文件权限，确保目录可写 |
| API调用超时 | 检查大模型API密钥配置，确认网络连接 |
| TTS语音无法播放 | 检查火山引擎TTS配置，确认音色ID正确 |

### 前端问题

| 问题 | 解决方案 |
|------|----------|
| `npm install` 失败 | 清除缓存 `npm cache clean --force`，重新安装 |
| 页面空白 | 检查浏览器控制台报错，确认后端服务正常运行 |
| 跨域错误 | 确认后端CORS配置正确，检查 `.env` 中的API地址 |
| 热更新失效 | 重启前端服务，或检查vite配置 |

### 文档解析问题

| 问题 | 解决方案 |
|------|----------|
| PDF解析失败 | 安装 `docling` 依赖，下载所需模型 |
| 中文乱码 | 确保系统支持UTF-8编码 |
| 公式识别失败 | 检查OCR API配置，或启用公式占位符模式 |

---

## 🌐 生产环境部署建议

### 1. 使用Nginx反向代理

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 前端静态资源
    location / {
        root /path/to/frontend/dist;
        try_files $uri $uri/ /index.html;
    }

    # 后端API代理
    location /api/ {
        proxy_pass http://localhost:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 2. 使用Gunicorn运行后端

```bash
# 安装gunicorn
uv pip install gunicorn

# 启动生产服务
uv run gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### 3. 启用HTTPS

建议使用Let's Encrypt免费证书：

```bash
# 安装certbot
sudo apt install certbot python3-certbot-nginx

# 申请证书
sudo certbot --nginx -d your-domain.com
```

---

## 📞 技术支持

- **项目文档**：详见 `docs/` 目录
- **API文档**：启动后端后访问 `/docs`
- **问题反馈**：请在Gitee仓库提交Issue

---

## ✅ 部署检查清单

- [ ] Python 3.12+ 已安装
- [ ] Node.js 20.x+ 已安装
- [ ] uv 包管理器已安装
- [ ] 后端依赖安装完成
- [ ] 前端依赖安装完成
- [ ] `.env` 文件已配置
- [ ] 大模型API密钥已配置
- [ ] TTS语音合成已配置
- [ ] 后端服务启动成功
- [ ] 前端服务启动成功
- [ ] 数据库初始化完成
- [ ] 测试用户已创建
- [ ] API文档可正常访问
- [ ] 前端页面可正常访问

---

**部署完成！** 现在您可以访问系统开始使用AI互动智课功能了。
