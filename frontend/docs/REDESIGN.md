# Smartrab AI 智课系统 — 前端全面重构设计文档

> 历史设计稿，日期为 2026-07-07。视觉与组件决策仅供追溯；当前页面结构和功能接线以 `page-design.md`、`frontend/src/`、前端契约测试及 `docs/DOCUMENTATION_INDEX.md` 为准。

> 基于 ui-ux-pro-max 设计智能规则生成 | 版本: 2.0 | 日期: 2026-07-07

***

## 一、项目背景与重构目标

### 1.1 现状问题（基于 ui-ux-pro-max 审计）

| 问题类别     | 严重度      | 具体表现                                                             |
| -------- | -------- | ---------------------------------------------------------------- |
| 设计令牌缺失   | CRITICAL | 40+ 硬编码颜色散落各文件，无 CSS 变量体系                                        |
| 图标系统缺失   | CRITICAL | 15+ 种 emoji 作图标，跨平台渲染不可控                                         |
| 视觉风格割裂   | HIGH     | 4 套风格混用（indigo 主流 / Login 紫蓝 / StudentPlayer 深色 Material / 空占位页） |
| 色彩不统一    | HIGH     | 成功色 3 套（#10b981 / #22c55e / #4CAF50），危险色 2 套（#ef4444 / #f43f5e）  |
| 响应式断点不统一 | HIGH     | 768/1024/1200px 三套混用，多个关键页面无响应式                                  |
| 无暗色模式    | MEDIUM   | 全站仅亮色，无主题切换                                                      |
| 动画过重     | MEDIUM   | GradientBackground 4 光球 + 噪点 + 鼠标跟随，影响性能                         |
| 代码缺陷     | MEDIUM   | UploadPanel defineEmits 重复调用；UserIndex 统计数据为随机数                  |

### 1.2 重构目标

1. **统一设计语言** — 建立 AI-Native Soft UI 设计体系，全站视觉一致
2. **设计令牌驱动** — 所有颜色/间距/字体通过 CSS 变量管理，支持主题切换
3. **SVG 图标体系** — 引入 Lucide Icons，消除全部 emoji 图标
4. **响应式全覆盖** — 统一断点策略，所有页面适配 375px\~1440px+
5. **性能优化** — 精简动画、代码分割、懒加载
6. **组件化架构** — 建立基础组件层，减少重复代码

***

## 二、设计系统

### 2.1 设计风格：AI-Native Soft UI

| 维度   | 决策                                                           | 理由                             |
| ---- | ------------------------------------------------------------ | ------------------------------ |
| 风格   | AI-Native Soft UI                                            | 结合柔和阴影/玻璃态与 AI 渐变，契合教育 AI 平台定位 |
| 关键词  | soft shadows, subtle depth, clean, professional, trustworthy | 教育 SaaS 需要专业可信又现代              |
| 适用场景 | 教育、SaaS、AI 工具                                                | 完美匹配本项目                        |
| 性能   | 优秀                                                           | CSS 阴影/过渡，无重计算                 |
| 无障碍  | WCAG AA                                                      | 所有文字对比度 ≥ 4.5:1                |

### 2.2 色彩系统

#### 主色板（Light Mode）

| 令牌                        | 色值                     | 用途          |
| ------------------------- | ---------------------- | ----------- |
| `--color-primary`         | `#6366f1` (Indigo-500) | 主操作、链接、活跃状态 |
| `--color-primary-hover`   | `#4f46e5` (Indigo-600) | 悬停态         |
| `--color-primary-light`   | `#eef2ff` (Indigo-50)  | 背景填充        |
| `--color-secondary`       | `#8b5cf6` (Violet-500) | 辅助渐变、标签     |
| `--color-secondary-light` | `#f5f3ff` (Violet-50)  | 辅助背景        |

#### 语义色（全站统一，消除多套混用）

| 令牌                      | 色值                      | 用途        |
| ----------------------- | ----------------------- | --------- |
| `--color-success`       | `#10b981` (Emerald-500) | 成功/在线/已完成 |
| `--color-success-light` | `#d1fae5` (Emerald-100) | 成功背景      |
| `--color-warning`       | `#f59e0b` (Amber-500)   | 警告/处理中    |
| `--color-warning-light` | `#fef3c7` (Amber-100)   | 警告背景      |
| `--color-danger`        | `#ef4444` (Red-500)     | 危险/删除/错误  |
| `--color-danger-hover`  | `#dc2626` (Red-600)     | 危险悬停      |
| `--color-danger-light`  | `#fee2e2` (Red-100)     | 危险背景      |
| `--color-info`          | `#0ea5e9` (Sky-500)     | 信息提示      |

