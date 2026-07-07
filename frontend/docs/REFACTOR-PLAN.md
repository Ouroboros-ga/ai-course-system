# Smartrab AI 智课系统 — 前端重构执行方案

> 基于 REDESIGN.md 设计文档 + 全量代码审计 | 版本: 1.0 | 日期: 2026-07-07

---

## 一、审计现状总结

### 已完成（无需改动）

| 模块 | 文件 | 状态 |
|------|------|------|
| 设计令牌 | `styles/tokens.css` | ✅ 完整定义色彩/间距/字体/阴影/动画/z-index |
| 暗色模式 | `styles/dark.css` | ✅ 通过 `[data-theme="dark"]` 覆盖令牌 |
| 全局重置 | `App.vue` | ✅ 使用令牌，含 reduced-motion |
| 导航栏 | `NavigationBar.vue` | ✅ Lucide 图标 + 令牌 + 响应式 + 暗色 |
| 背景层 | `GradientBackground.vue` | ✅ 精简为 2 光球 + 移动端优化 |
| UI 基础组件 | `ui/UiButton.vue` 等 10 个 | ✅ 全部令牌化 |
| 首页结构 | `Home.vue` | ✅ scroll-snap + 组件化分区 |

### 待重构（按严重度排序）

| 问题类别 | 涉及文件数 | 总处数 | 严重度 |
|----------|-----------|--------|--------|
| 旧渐变 `#667eea`/`#764ba2` | 11 | 33 | 最高 |
| 硬编码十六进制颜色 | 16 | 346 | 高 |
| Emoji 图标 | 30 | 150+ | 高 |
| px 值未用令牌 | 60 | 452 | 中 |
| 非标准断点 | 3 | 3 | 低 |

---

## 二、功能模块布置方案

### 2.1 模块划分与优先级

| 模块 | 涉及文件数 | 核心问题 | 优先级 | 实施批次 |
|------|-----------|---------|--------|---------|
| 基础层修补 | 2 | NavigationBar 混用硬编码；GradientBackground 变量对齐 | P0 | Phase 1 |
| Profile/Auth | 12 | 旧渐变（6 文件）+ Ant Design 调色板 + emoji + px | P0 | Phase 2 |
| Chat | 13 | emoji（20+ 处）+ Material Green 硬编码 + px | P0 | Phase 3 |
| Teacher | 6 | 硬编码 + 非标准断点 1200px + emoji | P1 | Phase 4 |
| Student | 12 | emoji（15+ 处）+ 硬编码 markdown 样式 + px | P1 | Phase 5 |
| 公共页面 | 5 | SsoCallback 旧渐变 + Edulib emoji + AdminPanel 硬编码 + FanyaBind 全问题 | P1 | Phase 6 |
| 最终验证 | — | markdown 样式令牌化 + 交付前检查清单 | P2 | Phase 7 |

### 2.2 各模块详细方案

---

#### Phase 1: 基础层修补（2 文件）

**目标**：消除基础组件中残留的硬编码值

| 文件 | 问题 | 修复方案 |
|------|------|---------|
| `NavigationBar.vue` L270 | `linear-gradient(135deg, var(--color-danger), #f87171)` 混用 | 替换为 `var(--gradient-danger)` |
| `GradientBackground.vue` L196-225 | 4 个 variant 的 `--bg-gradient-main` 使用硬编码色值 | 保留变体设计，但将关键色值对齐令牌体系（`--color-info`、`--color-primary` 等） |

**技术选型**：直接 SearchReplace 编辑，不改变组件 API

---

#### Phase 2: Profile/Auth 模块（12 文件）

**页面结构**：
```
/profile → UserIndex（容器）
  ├── Login（未登录时）
  ├── MenuGrid（登录后主菜单）
  │   ├── TeacherAssetManager（教师资产管理）
  │   ├── TeacherAvatarSetting（教师形象设置）
  │   ├── MyCourses（我的课程）
  │   ├── PreferenceSettings（偏好设置）
  │   └── UserInfoCard（用户信息）
  ├── MappingEditor（课程映射编辑）
  ├── PPTGenerationDialog（PPT生成对话框）
  ├── UserCard（用户卡片）
  ├── StatsCard（统计卡片）
  └── UsersData（用户数据）
```

