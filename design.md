# 教育智能体系统项目前端设计指南

> **文件职责**：本文件是本项目前端的**唯一权威设计指南**，统一回答"前端界面应该长什么样、如何布局、如何过渡、如何交互"。
> 覆盖范围：视觉语言、布局与滚动、页面过渡动画、组件外观、智能体面板、建设页面 stageActions 机制、按钮规范、常见反模式。
> **不负责**：页面信息架构、业务流程、权限逻辑与具体页面内容，这些由 [`page-design.md`](./page-design.md) 负责。
> **版本**：v0.6
> **产品主张**：让课程回应学习
> **配套令牌实现**：[`frontend/src/app/styles/tokens.css`](./frontend/src/app/styles/tokens.css) 1:1 实现本文件全部 CSS 令牌；[`frontend/src/app/styles/base.css`](./frontend/src/app/styles/base.css) 1:1 实现页面过渡动画与基础控件样式。
> **冲突优先级**：本文件 > 历史前端文档（含 `frontend/docs/`）> 旧比赛材料。代码实际行为与本文件不一致时，以代码为准并同步更新本文件。

---

## 设计定位

视觉关键词：

- Academic Intelligence
- Digital Textbook
- Learning Workspace
- Evidence-driven AI
- Quiet Technology

一句话定义：

> 像未来教材一样可阅读，像专业工作环境一样可靠。

基本原则：

1. **内容温润，操作现代**：学习内容、知识关系与原文引用可以带轻微学术编辑感；导航、表格、按钮、设置和批量操作必须清晰、克制。
2. **长期使用优先**：避免大面积纹理、霓虹、低对比文字、过多阴影和装饰性渐变。
3. **状态可辨识**：颜色不能单独承担语义，必须同时配合文字、图标、线型或形状。
4. **工具层稳定**：教师审核、课程建设、代码运行和安全设置应具有专业工具感，而不是宣传页式视觉。
5. **页面整体不滚动，内部可滚动**：见 §5「布局与滚动规范」。

---

# 1. 配色

## 1.1 主色：Academic Ink

主色来自深墨蓝，承担品牌、导航、主操作与可信 AI 状态。

| Token | 色值 | 主要用途 |
|---|---:|---|
| `ink-950` | `#101A31` | 超深标题、深色工作区外框 |
| `ink-900` | `#14213D` | 品牌主色、主按钮、一级标题 |
| `ink-700` | `#203A5F` | 选中导航、按钮 Hover、重要边界 |
| `ink-500` | `#355C7D` | 链接、焦点、AI 状态、图谱主关系 |
| `ink-300` | `#8EA7BE` | 弱图形、禁用辅助元素 |
| `ink-100` | `#E8EEF4` | 选中背景、浅色信息提示 |

语义令牌：

```css
--color-brand: #14213D;
--color-brand-hover: #203A5F;
--color-brand-soft: #E8EEF4;
--color-focus: #355C7D;
```

使用规则：

- 页面中同一时刻只允许一个主要墨蓝实心操作。
- 墨蓝用于建立层级，不用于大面积铺满所有卡片。
- 禁止再叠加廉价蓝紫渐变制造“AI 感”。

## 1.2 辅助色

### Learning Green

表达完成、掌握、验证通过和教师确认。

| Token | 色值 | 用途 |
|---|---:|---|
| `green-700` | `#3F6B52` | 成功状态文字 |
| `green-500` | `#5E8C61` | 验证通过、已掌握 |
| `green-300` | `#A8C3A5` | 成功边框、关系线 |
| `green-100` | `#EDF5EE` | 成功状态背景 |

### Annotation Red

表达错误、风险、易错点、教师批注。色调应像批改红笔，而不是警报灯。

| Token | 色值 | 用途 |
|---|---:|---|
| `red-700` | `#8B3A3A` | 高风险文字 |
| `red-500` | `#B85C5C` | 错误、冲突、易错关联 |
| `red-300` | `#D9A3A3` | 错误边框 |
| `red-100` | `#FAEEEE` | 错误背景 |

### Highlight Amber

表达待审核、AI 当前关注、搜索命中和课程重点。

| Token | 色值 | 用途 |
|---|---:|---|
| `amber-700` | `#9B6618` | 警示文字 |
| `amber-500` | `#C68B2C` | 待审核、重点状态 |
| `amber-300` | `#E5B95C` | 检索路径、局部高亮 |
| `amber-100` | `#FBF3DE` | 轻量高亮背景 |

## 1.3 背景色与表面

| Token | 色值 | 用途 |
|---|---:|---|
| `surface-page` | `#F7F5EF` | 产品页面主背景，温暖但不偏黄 |
| `surface-canvas` | `#FBFAF7` | 学习画布、知识图谱画布 |
| `surface-panel` | `#FFFFFF` | 操作面板、抽屉、表格 |
| `surface-soft` | `#F0EDE6` | 学习轨道、次级工具区 |
| `surface-cool` | `#F7F8FA` | 原文引用、系统说明、数据区 |
| `surface-overlay` | `rgba(16, 26, 49, 0.42)` | 模态遮罩 |

规则：

- 全页面明显纸张纹理禁止使用。
- 知识探索画布可加入不超过 `3%` 透明度的细微网格或纸感。
- 表格、表单、设置、审核页面使用纯净表面。
- 不用不同底色切割每一个小模块，优先使用留白和分割线。

## 1.4 文字色

| Token | 色值 | 用途 |
|---|---:|---|
| `text-primary` | `#172033` | 标题与正文核心信息 |
| `text-secondary` | `#4E5969` | 次级说明 |
| `text-muted` | `#7B8494` | 辅助信息、时间、非关键状态 |
| `text-disabled` | `#A7AFBC` | 禁用文字 |
| `text-inverse` | `#FFFFFF` | 深色背景文字 |
| `text-link` | `#355C7D` | 链接与原文引用入口 |

规则：

- 核心信息不得使用 `text-muted`。
- 课程正文必须使用 `text-primary`。
- 小字号文字不得叠加低对比背景纹理。

## 1.5 边框与中性色

| Token | 色值 | 用途 |
|---|---:|---|
| `border-default` | `#DDE2E8` | 默认边框、分隔线 |
| `border-strong` | `#C9CFD8` | 强边界、表格选中 |
| `border-subtle` | `#EDF0F3` | 弱分隔、Hover 背景 |

```css
--border-default: 1px solid #DDE2E8;
--border-strong: 1px solid #C9CFD8;
--border-focus: 2px solid #355C7D;
```

## 1.6 代码工作区

代码空间允许使用独立深色语言，但外围 App Shell 保持统一。

