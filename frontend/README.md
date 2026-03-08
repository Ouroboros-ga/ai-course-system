 **前端目录
** 
```
frontend/
├── public/                  # 静态资源（图片、favicon等）
├── src/
│   ├── main.js              # 项目入口
│   ├── App.vue              # 根组件
│   ├── router/              # 路由配置（分教师/学生端）
│   │   ├── index.js
│   │   ├── teacher_router.js  # 教师端路由
│   │   └── student_router.js  # 学生端路由
│   ├── store/               # 全局状态管理（Pinia，比Vuex更简单）
│   │   ├── index.js
│   │   ├── user.js          # 用户状态管理
│   │   ├── course.js        # 智课状态管理
│   │   └── qa.js            # 问答状态管理
│   ├── api/                 # 接口请求封装（与后端接口一一对应）
│   │   ├── index.js         # axios实例配置、拦截器
│   │   ├── smart_course_api.js
│   │   ├── qa_api.js
│   │   ├── progress_api.js
│   │   └── user_api.js
│   ├── components/          # 全局通用组件（全项目复用）
│   │   ├── CommonHeader.vue
│   │   ├── CoursePlayer.vue  # 智课播放核心组件
│   │   ├── QaChatBox.vue     # 问答聊天框核心组件
│   │   ├── Uploader.vue      # 文件上传组件
│   │   └── ProgressBar.vue   # 学习进度组件
│   ├── views/               # 页面组件（分教师/学生端，对应赛题功能）
│   │   ├── teacher/          # 教师端页面（前端A负责）
│   │   │   ├── Login.vue
│   │   │   ├── CourseList.vue       # 课件列表页
│   │   │   ├── CourseEdit.vue       # 课件解析、脚本编辑页（智课生成核心）
│   │   │   └── CoursePreview.vue    # 智课预览页
│   │   ├── student/          # 学生端页面（前端B负责）
│   │   │   ├── Login.vue
│   │   │   ├── CourseHall.vue       # 智课大厅页
│   │   │   ├── CourseStudy.vue      # 智课学习页（问答、进度核心）
│   │   │   └── StudyRecord.vue      # 学习记录页
│   │   └── Home.vue         # 项目首页
│   ├── utils/               # 通用工具函数
│   │   ├── auth.js          # 权限、token处理
│   │   ├── audio.js         # 音频播放、录音处理
│   │   └── format.js        # 时间、格式处理
│   ├── assets/              # 样式、图片资源
│   │   ├── css/             # 全局样式
│   │   └── images/          # 图片资源
├── package.json             # 前端依赖，一键npm安装
├── vite.config.js           # vite配置
├── .env.example             # 环境变量示例（后端接口地址）
└── README.md                # 前端启动说明
```