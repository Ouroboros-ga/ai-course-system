# 性能优化策略

## 1. 性能优化概述

前端性能优化是提升用户体验的关键因素。本项目采用了多种优化策略，包括代码分割、路由懒加载、资源优化等，旨在提高页面加载速度和运行效率。

## 2. 加载性能优化

### 2.1 路由懒加载

项目使用路由懒加载优化初始加载性能：

```javascript
const loadView = (view) => {
  return () => import(/* webpackChunkName: "view-[request]" */ `../views/${view}.vue`)
}
```

**优势：**
- 减少初始包大小
- 按需加载路由组件
- 提高首屏加载速度

### 2.2 代码分割

使用 Vite 的代码分割功能，自动将代码拆分为多个 chunk：

```javascript
// 自动分割
import(/* webpackChunkName: "view-chat" */ '../views/Chat.vue')
```

### 2.3 资源优化

#### 图片优化
- 使用适当的图片格式（WebP）
- 压缩图片大小
- 使用 CDN 加速图片加载

#### CSS 优化
- 移除未使用的 CSS
- 合并 CSS 文件
- 使用 CSS 压缩

#### JavaScript 优化
- 使用 Tree Shaking 移除未使用的代码
- 压缩 JavaScript 文件
- 使用 ES6+ 语法提高执行效率

## 3. 运行时性能优化

### 3.1 Vue 组件优化

#### 使用 v-memo 优化列表渲染

```vue
<template>
  <div v-for="item in items" :key="item.id" v-memo="[item.id, item.name]">
    {{ item.name }}
  </div>
</template>
```

#### 使用 v-once 优化静态内容

```vue
<template>
  <div v-once>
    {{ staticContent }}
  </div>
</template>
```

#### 使用 keep-alive 缓存组件

```vue
<template>
  <keep-alive>
    <router-view />
  </keep-alive>
</template>
```

### 3.2 响应式数据优化

#### 使用 shallowRef 和 shallowReactive

```javascript
import { shallowRef, shallowReactive } from 'vue'

// 浅层响应式，避免深层对象的响应式转换
const shallowData = shallowRef({
  deep: {
    nested: 'value'
  }
})

const shallowObj = shallowReactive({
  deep: {
    nested: 'value'
  }
})
```

#### 使用 markRaw 标记不可响应的对象

```javascript
import { markRaw } from 'vue'

// 标记为不可响应，提高性能
const nonReactive = markRaw({
  largeObject: {}
})
```

### 3.3 虚拟滚动

对于长列表，使用虚拟滚动优化性能：

```javascript
// 安装依赖
npm install vue-virtual-scroller

// 使用示例
<template>
  <virtual-scroller
    :items="items"
    :item-height="50"
    content-tag="div"
  >
    <template v-slot="{ item }">
      <div>{{ item.name }}</div>
    </template>
  </virtual-scroller>
</template>
```

## 4. 网络优化

### 4.1 HTTP 请求优化

#### 使用 axios 拦截器

```javascript
// 请求缓存
const requestCache = new Map()

service.interceptors.request.use(
  config => {
    const key = `${config.method}:${config.url}`
    if (requestCache.has(key)) {
      return Promise.resolve(requestCache.get(key))
    }
    return config
  }
)

service.interceptors.response.use(
  response => {
    const key = `${response.config.method}:${response.config.url}`
    requestCache.set(key, response)
    return response
  }
)
```

#### 请求合并

```javascript
// 将多个请求合并为一个
const pendingRequests = new Map()

function debounceRequest(key, requestFn, delay = 300) {
  if (pendingRequests.has(key)) {
    clearTimeout(pendingRequests.get(key))
  }
  
  return new Promise((resolve, reject) => {
    pendingRequests.set(key, setTimeout(async () => {
      try {
        const result = await requestFn()
        resolve(result)
      } catch (error) {
        reject(error)
      } finally {
        pendingRequests.delete(key)
      }
    }, delay))
  })
}
```

### 4.2 资源预加载

#### 预加载关键资源

```html
<!-- 预加载 CSS -->
<link rel="preload" href="styles.css" as="style">

<!-- 预加载 JavaScript -->
<link rel="preload" href="app.js" as="script">

<!-- 预加载图片 -->
<link rel="preload" href="image.jpg" as="image">
```

