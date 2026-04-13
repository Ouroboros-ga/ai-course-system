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
      component: loadView('Chat')
    },
    {
      path: '/Edulib',
      name: 'Edulib',
      component: loadView('Edulib')
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
    // 老师端路由
    {
      path: '/teacher',
      redirect: '/teacher/history'
    },
    {
      path: '/teacher/history',
      name: 'teacher-history',
      component: loadView('TeacherHistory'),
      meta: { requiresAuth: true, role: 'teacher' }
    },
    {
      path: '/teacher/create',
      name: 'teacher-create',
      component: loadView('TeacherDashboard'),
      meta: { requiresAuth: true, role: 'teacher' }
    },
    {
      path: '/teacher/course/:courseId',
      name: 'teacher-course',
      component: loadView('TeacherDashboard'),
      meta: { requiresAuth: true, role: 'teacher' }
    },
    // 学生端路由
    {
      path: '/student',
      name: 'student-dashboard',
      component: loadView('StudentDashboard'),
      meta: { requiresAuth: true, role: 'student' }
    },
    {
      path: '/student/course/:courseId',
      name: 'student-course',
      component: loadView('StudentDashboard'),
      meta: { requiresAuth: true, role: 'student' }
    },
  ],
  // 页面跳转时滚动到顶部（体验优化）
  scrollBehavior() {
    return { top: 0 }
  }
})

export default router
