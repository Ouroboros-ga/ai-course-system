# Smartrab 课堂 - 泛雅 AI 智课系统前端

基于泛雅教学平台的 AI 互动智课生成与实时问答系统，为教师备课与学生学习提供轻量化、高效率的智慧教学解决方案。

## 项目简介

本项目依托泛雅教学平台，结合 AI 大模型与 RAG 检索技术，实现智能课件生成、课堂互动、7×24 小时实时答疑。前端采用 Vue 3 + Vue Router + Pinia 构建，提供流畅的用户体验和响应式设计。

## 核心功能

- AI 课件生成 - 自动结构化排版，快速生成教学课件
- 实时智能答疑 - 基于知识库精准回答，无幻觉、更可靠
- 学习进度跟踪 - 记录学习轨迹，支持多端续学
- 极简清爽界面 - 统一设计语言，流畅舒适的使用体验
- 用户认证系统 - 完整的登录注册、个人信息管理功能

## 技术栈

- Vue 3 - 渐进式 JavaScript 框架
- Vue Router - 官方路由管理器
- Pinia - Vue 状态管理库
- Axios - HTTP 客户端
- Typed.js - 打字机效果动画

## 项目结构

```
src/
├── api/                    # API 接口
│   ├── chat.js            # 聊天相关接口
│   ├── user.js            # 用户相关接口
│   └── index.js          # 接口统一导出
├── assets/                # 静态资源
│   └── home/             # 首页图片资源
├── components/            # 组件目录（三层结构）
│   ├── about/            # 关于页面组件
│   │   ├── features/    # 核心功能
│   │   ├── footer/      # 页脚
│   │   ├── hero/        # 首屏
│   │   ├── intro/       # 项目介绍
│   │   └── techstack/   # 技术栈
│   ├── chat/            # 聊天页面组件
│   │   ├── layout/      # 布局组件
│   │   ├── panel/       # 聊天面板
│   │   ├── player/      # PPT 播放器
│   │   ├── history/     # 历史记录
│   │   ├── topnav/      # 顶部导航
│   │   ├── sidebar/     # 侧边栏
│   │   └── wait/        # 等待页面组件
│   ├── home/            # 首页组件
│   │   ├── sections/    # 页面区块
│   │   └── ui/          # UI 组件
│   ├── profile/         # 个人中心组件
│   │   ├── LoginIn/     # 登录相关组件
│   │   └── UserIndex.vue
│   ├── GradientBackground.vue  # 渐变背景
│   └── NavigationBar.vue       # 导航栏
├── data/                 # 数据文件
│   └── mindMapData.js   # 思维导图数据
├── router/               # 路由配置
│   └── index.js         # 路由定义
├── stores/               # 状态管理
│   └── counter.js       # Pinia Store
├── utils/                # 工具函数
│   ├── request.js       # Axios 封装
│   ├── toast.js         # Toast 提示
│   └── getCookies.js   # Cookie 工具
├── views/                # 页面视图
│   ├── Home.vue         # 首页
│   ├── Chat.vue         # 聊天页面
│   ├── About.vue        # 关于页面
│   └── Profile.vue      # 个人中心
├── App.vue              # 根组件
├── main.js              # 入口文件
└── .env                 # 环境变量
```

## 快速开始

### 环境要求

- Node.js >= 16.0.0
- npm >= 8.0.0 或 pnpm >= 7.0.0

### 安装依赖

```bash
npm install
```

### 配置环境变量

在项目根目录创建 `.env` 文件，配置后端 API 地址：

```env
VITE_APP_BASE_API=http://localhost:8000/api
```

### 启动开发服务器

```bash
npm run dev
```

访问 http://localhost:5173 查看项目

### 构建生产版本

```bash
npm run build
```

## 页面路由

| 路径 | 页面 | 说明 |
|------|------|------|
| `/` | 首页 | 产品展示和功能介绍 |
| `/chat` | 聊天 | PPT 上传和 AI 答疑 |
| `/about` | 关于 | 项目介绍和技术栈 |
| `/profile` | 个人中心 | 用户信息和设置 |

## 核心功能说明

### PPT 上传与解析

1. 用户上传 PPT/PDF 文件
2. 后端自动解析内容并生成结构化数据
3. 前端展示解析结果，支持翻页查看

### AI 智能答疑

1. 用户在聊天框输入问题
2. 基于上传的课件内容进行智能问答
3. 支持历史对话记录查看

### 用户认证

- 用户注册：用户名（1-80位英文字母）+ 密码（6-18位字母数字）
- 用户登录：基于 Token 的身份验证
- 个人信息管理：修改用户名、密码等

### 响应式设计

- 桌面端：左右分栏布局，PPT 和聊天并排显示
- 移动端：Tab 切换布局，支持 PPT 和聊天切换

## API 接口

### 用户接口

- `POST /api/v1/user/login` - 用户登录
- `POST /api/v1/user/register` - 用户注册
- `GET /api/v1/user/info` - 获取用户信息
- `POST /api/v1/user/logout` - 退出登录
- `PUT /api/v1/user/update` - 更新用户信息

### 聊天接口

- `POST /api/v1/chat/history` - 获取历史对话
- `POST /api/v1/document/upload` - 上传文件

## 请求签名

所有 API 请求都包含签名验证，确保请求安全性：

- 时间戳：`time` 参数
- 签名：`enc` 参数（MD5 加密）
- 静态密钥：`dev-static-key-change-in-prod`

## 状态管理

使用 Pinia 进行状态管理，主要 Store：

- `counter` - 全局状态
  - `messages` - 聊天消息列表
  - `userData` - 用户信息

## 组件规范

组件采用三层目录结构，便于维护和扩展：

```
功能模块/
├── 子功能1/
│   └── 组件.vue
├── 子功能2/
│   └── 组件.vue
└── 主组件.vue
```

## 样式规范

- 使用 CSS Scoped 避免样式污染
- 统一使用 Flexbox 和 Grid 布局
- 响应式断点：768px（移动端）
- 滚动条美化：自定义滚动条样式

## 浏览器支持

- Chrome >= 90
- Firefox >= 88
- Safari >= 14
- Edge >= 90

## 开发建议

1. 组件开发遵循单一职责原则
2. 使用 Composition API 编写组件
3. 合理使用 Pinia 进行状态管理
4. 注意组件复用和抽象
5. 保持代码风格统一

## 常见问题

### Q: 如何修改后端 API 地址？

A: 修改 `.env` 文件中的 `VITE_APP_BASE_API` 变量。

### Q: 如何添加新的页面？

A: 在 `views/` 目录创建页面组件，然后在 `router/index.js` 中添加路由配置。

### Q: 如何添加新的 API 接口？

A: 在 `api/` 目录对应的模块中添加接口函数，然后在组件中导入使用。

## 许可证

© 2026 泛雅 AI 智课系统 · 服创设计项目

## 联系方式

如有问题或建议，请联系项目维护者。