**问题与修复**：

| 文件 | 核心问题 | 修复方案 |
|------|---------|---------|
| `TeacherAvatarSetting.vue` | 6 处 `#667eea` 旧主色 | → `var(--color-primary)` |
| `TeacherAssetManager.vue` | 6 处 `#667eea` 旧主色 | → `var(--color-primary)` |
| `PPTGenerationDialog.vue` | 40 处 Ant Design 蓝 `#1890ff` | → `var(--color-primary)` 系列 |
| `MappingEditor.vue` | 48 处 Tailwind 裸色值 | → 对应 `var(--color-*)` 令牌 |
| `UserInfoCard.vue` | 2 处旧渐变 | → `var(--gradient-primary)` |
| `UserCard.vue` | 1 处旧渐变 | → `var(--gradient-primary)` |
| `StatsCard.vue` | 1 处 `#667eea` | → `var(--color-primary)` |
| `MenuGrid.vue` | 1 处 `#667eea` + 4 处 emoji | → 令牌 + Lucide 图标 |
| `PreferenceSettings.vue` | 5 处 emoji | → Lucide 图标 |
| `MyCourses.vue` | 1 处 emoji | → Lucide 图标 |
| `UserIndex.vue` | 随机数统计数据 | 保留逻辑，样式令牌化 |
| `Login.vue` | 检查是否已令牌化 | 按需修复 |

**交互逻辑设计**：
- 表单输入：`border-color: var(--color-primary)` 聚焦 + ring 效果
- 错误提示：`var(--color-danger)` 行内文字
- 提交按钮：loading 时禁用 + UiSpinner
- 模态框：`rgba(0,0,0,0.4)` 遮罩 + ESC 关闭

**Emoji → Lucide 映射**：
| Emoji | Lucide | 用途 |
|-------|--------|------|
| ⚙️ | `Settings` | 设置 |
| 🎨 | `Palette` | 主题 |
| 📚 | `BookOpen` | 课程 |
| 🚪 | `LogOut` | 退出 |
| ← | `ArrowLeft` | 返回 |
| 🤖 | `Bot` | AI |
| 🔔 | `Bell` | 通知 |
| 📅 | `Calendar` | 日程 |
| ✕ | `X` | 关闭 |
| 🎵 | `Music` | 音频 |
| 🎬 | `Clapperboard` | 视频 |
| ✏️ | `Pencil` | 编辑 |
| 🔒 | `Lock` | 锁定 |

**响应式策略**：
- 移动端 (<768px)：MenuGrid 改为单列纵向布局
- 表单全宽，按钮 `block` 模式
- 模态框移动端全屏底部抽屉

---

#### Phase 3: Chat 模块（13 文件）

**页面结构**：
```
/chat → Chat.vue（容器）
  ├── ChatTopNav（顶部导航）
  ├── HistorySidebar（历史侧栏）
  │   └── ChatHistory（历史列表）
  ├── DesktopLayout / MobileLayout（响应式布局）
  │   ├── PptPlayer（PPT播放器）
  │   │   ├── PptHeader / PptUpload / PptContent / PptControlBar
  │   │   ├── PptAnalyzing（解析中）
  │   │   ├── KnowledgeGraphModal
  │   │   ├── KnowledgeProgressPage
  │   │   │   └── KnowledgeTreeNode
  │   │   └── MindMap
  │   └── ChatPanel（聊天面板）
  │       ├── ChatInput
  │       ├── MessageList
  │       │   └── MessageBubble
  │       └── FileConfigModal
  ├── SplitVideoPlayer（分屏视频）
  ├── PptSlidePlayer（幻灯片播放）
  ├── DigitalHumanWindow（数字人窗口）
  ├── KnowledgeNavBar（知识导航）
  └── DraggableAvatar（可拖动数字人）
```

**问题与修复**：

