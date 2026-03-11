import { createRouter, createWebHashHistory } from 'vue-router'
import HomeView from '../views/home.vue'

const router = createRouter({
  history: createWebHashHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView
    },
    {
      path: '/about',
      name: 'about',
      component: () => import('../views/about.vue'),
    },
    {
      path: '/document',
      name: 'document',
      component: () => import('../views/document.vue'),
    },
  ],
})

export default router