| Token | 色值 | 用途 |
|---|---:|---|
| `code-bg` | `#101820` | 编辑器背景 |
| `code-panel` | `#161F2B` | 测试与终端面板 |
| `code-border` | `#2D3746` | 深色区边界 |
| `code-text` | `#E6EDF3` | 代码正文 |
| `code-muted` | `#8B98AA` | 行号与辅助信息 |

## 1.7 语义状态

| 状态 | 主色 | 背景 | 必须附带 |
|---|---|---|---|
| 已确认 / 已通过 | `green-500` | `green-100` | 勾选图标 + 状态文字 |
| 待审核 / 需关注 | `amber-500` | `amber-100` | 时钟或提示图标 + 状态文字 |
| 冲突 / 失败 | `red-500` | `red-100` | 错误图标 + 原因文字 |
| AI 处理 / 信息 | `ink-500` | `ink-100` | AI/信息图标 + 操作说明 |
| 实验能力 | `ink-500` | `surface-cool` | “实验”明确标签 |
| 研究预览 | `amber-500` | `amber-100` | “研究预览”明确标签 |

色彩比例建议：

```text
65% 中性与暖白背景
22% 墨蓝结构和操作
8% 成功 / 警示 / 错误状态
5% 高亮和品牌细节
```

---

# 2. 字体

## 2.1 字体栈

### 产品 UI 与课程正文

```css
font-family:
  Inter,
  "HarmonyOS Sans SC",
  "PingFang SC",
  "Microsoft YaHei",
  system-ui,
  sans-serif;
```

### 公开展示首页大型标题

```css
font-family:
  "Source Han Serif SC",
  "Noto Serif SC",
  serif;
```

衬线字体只用于公开首页 Hero 或大型章节标题。登录后的产品 App 不使用衬线字体作为常规页面标题。

### 代码

```css
font-family:
  "JetBrains Mono",
  "Fira Code",
  Consolas,
  monospace;
```

## 2.2 字号、字重、行高

| Token | 字号 | 行高 | 字重 | 用途 |
|---|---:|---:|---:|---|
| `display-xl` | 56px | 64px | 700 | 产品展示首页 Hero |
| `display-lg` | 44px | 54px | 650 | 产品首页章节标题 |
| `title-1` | 32px | 40px | 650 | 登录后页面主标题 |
| `title-2` | 24px | 32px | 600 | 页面模块标题 |
| `title-3` | 18px | 26px | 600 | 卡片、知识点、面板标题 |
| `body-lg` | 18px | 30px | 400 | 长篇课程解释、教学正文 |
| `body-md` | 16px | 28px | 400 | 标准正文、AI 回应 |
| `ui-md` | 14px | 20px | 500 | 按钮、导航、表格、输入 |
| `ui-sm` | 13px | 18px | 500 | Evidence、辅助标签 |
| `caption` | 12px | 18px | 450 | 时间、状态、注释 |
| `code` | 14px | 22px | 400 | 代码编辑器 |

## 2.3 字体使用规则

- 课程解释正文最低 `16px`，长篇核心讲解推荐 `18px`。
- 表格、审核、设置页面默认 `14px`。
- 小于 `14px` 的文字禁止使用宋体、仿宋、书法或手写字体。
- 不使用 `300` 以下超细字重。
- 同一区域标题层级不超过三级。
- 英文缩写、Evidence ID 和状态码使用无衬线或等宽字体，不使用装饰性字体。
- 手写字体只允许出现在教师批注装饰中，且不承载关键操作或正文。

---

# 3. 间距

## 3.1 基础网格

采用 `4px` 基础单位与 `8px` 主网格。

```text
4 / 8 / 12 / 16 / 24 / 32 / 40 / 48 / 64 / 80 / 96
```

| Token | 数值 | 用途 |
|---|---:|---|
| `space-1` | 4px | 图标与文字微间距 |
| `space-2` | 8px | 同组小元素 |
| `space-3` | 12px | 紧凑组件内边距 |
| `space-4` | 16px | 标准组件内边距 |
| `space-6` | 24px | 卡片内边距、模块间距 |
| `space-8` | 32px | 页面区域间距 |
| `space-10` | 40px | 大工作区留白 |
| `space-12` | 48px | 页面章节间距 |
| `space-16` | 64px | 展示首页章节内部留白 |
| `space-20` | 80px | Hero 与叙事章节间距 |

## 3.2 页面级间距

| 场景 | 规则 |
|---|---|
| 桌面页面左右安全边距 | 24–32px |
| 登录后 App 内容最大宽度 | 1440px，工作区可全宽 |
| 公开展示页正文最大宽度 | 1200–1280px |
| 页面标题与首模块 | 24–32px |
| 同级模块之间 | 24–32px |
| 大章节之间 | 48–64px |
| 卡片之间 | 16–24px |
| 表单字段之间 | 16px |
| 表单分组之间 | 24–32px |

## 3.3 关键布局尺寸

| 组件 | 展开尺寸 | 收缩 / 最小尺寸 |
|---|---:|---:|
| 一级顶部导航（`--nav-l1-height`） | 56px 高 | 不收缩 |
| 课程二级导航（`--nav-l2-height`） | 44px 高 | 不增加第三行菜单 |
| Local Rail / 建设侧栏（`--rail-width`） | 232px 宽 | 56px（`--rail-width-collapsed`） |
| 助教智能体面板（`--agent-panel-width`） | 460px 宽，可拖拽至 360–640px | 360px |
| 普通详情抽屉 | 420 / 480 / 640px | 根据任务选择 |
| 主按钮 / 标准输入框（`--control-height`） | 40px 高 | 图标按钮不小于 40×40px |
| 提问输入框 | 44–48px 高，可自动扩展为多行 | — |
| 标准表格行 | 44px | Compact 36px |

> 注：原"课程上下文条"已删除（详见 §11.2），不再计入布局尺寸。

## 3.4 密度模式

### Standard

用于：课程学习、知识探索、课程概览、公开首页。

- 卡片内边距：20–24px
- 表单控件高度：40px
- 列表行高：44–48px

### Compact

用于：教师批量审核、成员列表、任务中心、版本对比。

- 卡片或面板内边距：12–16px
- 表格行高：36px
- 不能因压缩而把正文缩小到 12px 以下

密度模式只改变内边距和行高，不改变信息架构。

---

# 4. 动效令牌

所有动效必须使用本节令牌，禁止在业务样式中硬编码 `transition-duration` 或 `cubic-bezier`。

```css
--duration-fast: 120ms;    /* 按钮、Hover、表单控件、页面过渡 */
--duration-normal: 200ms;  /* 抽屉、模态、面板展开 */
--duration-slow: 320ms;    /* 大型叙事动画、Hero */
--ease-out: cubic-bezier(0.16, 1, 0.3, 1);  /* 全局唯一缓动 */
```

