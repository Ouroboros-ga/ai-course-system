## Project Setup

```sh
npm install
```

### Compile and Hot-Reload for Development

```sh
npm run dev
```

### Compile and Minify for Production

```sh
npm run build
```

### Lint with [ESLint](https://eslint.org/)

```sh
npm run lint
```

## 前端目录结构

```text
frontend/
├── src/
│   ├── api/                    # API接口管理
│   │   ├── chat.js             # 聊天相关API
│   │   ├── index.js            # 基础API配置
│   │   └── user.js             # 用户相关API
│   │
│   ├── assets/                 # 静态资源
│   │   ├── home/               # 主页相关图片
│   │   │   └── 主页照片1.png
│   │   └── Avatar.svg          # 头像SVG
│   │
│   ├── components/             # 全局组件
│   │   ├── GradientBackground.vue  # 渐变背景组件
│   │   ├── NavigationBar.vue   # 导航栏组件
│   │   │
│   │   ├── chat/               # 聊天功能组件
│   │   │   ├── ChatBox.vue     # 聊天框容器
│   │   │   ├── InputBox.vue    # 输入框组件
│   │   │   └── bubble/         # 消息气泡
│   │   │       ├── AiBubble.vue    # AI消息气泡
│   │   │       └── UserBubble.vue  # 用户消息气泡
│   │   │
│   │   ├── home/               # 首页组件
│   │   │   ├── sections/       # 首页各模块
│   │   │   │   ├── Chat.vue        # 聊天模块
│   │   │   │   ├── Feature.vue     # 特性展示
│   │   │   │   ├── Footer.vue      # 页脚
│   │   │   │   ├── Hero.vue        # 英雄区域
│   │   │   │   └── Value.vue       # 价值主张
│   │   │   └── ui/             # UI辅助组件
│   │   │       ├── BackTop.vue     # 返回顶部
│   │   │       └── ScrollArrow.vue # 滚动箭头
│   │   │
│   │   └── profile/            # 个人资料组件
│   │       ├── data/           # 数据展示组件
│   │       │   ├── MenuGrid.vue    # 菜单网格
│   │       │   └── UserCard.vue    # 用户卡片
│   │       ├── Login.vue       # 登录组件
│   │       ├── UserIndex.vue   # 用户主页
│   │       ├── UserInfoCard.vue # 用户信息卡片
│   │       └── UsersData.vue   # 用户数据列表
│   │
│   ├── router/                 # 路由配置
│   │   └── index.js            # 路由定义
│   │
│   ├── stores/                 # 状态管理
│   │   └── counter.js          # Pinia状态存储
│   │
│   ├── utils/                  # 工具函数
│   │   ├── getCookies.js       # Cookie获取
│   │   ├── request.js          # 请求封装
│   │   └── toast.js            # 提示消息
│   │
│   ├── views/                  # 页面视图
│   │   ├── About.vue           # 关于页面
│   │   ├── Chat.vue            # 聊天页面
│   │   ├── Home.vue            # 首页
│   │   └── Profile.vue         # 个人资料页
│   │
│   ├── App.vue                 # 根组件
│   └── main.js                 # 应用入口
│
├── package.json                # 项目依赖和脚本
└── vite.config.js              # Vite构建配置
```

## API接口文档

### 1. 用户模块接口

#### 1.1 用户登录
- **接口地址**: `/user/login`
- **请求方法**: POST
- **请求参数**:
```json
{
  "username": "用户名",
  "password": "密码" 
}
```
- **返回结果**:
```json
{ 
  "code": 200,
  "message": "登录成功", 
  "data": { 
    "token": "用户令牌",
    "userInfo": { 
      "id": "用户ID"
    }
  }
}
```
- **错误处理**:
```json
{
  "code": 401,
  "message": "用户名密码错误",
  "data": null
}
```

#### 1.2 用户注册
- **接口地址**: `/user/register`
- **请求方法**: POST
- **请求参数**:
```json
{
  "username": "用户名",
  "password": "密码"
}
```
- **返回结果**:
```json
{ 
  "code": 200,
  "message": "注册并登录成功", 
  "data": { 
    "token": "用户令牌",
    "userInfo": { 
      "id": "用户ID"
    }
  }
}
```
- **错误处理**:
```json
{
  "code": 409,
  "message": "用户名已存在",
  "data": null
}
```