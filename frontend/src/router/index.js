import { createRouter, createWebHistory } from 'vue-router'
import { useCounterStore } from '@/stores/counter.js'

const loadView = (view) => {
  return () => import(`../views/${view}.vue`)
}

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: loadView('Home')
    },
    {
      path: '/chat',
      name: 'chat',
      component: loadView('Chat')
    },
    {
      path: '/edulib',
      name: 'Edulib',
      component: loadView('Edulib')
    },
    {
      path: '/Edulib',
      redirect: '/edulib'
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
    {
      path: '/sso/callback',
      name: 'sso-callback',
      component: loadView('SsoCallback')
    },
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
    {
      path: '/admin',
      name: 'admin-panel',
      component: loadView('AdminPanel'),
      meta: { requiresAuth: true, role: 'admin' }
    },
  ],
  scrollBehavior() {
    return { top: 0 }
  }
})

router.beforeEach((to, from, next) => {
  const counter = useCounterStore()

  if (to.meta.requiresAuth && !counter.isLoggedIn) {
    next({ path: '/profile', query: { redirect: to.fullPath } })
  } else if (to.meta.role && counter.userData.role !== to.meta.role) {
    next({ path: '/' })
  } else {
    next()
  }
})

export default router