规则：

- 全产品仅使用一条 `--ease-out` 缓动曲线，不引入 `ease-in`、`bounce`、`elastic` 等装饰性曲线（思考点动画除外，见 §8.3）。
- 任何 transition 时长不得低于 `--duration-fast`（120ms），避免肉眼不可见的"闪现"。
- 任何 transition 时长不得高于 `--duration-slow`（320ms），避免拖沓。
- `prefers-reduced-motion: reduce` 下所有动画降级为 0.01ms（已在 [`base.css`](./frontend/src/app/styles/base.css) 中统一实现）。

---

# 5. 布局与滚动规范

> 本节规则来源于长期开发中反复出现的滚动溢出、整页抖动、内部容器塌陷等问题。所有新建页面必须遵守。

## 5.1 三层滚动容器模型

产品采用三层嵌套的"整页不滚动 / 内部滚动"模型：

| 层级 | 容器 | 滚动行为 |
|---|---|---|
| L1 应用 Shell | `.sfx-shell`（[AppShell.vue](./frontend/src/app/shell/AppShell.vue)） | `height: 100dvh; overflow: hidden`，自身永不滚动 |
| L2 主内容区 | `.sfx-shell-main` | `flex: 1; overflow-y: auto`，承担整页滚动 |
| L3 页面内部 | 各页面根容器 + 内部 list/panel | `min-height: 0; overflow-y: auto`，承担局部滚动 |

**强制规则**：

1. `.sfx-shell` 必须保持 `overflow: hidden`，任何情况下不允许整页出现浏览器滚动条。
2. L2 `.sfx-shell-main` 是**唯一**的全页滚动容器；路由切换时由 [AppShell.vue](./frontend/src/app/shell/AppShell.vue) 中的 `mainRef.scrollTo({ top: 0 })` 重置滚动位置。
3. L3 内部滚动容器必须显式设置 `min-height: 0`，否则 flex/grid 子元素会被内容撑爆，触发整页滚动。
4. 任何使用 `grid-template-rows` 的容器必须用 `minmax(0, 1fr)` 限制可滚动行高，禁止直接写 `1fr`（会被内容撑开）。

## 5.2 Grid 布局行高陷阱

错误示例（会导致整页被内容撑爆）：

```css
.stage { display: grid; grid-template-rows: auto 1fr; } /* ❌ 1fr 会被撑开 */
```

正确示例：

```css
.stage { display: grid; grid-template-rows: auto minmax(0, 1fr); } /* ✅ */
.stage-body { min-height: 0; overflow-y: auto; }
```

## 5.3 建设页面布局结构

[BuildLayout.vue](./frontend/src/app/pages/course/build/BuildLayout.vue) 是建设页面的标准布局参考：

```text
.build-workspace        ← flex column, overflow:hidden, 整个建设区不滚动
└── .build-grid         ← grid: 236px | 1fr | 440px, grid-template-rows: minmax(0,1fr)
    ├── .build-rail     ← overflow-y:auto，左侧步骤导航独立滚动
    ├── .build-stage    ← flex column, overflow:hidden
    │   ├── .stage-context   ← flex-shrink:0，标题与操作区固定
    │   └── .stage-body      ← flex:1; min-height:0; overflow:hidden
    │       └── <router-view/> ← 子页面内部管理自身滚动
    └── CourseBuildAgentPanel ← overflow:hidden，内部消息区独立滚动
```

**强制规则**：

- 建设页面根容器 `.build-workspace` 必须保持 `overflow: hidden`。
- `.build-stage` 不得使用 `overflow-y: auto`（曾导致整页滚动）。
- `.stage-body` 必须是 `flex: 1; min-height: 0; overflow: hidden`，由子页面内部决定滚动。
- 子页面（BuildStructurePage / BuildScriptsPage / BuildMappingPage 等）的根节点必须自己设置 `height: 100%; overflow-y: auto` 或在内部 list/panel 上设置局部滚动。

## 5.4 节点目录与编辑框独立滚动

以 [BuildStructurePage.vue](./frontend/src/app/pages/course/build/BuildStructurePage.vue) 为参考，左侧节点目录树与右侧编辑区必须各自独立滚动，互不影响：

```css
.structure-stage {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);   /* 关键：限制行高 */
  gap: var(--space-4);
  height: 100%;
  min-height: 0;
}
.node-list  { overflow-y: auto; min-height: 0; }
.node-editor { overflow-y: auto; min-height: 0; }
```

---

# 6. 页面过渡动画规范

> 本节规则来源于一级/二级菜单切换时的页面抽搐抖动、菜单栏消失、视觉错位等问题。

## 6.1 全局过渡方案

所有 `<router-view>` 必须使用 `sfx-page` 过渡名，已在 [`base.css`](./frontend/src/app/styles/base.css) 中统一定义：

```css
.sfx-page-enter-active,
.sfx-page-leave-active {
  transition: opacity var(--duration-fast) var(--ease-out);
  will-change: opacity;
  backface-visibility: hidden;
  -webkit-backface-visibility: hidden;
}
.sfx-page-leave-active { pointer-events: none; }
.sfx-page-enter-from,
.sfx-page-leave-to { opacity: 0; }
```

## 6.2 过渡规则

1. **仅使用 `opacity`，禁止使用 `transform` 位移**。曾有实现使用 `transform: translateY(8px)` 制造"滑入"效果，导致一级菜单点击时整个 main 区域上下错动、二级菜单被瞬时挤掉。
2. **离开期间必须 `pointer-events: none`**，避免用户误触正在消失的旧组件触发额外路由或请求。
3. **必须配合 `mode="out-in"`**：旧组件完全离开后再渲染新组件，避免两者同时存在导致 grid/flex 布局塌陷。
4. **必须使用 `backface-visibility: hidden`** 强制独立合成层，避免过渡期间触发重绘。
5. **总时长 = `--duration-fast` (120ms)**，配合 `mode="out-in"` 总感知约 240ms，既不生硬也不拖沓，符合 Quiet Technology 克制原则。

## 6.3 router-view 模板标准写法

```vue
<router-view v-slot="{ Component, route }">
  <Transition name="sfx-page" mode="out-in">
    <component :is="Component" :key="route.path" />
  </Transition>
</router-view>
```

## 6.4 关键反模式：key 滥用导致组件重挂载

[CourseLayout.vue](./frontend/src/app/pages/course/CourseLayout.vue) 的 `<router-view>` **不得**使用 `:key="route.path"`：