#### 中性色

| 令牌                       | 色值                    | 用途      |
| ------------------------ | --------------------- | ------- |
| `--color-bg`             | `#f8fafc` (Slate-50)  | 页面背景    |
| `--color-surface`        | `#ffffff`             | 卡片/面板背景 |
| `--color-surface-2`      | `#f1f5f9` (Slate-100) | 次级表面    |
| `--color-border`         | `#e2e8f0` (Slate-200) | 边框      |
| `--color-text`           | `#0f172a` (Slate-900) | 主要文字    |
| `--color-text-secondary` | `#475569` (Slate-600) | 次要文字    |
| `--color-text-muted`     | `#94a3b8` (Slate-400) | 占位/禁用   |

#### 暗色模式（Dark Mode）

| 令牌                       | 色值                    |
| ------------------------ | --------------------- |
| `--color-bg`             | `#0f172a` (Slate-900) |
| `--color-surface`        | `#1e293b` (Slate-800) |
| `--color-surface-2`      | `#334155` (Slate-700) |
| `--color-border`         | `#334155` (Slate-700) |
| `--color-text`           | `#f1f5f9` (Slate-100) |
| `--color-text-secondary` | `#94a3b8` (Slate-400) |
| `--color-text-muted`     | `#64748b` (Slate-500) |

#### 反模式（禁止使用）

* 禁止 `#4CAF50`（Material 绿）— 统一用 `#10b981`

* 禁止 `#22c55e` 作为状态色 — 统一用 `#10b981`

* 禁止 `#667eea`→`#764ba2` 渐变 — 统一用 `#6366f1`→`#8b5cf6`

* 禁止 `#f43f5e` 作为危险色 — 统一用 `#ef4444`

* 禁止 AI 紫粉渐变作为大面积背景（仅限小面积点缀）

### 2.3 字体系统

| 用途    | 字体族              | 回退                                         |
| ----- | ---------------- | ------------------------------------------ |
| UI/正文 | `Inter`          | `system-ui, -apple-system, sans-serif`     |
| 中文    | `Noto Sans SC`   | `PingFang SC, Microsoft YaHei, sans-serif` |
| 代码    | `JetBrains Mono` | `Consolas, monospace`                      |

Google Fonts 引入：

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Noto+Sans+SC:wght@400;500;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

#### 字号阶梯

| 令牌            | 值               | 用途        |
| ------------- | --------------- | --------- |
| `--text-xs`   | 0.75rem (12px)  | 标签/辅助     |
| `--text-sm`   | 0.875rem (14px) | 次要文字      |
| `--text-base` | 1rem (16px)     | 正文（移动端最小） |
| `--text-lg`   | 1.125rem (18px) | 卡片标题      |
| `--text-xl`   | 1.25rem (20px)  | 区域标题      |
| `--text-2xl`  | 1.5rem (24px)   | 页面标题      |
| `--text-3xl`  | 2rem (32px)     | Hero 副标题  |
| `--text-4xl`  | 3.5rem (56px)   | Hero 主标题  |

#### 行高

* 正文：`1.6`（60% 行间距）

* 标题：`1.2`\~`1.3`

* 代码：`1.5`

### 2.4 图标系统：Lucide Icons

| 规则  | 说明                                    |
| --- | ------------------------------------- |
| 图标库 | `lucide-vue-next`（SVG, 24x24 viewBox） |
| 尺寸  | `w-5 h-5`（20px）默认，`w-6 h-6`（24px）导航   |
| 描边  | 2px（Lucide 默认）                        |
| 颜色  | `currentColor` 继承文字颜色                 |
| 禁止  | emoji 作为 UI 图标（🦀👥📚📁 等）            |

### 2.5 间距系统（8px 基准）

| 令牌           | 值    | 用途      |
| ------------ | ---- | ------- |
| `--space-1`  | 4px  | 紧凑间距    |
| `--space-2`  | 8px  | 元素内间距   |
| `--space-3`  | 12px | 小间距     |
| `--space-4`  | 16px | 默认间距    |
| `--space-5`  | 24px | 区块间距    |
| `--space-6`  | 32px | 大区块间距   |
| `--space-8`  | 48px | 页面级间距   |
| `--space-10` | 64px | Hero 间距 |

