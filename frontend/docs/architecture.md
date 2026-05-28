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
   - **环境感知baseURL**: 开发环境使用相对路径 `/api/v1`（走Vite代理），生产环境使用完整后端URL
   - **Blob响应错误处理**: 当blob响应实际为JSON错误信息时，自动解析并提示
5. **代码规范**: 使用ESLint和OXLint确保代码质量
6. **响应式设计**: 适配不同屏幕尺寸的设备
7. **Vite开发代理**: 开发环境下将 `/api` 请求代理到后端 `http://localhost:8000`，解决跨域和媒体资源加载问题

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

## 8. 学生端音频自动播放机制

### 8.1 功能概述

在学生学习界面（`/student`），当用户点击课程结构中的节点时，对应节点的音频会自动开始播放，无需手动点击播放按钮。

### 8.2 实现架构

```
用户点击课程结构节点
       │
       ▼
StudentDashboard.jumpToNode(index)
       │
       ├── 更新 currentNodeIndex
       ├── 调用 updateCurrentNodeMedia()
       │       │
       │       ▼
       │   更新 currentNodeAudioUrl（触发 PptSlidePlayer 的 audioUrl watcher）
       │
       ▼
PptSlidePlayer audioUrl watcher 检测到 URL 变化
       │
       ├── 暂停当前音频、重置状态
       ├── 调用 audioRef.load() 加载新音频
       │
       ├── if (autoPlay && newUrl)
       │       │
       │       ▼
       │   tryAutoPlay()
       │       │
       │       ├── readyState >= 3 → 立即播放
       │       └── readyState < 3  → 监听 canplaythrough 事件后播放
       │
       ▼
audioRef.play()
       │
       ├── 成功 → isPlaying = true
       └── 失败（浏览器策略限制）→ emit('auto-play-blocked')
```

### 8.3 关键组件接口

#### PptSlidePlayer Props

| Prop | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `autoPlay` | Boolean | `false` | 当 audioUrl 变化时是否自动播放音频 |
| `audioUrl` | String | `''` | 音频资源URL |
| `audioDuration` | Number | `0` | 音频时长（秒） |

#### PptSlidePlayer Events

| Event | 参数 | 说明 |
|-------|------|------|
| `auto-play-blocked` | 无 | 浏览器自动播放策略阻止了音频播放 |
| `audio-ended` | 无 | 音频播放结束 |

#### PptSlidePlayer Exposed Methods

| 方法 | 说明 |
|------|------|
| `playAudio()` | 手动触发音频播放（供父组件通过 ref 调用） |

### 8.4 浏览器自动播放策略处理

现代浏览器对自动播放有严格限制，本实现采用以下策略：

1. **用户交互触发**：点击课程结构节点属于用户交互行为，浏览器通常允许在交互回调中播放音频
2. **Promise 捕获**：`play()` 返回的 Promise 如果被拒绝，会触发 `auto-play-blocked` 事件
3. **友好提示**：父组件监听 `auto-play-blocked` 事件，通过 Toast 提示用户手动点击播放按钮
4. **事件监听器清理**：使用 `pendingCanPlayHandler` 变量跟踪待处理的 `canplaythrough` 监听器，防止快速切换节点时监听器累积

## 9. 选择题互动问答机制

### 9.1 功能概述

在学生学习界面（`/student`），每个知识点讲解完毕后，系统自动生成一道单项选择题，学生通过点击选项作答，系统即时反馈对错并展示解析。

### 9.2 数据流

```
节点讲解完成 → generateQAForNode()
       │
       ▼
POST /chat/quiz { courseId, nodeId, nodeTitle }
       │
       ▼
后端 QAService.generate_quiz()
  ├── QUIZ_SYSTEM_PROMPT（选择题专用prompt）
  ├── build_quiz_prompt()（构建用户提示词）
  └── LLM 生成 JSON 格式选择题
       │
       ▼
前端渲染选择题卡片
  ├── 题目 + 4个选项按钮
  ├── 学生点击选项
  │       │
  │       ▼
  │   selectQuizOption()
  │   ├── 标记选中项 + 揭示答案
  │   ├── 正确：绿色高亮正确选项
  │   ├── 错误：红色高亮选中项 + 绿色高亮正确选项
  │   ├── 显示解析
  │   └── 更新理解度分析
  └── 降级处理：选择题生成失败时回退为自由问答
```

### 9.3 选择题消息数据结构

```javascript
{
  id: Date.now(),
  role: 'ai',
  content: '### ❓ 互动问答',
  quiz: {
    question: '题目内容',
    options: { A: '选项A', B: '选项B', C: '选项C', D: '选项D' },
    correct_answer: 'B',
    explanation: '解析内容'
  },
  selectedAnswer: null,      // 学生选中的选项 key
  answerRevealed: false,     // 是否已揭示答案
  isQA: true,
  nodeIndex: 0
}
```

### 9.4 后端接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/chat/quiz` | POST | 根据节点内容生成选择题 |

请求参数：`courseId`（可选）、`nodeId`（可选）、`nodeContent`（可选）、`nodeTitle`（可选）

### 9.5 理解度评估策略

选择题的回答结果直接映射为理解度评估：

| 回答结果 | 理解等级 | 分数 | 说明 |
|---------|---------|------|------|
| 正确 | high | 0.9 | 掌握良好 |
| 错误 | low | 0.3 | 需要加强，解析作为建议展示 |