| 文件 | 核心问题 | 修复方案 |
|------|---------|---------|
| `FileConfigModal.vue` | 20 处 emoji | → Lucide 图标映射 |
| `DigitalHumanWindow.vue` | 30 处硬编码 + 20 处 emoji | → 令牌 + Lucide |
| `SplitVideoPlayer.vue` | 38 处 Material Green `#4CAF50` | → `var(--color-success)` 系列 |
| `PptSlidePlayer.vue` | 深色硬编码 `#1a1a2e` 等 | → 令牌或 `var(--color-surface-2)` |
| `PptAnalyzing.vue` | `#3b82f6` 旧蓝 | → `var(--color-primary)` |
| `KnowledgeProgressPage.vue` | 10 处 emoji + px | → Lucide + 令牌 |
| `KnowledgeTreeNode.vue` | 4 处 emoji（script 返回值） | → Lucide |
| `PptControlBar.vue` | 3 处 emoji（script 返回值） | → Lucide |
| `KnowledgeNavBar.vue` | 2 处 emoji | → Lucide |
| `MessageList.vue` | 1 处 emoji | → Lucide |
| `DraggableAvatar.vue` | 1 处 emoji | → Lucide |
| `ChatTopNav.vue` | 旧渐变 + 1 处 emoji | → 令牌 + Lucide |

**Emoji → Lucide 映射（Chat 专用）**：
| Emoji | Lucide | 用途 |
|-------|--------|------|
| 🎬 | `Clapperboard` | 视频/生成 |
| 🔄 | `RefreshCw` | 刷新 |
| 🗑️ | `Trash2` | 删除 |
| ➖ | `Minus` | 最小化 |
| 📺 | `MonitorPlay` | 播放器 |
| 📡 | `Radio` | 信号/状态 |
| 🔗 | `Link` | 连接 |
| 📂 | `FolderOpen` | 文件夹 |
| 📁 | `Folder` | 文件夹 |
| 🔇/🔊 | `VolumeX`/`Volume2` | 音量 |
| 📄 | `FileText` | 文件 |
| 📚 | `BookOpen` | 知识库 |
| 📖 | `BookOpen` | 阅读 |
| ⭐ | `Star` | 收藏 |
| 🌳 | `Network` | 知识树 |
| 💾 | `Save` | 保存 |
| 🎯 | `Target` | 目标 |
| 💬 | `MessageCircle` | 消息 |
| 💡 | `Lightbulb` | 提示 |
| ⚡ | `Zap` | 快捷 |
| 🧠 | `Brain` | AI/知识 |
| ⚠️ | `AlertTriangle` | 警告 |
| ✅ | `CheckCircle` | 完成 |
| 🚀 | `Rocket` | 启动 |
| 🎒 | `Backpack` | 资源 |
| 📝 | `PenLine` | 编辑 |
| 🏆 | `Trophy` | 成就 |
| 🚫 | `Ban` | 禁止 |
| 🤝 | `Handshake` | 协作 |
| 👤 | `User` | 用户 |
| 🎙️ | `Mic` | 录音 |
| 📺 | `Tv` | 屏幕 |
| ↺ | `RotateCcw` | 重置 |
| 🔈/🔉 | `Volume1`/`Volume2` | 音量 |
| ⛶ | `Maximize` | 全屏 |

**响应式策略**：
- 桌面 (>1024px)：三栏（历史 + PPT + 聊天）
- 平板 (768~1024px)：双栏（PPT + 聊天），历史侧栏抽屉式
- 移动 (<768px)：单栏 Tab 切换（PPT ↔ 聊天）

---

#### Phase 4: Teacher 模块（6 文件）

**页面结构**：
```
/teacher/history → TeacherHistory（课程列表）
  └── 课程卡片 → /teacher/course/:id
/teacher/create → TeacherDashboard（课程创建/编辑）
  ├── UploadPanel（文档上传）
  ├── StatsPanel（统计面板）
  └── PublishBar（发布栏）
/teacher → TeacherHome（入口页，可能已弃用）
```

**问题与修复**：

