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
