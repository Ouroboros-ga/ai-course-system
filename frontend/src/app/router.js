import { featureFlags } from '@/config/featureFlags.js'

/**
 * Shadow frontend routes (Vertical Slice 0.1).
 *
 * - All routes live under /app/** and require auth (enforced by the global
 *   beforeEach guard in src/router/index.js).
 * - When the shadowFrontend flag is off, /app/** redirects to the legacy
 *   home so nothing 404s and the old frontend remains the default.
 * - Every page renders only real-endpoint-provable data. Missing backend
 *   capabilities degrade to explicit empty/disabled states, never mocks.
 */
export const shadowAppRoutes = featureFlags.shadowFrontend
  ? [
      {
        path: '/app',
        component: () => import('./shell/AppShell.vue'),
        meta: { requiresAuth: true, shadow: true },
        children: [
          {
            path: '',
            name: 'app-home',
            component: () => import('./pages/home/AppHomePage.vue'),
          },
          {
            path: 'courses/learning',
            name: 'app-courses-learning',
            component: () => import('./pages/courses/LearningCoursesPage.vue'),
          },
          {
            path: 'course/:courseId(\\d+)',
            component: () => import('./pages/course/CourseLayout.vue'),
            children: [
              {
                path: '',
                name: 'app-course-index',
                redirect: (to) => `/app/course/${to.params.courseId}/overview`,
              },
              {
                path: 'overview',
                name: 'app-course-overview',
                component: () => import('./pages/course/CourseOverviewPage.vue'),
              },
              {
                path: 'learn',
                name: 'app-course-learn',
                component: () => import('./pages/learn/LearnPage.vue'),
              },
              {
                // 批次4：算法可视化页（接收 courseId 与可选 nodeId）
                path: 'visualize/:nodeId?',
                name: 'app-course-visualize',
                component: () => import('@/views/VisualizationView.vue'),
              },
            ],
          },
        ],
      },
      {
        path: '/app/:pathMatch(.*)*',
        redirect: '/app',
      },
    ]
  : [
      {
        path: '/app/:pathMatch(.*)*',
        redirect: '/',
      },
    ]
