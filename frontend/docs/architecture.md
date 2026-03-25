# 前端项目架构说明

## 1. 项目概述

Smartrab AI课程系统前端项目采用现代化的Vue 3技术栈，基于Vite构建工具，实现了一个功能完整的AI辅助学习平台。项目架构清晰，代码组织规范，便于后续开发和维护。

## 2. 技术栈

- **框架**: Vue 3 (Composition API)
- **构建工具**: Vite 7.x
- **状态管理**: Pinia 3.x
- **路由**: Vue Router 5.x
- **HTTP客户端**: Axios
- **工具库**: 
  - @vueuse/core (Vue组合式API工具集)
  - js-cookie (Cookie管理)
  - typed.js (打字动画效果)
  - vue-particles (粒子动画背景)
- **代码规范**: ESLint + OXLint

## 3. 项目目录结构

```
frontend/
├── public/              # 静态资源目录
│   └── favicon.ico
├── src/                 # 源代码目录
│   ├── api/             # API接口定义
│   │   ├── chat.js      # 聊天相关API
│   │   ├── index.js     # API入口文件
│   │   └── user.js      # 用户相关API
│   ├── assets/          # 静态资源文件
│   │   ├── home/        # 首页相关资源
│   │   └── Avatar.svg   # 用户头像图标
│   ├── components/      # Vue组件
│   │   ├── chat/        # 聊天功能组件
│   │   ├── home/        # 首页组件
│   │   ├── profile/     # 用户中心组件
│   │   ├── GradientBackground.vue  # 渐变背景组件
│   │   └── NavigationBar.vue        # 导航栏组件
│   ├── router/          # 路由配置
│   │   └── index.js     # 路由入口文件
│   ├── stores/          # Pinia状态管理
│   │   └── counter.js   # 计数器状态管理
│   ├── utils/           # 工具函数
│   │   ├── getCookies.js  # Cookie获取工具
│   │   ├── request.js     # HTTP请求封装
│   │   └── toast.js       # 消息提示工具
│   ├── views/           # 页面视图
│   │   ├── About.vue    # 关于页面
│   │   ├── Chat.vue     # 聊天页面
│   │   ├── Home.vue     # 首页
│   │   └── Profile.vue  # 用户中心页面
│   ├── App.vue          # 根组件
│   └── main.js          # 应用入口文件
├── .editorconfig        # 编辑器配置
├── .gitattributes       # Git属性配置
├── .gitignore           # Git忽略文件
├── .oxlintrc.json       # OXLint配置
├── eslint.config.js     # ESLint配置
├── index.html           # HTML入口文件
├── jsconfig.json        # JavaScript配置
├── package-lock.json    # 依赖版本锁定
├── package.json         # 项目配置和依赖
├── README.md            # 项目说明
└── vite.config.js       # Vite配置文件
```

## 4. 架构设计

### 4.1 核心架构模式

项目采用经典的MVVM架构模式：

- **Model**: API接口层和状态管理
- **View**: Vue组件和页面视图
- **ViewModel**: Composition API和响应式数据

### 4.2 数据流

```
用户操作 → 组件方法 → API调用 → 状态更新 → 视图渲染
```

### 4.3 模块划分

1. **API层**: 封装所有后端接口调用
2. **组件层**: 可复用的UI组件
3. **视图层**: 页面级组件
4. **状态管理层**: 全局状态管理
5. **工具层**: 通用工具函数

## 5. 技术特点

1. **组合式API**: 使用Vue 3的Composition API，提高代码复用性和可维护性
2. **路由懒加载**: 优化页面加载性能
3. **状态管理**: 使用Pinia进行状态管理，支持模块化
4. **请求封装**: 统一的HTTP请求处理，包含签名验证和错误处理
5. **代码规范**: 使用ESLint和OXLint确保代码质量
6. **响应式设计**: 适配不同屏幕尺寸的设备

## 6. 开发流程

1. **环境搭建**: 安装依赖并启动开发服务器
2. **组件开发**: 创建可复用组件
3. **页面开发**: 组合组件创建页面
4. **API集成**: 调用后端接口获取数据
5. **状态管理**: 使用Pinia管理全局状态
6. **测试验证**: 运行构建和测试命令
7. **部署上线**: 构建生产版本并部署

## 7. 扩展建议

1. **国际化支持**: 添加多语言支持
2. **主题系统**: 实现深色模式和主题切换
3. **单元测试**: 添加Vue Test Utils测试
4. **性能监控**: 集成性能监控工具
5. **文档完善**: 使用VuePress生成API文档
