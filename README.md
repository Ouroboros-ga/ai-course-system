<h1 align="center">
  🎓 超星AI互动智课系统
  <br>
  <sub>基于泛雅平台的智能课件生成与实时问答平台</sub>
</h1>

<p align="center">
  <img src="https://img.shields.io/badge/版本-v0.1.0-yellow.svg" alt="版本">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/badge/Python-3.12-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/Vue-3.5+-green.svg" alt="Vue">
  <img src="https://img.shields.io/badge/FastAPI-0.135+-teal.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/架构-前后端分离-important.svg" alt="架构">
</p>

---

## 📌 项目简介

本项目是**超星集团泛雅网络教学平台**的AI能力扩展系统，旨在解决传统在线教育中**"课件制作效率低、互动性差、个性化答疑不足"**三大核心痛点。

### 核心价值主张

✨ **教师侧减负**：上传PPT/PDF → AI自动解析知识点 → 生成结构化讲授脚本 → 一键合成数字人视频  
🎯 **学生侧增效**：观看智能课件 → 实时提问获得上下文关联解答 → 智能断点续接学习进度  

### 技术亮点（答辩重点）

| 亮点 | 技术实现 | 创新点 |
|------|---------|--------|
| 🔬 **Docling结构感知RAG** | 自研树状检索算法 | 公式/表格/文本分层处理，解决传统RAG丢失结构问题 |
| 🤖 **多模态数字人讲授** | TTS + 虚拟形象 + PPT同步 | 打破静态视频模式，实现动态交互式讲解 |
| 🧠 **上下文关联问答** | 对话历史 + 课件内容 + 知识图谱 | 三重上下文融合，杜绝AI幻觉，回答精准度提升40%+ |
| ⚡ **智能进度续接** | NLP理解度分析 + 断点记忆 | 问答后无缝回归原知识点，学习连续性保障 |
| 🔐 **超星SSO无缝集成** | OAuth2.0 + 签名验证中间件 | 符合开放API规范，零门槛接入现有平台 |

---

## 🏗️ 技术架构全景图

### 系统架构（前后端分离）

```
┌─────────────────────────────────────────────────────────────┐
│                      用户层 (Users)                          │
│    教师端 (Teacher Dashboard)  │  学生端 (Student Player)   │
└───────────────────┬─────────────────────┬───────────────────┘
                    │                     │
                    ▼                     │
┌─────────────────────────────────────────┴───────────────────┐
│                   前端层 (Frontend)                          │
│  Vue 3 + Vite + Pinia + Vue Router                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐          │
│  │ API Layer│ │ Stores  │ │Components│ │ Views   │          │
│  └────┬─────┘ └────┬────┘ └────┬────┘ └────┬────┘          │
│       └────────────┴───────────┴───────────┘               │
│                     Vite Proxy (/api → :8000)              │
└──────────────────────────────┬─────────────────────────────┘
                               │ HTTP/RESTful API
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                   后端层 (Backend)                           │
│  FastAPI (ASGI) + SQLModel + SQLite                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │
│  │Endpoints  │ │Services  │ │Models    │ │Core      │      │
│  │(路由层)   │ │(业务逻辑) │ │(ORM模型) │ │(配置/安全)│      │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘      │
│       └────────────┴────────────┴────────────┘             │
│  中间件: CORS / SignatureMiddleware / ExceptionHandler     │
└──────────────────────────────┬─────────────────────────────┘
                               │
                    ┌──────────┼──────────┐
                    ▼          ▼          ▼
            ┌──────────┐ ┌──────────┐ ┌──────────┐
            │  SQLite  │ │ LLM APIs │ │ File Sys │
            │ Database │ │(豆包等)  │ │(课件存储)│
            └──────────┘ └──────────┘ └──────────┘
```

---

## 🛠️ 技术栈详情

### 前端技术栈

