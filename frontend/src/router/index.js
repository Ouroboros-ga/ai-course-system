import { createRouter, createWebHistory } from 'vue-router'
import { useCounterStore } from '@/stores/counter.js'
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
const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      // 新壳工作台（/app/**）是唯一默认入口；旧首页与旧版页面已删除。
      path: '/',
      redirect: '/app',
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
    ...prototypeRoutes,
    // Shadow frontend (/app/**)：新壳工作台，是当前唯一前端体系。
    ...shadowAppRoutes,
    {
      // 证据查看器已迁入新壳 /app/evidence-viewer/:courseId/:runId(见 app/router.js)。
      // 保留旧路径与 name 'evidence-viewer' 作为 redirect,旧外链与
      // KnowledgeReviewsPage / KnowledgeEvidencePage / graph-browser 的
      // router.push({ name: 'evidence-viewer', ... }) 调用全部自动落入新 UI。
      path: '/evidence-viewer/:courseId?/:runId?',
      name: 'evidence-viewer',
      redirect: (to) => {
        const parts = [to.params.courseId, to.params.runId].filter(Boolean)
        return { path: `/app/evidence-viewer/${parts.join('/')}`, query: to.query }
      },
    },
    {
      // Graph browser (P1-09 follow-up): visualizes ONLY real-endpoint-provable
      // structure (mapping course→knowledge-point→evidence). Admin-only.
      path: '/graph-browser/:courseId?',
      name: 'graph-browser',
      component: () => import('../features/graph-browser/GraphBrowser.vue'),
      meta: { requiresAuth: true, role: 'admin' }
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
      redirect: '/app',
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