| 文件 | 核心问题 | 修复方案 |
|------|---------|---------|
| `TeacherDashboard.vue` | L2482 `@media 1200px` 非标准断点 + 少量硬编码 | 断点→`1024px`，颜色→令牌 |
| `TeacherHistory.vue` | L1347 `@media 1200px` + JS 颜色映射对象 | 断点→`1024px`，JS 对象用令牌值 |
| `StatsPanel.vue` | 10 处硬编码 + 1 处 emoji | → 令牌 + Lucide `BarChart3` |
| `PublishBar.vue` | 10 处硬编码 + 3 处 emoji | → 令牌 + Lucide |
| `UploadPanel.vue` | 检查 defineEmits 重复调用 | 修复代码缺陷 + 令牌化 |
| `TeacherHome.vue` | 旧渐变 + 4 处 emoji | → 令牌 + Lucide |

**Emoji → Lucide 映射**：
| Emoji | Lucide | 用途 |
|-------|--------|------|
| 📊 | `BarChart3` | 统计 |
| 💾 | `Save` | 保存 |
| ✅ | `CheckCircle` | 确认 |
| 🚀 | `Rocket` | 发布 |
| 📥 | `Download` | 导入 |
| 👨‍🏫 | `GraduationCap` | 教师 |
| 📚 | `BookOpen` | 课程 |
| ➕ | `Plus` | 新增 |
| ⚙️ | `Settings` | 设置 |

---

#### Phase 5: Student 模块（12 文件）

**页面结构**：
```
/student → StudentDashboard（课程大厅）
  ├── CourseSelection（选课）
  └── LearningInterface（学习界面）
      ├── CourseStructure（课程结构）
      └── ChatLearningArea（聊天学习区）
          ├── ChatMessage（消息）
          ├── QuizCard（测验）
          └── AnalysisCard（分析）
/student/course/:id → StudentDashboard（课程学习）
/player/course/:id → StudentPlayer（分屏播放器）
  └── LearningPathMap（学习路径）
      ├── PrerequisiteJumpDialog（先修跳转）
      └── JumpSourceBadge（来源标记）
```

**问题与修复**：

| 文件 | 核心问题 | 修复方案 |
|------|---------|---------|
| `StudentDashboard.vue` | 非 scoped markdown 样式硬编码 `#374151` 等 | → 令牌 + scoped |
| `StudentHome.vue` | 15 处 emoji | → Lucide |
| `StudentPlayer.vue` | 6 处 emoji | → Lucide |
| `CourseSelection.vue` | 7 处 emoji | → Lucide |
| `CourseStructure.vue` | 5 处 emoji | → Lucide |
| `ChatLearningArea.vue` | 2 处 emoji + px | → Lucide + 令牌 |
| `PrerequisiteJumpDialog.vue` | 25 处硬编码 + 旧渐变 + emoji | → 令牌 + Lucide |
| `LearningPathMap.vue` | 4 处 emoji + px | → Lucide + 令牌 |
| `QuizCard.vue` | 2 处 emoji | → Lucide |
| `AnalysisCard.vue` | 2 处 emoji | → Lucide |
| `ChatMessage.vue` | 1 处 emoji | → Lucide |
| `JumpSourceBadge.vue` | 5 处 emoji | → Lucide |

**Emoji → Lucide 映射**：
| Emoji | Lucide | 用途 |
|-------|--------|------|
| 👨‍🎓 | `GraduationCap` | 学生 |
| 🔍 | `Search` | 搜索 |
| 📚 | `BookOpen` | 课程 |
| 📖 | `BookOpen` | 学习 |
| 📐 | `Ruler` | 知识点 |
| 👨‍🏫 | `Presentation` | 教师 |
| 🚀 | `Rocket` | 开始 |
| ⏳ | `Hourglass` | 加载 |
| 🎯 | `Target` | 目标 |
| 👥 | `Users` | 用户组 |
| 📊 | `BarChart3` | 统计 |
| ✨ | `Sparkles` | AI |
| 🧠 | `Brain` | 知识 |
| 💡 | `Lightbulb` | 提示 |
| ✅ | `CheckCircle` | 完成 |
| ❌ | `XCircle` | 错误 |
| 📝 | `PenLine` | 测验 |
| 🎬 | `Clapperboard` | 视频 |
| 📋 | `ClipboardList` | 大纲 |
| ⭕ | `Circle` | 未完成 |
| 🔖 | `Bookmark` | 标记 |
| 🗺️ | `Map` | 路径 |
| 📍 | `MapPin` | 位置 |
| 🎓 | `GraduationCap` | 毕业 |
| 🔴🟡🟢⚪ | `Circle`（不同颜色） | 难度等级 |

