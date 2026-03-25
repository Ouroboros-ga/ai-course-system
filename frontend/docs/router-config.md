# 路由配置

## 1. 路由概述

项目使用 Vue Router 5.x 进行路由管理，采用了现代化的路由配置方式，包括路由懒加载、路由动画等特性。

## 2. 路由配置结构

### 2.1 路由定义

```javascript
import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '../views/Home.vue'

// 路由懒加载时添加加载提示（可选）
const loadView = (view) => {
  return () => import(/* webpackChunkName: "view-[request]" */ `../views/${view}.vue`)
}

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: ChatView
    },
    {
      path: '/chat',
      name: 'chat',
      component: loadView('Chat') // 简化懒加载写法
    },
    {
      path: '/about',
      name: 'about',
      component: loadView('About')
    },
    {
      path: '/profile',
      name: 'profile',
      component: loadView('Profile')
    },
  ],
  // 页面跳转时滚动到顶部（体验优化）
  scrollBehavior() {
    return { top: 0 }
  }
})

export default router
```

### 2.2 路由配置说明

| 路径 | 名称 | 组件 | 加载方式 | 说明 |
|------|------|------|----------|------|
| `/` | `home` | `Home.vue` | 直接加载 | 首页，展示聊天功能 |
| `/chat` | `chat` | `Chat.vue` | 懒加载 | 聊天页面 |
| `/about` | `about` | `About.vue` | 懒加载 | 关于页面 |
| `/profile` | `profile` | `Profile.vue` | 懒加载 | 用户中心页面 |

## 3. 路由功能特性

### 3.1 路由懒加载

项目使用路由懒加载优化页面加载性能：

```javascript
const loadView = (view) => {
  return () => import(/* webpackChunkName: "view-[request]" */ `../views/${view}.vue`)
}
```

**优势：**
- 减少初始加载时间
- 按需加载组件
- 优化首屏性能

### 3.2 滚动行为

配置了页面跳转时自动滚动到顶部：

```javascript
scrollBehavior() {
  return { top: 0 }
}
```

### 3.3 路由动画

在 `NavigationBar.vue` 中配置了路由切换动画：

```vue
<router-view v-slot="{ Component }">
  <transition name="fade" mode="out-in">
    <component :is="Component" />
  </transition>
</router-view>
```

动画样式：

```css
/* 路由切换淡入淡出动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease, transform 0.3s ease;
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.fade-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
```

## 4. 路由使用方式

### 4.1 路由链接

使用 `router-link` 创建导航链接：

```vue
<router-link to="/" class="nav-item">
  Home
</router-link>

<router-link to="/chat" class="nav-item">
  Chat
</router-link>
```

### 4.2 编程式导航

使用 `$router` 进行编程式导航：

```javascript
// 字符串路径
router.push('/chat')

// 对象路径
router.push({ path: '/chat' })

// 命名路由
router.push({ name: 'chat' })

// 带参数
router.push({ name: 'chat', params: { id: '123' } })
```

### 4.3 路由守卫

可以添加路由守卫进行权限控制：

```javascript
// 全局前置守卫
router.beforeEach((to, from, next) => {
  // 检查用户是否登录
  const token = localStorage.getItem('token')
  if (to.meta.requiresAuth && !token) {
    next('/login')
  } else {
    next()
  }
})
```

## 5. 路由扩展建议

### 5.1 路由参数

可以为路由添加动态参数：

```javascript
{
  path: '/chat/:id',
  name: 'chatDetail',
  component: loadView('ChatDetail'),
  props: true
}
```

在组件中接收参数：

```javascript
defineProps({
  id: {
    type: String,
    required: true
  }
})
```

### 5.2 路由元信息

可以为路由添加元信息：

```javascript
{
  path: '/profile',
  name: 'profile',
  component: loadView('Profile'),
  meta: {
    requiresAuth: true,
    title: '用户中心'
  }
}
```

### 5.3 嵌套路由

可以配置嵌套路由实现复杂页面结构：

