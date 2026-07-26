import { featureFlags } from '@/config/featureFlags.js'

/**
 * Shadow frontend routes（design.md / page-design.md / PageDesign前端API契约规划）。
 *
 * - All routes live under /app/** and require auth (enforced by the global
 *   beforeEach guard in src/router/index.js).
 * - When the shadowFrontend flag is off, /app/** redirects to the legacy
 *   home so nothing 404s and the old frontend remains the default.
 * - Pages render real-endpoint-provable data; `planned` 契约（当前后端未实现）
 *   只展示冻结契约与可解释空状态，绝不伪造数据（API 契约 §1.1/§4）。
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

          // ── 我的课程（page-design §9）：L2 我学习的｜我建设的｜课程大厅 ──
          {
            path: 'courses',
            component: () => import('./pages/courses/CoursesLayout.vue'),
            children: [
              { path: '', redirect: '/app/courses/learning' },
              {
                path: 'learning',
                name: 'app-courses-learning',
                component: () => import('./pages/courses/LearningCoursesPage.vue'),
              },
              {
                path: 'building',
                name: 'app-courses-building',
                component: () => import('./pages/courses/BuildingCoursesPage.vue'),
              },
              {
                path: 'hall',
                name: 'app-courses-hall',
                component: () => import('./pages/courses/CourseHallPage.vue'),
              },
            ],
          },

          // ── 平台实验室（page-design §19） ──
          {
            path: 'lab',
            component: () => import('./pages/lab/LabLayout.vue'),
            children: [
              { path: '', redirect: '/app/lab/hall' },
              {
                path: 'hall',
                name: 'app-lab-hall',
                component: () => import('./pages/lab/LabHallPage.vue'),
              },
              {
                path: 'course-tasks',
                name: 'app-lab-course-tasks',
                component: () => import('./pages/lab/LabCourseTasksPage.vue'),
              },
              {
                path: 'my-experiments',
                name: 'app-lab-my-experiments',
                component: () => import('./pages/lab/LabMyExperimentsPage.vue'),
              },
              {
                path: 'records',
                name: 'app-lab-records',
                component: () => import('./pages/lab/LabRecordsPage.vue'),
              },
            ],
          },

          // ── 资源库（page-design §20） ──
          {
            path: 'resources',
            component: () => import('./pages/resources/ResourcesLayout.vue'),
            children: [
              { path: '', redirect: '/app/resources/files' },
              {
                path: 'files',
                name: 'app-resources-files',
                component: () => import('./pages/resources/ResourceFilesPage.vue'),
              },
              {
                path: 'course-links',
                name: 'app-resources-course-links',
                component: () => import('./pages/resources/ResourceCourseLinksPage.vue'),
              },
              {
                path: 'recent',
                name: 'app-resources-recent',
                component: () => import('./pages/resources/ResourceRecentPage.vue'),
              },
              {
                path: 'trash',
                name: 'app-resources-trash',
                component: () => import('./pages/resources/ResourceTrashPage.vue'),
              },
            ],
          },

          // ── 任务中心（page-design §21） ──
          {
            path: 'tasks',
            component: () => import('./pages/tasks/TasksLayout.vue'),
            children: [
              { path: '', redirect: '/app/tasks/todo' },
              {
                path: 'todo',
                name: 'app-tasks-todo',
                component: () => import('./pages/tasks/TaskTodoPage.vue'),
              },
              {
                path: 'created',
                name: 'app-tasks-created',
                component: () => import('./pages/tasks/TaskCreatedPage.vue'),
              },
              {
                path: 'system',
                name: 'app-tasks-system',
                component: () => import('./pages/tasks/TaskSystemPage.vue'),
              },
              {
                path: 'completed',
                name: 'app-tasks-completed',
                component: () => import('./pages/tasks/TaskCompletedPage.vue'),
              },
            ],
          },

          // ── 课程空间（page-design §10–§18） ──
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

              // 知识空间（§15）：Local Rail 结构视图｜原文引用｜候选审核｜版本记录
              {
                path: 'knowledge',
                component: () => import('./pages/course/knowledge/KnowledgeLayout.vue'),
                children: [
                  { path: '', redirect: (to) => `/app/course/${to.params.courseId}/knowledge/graph` },
                  {
                    path: 'graph/:nodeId?',
                    name: 'app-course-knowledge',
                    component: () => import('./pages/course/knowledge/KnowledgeGraphPage.vue'),
                  },
                  {
                    path: 'evidence',
                    name: 'app-course-knowledge-evidence',
                    component: () => import('./pages/course/knowledge/KnowledgeEvidencePage.vue'),
                  },
                  {
                    path: 'reviews',
                    name: 'app-course-knowledge-reviews',
                    component: () => import('./pages/course/knowledge/KnowledgeReviewsPage.vue'),
                  },
                  {
                    path: 'snapshots',
                    name: 'app-course-knowledge-snapshots',
                    component: () => import('./pages/course/knowledge/KnowledgeSnapshotsPage.vue'),
                  },
                ],
              },

              // 教师课程建设（§14）：Local Rail 七步
              {
                path: 'build',
                component: () => import('./pages/course/build/BuildLayout.vue'),
                children: [
                  { path: '', redirect: (to) => `/app/course/${to.params.courseId}/build/materials` },
                  {
                    path: 'materials',
                    name: 'app-course-build-materials',
                    component: () => import('./pages/course/build/BuildMaterialsPage.vue'),
                  },
                  {
                    path: 'structure',
                    name: 'app-course-build-structure',
                    component: () => import('./pages/course/build/BuildStructurePage.vue'),
                  },
                  {
                    path: 'scripts',
                    name: 'app-course-build-scripts',
                    component: () => import('./pages/course/build/BuildScriptsPage.vue'),
                  },
                  {
                    path: 'mapping',
                    name: 'app-course-build-mapping',
                    component: () => import('./pages/course/build/BuildMappingPage.vue'),
                  },
                  {
                    path: 'media',
                    name: 'app-course-build-media',
                    component: () => import('./pages/course/build/BuildMediaPage.vue'),
                  },
                  {
                    path: 'validate',
                    name: 'app-course-build-validate',
                    component: () => import('./pages/course/build/BuildValidatePage.vue'),
                  },
                  {
                    path: 'releases',
                    name: 'app-course-build-releases',
                    component: () => import('./pages/course/build/BuildReleasesPage.vue'),
                  },
                ],
              },

              // 课程实验任务（§16）
              {
                path: 'experiments',
                name: 'app-course-experiments',
                component: () => import('./pages/course/CourseExperimentsPage.vue'),
              },

              // 成员（§17）：成员列表｜加入申请
              {
                path: 'members',
                component: () => import('./pages/course/members/MembersLayout.vue'),
                children: [
                  { path: '', redirect: (to) => `/app/course/${to.params.courseId}/members/list` },
                  {
                    path: 'list',
                    name: 'app-course-members-list',
                    component: () => import('./pages/course/members/MemberListPage.vue'),
                  },
                  {
                    path: 'requests',
                    name: 'app-course-members-requests',
                    component: () => import('./pages/course/members/JoinRequestsPage.vue'),
                  },
                ],
              },

              // 课程设置（§18）：六项 Local Rail
              {
                path: 'settings',
                component: () => import('./pages/course/settings/SettingsLayout.vue'),
                children: [
                  { path: '', redirect: (to) => `/app/course/${to.params.courseId}/settings/profile` },
                  {
                    path: 'profile',
                    name: 'app-course-settings-profile',
                    component: () => import('./pages/course/settings/SettingsProfilePage.vue'),
                  },
                  {
                    path: 'access',
                    name: 'app-course-settings-access',
                    component: () => import('./pages/course/settings/SettingsAccessPage.vue'),
                  },
                  {
                    path: 'agent',
                    name: 'app-course-settings-agent',
                    component: () => import('./pages/course/settings/SettingsAgentPage.vue'),
                  },
                  {
                    path: 'safety',
                    name: 'app-course-settings-safety',
                    component: () => import('./pages/course/settings/SettingsSafetyPage.vue'),
                  },
                  {
                    path: 'sandbox',
                    name: 'app-course-settings-sandbox',
                    component: () => import('./pages/course/settings/SettingsSandboxPage.vue'),
                  },
                  {
                    path: 'integrations',
                    name: 'app-course-settings-integrations',
                    component: () => import('./pages/course/settings/SettingsIntegrationsPage.vue'),
                  },
                ],
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
