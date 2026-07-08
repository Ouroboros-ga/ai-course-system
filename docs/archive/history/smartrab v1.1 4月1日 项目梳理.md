## 待完善功能列表

1.







---

## 1. 核心业务

**用户登录后可上传课件文档，系统自动解析文档内容并生成AI智课脚本，用户可与AI助教进行基于文档内容的实时问答。**

---

## 2. 主要业务流程

### 流程 1：用户登录/注册

| 步骤      | 操作                                                         |
| --------- | ------------------------------------------------------------ |
| 前端输入  | 用户输入用户名、密码                                         |
| 前端校验  | 用户名：1-80位英文字母；密码：6-18位字母或数字               |
| 调用接口  | `POST /api/v1/user/login` 或 `POST /api/v1/user/register`    |
| 后端验证  | 查询数据库验证用户名密码 / 检查用户名是否已存在              |
| 生成Token | 使用 JWT 生成 `access_token`，包含 `user_id`, `username`, `role` |
| 前端存储  | `localStorage.setItem('token', res.token)`                   |
| 进入系统  | 更新 Pinia Store，显示用户信息                               |
| 后续请求  | 请求拦截器自动添加 `Authorization: Bearer <token>`           |

---

### 流程 2：上传文档生成智课

| 步骤       | 操作                                                         |
| ---------- | ------------------------------------------------------------ |
| 用户操作   | 点击上传区域选择文件（PDF/PPT/DOCX）或拖拽文件               |
| 前端校验   | 检查用户是否登录（`token` 是否存在）                         |
| 调用接口   | `POST /api/v1/chat/file/upload` (FormData: `file`, `fileName`, `userId`) |
| 后端认证   | JWT 验证用户身份                                             |
| 文件存储   | 保存到临时目录，检查文件大小（最大50MB）                     |
| 创建课程   | 写入 `courses` 表，`teacher_id` = 当前用户ID                 |
| 文档解析   | 调用 Docling 解析文档为 Markdown                             |
| AI生成脚本 | 调用豆包AI，基于 Markdown 生成智课脚本                       |
| 创建节点   | 拆分脚本为多个 `script_nodes` 记录                           |
| 创建聊天   | 创建 `ChatHistory` 记录，关联用户                            |
| 返回结果   | `chatId`, `courseId`, `fullContent`, `mindMapJson`           |
| 前端展示   | 显示解析内容、思维导图、启用AI聊天                           |

---

### 流程 3：AI问答（基于文档）

| 步骤       | 操作                                                         |
| ---------- | ------------------------------------------------------------ |
| 用户操作   | 在聊天框输入问题，点击发送                                   |
| 前端校验   | 检查 `hasFile && !isAnalyzing && hasValidData`               |
| 调用接口   | `POST /api/v1/chat/ask`                                      |
| 请求参数   | `question`, `chatId`, `courseId`                             |
| 后端处理   | 验证用户身份 → 查询会话权限                                  |
| 获取上下文 | 根据 `courseId` 查询 `DoclingDocument` 和 `CourseScript` 内容 |
| 构建消息   | System Prompt + 文档内容 + 历史消息（最近10条）              |
| 调用LLM    | 豆包AI生成回答                                               |
| 存储消息   | 用户问题 → `ChatMessage(role=user)`                          |
|            | AI回答 → `ChatMessage(role=assistant)`                       |
| 返回结果   | `answer`, `chatId`, `messageId`                              |
| 前端展示   | 添加AI消息到消息列表                                         |

---

### 流程 4：查看历史记录

| 步骤     | 操作                                                         |
| -------- | ------------------------------------------------------------ |
| 用户操作 | 点击侧边栏"历史对话"                                         |
| 调用接口 | `GET /api/v1/chat/history?userId=xxx&page=1&pageSize=20`     |
| 后端验证 | JWT 验证 + 检查 `userId` 是否匹配当前用户                    |
| 查询数据 | 从 `ChatHistory` 表查询用户的聊天记录                        |
| 返回结果 | 分页数据：`total`, `page`, `list[{id, content, createTime}]` |
| 前端展示 | 渲染历史记录列表                                             |

