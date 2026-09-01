/**
 * Shadow frontend routes（design.md / page-design.md / PageDesign前端API契约规划）。
 *
 * - All routes live under /app/** and require auth (enforced by the global
 *   beforeEach guard in src/router/index.js).
 * - Pages render real-endpoint-provable data; `planned` 契约（当前后端未实现）
 *   只展示冻结契约与可解释空状态，绝不伪造数据（API 契约 §1.1/§4）。
 */
export const shadowAppRoutes = [
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
              {
                path: 'create',
                name: 'app-courses-create',
                component: () => import('./pages/courses/CreateCoursePage.vue'),
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

          // ── 学科知识库（XH-202620 CS 垂类，只读检索） ──
          {
            path: 'discipline-knowledge',
            name: 'app-discipline-knowledge',
            component: () => import('./pages/discipline/DisciplineKnowledgePage.vue'),
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
                path: 'course-materials',
                name: 'app-resources-course-materials',
                component: () => import('./pages/resources/CourseMaterialsLibraryPage.vue'),
              },
              {
                path: 'notes',
                name: 'app-resources-notes',
                component: () => import('./pages/resources/CourseNotesLibraryPage.vue'),
              },
              {
                path: 'notes/:courseId(\\d+)',
                name: 'app-resources-notes-course',
                component: () => import('./pages/resources/CourseNotesPage.vue'),
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

          {
            path: 'admin',
            name: 'app-admin',
            component: () => import('./pages/admin/PlatformAdminPage.vue'),
            meta: { requiredPlatformPermission: 'platform.user.manage' },
          },
          {
            path: 'account',
            name: 'app-account',
            component: () => import('./pages/account/AccountPage.vue'),
          },

          // 证据查看器：读取 Canonical DocumentIR 原文，全宽阅读体验，
          // 直接挂 AppShell 一级导航（无课程二级菜单）。
          {
            path: 'evidence-viewer/:courseId?/:runId?',
            name: 'app-evidence-viewer',
            component: () => import('@/views/EvidenceViewerPage.vue'),
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
              {
                path: 'analytics',
                name: 'app-course-analytics',
                component: () => import('./pages/course/CourseAnalyticsPage.vue'),
                meta: { requiredPermission: 'analytics.view_course' },
              },
              {
                path: 'research',
                name: 'app-course-research',
                component: () => import('./pages/course/research/ResearchWorkspacePage.vue'),
                // Discoverability and execution are separate: any course member
                // with course.view can open the workspace, while every mutating
                // Harness API/tool still rechecks course.question.ask.
                meta: { requiredPermission: 'course.view' },
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
                    path: 'candidates',
                    name: 'app-course-knowledge-candidates',
                    component: () => import('./pages/course/knowledge/KnowledgeCandidateReviewPage.vue'),
                  },
                  {
                    path: 'snapshots',
                    name: 'app-course-knowledge-snapshots',
                    component: () => import('./pages/course/knowledge/KnowledgeSnapshotsPage.vue'),
                  },
                ],
              },

              // 教师课程建设（§14）：七个 build 子路由 + 一个跨布局知识步骤
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
                  {
                    path: 'drafts',
                    name: 'app-course-build-drafts',
                    redirect: (to) => `/app/course/${to.params.courseId}/knowledge/`,
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