```vue
<!-- ❌ 错误：BuildLayout 会被反复销毁重建，导致轮询定时器重置、动画抖动、菜单消失 -->
<router-view v-slot="{ Component }">
  <Transition name="sfx-page" mode="out-in">
    <component :is="Component" :key="route.path" />
  </Transition>
</router-view>

<!-- ✅ 正确：依赖组件类型自动复用，BuildLayout 只挂载一次 -->
<router-view v-slot="{ Component }">
  <Transition name="sfx-page" mode="out-in">
    <component :is="Component" />
  </Transition>
</router-view>
```

`key` 只应在需要强制重挂载的最内层 `<router-view>` 上使用（如 [BuildLayout.vue](./frontend/src/app/pages/course/build/BuildLayout.vue) 内部的 step 切换），中间层 `<router-view>` 必须保持无 key。

## 6.5 可选升级：交叉淡入淡出

如未来需要进一步消除"空白感"，可将 8 处 `<Transition>` 改为非 `out-in` 模式（交叉淡入淡出），并在父容器添加 `position: relative`，新组件 `position: absolute` 叠加渲染。**当前 240ms 总感知已足够流畅，非必要不升级**。

---

# 7. 助教智能体面板规范

## 7.1 命名约定

- **统一名称**：助教智能体（**禁止**使用"备课 Agent"、"AI 助手"、"Chat Bot"等别名）。
- 前端触发按钮文案：`打开助教智能体`。
- 面板组件：[CourseBuildAgentPanel.vue](./frontend/src/app/pages/course/build/CourseBuildAgentPanel.vue)。

## 7.2 宽度与拖拽

- 默认宽度：`--agent-panel-width: 460px`。
- 可拖拽范围：360px – 640px。
- 调整手柄必须作为面板左侧的独立元素，与面板共同作为 grid 的第三列；不得作为 grid 的独立第四列子元素（曾导致布局错乱）。

参考结构：

```text
.build-grid (grid: 236px | 1fr | auto)
└── 第三列 = flex row
    ├── .agent-resizer（拖拽手柄，width:6px, cursor:col-resize）
    └── CourseBuildAgentPanel
```

## 7.3 内容溢出与独立滚动

- 面板根容器 `overflow: hidden`。
- 消息列表区 `flex: 1; min-height: 0; overflow-y: auto`。
- 输入区 `flex-shrink: 0`，固定在底部。
- 输入框 `resize: none`，由内部 auto-expand 控制高度。

## 7.4 思考气泡（Thought 气泡）

智能体处理中时显示思考气泡，结构固定为：头像（脉冲动画） + 思考点动画 + 文案。

```css
.thinking-avatar { animation: thinking-pulse 1.5s ease-in-out infinite; }
.thinking-dots span {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--ink-500);
  animation: thinking-bounce 1.4s ease-in-out infinite;
}
.thinking-dots span:nth-child(2) { animation-delay: 0.16s; }
.thinking-dots span:nth-child(3) { animation-delay: 0.32s; }
```

> 思考点动画的 `thinking-bounce` 是 §4 中"装饰性曲线"的唯一例外，仅用于智能体状态指示。

## 7.5 "让智能体调整"按钮行为

按钮不得只打开面板而不发送指令。必须通过 `workbench.pendingInstruction` 传递指令字符串，并由 AgentPanel 监听后自动发送当前选中节点的调整请求。同时通过 `workbench.pendingNodeId` 标记目标节点，避免指令发送期间用户切换节点导致错位。自由文本不再由前端或后端关键词正则猜测 action：未传显式 action 时由 Prep 结构化意图路由器基于完整语义判断五种既有 action；低置信度、范围不明、多意图冲突或路由模型不可用时必须澄清/报错，不得猜测。

## 7.6 全量一键优化行为

- `一键整理结构` 与 `一键优化讲解` 是教师主动触发的低风险草稿批量编辑，不进入待确认提案区。
- 后端必须覆盖全部未锁定目标；任一批次未完整覆盖时整体失败，不能只应用前若干节点。
- 批量操作仍需保存已接受的审计记录，锁定节点必须排除并在结果中明确显示。
- 单节点自然语言调整继续走待审核提案流程，两种交互不得混用；只有意图路由器以至少 0.90 置信度识别出教师明确授权的全课程结构/讲稿批量直接应用时，才复用批量原子写入链路，其余批量文本仍生成待审核提案。
- 一键入口调用 batch API 前，先在当前 `agentMessages` 会话写入一条带 `source: "quick_action"`、对应 `action` 与 `executionMode: "immediate_apply"` 的本地教师消息，文案明确“授权完成后直接应用”，并以 `SfxBadge` 显示“一键操作 · 已授权直接应用”；随后再写入运行中的智能体消息。该消息不持久化，普通用户消息不变。

---

# 8. 建设页面 stageActions 机制

[BuildLayout.vue](./frontend/src/app/pages/course/build/BuildLayout.vue) 顶部 `.stage-context-actions` 区域通过 `workbench.stageActions` 与子页面解耦：

```js
// 子页面 onMounted 时注册
const workbench = inject('courseBuildWorkbench')
onMounted(() => {
  workbench.stageActions.value = {
    canAdd: true,
    canDelete: selected.value !== null,
    canOrganize: nodes.value.length > 0,
    canRefresh: true,
    onAdd: addNode,
    onDelete: deleteNode,
    onOrganize: organizeAll,
    onRefresh: load,
    organizing: false,
    deleting: false,
    refreshing: false,
    addLabel: '新增节点',
    organizeLabel: '智能体一键整理',
    refreshLabel: '刷新状态',
  }
})
onBeforeUnmount(() => { workbench.stageActions.value = null })
```

**强制规则**：

1. 子页面必须在 `onMounted` 中注册 `stageActions`，在 `onBeforeUnmount` 中清空，避免泄露到下一页面。
2. 按钮可见性由字段是否存在决定（`v-if="stageActions.canAdd !== undefined"`），子页面不展示的能力直接不设置该字段。
3. 删除节点按钮必须实现二次确认（见 §9.2）。
4. 智能体一键整理按钮文案默认为"智能体一键整理"，可通过 `organizeLabel` 覆盖。

---

# 9. 按钮与交互规范

## 9.1 统一按钮组件

**所有按钮必须使用 [SfxButton.vue](./frontend/src/app/ui/SfxButton.vue)**，禁止使用原生 `<button>` 元素或自造样式类（除导航链接、icon-only 按钮等特殊场景）。

```vue
<SfxButton variant="primary" size="md" :loading="saving" @click="save">保存</SfxButton>
<SfxButton variant="secondary" size="sm" :disabled="!canEdit" @click="preview">预览</SfxButton>
<SfxButton variant="danger" size="sm" :loading="deleting" @click="requestDelete">删除节点</SfxButton>
<SfxButton variant="tertiary" size="sm" @click="cancel">取消</SfxButton>
```