---

### 流程 5：权限控制流程

| 场景         | 处理逻辑                                            |
| ------------ | --------------------------------------------------- |
| 未登录访问   | 前端：`showToast('请先登录')`；后端：返回 401       |
| Token过期    | 后端验证失败返回 401，前端清除token跳转登录         |
| 访问他人数据 | 后端检查 `token_user_id != request.userId` 返回 403 |
| 删除记录     | 只能删除 `chat.user_id == current_user_id` 的记录   |

---

## 3. 关键业务规则

| 规则项                     | 实现方式                                                     |
| -------------------------- | ------------------------------------------------------------ |
| **密码加密**               | `bcrypt` 哈希存储，`get_password_hash()` 加密，`verify_password()` 验证 |
| **Token有效期**            | `ACCESS_TOKEN_EXPIRE_MINUTES = 30`（30分钟）                 |
| **文件大小限制**           | 最大 50MB，超限返回 `code=400`                               |
| **文件类型支持**           | PDF, DOCX, PPTX, TXT, MD 等（通过 Docling 或 fallback 解析） |
| **用户只能访问自己的数据** | 每个查询都检查 `current_user["user_id"]`                     |
| **AI上下文长度限制**       | 文档内容截断至 8000 字符，历史消息保留最近10条               |
| **聊天记录持久化**         | `ChatMessage` 表存储问答历史，支持多轮对话                   |
| **数据恢复机制**           | `localStorage` 保存 `currentData`，页面刷新后自动恢复        |

---

## 4. 数据流向图

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   用户上传   │────→│  文档解析    │────→│  AI生成脚本  │
│   (前端)    │     │  (Docling)  │     │  (豆包AI)   │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                                │
                       ┌────────────────────────┘
                       ↓
              ┌─────────────┐     ┌─────────────┐
              │  数据库存储  │←───→│  用户问答   │
              │  courses    │     │  (基于文档) │
              │  scripts    │     │             │
              │  nodes      │     └─────────────┘
              │  chat_hist  │
              │  chat_msg   │
              └─────────────┘
```

---

## 5. 核心实体关系

```
User (1) ────< (N) ChatHistory (会话)
                │
                └──< (N) ChatMessage (消息)

User (1) ────< (N) Course (课程/文档)
                │
                ├── (1) DoclingDocument (解析结果)
                │
                └──< (N) CourseScript (脚本版本)
                        │
                        └──< (N) ScriptNode (节点)