### 2.6 圆角系统

| 令牌              | 值      | 用途     |
| --------------- | ------ | ------ |
| `--radius-sm`   | 6px    | 小元素/标签 |
| `--radius-md`   | 8px    | 按钮/输入框 |
| `--radius-lg`   | 12px   | 卡片     |
| `--radius-xl`   | 16px   | 大卡片/面板 |
| `--radius-full` | 9999px | 圆形/胶囊  |

### 2.7 阴影系统

| 令牌                 | 值                                                                    | 用途   |
| ------------------ | -------------------------------------------------------------------- | ---- |
| `--shadow-sm`      | `0 1px 2px rgba(0,0,0,0.05)`                                         | 轻微浮起 |
| `--shadow-md`      | `0 4px 6px -1px rgba(0,0,0,0.08), 0 2px 4px -2px rgba(0,0,0,0.05)`   | 卡片默认 |
| `--shadow-lg`      | `0 10px 15px -3px rgba(0,0,0,0.08), 0 4px 6px -4px rgba(0,0,0,0.05)` | 悬浮卡片 |
| `--shadow-primary` | `0 4px 14px rgba(99,102,241,0.25)`                                   | 主色按钮 |

### 2.8 动画系统

| 令牌                  | 值                              | 用途    |
| ------------------- | ------------------------------ | ----- |
| `--duration-fast`   | 150ms                          | 微交互   |
| `--duration-normal` | 200ms                          | 默认过渡  |
| `--duration-slow`   | 300ms                          | 大面积过渡 |
| `--ease`            | `cubic-bezier(0.4, 0, 0.2, 1)` | 默认缓动  |

**规则：**

* 所有过渡使用 150\~300ms

* 使用 `transform`/`opacity` 而非 `width`/`height`

* 尊重 `prefers-reduced-motion`

* GradientBackground 精简为最多 2 个光球，移动端关闭动画

### 2.9 z-index 层级

| 层级       | 值  | 用途   |
| -------- | -- | ---- |
| base     | 0  | 正常内容 |
| dropdown | 10 | 下拉菜单 |
| sticky   | 20 | 粘性导航 |
| fixed    | 30 | 固定导航 |
| overlay  | 40 | 遮罩层  |
| modal    | 50 | 模态框  |
| toast    | 60 | 通知提示 |

***

## 三、技术选型

### 3.1 新增依赖

| 依赖                | 版本       | 用途                             |
| ----------------- | -------- | ------------------------------ |
| `lucide-vue-next` | ^0.475.0 | SVG 图标系统                       |
| `tailwindcss`     | ^4.0.0   | 原子化 CSS（按需引入，不替代全部 scoped CSS） |

### 3.2 保留依赖

Vue 3 / Vite / Pinia / Vue Router / Chart.js / Marked / KaTeX / highlight.js / DOMPurify / @vueuse/core — 均保留，不更换。

### 3.3 架构决策

| 决策   | 方案                                      | 理由                         | <br />           |
| ---- | --------------------------------------- | -------------------------- | :--------------- |
| 样式策略 | 设计令牌（CSS 变量）+ scoped CSS 为主，Tailwind 为辅 | 渐进式迁移，不破坏现有 scoped CSS     | <br />           |
| 图标   | lucide-vue-next 按需引入                    | Tree-shakable, SVG, 一致性    | <br />           |
| 主题   | \`data-theme="light                     | dark"`on`<html>\` + CSS 变量 | 零运行时开销，原生 CSS 切换 |
| 组件   | 建立 `components/ui/` 基础组件层               | 统一交互/视觉，减少重复               | <br />           |

***

## 四、页面结构规划

### 4.1 路由结构（保持不变）

```
/                        → Home（Landing Page）
/about                   → About
/profile                 → Profile（登录/个人中心）
/chat                    → Chat（AI 问答）
/edulib                  → Edulib（资源库）
/sso/callback            → SsoCallback
/teacher/history         → TeacherHistory（课程管理）
/teacher/create          → TeacherDashboard（课程创建/编辑）
/teacher/course/:id      → TeacherDashboard（编辑已有课程）
/student                 → StudentDashboard（课程大厅）
/student/course/:id      → StudentDashboard（课程学习）
/player/course/:id       → StudentPlayer（分屏播放器）
/admin                   → AdminPanel（用户管理）
```

### 4.2 页面布局模式

| 布局            | 适用页面                                        | 结构                 |
| ------------- | ------------------------------------------- | ------------------ |
| **Landing**   | Home                                        | 全屏分区 + scroll-snap |
| **Auth**      | Profile/Login                               | 居中卡片               |
| **Dashboard** | TeacherDashboard, StudentDashboard          | 侧栏 + 主内容区          |
| **List**      | TeacherHistory, AdminPanel, CourseSelection | 顶部统计 + 网格列表        |
| **Player**    | StudentPlayer                               | 顶栏 + 主体 + 底栏       |
| **Chat**      | Chat                                        | 三栏（侧栏 + PPT + 聊天）  |
| **Full**      | CodeBench, Cognitive, Visualization         | 全屏工作区              |

### 4.3 容器规范

```css
/* 页面容器 */
.page-container {
  max-width: 1440px;
  margin: 0 auto;
  padding: 0 var(--space-5);
}