| variant | 用途 | 视觉 |
|---|---|---|
| `primary` | 主操作（保存、提交、运行） | 墨蓝实心 |
| `secondary` | 次级操作（预览、刷新、整理） | 白底墨蓝字 + 灰边 |
| `tertiary` | 文字按钮（取消、查看原文） | 无背景无边框 |
| `danger` | 不可逆高风险操作 | 白底红字红边；最终确认模态中才允许红色实心 |

| size | 高度 | 用途 |
|---|---|---|
| `md` | 40px | 默认页面操作 |
| `sm` | 32px | 工具条、stage actions、面板内操作 |

## 9.2 二次确认模式

删除节点等不可逆操作必须使用"两段式点击"二次确认，不使用 `window.confirm`：

```js
const confirmDelete = ref(false)
watch([selectedNode, () => route.path], () => { confirmDelete.value = false })
function requestDelete() {
  if (!stageActions.value?.canDelete) return
  if (!confirmDelete.value) { confirmDelete.value = true; return }  // 第一次点击：切换文案
  confirmDelete.value = false
  stageActions.value.onDelete?.()                                    // 第二次点击：执行
}
```

按钮文案随状态切换：`删除节点` → `确认删除？`。切换选中节点或路由时自动重置 `confirmDelete`。

## 9.3 锁定/解锁切换

锁定按钮必须实现"锁定 / 取消锁定"双向切换，不得只支持单向锁定：

```vue
<SfxButton variant="secondary" size="sm" @click="toggleLock(node)">
  <LockKeyhole v-if="node.locked" :size="14" /> 取消锁定
  <LockOpen v-else :size="14" /> 锁定
</SfxButton>
```

## 9.4 Icon Button

- 36×36 或 40×40px
- 点击目标不小于 40px
- 必须提供 `aria-label` 或 Tooltip

---

# 10. 首次智慧备课等待状态

当 `workbench.draftBuildPhase` 处于以下阶段时，structure / scripts / mapping 三个子页面必须显示"智能体首次智慧备课中"等待视图：

```js
const FIRST_PREP_PHASES = new Set([
  'parsing_materials',
  'assembling_corpus',
  'submitting_build',
  'building',
])
```

## 10.1 轮询机制

由 [BuildLayout.vue](./frontend/src/app/pages/course/build/BuildLayout.vue) 统一通过 `getDraftBuildStatus(courseId)` 轮询，间隔 5000ms：

- `onMounted` 启动轮询。
- `onBeforeUnmount` 清理定时器。
- `watch(courseId)` 切换课程时重置并重新轮询。
- 轮询失败时 `draftBuildPhase` 静默置空，不阻塞页面渲染。

## 10.2 等待视图样式

```vue
<div class="first-prep-pending" role="status" aria-live="polite">
  <div class="first-prep-icon" aria-hidden="true"><Sparkles :size="26" :stroke-width="1.8" /></div>
  <h3>智能体首次智慧备课中</h3>
  <p>助教智能体正在解析课程材料，并整理目录草稿与知识点结构。完成后此处会自动呈现可编辑的课程结构。</p>
  <div class="first-prep-progress" aria-hidden="true"><span></span><span></span><span></span></div>
</div>
```

样式要点：

- 居中栅格布局，`gap: var(--space-3)`，`padding: var(--space-12) var(--space-5)`。
- 图标 56×56 圆形 `ink-100` 背景 + `ink-700` 图标色，配 `first-prep-pulse` 1.6s 脉冲动画。
- 三个进度点 8×8 圆形，`first-prep-bounce` 1.2s 上下浮动，依次延迟 0/0.16/0.32s。
- 必须有 `role="status"` 与 `aria-live="polite"`，供屏幕阅读器播报。

`first-prep-pulse` 动画规范（v0.5 起统一，禁止用阴影模拟脉冲）：

- 三个页面（BuildStructurePage / BuildScriptsPage / BuildMappingPage）共用同一 keyframes，必须保持一致
- 不使用 `box-shadow: 0 0 0 Npx rgba(...)` 扩散阴影做脉冲（视觉噪点重，与 Quiet Technology 冲突）
- 改用 `transform: scale(1) → scale(1.06)` 微缩放 + `opacity: 0.85 → 1` 透明度变化维持脉冲感
- 完整 keyframes：`@keyframes first-prep-pulse{0%,100%{transform:scale(1);opacity:.85}50%{transform:scale(1.06);opacity:1}}`

---

# 11. 已删除组件与历史决策

> 本节记录为了空间利用或视觉一致性而删除的组件，避免后续 Agent 误恢复。

## 11.1 LearnContextBar（学习上下文条）

- **位置**：原 [`frontend/src/app/components/learn/LearnContextBar.vue`](./frontend/src/app/components/learn/LearnContextBar.vue)
- **删除原因**：与二级菜单功能重叠，挤压页面空间，视觉冗余。
- **DOM 选择器**：`document.querySelector("#app > div > main > div > div.sfx-learn > div.sfx-learn-bar")`。
- **后续规则**：禁止以任何形式恢复学习上下文条；学习页面顶部直接由二级菜单承担课程上下文。

## 11.2 --contextbar-height 令牌

- **位置**：原 [`frontend/src/app/styles/tokens.css`](./frontend/src/app/styles/tokens.css) §3.3。
- **删除原因**：上下文条删除后该令牌无消费者。
- **后续规则**：禁止重新引入 `--contextbar-height` 令牌；二级菜单高度由 `--nav-l2-height` (44px) 统一承担。

## 11.3 全屏模式（isFullscreen / toggleFullscreen）

- **位置**：原 [LearnPage.vue](./frontend/src/app/pages/learn/LearnPage.vue) 中的 `isFullscreen` ref 与 `toggleFullscreen` 函数。
- **删除原因**：与现代浏览器原生全屏（F11）功能重复，且维护成本高。
- **后续规则**：禁止在前端引入自定义全屏切换；如需沉浸模式，通过二级菜单隐藏或路由布局调整实现。

## 11.4 "备课 Agent" 命名

- **替换**：全部替换为"助教智能体"。
- **范围**：包括按钮文案、面板标题、状态提示、注释、变量名（`agentOpen` 保留，但 `备课Agent` 字符串必须替换）。
- **后续规则**：禁止在新代码或注释中使用"备课 Agent"字样；所有面向用户的"Agent"统一改为"智能体"。

## 11.5 讲解栏 PPT 缩略图（原数字人位）