```









## *后端 API*



## 后端 API 接口映射表

| 模块         | 请求方法 | 接口路径                              | 功能说明                      | 权限（JWT） | 请求参数                                                     | 返回数据                                                     |
| ------------ | -------- | ------------------------------------- | ----------------------------- | ----------- | ------------------------------------------------------------ | :----------------------------------------------------------- |
| **健康检查** | GET      | `/`                                   | 服务健康检查                  | 无需        | -                                                            | `{version: "v1"}`                                            |
| **用户模块** | POST     | `/api/v1/user/login`                  | 用户登录获取Token             | 无需        | `username`, `password`                                       | `token`, `userInfo`                                          |
| **用户模块** | POST     | `/api/v1/user/register`               | 用户注册并自动登录            | 无需        | `username`, `password`                                       | `token`, `userInfo`                                          |
| **用户模块** | GET      | `/api/v1/user/me`                     | 获取当前用户信息              | **需要**    | -                                                            | 用户详情                                                     |
| **用户模块** | POST     | `/api/v1/user/modify`                 | 修改用户信息（用户名/密码）   | 无需        | `id`, `username`, `password`, `newUsername?`, `newPassword?` | `token`, `userInfo`                                          |
| **聊天模块** | GET      | `/api/v1/chat/history`                | 获取用户历史聊天记录（分页）  | **需要**    | `userId`, `page?`, `pageSize?`                               | `total`, `page`, `pageSize`, `list`                          |
| **聊天模块** | GET      | `/api/v1/chat/messages/{chat_id}`     | 获取会话中的所有消息          | **需要**    | `chat_id` (路径)                                             | `chatId`, `messages`                                         |
| **聊天模块** | POST     | `/api/v1/chat/ask`                    | AI问答（支持基于文档）        | **需要**    | `question`, `chatId?`, `courseId?`                           | `chatId`, `answer`, `messageId`                              |
| **聊天模块** | POST     | `/api/v1/chat/create`                 | 创建新的聊天记录              | **需要**    | `userId`, `content`                                          | 聊天记录对象                                                 |
| **聊天模块** | DELETE   | `/api/v1/chat/{chat_id}`              | 删除聊天记录及消息            | **需要**    | `chat_id` (路径), `userId`                                   | -                                                            |
| **文档处理** | POST     | `/api/v1/document/upload`             | 上传文档并解析生成智课        | **需要**    | `file` (FormData)                                            | `fullContent`, `title`, `audioUrl`, `mindMapJson`, `chatId`, `courseId` |
| **文档处理** | POST     | `/api/v1/document/analyze`            | 对已有文档进行AI分析          | 无需        | `document_id`                                                | `success`, `message`, `analysis`                             |
| **文档处理** | GET      | `/api/v1/document/{document_id}`      | 获取文档信息                  | 无需        | `document_id` (路径)                                         | 文档详情                                                     |
| **文档处理** | GET      | `/api/v1/document/course/{course_id}` | 获取课程完整详情              | 无需        | `course_id` (路径)                                           | 课程、脚本、节点详情                                         |
| **聊天模块** | POST     | `/api/v1/chat/file/upload`            | 上传文件（同document/upload） | **需要**    | `file` (FormData)                                            | 同上                                                         |

---

## 权限说明

### 无需 JWT 的api
- `GET /` - 健康检查
- `POST /api/v1/user/login` - 登录
- `POST /api/v1/user/register` - 注册
- `POST /api/v1/user/modify` - 修改用户信息
- `POST /api/v1/document/analyze` - 文档分析
- `GET /api/v1/document/{document_id}` - 获取文档
- `GET /api/v1/document/course/{course_id}` - 获取课程详情

###  需要 JWT 的api（需携带 `Authorization: Bearer <token>`）
| 接口                                  | 权限验证说明       |
| ------------------------------------- | ------------------ |
| `GET /api/v1/user/me`                 | 验证token有效性    |
| `GET /api/v1/chat/history`            | 只能查看自己的记录 |
| `GET /api/v1/chat/messages/{chat_id}` | 只能访问自己的会话 |
| `POST /api/v1/chat/ask`               | 用户身份验证       |
| `POST /api/v1/chat/create`            | 只能为自己创建     |
| `DELETE /api/v1/chat/{chat_id}`       | 只能删除自己的记录 |
| `POST /api/v1/document/upload`        | 用户身份验证       |
| `POST /api/v1/chat/file/upload`       | 用户身份验证       |

---

## 接口类型分类

### 查询接口（GET）
- `/` - 健康检查
- `/api/v1/user/me` - 获取当前用户
- `/api/v1/chat/history` - 历史记录列表
- `/api/v1/chat/messages/{chat_id}` - 会话消息
- `/api/v1/document/{document_id}` - 文档详情
- `/api/v1/document/course/{course_id}` - 课程详情

### 提交接口（POST）
- `/api/v1/user/login` - 登录
- `/api/v1/user/register` - 注册
- `/api/v1/user/modify` - 修改信息
- `/api/v1/chat/ask` - AI问答
- `/api/v1/chat/create` - 创建记录
- `/api/v1/document/upload` - 上传文档
- `/api/v1/document/analyze` - 分析文档
- `/api/v1/chat/file/upload` - 上传文件

### 删除接口（DELETE）
- `/api/v1/chat/{chat_id}` - 删除记录

---

## 路由前缀汇总

| 模块     | 前缀                | 实际完整路径示例           |
| -------- | ------------------- | -------------------------- |
| 用户模块 | `/api/v1/user`      | `/api/v1/user/login`       |
| 文档处理 | `/api/v1/document`  | `/api/v1/document/upload`  |
| 聊天模块 | `/api/v1/chat`      | `/api/v1/chat/history`     |
| 聊天文件 | `/api/v1/chat/file` | `/api/v1/chat/file/upload` |







### 前端功能api映射

## 前端功能 ↔ API 对应表

| 页面路径   | 页面名称 | 功能点           | 调用的 API | 触发方式                                    |
| ---------- | -------- | ---------------- | ---------- | ------------------------------------------- |
| `/` (Home) | 首页     | 页面滚动导航     | 无         | 点击滚动箭头                                |
| `/` (Home) | 首页     | 跳转到聊天页     | 无         | 点击"开始体验"按钮 → `router.push('/chat')` |
| `/chat`    | 聊天页   | 恢复上次会话数据 | 无         | `onMounted` 读取 `localStorage`             |
| `/chat`    | 聊天页   | 保存会话数据     | 无         | `watch` 自动保存到 `localStorage`           |
| `/chat`    | 聊天页   | 创建新会话       | 无         | 点击"新对话"按钮 → 清除本地数据             |
| `/chat`    | 聊天页   | 检测移动端布局   | 无         | `onMounted` + `resize` 事件监听             |
| `/profile` | 个人中心 | 恢复登录状态     | 无         | `onMounted` 读取 `localStorage`             |
| `/profile` | 个人中心 | 加载用户统计数据 | 无         | 登录后随机生成（模拟数据）                  |

---

## 组件级 API 调用详情

### UserIndex.vue (/profile 页面)
| 功能点     | 调用的 API                   | 触发方式     | 参数                                        |
| ---------- | ---------------------------- | ------------ | ------------------------------------------- |
| 用户登录   | `POST /api/v1/user/login`    | 点击登录按钮 | `username`, `password`                      |
| 用户注册   | `POST /api/v1/user/register` | 点击注册按钮 | `username`, `password`                      |
| 修改用户名 | `POST /api/v1/user/modify`   | 点击保存按钮 | `id`, `username`, `password`, `newUsername` |
| 修改密码   | `POST /api/v1/user/modify`   | 点击保存按钮 | `id`, `username`, `password`, `newPassword` |
| 退出登录   | 无                           | 点击退出按钮 | 清除 `localStorage` 和 Store                |

### PptPlayer.vue (Chat 页面组件)
| 功能点         | 调用的 API                      | 触发方式          | 参数                                    |
| -------------- | ------------------------------- | ----------------- | --------------------------------------- |
| 上传文件并解析 | `POST /api/v1/chat/file/upload` | 选择文件/拖拽文件 | `file`, `fileName`, `userId` (FormData) |

### ChatPanel.vue (Chat 页面组件)
| 功能点  | 调用的 API              | 触发方式      | 参数                               |
| ------- | ----------------------- | ------------- | ---------------------------------- |
| AI 问答 | `POST /api/v1/chat/ask` | 点击发送/回车 | `question`, `chatId?`, `courseId?` |

### ChatHistory.vue (Chat 页面组件)
| 功能点       | 调用的 API                 | 触发方式   | 说明           |
| ------------ | -------------------------- | ---------- | -------------- |
| 获取历史记录 | `GET /api/v1/chat/history` | **待实现** | 当前为模拟数据 |
| 选中历史记录 | 无                         | 点击记录项 | 当前仅打印日志 |

---

## 前端路由汇总

| 路由路径   | 对应组件      | 页面功能                     |
| ---------- | ------------- | ---------------------------- |
| `/`        | `Home.vue`    | 首页展示、功能介绍、引导入口 |
| `/chat`    | `Chat.vue`    | 文件上传、AI 问答、历史记录  |
| `/about`   | `About.vue`   | 关于页面（内容未分析）       |
| `/profile` | `Profile.vue` | 登录/注册、用户信息管理      |

---

## 前端 Store (Pinia) 状态管理

| Store         | 功能                                        | 持久化                                    |
| ------------- | ------------------------------------------- | ----------------------------------------- |
| `counter.js`  | 用户认证状态 (`token`, `userData`)          | `localStorage.setItem('token')`           |
| Chat.vue      | 当前会话数据 (`currentFile`, `currentData`) | `localStorage.setItem('chatCurrentData')` |
| UserIndex.vue | 学习偏好设置                                | `localStorage.setItem('userPreferences')` |

---

## 未实现/待完善的 API 调用

| 组件              | 功能             | 应调用的 API                          | 当前状态 |
| ----------------- | ---------------- | ------------------------------------- | -------- |
| `ChatHistory.vue` | 获取历史记录列表 | `GET /api/v1/chat/history`            | 模拟数据 |
| `ChatHistory.vue` | 获取会话消息     | `GET /api/v1/chat/messages/{chat_id}` | 未实现   |
| `ChatHistory.vue` | 删除历史记录     | `DELETE /api/v1/chat/{chat_id}`       | 未实现   |
| `UserIndex.vue`   | 获取真实统计数据 | 需后端提供                            | 随机生成 |

---

## API 调用路径汇总 (frontend/src/api)

| API 文件      | 方法                               | 对应后端接口                          |
| ------------- | ---------------------------------- | ------------------------------------- |
| `api/user.js` | `login(data)`                      | `POST /api/v1/user/login`             |
| `api/user.js` | `register(data)`                   | `POST /api/v1/user/register`          |
| `api/user.js` | `modify(params)`                   | `POST /api/v1/user/modify`            |
| `api/chat.js` | `getChatHistory(params)`           | `GET /api/v1/chat/history`            |
| `api/chat.js` | `createChatRecord(params)`         | `POST /api/v1/chat/create`            |
| `api/chat.js` | `deleteChatRecord(chatId, userId)` | `DELETE /api/v1/chat/{chat_id}`       |
| `api/chat.js` | `uploadFile(formData)`             | `POST /api/v1/chat/file/upload`       |
| `api/chat.js` | `askQuestion(data)`                | `POST /api/v1/chat/ask`               |
| `api/chat.js` | `getChatMessages(chatId)`          | `GET /api/v1/chat/messages/{chat_id}` |





### *数据库梳理*




---

## 数据库设计总览

**数据库类型**: SQLite  
**数据库文件**: `e:\smartcarb\ai-course-system\database\smart_class.db`  
**ORM框架**: SQLModel (SQLAlchemy 2.0)

---

## 数据表清单（共11张表）

### 1. 用户相关表

| 表名             | 说明         | 核心字段                                   |
| ---------------- | ------------ | ------------------------------------------ |
| `users`          | 用户主表     | id, username, hashed_password, role, email |
| `chat_histories` | 聊天会话记录 | id, user_id, content, created_at           |
| `chat_messages`  | 聊天消息详情 | id, chat_id, role, content, created_at     |

### 2. 课程/文档相关表

| 表名             | 说明         | 核心字段                                              |
| ---------------- | ------------ | ----------------------------------------------------- |
| `courses`        | 课程主表     | id, title, teacher_id, status, source_file_name       |
| `course_scripts` | AI生成的脚本 | id, course_id, script_content, summary_text, keywords |
| `script_nodes`   | 脚本节点     | id, script_id, node_type, title, content, duration    |

### 3. Docling文档解析表

| 表名                  | 说明         | 核心字段                                   |
| --------------------- | ------------ | ------------------------------------------ |
| `docling_documents`   | 解析文档主表 | id, course_id, doc_name, status, raw_json  |
| `docling_groups`      | 文档分组     | id, doc_id, name, label                    |
| `docling_tables`      | 表格数据     | id, doc_id, num_rows, num_cols, table_data |
| `docling_table_cells` | 表格单元格   | id, table_id, row_idx, col_idx, text       |
| `docling_texts`       | 文本内容     | id, doc_id, text, page_no, sort_order      |
| `docling_pictures`    | 图片信息     | id, doc_id, image_url, page_no, bbox       |

---

## 核心表结构详解

### users（用户表）
```sql
- id: INTEGER PRIMARY KEY
- username: VARCHAR(50) UNIQUE INDEX  -- 用户名
- real_name: VARCHAR(50)              -- 真实姓名
- email: VARCHAR UNIQUE INDEX          -- 邮箱
- fanya_account_id: VARCHAR UNIQUE     -- 泛雅平台账号
- hashed_password: VARCHAR             -- bcrypt加密密码
- school_id: VARCHAR                   -- 学校ID
- is_fanya_verified: BOOLEAN           -- 是否泛雅认证
- role: VARCHAR DEFAULT 'student'      -- 角色: teacher/student
- is_active: BOOLEAN DEFAULT true      -- 账号状态
- last_active_course_id: INTEGER       -- 最后学习课程
- last_learning_node: VARCHAR          -- 最后学习节点
- created_at: DATETIME
- updated_at: DATETIME
```

### courses（课程表）
```sql
- id: INTEGER PRIMARY KEY
- fanya_course_id: VARCHAR INDEX       -- 泛雅课程ID
- fanya_course_name: VARCHAR           -- 泛雅课程名
- title: VARCHAR                       -- 智课标题
- description: TEXT                    -- 描述
- cover_image: VARCHAR                 -- 封面URL
- teacher_id: INTEGER FOREIGN KEY      -- 教师ID → users.id
- status: VARCHAR DEFAULT 'draft'      -- draft/published/archived
- is_ai_generated: BOOLEAN             -- 是否AI生成
- total_duration: INTEGER              -- 总时长(秒)
- total_nodes: INTEGER                 -- 节点总数
- source_file_name: VARCHAR            -- 原始文件名
- source_file_path: VARCHAR            -- 文件路径
- source_mimetype: VARCHAR             -- MIME类型
- total_pages: INTEGER                 -- 总页数
- created_at: DATETIME
- updated_at: DATETIME
```

### chat_histories（聊天会话表）
```sql
- id: INTEGER PRIMARY KEY
- user_id: INTEGER FOREIGN KEY INDEX   -- 用户ID → users.id
- content: VARCHAR                     -- 会话标题
- created_at: DATETIME
```

### chat_messages（聊天消息表）
```sql
- id: INTEGER PRIMARY KEY
- chat_id: INTEGER FOREIGN KEY INDEX   -- 会话ID → chat_histories.id
- role: VARCHAR                        -- user/assistant/system
- content: TEXT                        -- 消息内容
- created_at: DATETIME
```

### docling_documents（文档解析主表）
```sql
- id: INTEGER PRIMARY KEY
- course_id: INTEGER FOREIGN KEY INDEX -- 课程ID → courses.id
- schema_name: VARCHAR                 -- Docling schema
- version: VARCHAR                     -- Docling版本
- doc_name: VARCHAR                    -- 文档名称
- origin_filename: VARCHAR             -- 原始文件名
- origin_mimetype: VARCHAR             -- MIME类型
- origin_binary_hash: VARCHAR          -- 文件哈希
- source_file_path: VARCHAR            -- 存储路径
- status: VARCHAR                      -- pending/processing/completed/failed
- total_groups: INTEGER                -- 分组数
- total_tables: INTEGER                -- 表格数
- total_texts: INTEGER                 -- 文本数
- total_pictures: INTEGER              -- 图片数
- raw_json: JSON                       -- 完整解析数据
- error_message: TEXT                  -- 错误信息
- created_at: DATETIME
- updated_at: DATETIME
```

---

## 实体关系图（ER图）

```
┌─────────────────┐       ┌──────────────────┐
│     users       │       │  chat_histories  │
├─────────────────┤       ├──────────────────┤
│ PK id           │◄──────┤ FK user_id       │
│    username     │  1:N  │    content       │
│    role         │       │ PK id            │
│    ...          │       └────────┬─────────┘
└────────┬────────┘                │
         │                         │
         │                  ┌──────┴─────────┐
         │                  │  chat_messages │
         │                  ├────────────────┤
         │                  │ PK id          │
         │                  │ FK chat_id     │
         │                  │    role        │
         │                  │    content     │
         │                  └────────────────┘
         │
         │  1:N
         ▼