/* 内容容器 */
.content-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 var(--space-5);
}

/* 宽容器 */
.wide-container {
  max-width: 1600px;
  margin: 0 auto;
  padding: 0 var(--space-4);
}
```

***

## 五、组件架构

### 5.1 组件分层

```
components/
├── ui/                    # 基础组件层（新增）
│   ├── UiButton.vue       # 按钮（primary/secondary/ghost/danger）
│   ├── UiCard.vue         # 卡片（default/glass/elevated）
│   ├── UiInput.vue        # 输入框
│   ├── UiTextarea.vue     # 文本域
│   ├── UiModal.vue        # 模态框
│   ├── UiBadge.vue        # 徽章/标签
│   ├── UiAvatar.vue       # 头像
│   ├── UiSpinner.vue      # 加载动画
│   ├── UiTooltip.vue      # 工具提示
│   ├── UiTabs.vue         # 标签页
│   ├── UiProgress.vue     # 进度条
│   └── UiEmpty.vue        # 空状态
├── layout/                # 布局组件（重构）
│   ├── AppNavbar.vue      # 全局导航栏（原 NavigationBar）
│   ├── AppBackground.vue  # 背景层（原 GradientBackground，精简）
│   ├── PageContainer.vue  # 页面容器
│   └── Sidebar.vue        # 侧栏通用组件
├── home/                  # 首页（重构）
├── chat/                  # 聊天（重构）
├── teacher/               # 教师（重构）
├── student/               # 学生（重构）
├── profile/               # 个人中心（重构）
├── common/                # 通用业务组件
└── ...                    # 其他功能组件
```

### 5.2 基础组件设计

#### UiButton

```
Props:
  variant: 'primary' | 'secondary' | 'ghost' | 'danger' | 'success'
  size: 'sm' | 'md' | 'lg'
  loading: boolean
  disabled: boolean
  icon: string (Lucide icon name, optional)
  block: boolean (全宽)

Slots:
  default (按钮文字)

使用:
  <UiButton variant="primary" icon="rocket">免费使用</UiButton>
```

#### UiCard

```
Props:
  variant: 'default' | 'glass' | 'elevated'
  hover: boolean (是否启用悬浮效果)
  padding: 'sm' | 'md' | 'lg'

Slots:
  default, header, footer
```

#### UiBadge

```
Props:
  variant: 'primary' | 'success' | 'warning' | 'danger' | 'info' | 'neutral'
  size: 'sm' | 'md'