- **位置**：[LectureStage.vue](./frontend/src/app/components/learn/LectureStage.vue) "讲解与字幕"栏内的 `.sfx-stage-lecture-ppt`（含智能体面板打开时的缩略图分支）。
- **删除原因**：数字人移除后该位置临时改为展示 PPT，与右栏"同步课件"内容重复；讲解原文被压缩为 178px 小条，浪费左栏阅读空间。
- **后续规则**：讲解与字幕栏只承载讲解原文（占满整栏，字号 `--ui-md-size`）；兼容视频仅在无音频的旧课程回退显示并压缩原文条；PPT 统一由右栏"同步课件"展示，禁止在讲解栏恢复 PPT 缩略图或数字人。

---

# 12. 组件样式细则

## 12.1 圆角体系

| Token | 数值 | 用途 |
|---|---:|---|
| `radius-xs` | 4px | 状态条、代码小标签 |
| `radius-sm` | 6px | 标签、紧凑输入 |
| `radius-md` | 10px | 按钮、输入框 |
| `radius-lg` | 14px | 课程卡片、面板 |
| `radius-xl` | 18px | 主舞台、抽屉、模态 |
| `radius-full` | 999px | 状态圆点、少量胶囊 |

规则：

- 禁止全产品所有元素统一使用大圆角。
- 表格、导航和代码区使用较小圆角或直角。
- 原文引用块只在右侧使用圆角，保留编辑出版物感。

## 12.2 阴影体系

```css
--shadow-xs: 0 1px 2px rgba(16, 26, 49, 0.04);
--shadow-sm: 0 4px 12px rgba(16, 26, 49, 0.06);
--shadow-md: 0 12px 32px rgba(16, 26, 49, 0.10);
```

规则：

- 普通卡片默认只使用边框，不使用阴影。
- Hover 卡片可使用 `shadow-xs`。
- 抽屉、悬浮 Local Rail、模态使用 `shadow-sm` 或 `shadow-md`。
- 禁止发光、霓虹、多层重阴影和大面积玻璃拟态。

### 禁止用 3px 色条作为状态高亮（v0.5 起）

`border-left: 3px solid <color>` 和 `box-shadow: inset 3px 0 0 <color>` 在视觉上构成左侧 3px 实色条，等同阴影条，禁止用作"选中态/当前态/进行中态"等状态高亮。这类状态必须改用以下两种方式之一：

1. **`::before` 伪元素状态线**（首选，用于行/项选中态）：
   ```css
   .row { position: relative; }
   .row.selected { background: var(--ink-100); color: var(--ink-900); }
   .row.selected::before {
     position: absolute; left: 0; top: var(--space-2); bottom: var(--space-2);
     width: 3px; background: var(--ink-900); content: ""; border-radius: var(--radius-full);
   }
   ```
   `::before` 是独立伪元素，不参与 `overflow` 裁剪、不污染 `box-shadow`，且能配合 `border-radius` 形成圆角状态线，视觉比硬边色条更柔和。
2. **整框语义色边框**（用于状态提示盒/警告盒）：
   ```css
   .status-box.failed { border: 1px solid var(--amber-300); background: var(--amber-50); color: var(--amber-700); }
   ```

**例外（保留 3px 左边框）**：原文引用块、Citation、Source Summary、Agent Citations 等"引用语义"块沿用 §12.4 原文引用块规范，仍用 `border-left: 3px solid var(--ink-500)` 表达引用语义，不属于状态高亮。

**已清理的主代码位置**（v0.5）：

- `BuildMaterialsPage.vue` `.draft-build-status` 系列状态条 → 整框中性/amber 边框
- `BuildStructurePage.vue` `.outline-row.selected` → `::before` 状态线
- `BuildScriptsPage.vue` `.script-row.selected` → `::before` 状态线
- `LearningTrack.vue` `.sfx-track-item.is-current` → `::before` 状态线（见 §12.5）
- `BuildLayout.vue` `.build-link.active` → `::before` 状态线（见 §12.5）
- `first-prep-pulse` 动画 → 去掉 `box-shadow` 扩散，改用 `scale + opacity`（见 §10.2）

**未清理的历史代码**（`prototypes/`、`views/`、`features/student-learning/styles/learning-workspace.css` 等非主代码）：在重构到主代码时一并清理，新代码不得复用其 3px 色条模式。

## 12.3 输入框与选择控件

- 标准高度：40px（`--control-height`）
- 圆角：10px（`--radius-md`）
- 默认边框：`--border-default`
- Hover 边框：`--border-strong`
- Focus：`border-color: var(--color-focus); box-shadow: 0 0 0 2px var(--ink-100)`
- Placeholder：`--text-muted`
- 错误状态必须同时显示图标和错误文案
- 大型智能体提问框高度：44–48px，可自动扩展为多行

## 12.4 卡片与面板

### 普通卡片

```css
background: var(--surface-panel);
border: 1px solid var(--border-default);
border-radius: var(--radius-lg);
padding: var(--space-6);
```

使用场景：课程卡片、实验卡片、关键状态摘要。

规则：

- 卡片不是默认布局容器。
- 普通信息分组优先用留白和分割线。
- 禁止卡片套卡片。

### 主工作面板

- 背景：`--surface-panel`
- 边框：`--border-default`
- 圆角：14–18px
- 内边距：24px
- 编辑器、知识画布可取消内边距，由内部工具条控制

### AI 回应面板

- 右侧滑入
- 宽度：420–480px
- 白色背景
- 左边框 `1px solid var(--border-strong)`
- 左上和左下圆角：18px
- 阴影：`--shadow-sm`

视觉结构固定为：

1. 当前问题
2. 系统观察
3. 解释或回答
4. 原文引用 / 运行依据
5. 下一步教学行动
6. 输入区

它不是社交聊天气泡墙。

### 原文引用块

```css
background: var(--surface-cool);
border-left: 3px solid var(--color-focus);
padding: var(--space-3) var(--space-4);
border-radius: 0 var(--radius-md) var(--radius-md) 0;
```

内部使用：

- Evidence ID：`ui-sm` / 等宽字体
- 来源标题：`ui-md` / 500
- 原文：`body-md`
- 页码和状态：`caption`

## 12.5 导航栏

### 一级导航

- 高度：56px（`--nav-l1-height`）
- 背景：白色或 `--surface-page`
- 底边框：`1px solid var(--border-default`
- 当前项：`ink-900` 文字 + 2px 底部状态线
- 不使用大胶囊包裹每一个菜单项

### 二级导航

- 高度：44px（`--nav-l2-height`）
- 只承载当前空间的主要任务
- 当前项使用墨蓝文字和底部短线
- 页面顶部不得出现第三层横向菜单

### Local Rail / 学习轨道 / 建设侧栏

学习轨道（`.sfx-track` / LearningTrack.vue）与建设侧栏（`.build-rail` / BuildLayout.vue）共享同一套交互与视觉规范。