```javascript
{
  path: '/profile',
  name: 'profile',
  component: loadView('Profile'),
  children: [
    {
      path: 'settings',
      name: 'profileSettings',
      component: loadView('ProfileSettings')
    },
    {
      path: 'courses',
      name: 'myCourses',
      component: loadView('MyCourses')
    }
  ]
}
```

### 5.4 路由重定向

可以配置路由重定向：

```javascript
{
  path: '/old-path',
  redirect: '/new-path'
}
```

### 5.5 路由别名

可以为路由添加别名：

```javascript
{
  path: '/chat',
  name: 'chat',
  component: loadView('Chat'),
  alias: '/talk'
}
```

## 6. 路由优化建议

### 6.1 代码分割优化

使用路由懒加载时，可以添加加载状态：

```javascript
const loadView = (view) => {
  return () => new Promise((resolve, reject) => {
    // 显示加载状态
    document.body.classList.add('loading')
    
    import(`../views/${view}.vue`)
      .then(module => {
        resolve(module)
      })
      .catch(error => {
        reject(error)
      })
      .finally(() => {
        // 隐藏加载状态
        document.body.classList.remove('loading')
      })
  })
}
```

### 6.2 预加载路由

可以预加载常用路由：

```javascript
// 在首页加载完成后预加载聊天页面
window.addEventListener('load', () => {
  import('../views/Chat.vue')
})
```

### 6.3 路由缓存

使用 `keep-alive` 缓存路由组件：

```vue
<router-view v-slot="{ Component }">
  <transition name="fade" mode="out-in">
    <keep-alive>
      <component :is="Component" />
    </keep-alive>
  </transition>
</router-view>
```

## 7. 路由调试技巧

### 7.1 路由信息查看

可以在浏览器控制台查看路由信息：

```javascript
console.log(router.currentRoute.value)
```

### 7.2 Vue DevTools

使用 Vue DevTools 可以查看路由状态和历史记录。

### 7.3 路由日志

添加路由日志方便调试：

```javascript
router.beforeEach((to, from) => {
  console.log(`路由跳转: ${from.path} -> ${to.path}`)
})
```

## 8. 路由安全考虑

### 8.1 权限控制

对需要登录的路由添加权限检查：

```javascript
router.beforeEach((to, from, next) => {
  if (to.meta.requiresAuth) {
    const token = localStorage.getItem('token')
    if (!token) {
      next('/login')
      return
    }
  }
  next()
})
```

### 8.2 路由参数验证

对路由参数进行验证，防止恶意输入：

```javascript
router.beforeEach((to, from, next) => {
  if (to.params.id && !/^\d+$/.test(to.params.id)) {
    next('/404')
    return
  }
  next()
})
```

## 9. 路由扩展计划

### 9.1 新增路由

建议添加以下路由：

1. **登录页**: `/login`
2. **注册页**: `/register`
3. **课程详情**: `/course/:id`
4. **学习记录**: `/learning-history`
5. **设置页面**: `/settings`
6. **404页面**: `/:pathMatch(.*)*`

### 9.2 路由配置示例

```javascript
const routes = [
  // 现有路由...
  
  // 新增路由
  {
    path: '/login',
    name: 'login',
    component: loadView('Login'),
    meta: { requiresGuest: true }
  },
  {
    path: '/register',
    name: 'register',
    component: loadView('Register'),
    meta: { requiresGuest: true }
  },
  {
    path: '/course/:id',
    name: 'courseDetail',
    component: loadView('CourseDetail'),
    props: true
  },
  {
    path: '/learning-history',
    name: 'learningHistory',
    component: loadView('LearningHistory'),
    meta: { requiresAuth: true }
  },
  {
    path: '/settings',
    name: 'settings',
    component: loadView('Settings'),
    meta: { requiresAuth: true }
  },
  // 404页面
  {
    path: '/:pathMatch(.*)*',
    name: 'notFound',
    component: loadView('NotFound')
  }
]
```