**响应式策略**：
- Dashboard 移动端：侧栏变底部 Tab
- 播放器移动端：全屏单视频
- 课程列表：1 列→2 列→3~4 列

---

#### Phase 6: 公共页面（5 文件）

| 文件 | 核心问题 | 修复方案 |
|------|---------|---------|
| `SsoCallback.vue` | 6 处旧渐变 + 15 处硬编码 + 4 处 emoji | 全面令牌化 + Lucide |
| `Edulib.vue` | 20 处 emoji + 非标准断点 480px + px | → Lucide + 断点 640px + 令牌 |
| `AdminPanel.vue` | 25 处硬编码 + 2 处 emoji | → 令牌 + Lucide |
| `FanyaBind.vue` | 42 处硬编码 + 6 处旧渐变 + 6 处 emoji + px | 全面令牌化 + Lucide |
| `About.vue` | 15 处 emoji（多为流程箭头） | → Lucide 图标（流程图改用 CSS） |

---

#### Phase 7: 最终验证

1. **StudentDashboard markdown 样式令牌化** — 将非 scoped `#374151`/`#111827` 等替换为令牌
2. **全量检查**：
   - [ ] 无 emoji 用作图标
   - [ ] 无 `#667eea`/`#764ba2` 旧渐变
   - [ ] 无 `#4CAF50`/`#1890ff` 旧调色板
   - [ ] 所有可点击元素有 `cursor: pointer`
   - [ ] 响应式断点统一（375/640/768/1024/1280px）
   - [ ] `prefers-reduced-motion` 被尊重
3. **构建验证**：`npm run build` 无错误

---

## 三、技术选型汇总

| 领域 | 技术 | 说明 |
|------|------|------|
| 框架 | Vue 3 `<script setup>` | 保留，不更换 |
| 构建 | Vite 7 | 保留 |
| 状态管理 | Pinia | 保留 |
| 路由 | Vue Router | 保留 |
| 样式 | CSS 变量 + scoped CSS | 令牌驱动，不引入 Tailwind |
| 图标 | `lucide-vue-next` | 按需引入，tree-shakable |
| 图表 | Chart.js + vue-chartjs | 保留，统一配色 |
| HTTP | axios | 保留 |
| 工具 | @vueuse/core | 虚拟滚动/防抖 |

## 四、实现路径

```
Phase 1 (基础层) ──→ Phase 2 (Profile) ──→ Phase 3 (Chat)
                                              │
Phase 4 (Teacher) ──→ Phase 5 (Student) ←─────┘
                              │
Phase 6 (公共页面) ←──────────┘
        │
Phase 7 (验证)
```

Phase 2~6 可并行执行（模块间无依赖），Phase 7 在所有模块完成后执行。

## 五、交付前检查清单（来自 ui-ux-pro-max）

### 视觉质量
- [ ] 无 emoji 用作图标（全部替换为 Lucide SVG）
- [ ] 所有图标来自 Lucide（一致 viewBox 24x24）
- [ ] hover 状态不引起布局偏移
- [ ] 使用设计令牌（不硬编码颜色）

### 交互
- [ ] 所有可点击元素有 `cursor: pointer`
- [ ] hover 有清晰视觉反馈
- [ ] 过渡平滑（150~300ms）
- [ ] 键盘导航可见焦点环

### 色彩对比
- [ ] 亮色模式文字对比度 ≥ 4.5:1
- [ ] 玻璃态元素在亮色模式可见
- [ ] 边框在两种模式下均可见

### 布局
- [ ] 浮动元素有边缘间距
- [ ] 无内容被固定导航栏遮挡
- [ ] 响应式：375px, 768px, 1024px, 1440px
- [ ] 移动端无水平滚动

### 无障碍
- [ ] 图片有 alt 文本
- [ ] 表单输入有 label
- [ ] 颜色不是唯一指示器
- [ ] `prefers-reduced-motion` 被尊重
