import { createRouter, createWebHistory } from 'vue-router'
import { useCounterStore } from '@/stores/counter.js'
import { featureFlags } from '@/config/featureFlags.js'
import { shadowAppRoutes } from '@/app/router.js'
import { getMyInfo } from '@/api/user.js'

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
      // 正式首页为 /app(shadow 前端工作台),根路径统一重定向,不再渲染旧首页。
      // shadowFrontend 关闭时回退到 /home(旧首页),避免 / 与 /app/** 互相重定向成环。
      path: '/',
      redirect: featureFlags.shadowFrontend ? '/app' : '/home',
    },
    {
      // 旧首页(landing)仅作为 shadowFrontend 关闭时的回退挂载,不再是根路径页面。
      path: '/home',
      name: 'home',
      component: loadView('Home'),
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
      component: loadView('TeacherCourseWorkbench'),
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
    // Shadow frontend (/app/**). Flag-gated; legacy routes above stay the
    // default until the cutover phase flips the flag default.
    ...shadowAppRoutes,
    {
      path: '/admin',
      name: 'admin-panel',
      component: loadView('AdminPanel'),
      meta: { requiresAuth: true, requiredPlatformPermission: 'platform.admin' }
    },
    {
      // 证据查看器已迁入新壳 /app/evidence-viewer/:courseId/:runId(见 app/router.js)。
      // 保留旧路径与 name 'evidence-viewer' 作为 redirect,旧外链与
      // KnowledgeReviewsPage / KnowledgeEvidencePage / graph-browser 的
      // router.push({ name: 'evidence-viewer', ... }) 调用全部自动落入新 UI,
      // 不再套旧版 NavigationBar 壳。
      path: '/evidence-viewer/:courseId?/:runId?',
      name: 'evidence-viewer',
      redirect: (to) => {
        const parts = [to.params.courseId, to.params.runId].filter(Boolean)
        return { path: `/app/evidence-viewer/${parts.join('/')}`, query: to.query }
      },
    },
    {
      // Graph browser (P1-09 follow-up): visualizes ONLY real-endpoint-provable
      // structure (mapping course→knowledge-point→evidence). Retrieval trace is
      // not fabricated while the V2 shadow is unwired. Admin-only, flag-gated
      // (matches the V2 evidence endpoint admin-only discipline).
      path: '/graph-browser/:courseId?',
      name: 'graph-browser',
      component: featureFlags.graphBrowser
        ? () => import('../features/graph-browser/GraphBrowser.vue')
        : loadView('KnowledgeMappingWorkspace'),
      meta: { requiresAuth: true, role: 'admin', feature: 'graph-browser' }
    },
    {
      // Shadow-1 is a standalone local demo route. It is deliberately not
      // mounted inside Chat/StudentPlayer and always reports its disabled
      // state when the frontend/backend flags are off.
      path: '/demo/retrieval',
      name: 'retrieval-demo',
      component: loadView('RetrievalDemoPage'),
      meta: { requiresAuth: true, role: 'admin', feature: 'retrieval-demo' }
    },
    {
      // 顶层公开文档中心：不挂 AppShell、无需登录。
      // 文档文件在 frontend/public/static/docs/（构建进 dist 后由 nginx 直接静态服务），
      // /docs/view 为 PDF / Word 在线阅读器，file 参数相对 /docs 目录做白名单校验。
      path: '/docs',
      name: 'docs-home',
      component: () => import('@/app/pages/docs/DocsHomePage.vue'),
    },
    {
      path: '/docs/view',
      name: 'docs-view',
      component: () => import('@/app/pages/docs/DocsReaderPage.vue'),
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      redirect: featureFlags.shadowFrontend ? '/app' : '/home',
    }
  ],
  scrollBehavior() {
    return { top: 0 }
  }
})

router.beforeEach(async (to) => {
  const counter = useCounterStore()
  counter.checkAuth()

  if (to.meta.requiresAuth && !counter.isLoggedIn) {
    return { path: '/profile', query: { redirect: to.fullPath } }
  }

  // 目标模型：平台只有 user/admin；任何用户都可创建/建设课程，遗留 teacher 路由不再
  // 要求平台级 course.create 权限（课程内教学权限由 Course Access 决定）。
  const legacyRolePermission = to.meta.role === 'admin' ? 'platform.admin' : null
  const requiredPermission = to.meta.requiredPlatformPermission || legacyRolePermission
  if (requiredPermission && counter.isLoggedIn && !counter.hasPlatformPermission(requiredPermission)) {
    try {
      const data = await getMyInfo()
      counter.userData.username = data.username || counter.userData.username
      counter.userData.id = data.user_id || counter.userData.id
      counter.userData.role = data.role || 'user'
      counter.setPlatformPermissions(data.platform_permissions)
    } catch {
      return { path: '/app' }
    }
  }
  if (requiredPermission && !counter.hasPlatformPermission(requiredPermission)) return { path: '/app' }
  return true
})

export default router
