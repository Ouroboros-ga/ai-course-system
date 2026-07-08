# M5C 前端阻断缺陷修复报告

更新时间：2026-07-08

## 1. 修复的问题

### 已修复：分屏播放器初始化响应契约

M5 确认的 P0 风险来自以下调用链：

- 前端：`frontend/src/components/chat/player/SplitVideoPlayer.vue` 调用 `getPlayerInitData(courseId)` 后按 `response.data` 读取播放器数据。
- API 封装：`frontend/src/api/player.js` 原先直接返回 `request.get('/player/init/{courseId}')`。
- 请求拦截：`frontend/src/utils/request.js` 只接受统一响应外壳，要求 `res.code === 200`，成功时返回 `res.data`。
- 后端：`backend/app/api/v1/endpoints/player.py` 的 `GET /api/v1/player/init/{course_id}` 返回 `PlayerInitData` 扁平结构；`backend/tests/test_m4b_main_flows.py` 已按扁平结构断言 `player_payload['course_id']` 和 `player_payload['nodes']`。

修复方式：在 `request.js` 增加 `allowFlatResponse` opt-in 兼容开关，仅当单个请求显式设置该开关，并且响应体没有 `code` 字段时，返回扁平响应本体。`player.js` 只对 `/player/init/{courseId}` 使用该开关，并继续包装为 `{ data }`，保持 `SplitVideoPlayer.vue` 原有读取方式不变。

### 已修复：PPTGenerationDialog 响应读取

M5 确认的条件性高风险来自 `frontend/src/components/profile/LoginIn/courses/PPTGenerationDialog.vue`：组件按 `res.data.code` / `res.data.data` 读取 PPT 模板和同步生成结果，但 `request.js` 对统一响应成功结果会返回解包后的 `data`。

修复方式：只在该组件内兼容两种结构：

- 旧包裹结构：`res.data.data`
- 当前解包结构：`res`

模板列表读取改为 `themePayload?.templateList || themePayload?.templates || []`；同步生成读取改为检查 `payload?.course_id`，并从 `payload.course_id`、`payload.total_nodes`、`payload.total_duration` 填充结果。

## 2. 修改文件

| 文件 | 修改范围 | 说明 |
|---|---|---|
| `frontend/src/utils/request.js` | 响应拦截器新增 4 行 opt-in 分支 | 只在 `config.allowFlatResponse` 为真且响应无 `code` 字段时返回扁平响应；默认行为不变 |
| `frontend/src/api/player.js` | `getPlayerInitData` | 对 `/player/init/{courseId}` 启用 `allowFlatResponse`，并返回 `{ data }` 以兼容现有组件 |
| `frontend/src/components/profile/LoginIn/courses/PPTGenerationDialog.vue` | `loadTemplates`、`handleGenerate` | 兼容 request 解包后的 PPT 模板与生成结果数据 |

## 3. 修改前后响应结构说明

### 播放器初始化

修改前：

```js
// 后端实际返回
{
  course_id,
  course_title,
  script_id,
  total_duration,
  total_nodes,
  nodes,
  video_base_url,
  ppt_pages,
  slide_images,
  saved_progress
}

// request.js 期望
{ code: 200, message, data }
```

由于响应没有 `code`，会被 `request.js` 当成业务失败。

修改后：

```js
// player.js 内部
const data = await request.get(`/player/init/${courseId}`, { allowFlatResponse: true })
return { data }

// SplitVideoPlayer.vue 仍读取
response.data
```

后端扁平响应保持不变，前端只在播放器 init 这一条调用上兼容。

### PPT 模板和同步生成

修改前：

```js
res.data.code
res.data.data.templateList
res.data.data.course_id
```

但 `request.js` 成功时已经返回 `res.data`，组件拿到的是接口 `data` 本体。

修改后：

```js
const themePayload = res?.data?.data || res?.data || res
const payload = res?.data?.data || res?.data || res
```

因此可以同时兼容旧包裹结构和当前解包结构。

## 4. 是否改变后端 API

否。未修改任何后端 endpoint、service、model、schema、数据库结构或启动方式。

`GET /api/v1/player/init/{course_id}` 仍返回 `PlayerInitData` 扁平结构；M4B 后端测试继续按扁平结构验证。

## 5. 是否改变用户可见业务流程

否。未改变路由、页面布局、按钮、步骤流转和业务语义。

用户可见变化只体现在原本可能失败的播放器初始化和 PPT 结果读取现在能按现有后端响应继续走原流程。

