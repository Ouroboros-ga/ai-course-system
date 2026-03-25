# 状态管理方案

## 1. 状态管理概述

项目使用 Pinia 作为状态管理库，Pinia 是 Vue 3 官方推荐的状态管理解决方案，具有以下优势：

- 支持 Vue 3 的 Composition API
- 更好的 TypeScript 支持
- 模块化设计，便于维护
- 内置 DevTools 支持

## 2. Pinia Store 结构

### 2.1 核心 Store

项目目前主要使用 `counter` store 管理全局状态：

```javascript
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

export const useCounterStore = defineStore('counter', () => {
  // messages格式：[{id: 1, class: 'user', message: 'Hello World'}]
  const messages = ref([])  // 消息列表

  function addMessage(message) {
    messages.value.push(message)
  }

  function removeMessage(id) {
    messages.value = messages.value.filter(msg => msg.id !== id)
  }

  function clearMessages() {
    messages.value = []
  }

  const userData = ref({
    username: null,
    id: null,
  })

  return {
    messages,
    addMessage,
    clearMessages,
    removeMessage,
    userData,
  }
})
```

### 2.2 Store 类型

目前项目中的 Store 包含以下状态：

1. **messages**: 聊天消息列表
   - 类型: Array
   - 结构: `[{id: number, class: string, message: string}]`
   - 用途: 存储聊天对话记录

2. **userData**: 用户数据
   - 类型: Object
   - 结构: `{username: string, id: number}`
   - 用途: 存储当前登录用户信息

## 3. Store 使用示例

### 3.1 访问 Store

```javascript
import { useCounterStore } from '@/stores/counter'

const store = useCounterStore()

// 访问状态
console.log(store.messages)
console.log(store.userData)

// 调用方法
store.addMessage({
  id: 1,
  class: 'user',
  message: 'Hello AI'
})

store.clearMessages()
```

### 3.2 在组件中使用

```vue
<template>
  <div>
    <div v-for="message in store.messages" :key="message.id" :class="message.class">
      {{ message.message }}
    </div>
    <button @click="sendMessage">发送消息</button>
  </div>
</template>

<script setup>
import { useCounterStore } from '@/stores/counter'

const store = useCounterStore()

const sendMessage = () => {
  store.addMessage({
    id: Date.now(),
    class: 'user',
    message: 'Hello from component'
  })
}
</script>
```

### 3.3 使用计算属性

```javascript
import { computed } from 'vue'
import { useCounterStore } from '@/stores/counter'

const store = useCounterStore()

// 创建计算属性
const userMessageCount = computed(() => {
  return store.messages.filter(msg => msg.class === 'user').length
})

const aiMessageCount = computed(() => {
  return store.messages.filter(msg => msg.class !== 'user').length
})
```

## 4. 状态管理最佳实践

### 4.1 Store 组织

1. **按功能模块划分**: 每个功能模块创建独立的 store
2. **单一职责**: 每个 store 只负责特定领域的状态管理
3. **命名规范**: 
   - store 文件使用小写字母加下划线（如 `counter.js`）
   - store 名称使用 camelCase（如 `useCounterStore`）

### 4.2 状态更新

1. **直接修改**: 对于简单状态，可以直接修改
   ```javascript
   store.userData.username = 'newUsername'
   ```

2. **使用方法**: 对于复杂的状态更新，建议使用方法
   ```javascript
   store.addMessage(message)
   ```

### 4.3 响应式处理

1. **自动响应**: Pinia 会自动处理响应式，无需手动调用 `ref` 或 `reactive`
2. **解构处理**: 如果需要解构 store 属性，使用 `storeToRefs`
   ```javascript
   import { storeToRefs } from 'pinia'
   const { messages, userData } = storeToRefs(store)
   ```

### 4.4 异步操作

对于异步操作，建议在 store 中定义异步方法：

```javascript
import { defineStore } from 'pinia'
import api from '@/api'

export const useUserStore = defineStore('user', () => {
  const user = ref(null)
  const loading = ref(false)

  async function fetchUser() {
    loading.value = true
    try {
      const response = await api.user.getUserInfo()
      user.value = response
    } catch (error) {
      console.error('获取用户信息失败:', error)
    } finally {
      loading.value = false
    }
  }

  return {
    user,
    loading,
    fetchUser
  }
})
```

## 5. 状态持久化

### 5.1 手动持久化

可以使用 localStorage 手动实现状态持久化：

```javascript
import { defineStore } from 'pinia'

export const useCounterStore = defineStore('counter', () => {
  const messages = ref(JSON.parse(localStorage.getItem('messages') || '[]'))
  
  // 监听状态变化，自动保存到 localStorage
  watch(messages, (newMessages) => {
    localStorage.setItem('messages', JSON.stringify(newMessages))
  }, { deep: true })

  // 其他方法...
})
```

### 5.2 使用插件

也可以使用 `pinia-plugin-persistedstate` 插件实现自动持久化：

```javascript
// main.js
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'

const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)

app.use(pinia)
```

```javascript
// store.js
export const useCounterStore = defineStore('counter', () => {
  // 状态定义...
}, {
  persist: true
})
```

## 6. 状态管理扩展建议

### 6.1 模块化扩展

建议按照功能模块扩展 store：

1. **userStore**: 管理用户相关状态
   - 用户信息
   - 登录状态
   - 用户偏好设置

2. **chatStore**: 管理聊天相关状态
   - 消息列表
   - 聊天历史
   - 当前会话

3. **courseStore**: 管理课程相关状态
   - 课程列表
   - 学习进度
   - 收藏课程

4. **uiStore**: 管理UI相关状态
   - 主题设置
   - 布局状态
   - 加载状态

### 6.2 高级特性

1. **Action 组合**: 将复杂操作拆分为多个小 action
2. **Getter 优化**: 使用 getter 缓存计算结果
3. **状态重置**: 提供重置状态的方法
4. **批量更新**: 使用 `$patch` 方法批量更新状态

## 7. 调试技巧

### 7.1 使用 DevTools

1. 安装 Vue DevTools 浏览器扩展
2. 在 DevTools 中查看 Pinia 面板
3. 实时查看和修改状态

### 7.2 日志记录

在关键操作处添加日志：

```javascript
function addMessage(message) {
  console.log('添加消息:', message)
  messages.value.push(message)
}
```

## 8. 性能优化

1. **避免不必要的重渲染**: 使用 `shallowRef` 和 `shallowReactive`
2. **懒加载**: 只在需要时加载 store
3. **缓存计算**: 使用 getter 缓存计算结果
4. **批量更新**: 使用 `$patch` 减少更新次数

## 9. 安全性考虑

1. **敏感信息处理**: 避免在 store 中存储敏感信息
2. **状态验证**: 对输入数据进行验证
3. **权限控制**: 在 action 中添加权限检查