**容器布局**（与 `.sfx-learn` 三层 flex 一致，不卡片化）：

- 外层 `.sfx-learn` / `.build-workspace`：`flex:1; min-height:0; display:flex; flex-direction:column; overflow:hidden`，不设 `width:min(...)` / `margin:auto` / `padding`，直接撑满 main
- 中间层 `.sfx-learn-body` / `.build-grid`：`flex:1; display:flex; overflow:hidden; position:relative`，rail 与 stage 直接相邻，由 `border-right` 分隔
- 展开宽度：`--rail-width`（232px）；收缩宽度：`--rail-width-collapsed`（56px）
- 背景 `--surface-soft`，右边框 `--border-default`
- aside 容器加 `z-index:1` 建立 stacking context，让收起按钮能盖住右侧 stage
- `transition: width var(--duration-normal) var(--ease-out)` 平滑收缩

**收起按钮（圆形浮按钮，统一规范）**：

- 不再用 sticky 全宽 36px 横条；改为 26×26 圆形浮按钮（`border-radius: var(--radius-full)`）
- 位置：`position:absolute; top: var(--space-3)`，水平落在 rail 与 stage 边界上（学习轨道用 `right:-13px`，建设侧栏用 `left:calc(var(--rail-width) - 13px)` 并随收缩态切换 `left:calc(var(--rail-width-collapsed) - 13px)`）
- 视觉：`background: var(--surface-panel)` + 1px `--border-default` 边框，hover 时边框加深为 `--border-strong`、文字变 `--ink-700`
- 图标：展开态 `ChevronLeft`，收缩态 `ChevronRight`（lucide-vue-next，size 16）
- `z-index: 30`，避免被相邻 stage 遮挡
- 按钮必须是 rail 父级（`.build-grid` / `.sfx-track` 的定位上下文）的直接子元素，不能放在 `overflow-y:auto` 的滚动容器内部，否则会被横向裁剪

**滚动职责**：

- aside 容器不直接 `overflow-y:auto`（避免 `overflow-x` 隐式变 auto 裁掉浮按钮）
- 滚动由内部列表承担：学习轨道 `.sfx-track-list` (`flex:1; min-height:0; overflow-y:auto`)，建设侧栏 `.build-rail` 内部 grid 仍可滚动

**收起状态持久化**：

- 用户手动选择后按设备记忆，避免刷新丢失
- 学习轨道：`localStorage["sfx:rail:learn"]`（`'1'` = 收起，`'0'`/缺失 = 展开）
- 建设侧栏：`localStorage["sfx:rail:build"]`（同上）
- 首次访问（无 localStorage 值）回退到自动判断：学习轨道由 `learnState !== LEARN` 决定，建设侧栏默认展开

**当前项高亮（统一规范，禁止用阴影模拟）**：

- 背景：`var(--ink-100)`；文字：`var(--ink-900)`
- 左侧 3px 状态线用 `::before` 伪元素实现（不用 `box-shadow: inset 3px 0 0`）：
  - `position:absolute; left:0; top/bottom: var(--space-2); width:3px; background: var(--ink-900); border-radius: var(--radius-full)`
- 学习轨道 current 态额外把左侧 status 圆圈变为实色反白徽章：`.sfx-track-item.is-current .sfx-track-item-status { background: var(--ink-900); color: var(--surface-panel); border-radius: var(--radius-full) }`

**学生学习状态可见性（2026-08-08）**：

- 学习轨道必须同时展示学习状态与认知状态，不能以观看完成替代掌握结论。
- `advanced/proficient` 用 Check + “已掌握”；`developing/beginner` 用提示图标 + “待掌握”；`unknown` 用 Help + “需要更多证据”；无映射用 Info + “暂不可分析”。
- 图标、文字、`aria-label` 和 tooltip 必须共同表达语义，颜色不能单独承担状态。
- 认知详情采用轨道内联展开；默认只请求聚合 `learning-context`，点击状态详情后按需读取认知六维接口。
- 建设侧栏 active 态保留原 step-index / step-copy / icon 视觉，仅在 `::before` 上对齐状态线规范

**收缩态视觉**：

- 只显示图标与状态点
- Hover 展示名称（`title` 属性）
- 沉浸任务中手动展开时以悬浮层覆盖，不挤压主舞台
- 760px 以下移动端隐藏收起按钮（移动端 rail 是横向滚动条，不收起）

**响应式**：

- `@media(max-width:1250px)`：建设侧栏 agent 面板 `display:none`（agent-is-open 时让 agent `flex:1; width:auto` 占满）
- `@media(max-width:760px)`：`flex-direction:column`，rail 用 `width:100%`，隐藏收起按钮

## 12.6 状态徽标

状态徽标必须包含：图标 + 文字 + 颜色。

示例：

- `✓ 已确认`
- `◷ 待审核`
- `! 证据不足`
- `× 任务失败`
- `◇ 实验能力`
- `△ 研究预览`

规则：

- 不使用仅有颜色的小圆点表达关键状态。
- 胶囊高度建议 24px，横向内边距 8px，圆角 6px。

## 12.7 表格与任务列表

### 表格

- 默认行高：44px
- Compact：36px
- 表头使用弱背景 `--surface-cool`
- 支持粘性表头
- 批量操作固定在表格上方
- 状态列使用图标 + 文字
- 长文字支持展开，不强制单行截断核心内容

### Task Row

任务中心优先使用列表，而不是卡片墙。

一行包括：

- 任务名称
- 来源对象
- 状态
- 截止或更新时间
- 一个主操作
- 更多操作菜单

## 12.8 抽屉和模态

### Drawer

- 宽度：420 / 480 / 640px
- 从右侧进入
- 圆角：18px 0 0 18px
- 保留触发页面上下文
- 关闭后焦点返回触发按钮

用于：加入课程、详情、审核、临时设置。

### Modal

- 仅用于高风险确认、短表单和阻塞式决定
- 不用于长篇阅读和复杂编辑
- 最大宽度 560–720px

## 12.9 代码工作区

- 代码编辑器采用深色背景
- 周围课程上下文、任务目标和安全状态保持浅色 App Shell
- 测试通过使用绿色图标与文字
- 编译错误和运行错误使用砖红色，但不大面积铺红
- 学生只看到 TeachingAgent，不出现独立 CodingAgent 品牌或角色切换
- 对话挑战卡原地经历 preparing / ready / failed / dismissed；异步准备不阻塞正文回答
- 工作区只有一个主操作“运行并获得反馈”，`Ctrl/Cmd+Enter` 必须调用同一路径；不拆分“运行/提交”
- 桌面使用题目 / 编辑器 / 结果三栏；移动端纵向自然高度排列，题面不得因 flex 收缩而消失
- 必须可见：为什么现在、公开样例、运行结果、TeachingAgent 反馈、返回课程入口
- 反馈分区固定为结果概览、已做对的部分、当前问题、下一步建议、按需展开的可选提示；提示未展开前不下发文本、不计提示使用，不展示隐藏测试 I/O 或复述源码
- 进入时暂停媒体并冻结 return anchor，退出后恢复到精确播放位置；刷新恢复当前 offer/session，不串接旧 run_id