## 6. 执行命令与结果

### 前端 build

受限沙箱首次执行：

```text
cd frontend
npm.cmd run build
```

结果：失败于 `Error: spawn EPERM`，发生在 Vite 加载配置时启动 esbuild 子进程，属于当前沙箱限制。

提升权限后重跑同一命令：

```text
cd frontend
npm.cmd run build
```

结果：通过。

```text
vite v7.3.1 building client environment for production...
2153 modules transformed.
✓ built in 3.42s
```

仍有历史体积警告：`markdown-C1N6mllq.js` 为 `1,271.47 kB`，gzip `401.37 kB`。

### lint

受限沙箱首次执行：

```text
cd frontend
npm.cmd run lint
```

结果：失败于 `ERROR: spawn EPERM`，属于当前沙箱限制。

提升权限后重跑：

```text
cd frontend
npm.cmd run lint
```

结果：失败，停在 `lint:oxlint`，共 16 个错误。错误仍是 M5 已记录的历史债，主要包括空占位文件和未使用变量/未使用 catch 参数。未为 lint 全绿扩大修复范围。

`lint --fix` 曾自动改动 `frontend/src/components/chat/panel/ChatPanel/MessageBubble.vue`，已单文件回滚；最终业务代码 diff 只剩 M5C 三个目标文件。

### 后端关键基线

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4a_isolation.py backend\tests\test_m4a_route_contract.py backend\tests\test_m4b_fakes.py backend\tests\test_m4b_main_flows.py -q
```

结果：通过。

```text
25 passed, 131 warnings in 3.28s
```

warnings 为既有 `datetime.utcnow()` 弃用、FastAPI duplicate operation id 等，不属于 M5C 修改引入。

### 静态验证

```text
rg -n "allowFlatResponse|res\.data\?\.code|res\.data\.data|getPlayerInitData|payload\?\.course_id|themePayload" frontend\src\utils\request.js frontend\src\api\player.js frontend\src\components\profile\LoginIn\courses\PPTGenerationDialog.vue frontend\src\components\chat\player\SplitVideoPlayer.vue
```

结果确认：

- `allowFlatResponse` 只出现在 `request.js` 和 `player.js` 的 `/player/init/{courseId}` 调用上。
- `PPTGenerationDialog.vue` 已不再读取 `res.data?.code` 或 `res.data.data`。
- `SplitVideoPlayer.vue` 仍通过 `getPlayerInitData` 后读取 `response.data`。

## 7. 仍未修复的问题

1. `npm.cmd run lint` 仍失败。M5C 不处理全量 lint 历史债。
2. `frontend/src/api/user.js` 的 `POST /user/logout` 后端不存在，本轮不处理。
3. `frontend/src/api/chat.js` 的 `DELETE /chat/${chatId}` 后端不存在，本轮不处理。
4. `Knowledge.vue` / `KnowledgeProgressPage.vue` 未注册路由且仍有缺失的 `api.chat` 方法，本轮不处理。
5. `PPTGenerationDialog.vue` 的“打开课程”按钮仍跳转 `/teacher?courseId={id}`；M5 路由矩阵显示当前教师编辑页为 `/teacher/course/:courseId`。该问题不是响应解包问题，本轮只记录，不扩大修复。
6. PPT 生成仍依赖外部 PPT 服务；自动化测试不得调用真实讯飞 PPT 或 LLM 服务。

## 8. 回滚方式

回滚 M5C 代码修改：

```text
git checkout -- frontend/src/utils/request.js frontend/src/api/player.js frontend/src/components/profile/LoginIn/courses/PPTGenerationDialog.vue
```

回滚 M5C 文档：

```text
git checkout -- docs/phase1/前后端API契约检查表.md docs/phase1/决赛演示页面矩阵.md
```

如果 `docs/phase1/M5C前端阻断缺陷修复报告.md` 尚未提交，可直接删除该文件。

## 9. 是否可以进入 R1 外部服务适配层重构

可以进入 R1，但建议进入前先完成一次人工冒烟：

1. 使用已有测试数据打开 `/player/course/{courseId}`，确认播放器能完成初始化并展示节点/PPT/视频占位或真实资源。
2. 若 8 月决赛要演示 AI PPT，使用可控 fake/mock 或明确可控真实服务人工验证模板加载、生成完成、错误提示和“打开课程”跳转。

M5C 已解决 M5 标记的响应解包阻断风险；R1 仍必须遵守“不调用真实付费服务做自动化测试”和“不改变公开 API”的阶段约束。