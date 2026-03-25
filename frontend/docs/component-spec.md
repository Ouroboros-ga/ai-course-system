# 组件设计与使用规范

## 1. 组件分类

项目中的组件按照功能和层级分为以下几类：

### 1.1 基础组件
- **NavigationBar**: 顶部导航栏组件
- **GradientBackground**: 渐变背景组件
- **BackTop**: 返回顶部按钮
- **ScrollArrow**: 滚动箭头指示器

### 1.2 聊天相关组件
- **ChatPanel**: 聊天面板主组件
- **ChatInput**: 聊天输入框组件
- **MessageBubble**: 消息气泡组件
- **MessageList**: 消息列表组件
- **PptPlayer**: PPT播放器组件
- **PptUpload**: PPT上传组件
- **PptControlBar**: PPT控制面板组件
- **PptHeader**: PPT头部组件
- **PptAnalyzing**: PPT分析状态组件

### 1.3 首页相关组件
- **Hero**: 首页英雄区域组件
- **Feature**: 功能特性组件
- **Value**: 价值主张组件
- **Chat**: 聊天预览组件
- **Footer**: 页脚组件

### 1.4 用户中心组件
- **UserIndex**: 用户中心主组件
- **Login**: 登录组件
- **MenuGrid**: 菜单网格组件
- **MyCourses**: 我的课程组件
- **PreferenceSettings**: 偏好设置组件
- **StatsCard**: 统计卡片组件
- **UserCard**: 用户信息卡片组件
- **UserInfoCard**: 用户详细信息卡片组件
- **UsersData**: 用户数据展示组件

## 2. 组件设计原则

### 2.1 单一职责原则
每个组件只负责一个明确的功能，避免组件功能过于复杂。

### 2.2 可复用性
设计通用的组件接口，便于在不同场景下复用。

### 2.3 响应式设计
所有组件都应支持响应式布局，适配不同屏幕尺寸。

### 2.4 命名规范
- **组件名**: 使用 PascalCase（大驼峰命名）
- **文件名**: 使用 PascalCase（大驼峰命名）
- **变量名**: 使用 camelCase（小驼峰命名）
- **CSS类名**: 使用 kebab-case（短横线命名）

### 2.5 样式规范
- 使用 scoped CSS 避免样式冲突
- 优先使用 CSS 变量进行样式管理
- 统一的颜色主题和间距规范

## 3. 组件使用示例

### 3.1 NavigationBar 组件

```vue
<template>
  <NavigationBar />
</template>

<script setup>
import NavigationBar from '@/components/NavigationBar.vue'
</script>
```

### 3.2 ChatPanel 组件

```vue
<template>
  <ChatPanel />
</template>

<script setup>
import ChatPanel from '@/components/chat/ChatPanel.vue'
</script>
```

### 3.3 MessageBubble 组件

```vue
<template>
  <MessageBubble 
    :message="message"
    :isUser="isUser"
  />
</template>

<script setup>
import MessageBubble from '@/components/chat/ChatPanel/MessageBubble.vue'

defineProps({
  message: {
    type: String,
    required: true
  },
  isUser: {
    type: Boolean,
    default: false
  }
})
</script>
```

## 4. 组件通信方式

### 4.1 Props 传递
使用 props 从父组件向子组件传递数据。

### 4.2 Emit 事件
使用 emit 从子组件向父组件发送事件。

### 4.3 Provide/Inject
使用 provide/inject 在组件树中共享数据。

### 4.4 Pinia 状态管理
使用 Pinia store 进行全局状态管理。

## 5. 组件开发规范

### 5.1 组件结构
```vue
<template>
  <!-- 组件模板 -->
</template>

<script setup>
// 组件逻辑
</script>

<style scoped>
/* 组件样式 */
</style>
```

### 5.2 Script Setup 语法
使用 Vue 3 的 Script Setup 语法，简化组件编写。

### 5.3 Props 定义
使用 `defineProps` 定义组件的属性。

```javascript
const props = defineProps({
  title: {
    type: String,
    required: true,
    default: 'Default Title'
  },
  count: {
    type: Number,
    default: 0
  }
})
```

### 5.4 Emits 定义
使用 `defineEmits` 定义组件的事件。

```javascript
const emit = defineEmits(['update', 'delete'])

// 触发事件
emit('update', data)
```

### 5.5 响应式数据
使用 `ref` 和 `reactive` 创建响应式数据。

```javascript
import { ref, reactive } from 'vue'

const count = ref(0)
const user = reactive({
  name: '',
  age: 0
})
```

### 5.6 生命周期钩子
使用 `onMounted`, `onUpdated`, `onUnmounted` 等生命周期钩子。

```javascript
import { onMounted, onUnmounted } from 'vue'

onMounted(() => {
  // 组件挂载时执行
})

onUnmounted(() => {
  // 组件卸载时执行
})
```

## 6. 组件测试建议

1. **单元测试**: 使用 Vue Test Utils 测试组件的基本功能
2. **集成测试**: 测试组件之间的交互
3. **视觉测试**: 使用快照测试确保组件外观一致

## 7. 组件优化建议

1. **组件拆分**: 将复杂组件拆分为多个小组件
2. **异步组件**: 使用异步组件减少初始加载时间
3. **虚拟滚动**: 对长列表使用虚拟滚动优化性能
4. **缓存策略**: 合理使用组件缓存避免不必要的重渲染
