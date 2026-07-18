import { createRouter, createWebHistory } from 'vue-router'
import { useCounterStore } from '@/stores/counter.js'
import { featureFlags } from '@/config/featureFlags.js'

const loadView = (view) => {
  return () => import(`../views/${view}.vue`)
}

const prototypeRoutes = import.meta.env.VITE_ENABLE_FRONTEND_PROTOTYPES === 'true' ? [
    {
      path: '/prototype/student-learning/:courseId?',
      name: 'prototype-student-learning',
      component: () => import('../prototypes/pages/StudentLearningPrototype.vue'),
      meta: { requiresAuth: true, role: 'student', prototype: true }
    },
    {
      path: '/prototype/teacher-pipeline/:courseId?',
      name: 'prototype-teacher-pipeline',
      component: () => import('../prototypes/pages/TeacherPipelinePrototype.vue'),
      meta: { requiresAuth: true, role: 'teacher', prototype: true }
    }
  ] : []

const teacherQaRoutes = import.meta.env.VITE_ENABLE_FRONTEND_PROTOTYPES === 'true' &&
  import.meta.env.VITE_ENABLE_TEACHER_WORKSPACE_QA === 'true' ? [
    {
      path: '/prototype/teacher-production/:courseId?',
      name: 'prototype-teacher-production-workspace',
      component: loadView('TeacherProductionWorkspace'),
      meta: { prototype: true }
    },
    {
      path: '/prototype/teacher-mapping/:courseId?',
      name: 'prototype-teacher-mapping-workspace',
      component: loadView('KnowledgeMappingWorkspace'),
      meta: { prototype: true }
    }
  ] : []
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
      path: '/teacher/course/:courseId/production',
      name: 'teacher-production-workspace',
      component: featureFlags.teacherProductionWorkspace
        ? loadView('TeacherProductionWorkspace')
        : loadView('TeacherDashboard'),
      meta: { requiresAuth: true, role: 'teacher', feature: 'teacher-production-workspace' }
    },
    {
      path: '/teacher/course/:courseId/mapping',
      name: 'teacher-knowledge-mapping',
      component: featureFlags.knowledgeMappingWorkspace
        ? loadView('KnowledgeMappingWorkspace')
        : loadView('TeacherDashboard'),
      meta: { requiresAuth: true, role: 'teacher', feature: 'knowledge-mapping-workspace' }
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
      path: '/player/course/:courseId',
      name: 'student-player',
      component: featureFlags.studentLearningWorkspace
        ? loadView('StudentLearningWorkspace')
        : loadView('StudentPlayer'),
      meta: {
        requiresAuth: true,
        role: 'student',
        feature: featureFlags.studentLearningWorkspace
          ? 'student-learning-workspace'
          : 'legacy-student-player'
      }
    },
    ...prototypeRoutes,
    ...teacherQaRoutes,
    {
      path: '/admin',
      name: 'admin-panel',
      component: loadView('AdminPanel'),
      meta: { requiresAuth: true, role: 'admin' }
    },
    {
      // P1-09 G4B: formal mount of the P1-04 Evidence Viewer.
      // Independent route; does not touch SplitVideoPlayer/TeacherDashboard/
      // StudentDashboard. Admin-only (matches ADR-0006 §9 V2 endpoint
      // admin-only). Wired to the V2 Evidence API via api/evidence.js.
      path: '/evidence-viewer/:documentId?',
      name: 'evidence-viewer',
      component: loadView('EvidenceViewerPage'),
      meta: { requiresAuth: true, role: 'admin' }
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: loadView('Home')
    }
  ],
  scrollBehavior() {
    return { top: 0 }
  }
})

router.beforeEach((to, from, next) => {
  const counter = useCounterStore()
  counter.checkAuth()

  if (to.meta.requiresAuth && !counter.isLoggedIn) {
    next({ path: '/profile', query: { redirect: to.fullPath } })
  } else if (to.meta.role && counter.userData.role !== to.meta.role) {
    next({ path: '/' })
  } else {
    next()
  }
})

export default router