```

### 5.3 图标映射表（emoji → Lucide）

| 原 emoji | Lucide 图标                      | 用途      |
| ------- | ------------------------------ | ------- |
| 🦀      | `Crab` (自定义) / `GraduationCap` | Logo    |
| 👥      | `Users`                        | 用户管理    |
| 📚      | `BookOpen`                     | 智课管理/课程 |
| 📁      | `Folder`                       | 文件夹     |
| 📄      | `FileText`                     | 文件      |
| ✨       | `Sparkles`                     | AI 生成   |
| 🌳      | `Network` / `GitBranch`        | 知识树     |
| 📖      | `BookOpen`                     | 阅读      |
| 📝      | `PenLine` / `Edit`             | 编辑      |
| ⭐       | `Star`                         | 收藏      |
| 💡      | `Lightbulb`                    | 提示      |
| 📐      | `Ruler` / `Layers`             | 知识点     |
| 📋      | `Clipboard` / `ClipboardList`  | 列表      |
| ❓       | `HelpCircle`                   | 帮助      |
| ⏱️      | `Clock`                        | 时长      |
| 👁️     | `Eye`                          | 预览      |
| ✏️      | `Pencil`                       | 编辑      |
| ▶️ / ▶  | `Play`                         | 播放      |
| ⏸️      | `Pause`                        | 暂停      |
| 🔊      | `Volume2`                      | 音量      |
| 💾      | `Save`                         | 保存      |
| 🔒      | `Lock`                         | 锁定/已发布  |
| 📸      | `Camera`                       | 快照      |
| 📢      | `Megaphone`                    | 发布      |
| 🚀      | `Rocket`                       | 启动/开始   |
| 🗑️     | `Trash2`                       | 删除      |
| ✕       | `X`                            | 关闭      |
| ⚙️      | `Settings`                     | 设置      |
| 🎨      | `Palette`                      | 主题/外观   |
| 🚪      | `LogOut`                       | 退出      |
| 🤖      | `Bot`                          | AI/数字人  |
| 💬      | `MessageCircle`                | 消息      |
| 🎬      | `Clapperboard`                 | 视频      |
| 📊      | `BarChart3`                    | 统计      |
| 📍      | `MapPin`                       | 位置/知识点  |
| ⏳       | `Hourglass`                    | 加载中     |
| 📭      | `Inbox`                        | 空收件箱    |
| ➕       | `Plus`                         | 新增      |
| ▼       | `ChevronDown`                  | 展开      |

***

## 六、交互逻辑设计

### 6.1 全局交互规范

| 场景    | 规范                                                           |
| ----- | ------------------------------------------------------------ |
| 可点击元素 | `cursor: pointer` + hover 视觉反馈（颜色/阴影/边框）                     |
| 过渡    | `transition: all 200ms var(--ease)`                          |
| 悬浮卡片  | `transform: translateY(-2px)` + `shadow-lg`（不用 scale 避免布局偏移） |
| 加载    | UiSpinner 或骨架屏（Skeleton）                                     |
| 错误    | 行内错误提示 + `--color-danger` 文字                                 |
| 表单    | label + input 关联，失焦校验，错误就近显示                                 |
| 模态    | 背景遮罩 `rgba(0,0,0,0.4)` + 居中卡片 + ESC 关闭                       |

### 6.2 导航交互

* 顶部导航栏：固定 `position: fixed`，毛玻璃 `backdrop-filter: blur(14px)`

* 导航项：hover 时 `background: var(--color-primary-light)`，active 时加粗

* 移动端：汉堡菜单展开抽屉式导航

* 路由切换：`fade` 过渡（200ms）

### 6.3 表单交互

* 输入框聚焦：`border-color: var(--color-primary)` + `ring` 效果

* 校验：失焦时校验，错误时 `border-color: var(--color-danger)` + 下方错误文字

* 提交按钮：loading 时禁用 + Spinner

* 记住我：复选框样式统一

### 6.4 列表交互

* 课程卡片：hover 上浮 + 阴影加深

* 空状态：UiEmpty 组件（图标 + 文字 + 操作按钮）

* 删除确认：UiModal 确认弹窗

* 分页/滚动：列表使用 `IntersectionObserver` 懒加载

***

## 七、响应式适配策略

### 7.1 统一断点

| 断点    | 宽度      | 目标设备        |
| ----- | ------- | ----------- |
| `sm`  | ≥640px  | 大手机/小平板（竖屏） |
| `md`  | ≥768px  | 平板（竖屏）      |
| `lg`  | ≥1024px | 平板（横屏）/小笔记本 |
| `xl`  | ≥1280px | 桌面          |
| `2xl` | ≥1536px | 大屏          |

**移动优先**：默认样式为移动端（≥375px），`@media (min-width: ...)` 逐级增强。

### 7.2 各布局响应式策略

| 布局        | 移动端 (<768px)   | 平板 (768\~1024px) | 桌面 (>1024px)      |
| --------- | -------------- | ---------------- | ----------------- |
| Dashboard | 单栏纵向，侧栏变底部 Tab | 单栏，侧栏可折叠         | 双栏（侧栏 + 主内容）      |
| Chat      | 单栏切换（PPT ↔ 聊天） | 双栏（PPT + 聊天）     | 三栏（历史 + PPT + 聊天） |
| List      | 1 列            | 2 列              | 3\~4 列            |
| Landing   | 纵向堆叠           | 纵向堆叠             | 左右分栏              |
| Player    | 全屏单视频          | 分屏               | 分屏 + 侧栏信息         |

### 7.3 移动端特殊处理

* 导航栏：汉堡菜单

* 表格：水平滚动或卡片化

* 光球动画：关闭（性能）

* 鼠标跟随：关闭

* `touch-action: manipulation` 消除 300ms 延迟

***

## 八、性能优化措施

### 8.1 构建优化

| 措施           | 实现                                                   |
| ------------ | ---------------------------------------------------- |
| 代码分割         | 路由级 `() => import()` 已有，保持                           |
| 手动分块         | `vite.config.js` 已配置 vue-vendor/markdown/ui-utils 分块 |
| Tree-shaking | lucide-vue-next 按需引入图标                               |
| 图片优化         | WebP 格式 + `loading="lazy"`                           |

### 8.2 运行时优化

| 措施    | 实现                                        |
| ----- | ----------------------------------------- |
| 动画精简  | GradientBackground 从 4 光球精简为 2 个，移动端关闭    |
| 虚拟滚动  | 长列表使用 `@vueuse/core` 的 `useVirtualList`   |
| 防抖节流  | 搜索/输入使用 `useDebounceFn`                   |
| 图片懒加载 | `loading="lazy"` + `IntersectionObserver` |
| 组件懒加载 | 重组件 `defineAsyncComponent`                |

### 8.3 CSS 优化

| 措施            | 实现                                   |
| ------------- | ------------------------------------ |
| 设计令牌          | CSS 变量集中管理，避免重复                      |
| scoped CSS    | 保持 Vue scoped，避免全局污染                 |
| 避免重排          | 动画用 `transform`/`opacity`            |
| `will-change` | 仅在动画元素上声明                            |
| `contain`     | 独立卡片使用 `contain: layout style paint` |

***

## 九、功能模块实现路径

### 9.1 实现阶段

| 阶段       | 内容                             | 优先级 |
| -------- | ------------------------------ | --- |
| Phase 1  | 设计令牌 + Tailwind 集成 + Lucide 引入 | P0  |
| Phase 2  | 基础组件层（ui/）                     | P0  |
| Phase 3  | 布局组件重构（Navbar/Background）      | P0  |
| Phase 4  | 首页 Landing Page 重构             | P1  |
| Phase 5  | 认证/个人中心重构                      | P1  |
| Phase 6  | 教师端重构                          | P1  |
| Phase 7  | 学生端重构                          | P1  |
| Phase 8  | Chat/AI 问答重构                   | P1  |
| Phase 9  | 管理员/其他页面重构                     | P2  |
| Phase 10 | 暗色模式 + 最终验证                    | P2  |

### 9.2 各模块技术选型

| 模块   | 技术方案                                          |
| ---- | --------------------------------------------- |
| 设计令牌 | `src/styles/tokens.css` — 全部 CSS 变量           |
| 暗色模式 | `src/styles/dark.css` + `data-theme` 属性切换     |
| 基础组件 | `src/components/ui/` — Vue 3 SFC + scoped CSS |
| 图标   | `lucide-vue-next` 按需引入                        |
| 状态管理 | Pinia（保留），重命名 `counter.js` → `auth.js`        |
| 路由   | Vue Router（保留），添加过渡动画                         |
| 请求   | axios（保留），统一错误处理                              |
| 图表   | Chart.js + vue-chartjs（保留），统一配色               |

***

## 十、交付前检查清单

### 视觉质量

* [ ] 无 emoji 用作图标（全部替换为 Lucide SVG）

* [ ] 所有图标来自 Lucide（一致 viewBox 24x24）

* [ ] hover 状态不引起布局偏移

* [ ] 使用设计令牌（不硬编码颜色）

### 交互

* [ ] 所有可点击元素有 `cursor: pointer`

* [ ] hover 有清晰视觉反馈

* [ ] 过渡平滑（150\~300ms）

* [ ] 键盘导航可见焦点环

### 色彩对比

* [ ] 亮色模式文字对比度 ≥ 4.5:1

* [ ] 玻璃态元素在亮色模式可见（`bg-white/80`+）

* [ ] 边框在两种模式下均可见

### 布局

* [ ] 浮动元素有边缘间距

* [ ] 无内容被固定导航栏遮挡

* [ ] 响应式：375px, 768px, 1024px, 1440px

* [ ] 移动端无水平滚动

### 无障碍

* [ ] 图片有 alt 文本

* [ ] 表单输入有 label

* [ ] 颜色不是唯一指示器

* [ ] `prefers-reduced-motion` 被尊重