#### 预连接

```html
<!-- 预连接到 CDN -->
<link rel="preconnect" href="https://cdn.example.com">

<!-- 预连接到 API 服务器 -->
<link rel="preconnect" href="https://api.example.com">
```

## 5. 浏览器渲染优化

### 5.1 减少重绘和回流

#### 使用 transform 和 opacity 进行动画

```css
.element {
  transition: transform 0.3s ease, opacity 0.3s ease;
}

.element:hover {
  transform: translateY(-2px);
  opacity: 0.8;
}
```

#### 使用 will-change 优化动画

```css
.element {
  will-change: transform;
}
```

#### 使用 CSS containment

```css
.element {
  contain: layout style paint;
}
```

### 5.2 优化渲染性能

#### 使用 requestAnimationFrame

```javascript
function animate() {
  // 动画逻辑
  requestAnimationFrame(animate)
}

requestAnimationFrame(animate)
```

#### 使用 Intersection Observer

```javascript
const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      // 元素进入视口时加载
      loadImage(entry.target)
    }
  })
})

// 监听元素
observer.observe(document.querySelector('.lazy-image'))
```

## 6. 缓存策略

### 6.1 浏览器缓存

配置适当的缓存策略：

```
Cache-Control: max-age=31536000, immutable
```

### 6.2 Service Worker 缓存

使用 Service Worker 实现离线缓存：

```javascript
// service-worker.js
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open('v1').then((cache) => {
      return cache.addAll([
        '/',
        '/index.html',
        '/app.js',
        '/styles.css'
      ])
    })
  )
})

self.addEventListener('fetch', (event) => {
  event.respondWith(
    caches.match(event.request).then((response) => {
      return response || fetch(event.request)
    })
  )
})
```

### 6.3 LocalStorage 缓存

```javascript
// 缓存数据
function cacheData(key, data, expiration = 86400000) {
  const item = {
    data,
    timestamp: Date.now(),
    expiration
  }
  localStorage.setItem(key, JSON.stringify(item))
}

// 获取缓存数据
function getCachedData(key) {
  const item = localStorage.getItem(key)
  if (!item) return null
  
  const { data, timestamp, expiration } = JSON.parse(item)
  if (Date.now() - timestamp > expiration) {
    localStorage.removeItem(key)
    return null
  }
  
  return data
}
```

## 7. 代码优化

### 7.1 使用防抖和节流

#### 防抖

```javascript
function debounce(func, wait) {
  let timeout
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout)
      func(...args)
    }
    clearTimeout(timeout)
    timeout = setTimeout(later, wait)
  }
}

// 使用
const debouncedSearch = debounce((query) => {
  searchAPI(query)
}, 300)
```

#### 节流

```javascript
function throttle(func, limit) {
  let inThrottle
  return function(...args) {
    if (!inThrottle) {
      func.apply(this, args)
      inThrottle = true
      setTimeout(() => inThrottle = false, limit)
    }
  }
}

// 使用
const throttledScroll = throttle(() => {
  updateScrollPosition()
}, 100)
```

### 7.2 优化循环和计算

```javascript
// 优化前
for (let i = 0; i < array.length; i++) {
  // 循环体
}

// 优化后
const length = array.length
for (let i = 0; i < length; i++) {
  // 循环体
}
```

### 7.3 使用 Web Workers

```javascript
// 创建 Worker
const worker = new Worker('worker.js')

// 发送消息
worker.postMessage({ type: 'process', data: largeData })

// 接收消息
worker.onmessage = (event) => {
  console.log('处理结果:', event.data)
}

// worker.js
self.onmessage = (event) => {
  const { type, data } = event.data
  if (type === 'process') {
    const result = processData(data)
    self.postMessage(result)
  }
}
```

## 8. 性能监控

### 8.1 使用 Performance API

```javascript
// 测量函数执行时间
function measurePerformance(label, fn) {
  performance.mark(`${label}-start`)
  const result = fn()
  performance.mark(`${label}-end`)
  performance.measure(label, `${label}-start`, `${label}-end`)
  
  const measure = performance.getEntriesByName(label)[0]
  console.log(`${label}: ${measure.duration}ms`)
  
  return result
}

// 使用
measurePerformance('data-processing', () => {
  return processData()
})
```