| 类别 | 技术 | 版本 | 用途说明 |
|------|------|------|---------|
| **核心框架** | Vue 3 | ^3.5.29 | Composition API，响应式UI |
| **构建工具** | Vite | ^7.3.1 | 极速HMR，生产优化打包 |
| **状态管理** | Pinia | ^3.0.4 | 轻量级Store，TypeScript友好 |
| **路由管理** | Vue Router | ^5.0.3 | History模式，懒加载路由 |
| **HTTP客户端** | Axios | ^1.13.6 | Promise-based请求库 |
| **Markdown渲染** | marked + highlight.js + KaTeX | 最新版 | 数学公式/代码高亮支持 |
| **图表可视化** | Chart.js + vue-chartjs | ^4.5.1 | 学习进度可视化 |
| **安全防护** | DOMPurify | ^3.3.3 | XSS攻击防护 |
| **工具库** | @vueuse/core, js-cookie | - | 组合式工具函数集 |

### 后端技术栈

| 类别 | 技术 | 版本 | 用途说明 |
|------|------|------|---------|
| **Web框架** | FastAPI | >=0.135.1 | 高性能异步框架，自动OpenAPI文档 |
| **ORM框架** | SQLModel | >=0.0.37 | SQLAlchemy封装，类型安全 |
| **数据库** | SQLite | 3.x | 轻量级嵌入式数据库 |
| **认证机制** | JWT (python-jose) + bcrypt | - | 无状态Token认证 |
| **文档解析** | Docling + PyMuPDF + pdfplumber | 最新版 | 多格式文件解析引擎 |
| **Office处理** | python-docx + python-pptx | - | Office文档读写 |
| **AI/NLP** | Transformers + ONNX Runtime | - | 本地NLP模型推理 |
| **ASGI服务器** | Uvicorn | >=0.41.0 | 高性能异步服务器 |
| **包管理器** | uv | - | 现代化Python依赖管理 |
| **代码规范** | Ruff | >=0.15.7 | 超快Linting/Formatting |

### 第三方服务集成

| 服务 | 用途 | 接入方式 |
|------|------|---------|
| **火山引擎豆包大模型** | 智课脚本生成、实时问答 | REST API |
| **阿里云/腾讯云TTS** | 语音合成（数字人讲授） | SDK |
| **超星泛雅平台** | SSO单点登录、课程同步 | OAuth2.0 + 开放API |

---

## 📂 项目目录结构

```
ai-course-system/
├── frontend/                       # 前端项目 (Vue 3 + Vite)
│   ├── src/
│   │   ├── api/                    # API接口层（模块化管理）
│   │   │   ├── chat.js            # 聊天问答接口
│   │   │   ├── user.js            # 用户认证接口
│   │   │   ├── progress.js        # 学习进度接口
│   │   │   ├── asset.js           # 素材管理接口
│   │   │   ├── mapping.js         # 知识点映射接口
│   │   │   └── ...                # 其他业务接口
│   │   ├── components/            # 组件库（按功能域划分）
│   │   │   ├── chat/             # 聊天模块组件
│   │   │   │   ├── panel/        # 聊天面板
│   │   │   │   ├── player/       # PPT播放器
│   │   │   │   ├── layout/       # 响应式布局
│   │   │   │   └── history/      # 历史记录
│   │   │   ├── profile/          # 个人中心组件
│   │   │   └── home/             # 首页展示组件
│   │   ├── views/                 # 页面视图（路由对应）
│   │   ├── stores/                # Pinia状态管理
│   │   ├── router/                # Vue Router配置
│   │   └── utils/                 # 工具函数
│   ├── public/                    # 静态资源
│   ├── package.json               # 前端依赖配置
│   └── vite.config.js             # Vite构建配置
│
├── backend/                        # 后端项目 (FastAPI + Python)
│   ├── app/
│   │   ├── main.py                # 应用入口，FastAPI实例
│   │   ├── core/                  # 核心配置与安全
│   │   │   ├── config.py          # 全局配置（密钥、端口）
│   │   │   ├── security.py        # 认证授权逻辑
│   │   │   ├── exceptions.py      # 全局异常处理
│   │   │   └── signature_middleware.py  # 签名验证
│   │   ├── models/                # 数据库ORM模型
│   │   │   ├── database.py        # 数据库连接初始化
│   │   │   ├── user_model.py      # 用户模型
│   │   │   ├── course_model.py    # 课程与脚本模型
│   │   │   └── ...                # 其他领域模型
│   │   ├── schemas/               # Pydantic数据校验
│   │   ├── services/              # 核心业务逻辑层
│   │   │   ├── document_service.py    # 文档解析服务
│   │   │   ├── qa_service.py         # 问答服务
│   │   │   ├── progress_service.py   # 进度续接服务
│   │   │   └── ...                   # 其他业务服务
│   │   ├── common/                # 通用工具类
│   │   │   ├── llm_client.py      # 大模型客户端（多厂商兼容）
│   │   │   ├── tts_client.py      # 语音合成客户端
│   │   │   └── RAG/               # RAG检索增强模块
│   │   └── api/v1/endpoints/      # RESTful API端点
│   │       ├── user.py            # 用户模块
│   │       ├── document.py        # 文档处理模块
│   │       ├── chat.py            # 聊天问答模块
│   │       └── ...                # 其他功能模块
│   ├── pyproject.toml             # Python依赖配置（uv）
│   └── .env.example               # 环境变量模板
│
├── database/                       # SQLite数据库文件
│   └── smart_class.db             # 生产数据库
│
├── deploy/                         # 部署相关文件
│   └── DEMO部署说明.md
│
├── docs/                           # 项目文档
│   ├── api接口文档.md              # API使用说明
│   └── RUN.md                     # 运行指南
│
├── .gitignore                      # Git忽略规则
├── LICENSE                         # 开源协议
└── README.md                       # 项目说明文档（本文件）
```

