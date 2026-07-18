export const studentCourseMock = {
  id: 101,
  name: '数据结构与算法',
  chapterLabel: '第 3 章 · 图的遍历',
  progress: 42,
  savedAt: '刚刚已保存',
  currentTime: 223,
  duration: 928,
  slidePage: 18,
  chapters: [
    {
      id: 'chapter-1',
      title: '第 1 章 绪论',
      progress: '3/3',
      expanded: false,
      points: [
        { id: '1-1', title: '1.1 数据结构的基本概念', status: 'completed', duration: '12:30' }
      ]
    },
    {
      id: 'chapter-2',
      title: '第 2 章 线性表',
      progress: '6/6',
      expanded: false,
      points: [
        { id: '2-3', title: '2.3 队列（Queue）', status: 'completed', duration: '11:20' }
      ]
    },
    {
      id: 'chapter-3',
      title: '第 3 章 图的遍历',
      progress: '4/7',
      expanded: true,
      points: [
        { id: '3-1', title: '3.1 图的基本概念', status: 'completed', duration: '14:18' },
        { id: '3-2', title: '3.2 图的存储表示', status: 'completed', duration: '16:04' },
        { id: '3-3', title: '3.3 深度优先遍历（DFS）', status: 'completed', duration: '18:42' },
        { id: '3-4', title: '3.4 广度优先遍历（BFS）', status: 'current', duration: '15:28' },
        { id: '3-5', title: '3.5 遍历算法复杂度', status: 'upcoming', duration: '12:16' },
        { id: '3-6', title: '3.6 遍历应用实例', status: 'upcoming', duration: '10:54' }
      ]
    },
    {
      id: 'chapter-4',
      title: '第 4 章 最小生成树',
      progress: '0/6',
      expanded: false,
      points: [
        { id: '4-1', title: '4.1 最小生成树概念', status: 'upcoming', duration: '13:40' }
      ]
    }
  ],
  prerequisite: {
    id: '2-3',
    title: '2.3 队列（Queue）',
    reason: 'BFS 依赖队列的先进先出特性',
    duration: '约 12 分钟'
  },
  guidedSummary: 'BFS 从起始顶点出发，按层访问相邻顶点。队列保证先发现的顶点先被处理，因此能得到无权图中的最短层级路径。',
  transcript: '现在把访问过程想象成水波向外扩散：先访问距离起点为 1 的顶点，再访问距离为 2 的顶点。每发现一个新顶点，就把它放入队列等待处理。',
  note: 'BFS 核心：队列 + visited 集合。\n复习：为什么入队时就要标记访问？',
  suggestedQuestions: [
    'BFS 与 DFS 的时间复杂度分别是多少？',
    '为什么 BFS 需要使用队列？',
    'BFS 为什么能找到无权图最短路径？'
  ],
  answer: {
    id: 'answer-1',
    question: '为什么 BFS 能找到距离最近的顶点？',
    text: 'BFS 通过队列按“层”推进。一个顶点出队时，它的所有未访问邻接点会依次入队，因此距离起点更近的顶点总会先于更远的顶点被处理。',
    confidence: 'low',
    confidenceText: '该回答由课程内容生成，引用定位契约仍在规划中，请结合课件核验。',
    citations: [
      {
        id: 'citation-1',
        title: '课件第 18 页 · 广度优先遍历',
        excerpt: '使用队列维护访问顺序，先将起始顶点入队并标记，循环取出队首顶点。',
        locatable: true,
        label: '规划引用 · Mock'
      },
      {
        id: 'citation-2',
        title: '教学脚本 · 3.4 当前讲解段',
        excerpt: '先访问距离起点为 1 的顶点，再访问距离为 2 的顶点。',
        locatable: false,
        label: '来源可读，尚不可稳定定位'
      }
    ]
  }
}

export const teacherCourseMock = {
  id: 101,
  name: '数据结构与算法',
  version: 'v1.3 草稿',
  savedAt: '10:32 已自动保存',
  steps: [
    { key: 'basic', title: '基本信息', status: 'confirmed', meta: '已确认' },
    { key: 'materials', title: '教学资料', status: 'confirmed', meta: '5 份资料' },
    { key: 'parsing', title: '文档解析', status: 'processing', meta: '65%' },
    { key: 'structure', title: '课程结构', status: 'confirmed', meta: '5 章' },
    { key: 'knowledge', title: '知识点', status: 'confirmed', meta: '28 个' },
    { key: 'script', title: '教学脚本', status: 'review_required', meta: '待确认 3' },
    { key: 'mapping', title: 'PPT 映射', status: 'warning', meta: '缺失 1' },
    { key: 'audio', title: '音频生成', status: 'failed', meta: '失败 1' },
    { key: 'avatar', title: '数字人生成', status: 'not_started', meta: '未开始' },
    { key: 'preview', title: '课程预览', status: 'not_started', meta: '未开始' },
    { key: 'publish', title: '发布检查', status: 'not_started', meta: '阻断 2' }
  ],
  chapters: [
    { title: '第 1 章 绪论', points: ['1.1 数据结构的基本概念', '1.2 抽象数据类型'] },
    { title: '第 2 章 线性表', points: ['2.1 线性表的定义', '2.2 顺序表', '2.3 队列'] },
    { title: '第 3 章 树与二叉树', points: ['3.1 树的基本概念', '3.2 二叉树', '3.3 遍历与应用'] }
  ],
  scriptBlocks: [
    {
      id: 'script-1',
      time: '00:00–00:24',
      text: '同学们好，欢迎学习《数据结构与算法》。在正式开始之前，我们先理解“数据结构”到底是什么。',
      slide: 3,
      generated: true,
      review: 'confirmed'
    },
    {
      id: 'script-2',
      time: '00:24–01:02',
      text: '数据结构是相互之间存在一种或多种特定关系的数据元素的集合，以及在这些元素上定义的操作的集合。',
      slide: 4,
      generated: true,
      review: 'review_required'
    },
    {
      id: 'script-3',
      time: '01:02–01:38',
      text: '我们可以从数据、结构和操作三个方面理解。数据是客观事物的符号表示，结构是组织关系，操作是处理方法。',
      slide: 5,
      generated: true,
      review: 'review_required'
    }
  ],
  tasks: [
    {
      id: 'task-audio-1',
      title: '音频生成 · 2.2 顺序表',
      type: 'audio',
      status: 'failed',
      progress: 0,
      error: '语音合成服务超时（503）',
      retryable: true
    },
    {
      id: 'task-parse-1',
      title: '文档解析 · 算法设计与分析.pdf',
      type: 'parsing',
      status: 'running',
      progress: 65,
      error: '',
      retryable: false
    }
  ],
  checks: [
    { id: 'check-1', title: '1.1.3 知识点脚本未填写', severity: 'blocker', step: 'script', resolved: false },
    { id: 'check-2', title: '2.2.2 缺少 PPT 映射', severity: 'warning', step: 'mapping', resolved: false },
    { id: 'check-3', title: '3.3.1 缺少参考资料来源', severity: 'warning', step: 'script', resolved: false }
  ]
}

export const prototypeStatusLabels = {
  not_started: '未开始',
  processing: '处理中',
  running: '处理中',
  generated: 'AI 已生成',
  review_required: '待教师确认',
  confirmed: '已确认',
  warning: '有警告',
  failed: '失败',
  completed: '已完成',
  current: '学习中',
  upcoming: '待学习'
}