┌─────────────────┐       ┌──────────────────┐
│    courses      │◄──────┤ course_scripts   │
├─────────────────┤  1:N  ├──────────────────┤
│ PK id           │       │ PK id            │
│ FK teacher_id   │       │ FK course_id     │
│    title        │       │    script_content│
│    status       │       │    summary_text  │
│    ...          │       │    is_active     │
└────────┬────────┘       └────────┬─────────┘
         │                         │
         │                    1:N  │
         │                  ┌──────┴─────────┐
         │                  │  script_nodes  │
         │                  ├────────────────┤
         │                  │ PK id          │
         │                  │ FK script_id   │
         │                  │    node_type   │
         │                  │    title       │
         │                  │    content     │
         │                  └────────────────┘
         │
         │  1:1
         ▼
┌─────────────────┐
│docling_documents│
├─────────────────┤
│ PK id           │
│ FK course_id    │
│    doc_name     │
│    status       │
│    raw_json     │
└────────┬────────┘
         │
    ┌────┼────┬────────┐
    │    │    │        │
    ▼    ▼    ▼        ▼
┌──────┐┌──────┐┌──────────┐┌─────────┐
│groups││tables││table_cells││  texts  │
└──────┘└──────┘└──────────┘└─────────┘
```

---

## 关键索引设计

| 表名              | 索引字段                          | 用途                 |
| ----------------- | --------------------------------- | -------------------- |
| users             | username, email, fanya_account_id | 唯一性校验、快速登录 |
| courses           | teacher_id                        | 查询教师课程         |
| courses           | fanya_course_id                   | 泛雅平台关联         |
| chat_histories    | user_id                           | 查询用户历史记录     |
| chat_messages     | chat_id                           | 查询会话消息         |
| docling_documents | course_id                         | 关联课程查询         |
| docling_texts     | doc_id                            | 查询文档文本         |

---

## 数据流转示例

```
用户上传文件
    │
    ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   courses   │───→│docling_docs │───→│docling_texts│
│  (创建记录) │    │ (解析状态)  │    │ (存储文本)  │
└─────────────┘    └─────────────┘    └─────────────┘
    │
    ▼
┌─────────────┐    ┌─────────────┐
│course_scripts│───→│script_nodes │
│  (AI脚本)   │    │  (节点拆分)  │
└─────────────┘    └─────────────┘
    │
    ▼
┌─────────────┐
│chat_histories│◄── 用户提问
│  (创建会话)  │
└─────────────┘
    │
    ▼
┌─────────────┐
│chat_messages│◄── 存储问答记录
│  (消息记录)  │
└─────────────┘
```

---

## 枚举类型定义

| 枚举名         | 值                                                          | 说明     |
| -------------- | ----------------------------------------------------------- | -------- |
| UserRole       | teacher, student                                            | 用户角色 |
| CourseStatus   | draft, published, archived                                  | 课程状态 |
| ScriptNodeType | lecture, question, breakpoint, summary, video, interactive  | 节点类型 |
| ParseStatus    | pending, processing, completed, failed                      | 解析状态 |
| MessageRole    | user, assistant, system                                     | 消息角色 |
| DoclingLabel   | section, table, text, picture, code, list, title, paragraph | 文档标签 |