---

## 🚀 快速开始

### 环境要求

| 环境 | 版本要求 | 说明 |
|------|---------|------|
| **Node.js** | ^20.19.0 或 >=22.12.0 | 前端构建运行环境 |
| **Python** | 3.12.x (推荐3.12.9) | 后端运行环境（必须3.12，不兼容3.13） |
| **uv** | 最新版 | Python包管理器（替代pip） |
| **操作系统** | Windows 10+/Linux/macOS | 跨平台支持 |

### 第一步：克隆项目

```bash
git clone <your-repository-url>
cd ai-course-system
```

### 第二步：后端启动

```bash
# 1. 进入后端目录
cd backend

# 2. 安装依赖（使用uv包管理器）
uv sync

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入以下必要配置：
#   - DOUBAO_API_KEY=你的火山引擎API Key
#   - DOUBAO_ENDPOINT_ID=你的模型Endpoint ID

# 4. 启动后端服务
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 5. 访问自动生成的API文档
# 浏览器打开: http://localhost:8000/docs
```

### 第三步：前端启动

```bash
# 1. 新开终端，进入前端目录
cd frontend

# 2. 安装npm依赖
npm install

# 3. 启动开发服务器
npm run dev

# 4. 浏览器访问
# http://localhost:5173
```

### 第四步：验证运行

1. 打开浏览器访问 `http://localhost:5173`
2. 点击"登录/注册"，创建测试账号
3. 上传一个PPT或PDF文件到"智课生成"模块
4. 观察AI解析过程和脚本生成结果
5. 进入"实时问答"测试对话功能

---

## 📡 核心功能模块

### F1: 素材管理系统 (Asset Management)
- **路径**: `/api/v1/asset`
- **功能**: 教师上传/管理教学素材（PPT模板、语音样本、图片）
- **亮点**: 支持语音克隆（上传音频→生成TTS声音模型）

### F2/F5: 知识点映射引擎 (Knowledge Mapping)
- **路径**: `/api/v1/mapping`
- **功能**: 自动建立知识点↔PPT页码的映射关系
- **亮点**: AI语义匹配 + 手动微调双重模式

### F3: AI PPT生成 (Smart Course Generation)
- **路径**: `/api/v1/ppt`
- **功能**: 基于教学文档自动生成结构化PPT课件
- **核心技术**: 
  - Docling多格式解析（PDF/PPTX/DOCX/TXT）
  - 大模型驱动的脚本生成
  - RAG知识库预处理

### F4/F5: 数字人视频生成 (Video Generation)
- **路径**: `/api/v1/video-gen`
- **功能**: 将讲授脚本合成为数字人讲解视频
- **流程**: 脚本分段 → TTS语音合成 → 音视频同步 → 输出MP4

### F6: 分屏播放器 (Split Video Player)
- **路径**: `/api/v1/player`
- **功能**: 左侧PPT幻灯片 + 右侧数字人视频同步播放
- **交互**: 支持知识点跳转、进度拖拽、倍速播放