### 8.2 使用 Lighthouse 进行性能检测

```bash
# 安装 Lighthouse
npm install -g lighthouse

# 运行检测
lighthouse https://example.com --view
```

### 8.3 使用 Vue DevTools 性能面板

Vue DevTools 提供了性能面板，可以查看组件渲染时间和更新频率。

## 9. 构建优化

### 9.1 Vite 构建优化

```javascript
// vite.config.js
export default {
  build: {
    // 启用代码分割
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor': ['vue', 'vue-router', 'pinia'],
          'ui': ['@vueuse/core'],
          'api': ['axios']
        }
      }
    },
    // 压缩选项
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,
        drop_debugger: true
      }
    }
  }
}
```

### 9.2 环境变量优化

```javascript
// 根据环境配置不同的优化策略
if (import.meta.env.PROD) {
  // 生产环境优化
  console.log = () => {}
}
```

### 9.3 Tree Shaking 优化

确保代码支持 Tree Shaking：

```javascript
// 导出单个函数，支持 Tree Shaking
export function utilFunction() {}

// 避免导出整个对象
// ❌ 不推荐
export default {
  func1() {},
  func2() {}
}
```

## 10. 移动端优化

### 10.1 触摸事件优化

```javascript
// 防止点击延迟
import FastClick from 'fastclick'
FastClick.attach(document.body)
```

### 10.2 响应式图片

```html
<picture>
  <source media="(max-width: 768px)" srcset="small.jpg">
  <source media="(max-width: 1024px)" srcset="medium.jpg">
  <img src="large.jpg" alt="图片">
</picture>
```

### 10.3 移动端性能优化

- 减少 DOM 元素数量
- 避免复杂的 CSS 选择器
- 使用硬件加速
- 优化字体加载

## 11. 优化效果评估

### 11.1 关键性能指标

- **FCP (First Contentful Paint)**: 首次内容绘制
- **LCP (Largest Contentful Paint)**: 最大内容绘制
- **FID (First Input Delay)**: 首次输入延迟
- **CLS (Cumulative Layout Shift)**: 累积布局偏移
- **TTI (Time to Interactive)**: 可交互时间

### 11.2 性能测试工具

1. **Lighthouse**: 综合性能评估
2. **WebPageTest**: 多地区性能测试
3. **Chrome DevTools Performance**: 实时性能分析
4. **Vue DevTools**: Vue 组件性能分析

## 12. 持续优化策略

### 12.1 建立性能基准

```javascript
// 性能基准测试
function runPerformanceBenchmark() {
  const startTime = performance.now()
  
  // 执行测试代码
  for (let i = 0; i < 10000; i++) {
    // 测试代码
  }
  
  const endTime = performance.now()
  console.log(`执行时间: ${endTime - startTime}ms`)
}
```

### 12.2 性能监控

```javascript
// 监控页面加载时间
window.addEventListener('load', () => {
  const loadTime = performance.now()
  console.log(`页面加载时间: ${loadTime}ms`)
  
  // 发送性能数据到服务器
  fetch('/api/performance', {
    method: 'POST',
    body: JSON.stringify({
      loadTime,
      url: window.location.href,
      userAgent: navigator.userAgent
    })
  })
})
```

### 12.3 定期优化

- 定期运行性能测试
- 监控关键性能指标
- 根据测试结果进行优化
- 更新优化策略

## 13. 常见优化误区

### 13.1 过度优化

- 不要过早优化
- 先确保功能正确，再进行优化
- 基于性能测试结果进行优化

### 13.2 忽略用户体验

- 优化不应牺牲用户体验
- 平衡性能和功能
- 优先保证核心功能的可用性

### 13.3 盲目使用新特性

- 评估新特性的兼容性
- 测试新特性的性能影响
- 考虑降级方案

## 14. 未来优化方向

1. **WebAssembly**: 使用 WebAssembly 提升计算密集型任务性能
2. **HTTP/3**: 采用 HTTP/3 协议提升网络性能
3. **Web Workers**: 更多地使用 Web Workers 处理后台任务
4. **边缘计算**: 将部分计算任务迁移到边缘节点
5. **AI 优化**: 使用 AI 技术优化性能