## 12.10 知识图谱

- 默认局部邻域，不显示全量毛线球
- 当前节点视觉焦点唯一
- 同类节点样式一致
- 非相关节点降低透明度
- 关系至少使用颜色 + 线型 + 箭头/图标三重编码
- Evidence 只显示锚点，点击后打开原文引用
- 图谱操作工具条使用纯净现代 UI，不使用手绘按钮

推荐关系视觉：

| 关系 | 颜色 | 线型 | 端点 |
|---|---|---|---|
| 先修 | Learning Green | 实线 | 三角箭头 |
| 推荐 / 推导 | Academic Ink | 实线 | 开放箭头 |
| Evidence | 灰蓝 | 点线 | 文档图标 |
| 易错关联 | Annotation Red | 短虚线 | 警示图标 |
| 相似概念 | 中性灰 | 细线 | 圆点 |

## 12.11 Toast / 轻提示

全局轻提示（`frontend/src/utils/toast.js` 的 `showToast(message, type)`）用于网络错误、保存成功等短暂反馈。统一规范：

**视觉（极简，禁止附加装饰）**：

- 浅底深字：背景用语义色 `-100`，文字用语义色 `-700`
- 不加阴影（`box-shadow: none`）
- 不加左侧深色长条
- 不加图标（含叉号、勾选、感叹等）
- 仅保留 1px `--border-default` 边框 + `--radius-md` 圆角

**类型映射**：

| type | 背景 | 文字 |
|---|---|---|
| success | `--green-100` | `--green-700` |
| error | `--red-100` | `--red-700` |
| warning | `--amber-100` | `--amber-700` |
| info | `--ink-100` | `--ink-700` |

**位置与动效**：

- 顶部居中：`top: 24px; left: 50%; transform: translateX(-50%)`
- Quiet Technology：240ms `--ease-out`，仅 12px 微位移，加 `prefers-reduced-motion` 支持
- 3 秒自动消失

**无障碍**：

- error 用 `role="alert"`，其他用 `role="status"`，配 `aria-live`
- 文本走 `textContent` 防 XSS

**调用约定**：

- 签名 `showToast(message, type='warning')` 不变，所有调用方（request.js / useStudentLearning.js / CourseTaskPanel.vue 等）无需修改
- 不用于关键教学决策反馈，关键决策走 [SfxError](./frontend/src/app/ui/SfxError.vue) 或模态

---

# 13. 路由与根路径跳转

- 访问根路径 `/` 必须自动重定向到 `/app`，由 [router/index.js](./frontend/src/router/index.js) 配置。
- `/app` 是登录后应用主入口，对应 [AppShell.vue](./frontend/src/app/shell/AppShell.vue)。
- 课程相关路由前缀：`/app/course/:courseId/`，二级菜单由 [CourseLayout.vue](./frontend/src/app/pages/course/CourseLayout.vue) 承载。
- 建设子路由前缀：`/app/course/:courseId/build/:step`，step ∈ `materials | structure | scripts | mapping | media | validate | releases`。
- CourseLayout 二级导航返回按钮（`.sfx-l2nav > div > div > button`）的目标必须按当前路由路径判断：
  - 当前在 `/build/*` 下 → 回到 `/app/courses/building`（"我建设的"）
  - 其他子页面（overview/learn/knowledge/experiments/members/settings）→ 回到 `/app/courses/learning`（"我学习的"）
  - 不允许硬编码任一固定目标，否则教师在建设页点返回会被错误带去学习列表。

---

# 14. 视觉验收底线

任何页面交付前至少确认：

- 主操作是否唯一且清晰；
- 课程正文是否达到 16px；
- 核心信息是否具有足够对比度；
- 状态是否不仅依赖颜色；
- 卡片、圆角和阴影是否被克制使用；
- 页面是否能连续使用两小时而不过度疲劳；
- 代码、知识图谱和原文引用是否仍属于同一个产品语言；
- **整页是否不出现浏览器滚动条**（仅 `.sfx-shell-main` 滚动）；
- **路由切换是否无抽搐抖动**（仅 opacity 过渡，无 transform 位移）；
- **按钮是否全部使用 SfxButton**（无原生 `<button>` 散落）；
- **删除类操作是否有二次确认**；
- **页面实现是否引用本文件令牌**，而不是随手增加新的 Hex、字号和圆角。

---

# 15. 实现参考索引

| 主题 | 文件 |
|---|---|
| 全局令牌 | [frontend/src/app/styles/tokens.css](./frontend/src/app/styles/tokens.css) |
| 基础样式与页面过渡 | [frontend/src/app/styles/base.css](./frontend/src/app/styles/base.css) |
| 应用 Shell | [frontend/src/app/shell/AppShell.vue](./frontend/src/app/shell/AppShell.vue) |
| 一级导航 | [frontend/src/app/shell/PrimaryNav.vue](./frontend/src/app/shell/PrimaryNav.vue) |
| 课程布局（二级导航） | [frontend/src/app/pages/course/CourseLayout.vue](./frontend/src/app/pages/course/CourseLayout.vue) |
| 建设布局 | [frontend/src/app/pages/course/build/BuildLayout.vue](./frontend/src/app/pages/course/build/BuildLayout.vue) |
| 课程结构页 | [frontend/src/app/pages/course/build/BuildStructurePage.vue](./frontend/src/app/pages/course/build/BuildStructurePage.vue) |
| 讲授脚本页 | [frontend/src/app/pages/course/build/BuildScriptsPage.vue](./frontend/src/app/pages/course/build/BuildScriptsPage.vue) |
| PPT 映射页 | [frontend/src/app/pages/course/build/BuildMappingPage.vue](./frontend/src/app/pages/course/build/BuildMappingPage.vue) |
| 助教智能体面板 | [frontend/src/app/pages/course/build/CourseBuildAgentPanel.vue](./frontend/src/app/pages/course/build/CourseBuildAgentPanel.vue) |
| 按钮组件 | [frontend/src/app/ui/SfxButton.vue](./frontend/src/app/ui/SfxButton.vue) |
| 路由配置 | [frontend/src/router/index.js](./frontend/src/router/index.js) |
| 页面信息架构 | [page-design.md](./page-design.md) |