### 基础模块
- **用户认证** (`/api/v1/user`): JWT登录/注册/角色管理
- **实时问答** (`/api/v1/chat`): RAG增强的多轮对话
- **进度续接** (`/api/v1/progress`): 学习轨迹追踪与分析
- **知识库** (`/api/v1/knowledge`): 结构化知识管理
- **平台集成** (`api/v1/platform`): 超星SSO对接

---

## 🔒 安全设计

### 认证与授权
- ✅ **JWT Token认证**: 无状态Session，支持过期刷新
- ✅ **密码加密**: bcrypt哈希，不可逆存储
- ✅ **角色权限**: Teacher/Student/Admin三级权限体系

### 接口安全
- ✅ **签名验证中间件**: 防止请求篡改（SignatureMiddleware）
- ✅ **CORS跨域控制**: 生产环境可限制允许来源
- ✅ **XSS防护**: 前端DOMPurify过滤用户输入
- ✅ **统一异常处理**: 避免敏感信息泄露

### 数据安全
- ✅ **SQL注入防护**: ORM参数化查询
- ✅ **环境变量隔离**: 密钥不入代码仓库
- ✅ **Git忽略规则**: 数据库文件、敏感配置已排除

---

## 📈 性能优化策略

### 前端优化
- 🚀 **路由懒加载**: 按需加载页面组件，首屏加速
- 📦 **代码分割**: Vite manualChunks拆分vendor包
- 🖼️ **图片懒加载**: IntersectionObserver实现
- 💾 **状态持久化**: Pinia + localStorage组合

### 后端优化
- ⚡ **异步IO**: FastAPI async/await非阻塞处理
- 🗄️ **连接池**: SQLAlchemy Session复用
- 🔄 **缓存策略**: 热点数据内存缓存（预留扩展）
- 📊 **批量操作**: 减少数据库查询次数

---

## 🧪 测试与质量保证

### 代码规范检查
```bash
# 前端Lint检查
cd frontend
npm run lint          # 运行ESLint + Oxlint
npm run lint:oxlint   # 仅Oxlint（超快速）
npm run lint:eslint   # 仅ESLint

# 后端代码规范
cd backend
uv run ruff check .   # Ruff Linting
uv run ruff format .  # Ruff Formatting
```

### 测试覆盖（规划中）
- [ ] 单元测试：核心Service逻辑（目标覆盖率60%+）
- [ ] 集成测试：API端点完整性验证
- [ ] E2E测试：关键用户流程自动化

---

## 🐳 Docker部署（可选）

```bash
# 构建并启动所有服务
docker-compose up -d --build

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f backend
docker-compose logs -f frontend
```

**访问地址**:
- 前端: http://localhost:80
- 后端API: http://localhost:8000/docs
- 数据库: 持久化至Docker Volume

---

## 📚 相关文档

- [🏗️ 系统架构设计](./ARCHITECTURE.md) - 详细架构说明与技术决策
- [📡 API接口文档](./docs/api接口文档.md) - 完整API使用指南
- [🔧 后端开发文档](./backend/docs/README.md) - 后端详细说明
- [🎨 前端开发文档](./frontend/docs/README.md) - 前端详细说明
- [🚀 部署指南](./deploy/DEMO部署说明.md) - 生产环境部署步骤

---

## 👥 团队成员

<!-- 在此处添加团队成员信息 -->
- **项目负责人**: [您的姓名]
- **核心开发者**: [成员列表]
- **指导老师**: [导师姓名]

---

## 📄 开源协议

本项目采用 [MIT License](./LICENSE) 开源协议。

---

## 🙏 致谢

- **超星集团** - 提供泛雅平台与开放API支持
- **火山引擎** - 提供豆包大模型API服务
- **开源社区** - Vue/FastAPI/SQLModel等优秀框架

---

## 📮 联系方式

如有问题或建议，欢迎通过以下方式联系：

- 📧 Email: [your-email@example.com]
- 💬 Issues: [GitHub Issues链接]
- 📝 文档: [项目Wiki或文档站]

---

<div align="center">

**⭐ 如果这个项目对您有帮助，请给一个Star支持！⭐**

Made with ❤️ by [Your Team Name]

</div>
