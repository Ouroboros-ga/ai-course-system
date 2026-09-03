/**
 * Nexus 前端数据契约与数据源统一适配层。
 *
 * 核心设计原则：
 * 1. 【真实/演示双实现】通过 NEXUS_DATA_SOURCE 单一入口切换：
 *    - 'real'：真实调用后端反代 /api/v1/nexus/* + 既有 facade/discipline 接口
 *    - 'demo'：本地回放脚本化数据流（用于纯前端演示、评审审查）
 * 2. 【契约对齐】两套实现的函数签名、返回值结构完全一致。
 * 3. 【可观测性】demo 模式下 UI 会显式展示「演示数据」提示徽标，绝不假造真实成功。
 */

import { ref } from 'vue'
import { getNexusHealth, streamNexusMessage } from '@/api/nexus.js'
import { listFacadeCourses } from '@/api/facade.js'
import { listBuildMaterials } from '@/api/course_build.js'
import { getDisciplineKnowledgeOverview } from '@/api/disciplineKnowledge.js'

export const NEXUS_MODES = {
  GENERAL: 'nexus_general',
  RESEARCH: 'nexus_research',
}

export const NEXUS_MODE_CONFIG = {
  [NEXUS_MODES.GENERAL]: {
    label: 'Nexus',
    badge: 'General',
    desc: '通用复杂任务、资料整理、知识问答与文档生成',
    icon: 'Sparkles',
    tools: ['web_search'],
  },
  [NEXUS_MODES.RESEARCH]: {
    label: 'Nexus Research',
    badge: 'Research',
    desc: '论文研究、学术检索、研究比较与 NexusLab 复现',
    icon: 'Microscope',
    tools: ['web_search', 'search_arxiv_papers', 'plan_reproduction', 'run_reproduction'],
  },
}

// 当前数据源模式：'real' | 'demo'
export const nexusDataSourceMode = ref(
  localStorage.getItem('nexus_datasource_mode') || 'demo'
)

export function setNexusDataSourceMode(mode) {
  if (['real', 'demo'].includes(mode)) {
    nexusDataSourceMode.value = mode
    localStorage.setItem('nexus_datasource_mode', mode)
  }
}

// ── 本地 Demo 模拟会话库 ──
const DEMO_SESSIONS_KEY = 'nexus_demo_sessions_v1'

const DEFAULT_DEMO_SESSIONS = [
  {
    id: 'demo-s1',
    title: 'Transformer 架构与注意力机制演进',
    mode: NEXUS_MODES.RESEARCH,
    pinned: true,
    createdAt: Date.now() - 3600 * 1000 * 2, // 2小时前
    updatedAt: Date.now() - 3600 * 1000 * 2,
    courseId: 1,
    courseName: '数据结构与算法',
    turns: [
      {
        question: '对比一下 standard attention 与 flash attention 的内存占用机制，并列出经典论文。',
        answer: '### 标准注意力与 FlashAttention 显存开销对比\n\n在传统 **Standard Attention** 中，计算 Softmax 矩阵需要将 $N \\times N$ 的中间注意力得分矩阵显式写入 HBM（高带宽显存），其显存复杂度为 $\\mathcal{O}(N^2)$，这构成了长文本推理的核心瓶颈。\n\n**FlashAttention (Dao et al., 2022)** 通过 **Tiling（分块计算）** 与 **Recomputation（前向重计算）** 避免了向 HBM 写入完整的注意力矩阵，仅在 GPU SRAM（高速片上缓存）中流式增量计算 Softmax，将显存复杂度降至 $\\mathcal{O}(N)$。\n\n```python\n# 标准注意力 vs FlashAttention 计算流程差异\n# Standard: Q, K -> S = QK^T (HBM) -> P = softmax(S) (HBM) -> O = PV (HBM)\n# Flash:    分块加载 Q_i, K_j 到 SRAM -> 局部 Softmax 归一化 -> 累加输出 O_i\n```\n\n#### 核心文献索引\n1. **Attention Is All You Need** (Vaswani et al., 2017) - arXiv:1706.03762\n2. **FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness** (Dao et al., 2022) - arXiv:2205.14135',
        toolEvents: [
          { kind: 'call', name: 'search_arxiv_papers', args: { query: 'FlashAttention Fast and Memory-Efficient Exact Attention', limit: 3 } },
          { kind: 'result', name: 'search_arxiv_papers', status: 'success', content: '{"total": 2, "items": [{"paper_id": "2205.14135", "title": "FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness", "authors": ["Tri Dao", "Daniel Y. Fu", "Stefano Ermon", "Atri Rudra", "Christopher Ré"], "year": 2022}]}' },
        ],
        tokenCount: 420,
        taskPlan: {
          title: '论文检索与机制剖析',
          steps: [
            { id: 1, text: '检索 arXiv 上的 FlashAttention 原文', status: 'completed' },
            { id: 2, text: '提取 HBM 与 SRAM 访存模型公式', status: 'completed' },
            { id: 3, text: '整理长序列复杂度对比并生成报告', status: 'completed' },
          ],
        },
        papers: [
          {
            paper_id: '2205.14135',
            title: 'FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness',
            authors: ['Tri Dao', 'Daniel Y. Fu', 'Stefano Ermon', 'Atri Rudra', 'Christopher Ré'],
            published_at: '2022-05-27T17:59:00Z',
            year: 2022,
            primary_category: 'cs.LG',
            source_url: 'https://arxiv.org/abs/2205.14135',
            abstract: 'Transformers are slow and memory-hungry on long sequences, since the time and memory complexity of self-attention are quadratic in sequence length. We propose FlashAttention, an IO-aware exact attention algorithm that uses tiling to reduce the number of memory reads/writes between GPU high bandwidth memory (HBM) and GPU on-chip SRAM.',
          },
          {
            paper_id: '1706.03762',
            title: 'Attention Is All You Need',
            authors: ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar', 'Jakob Uszkoreit', 'Llion Jones', 'Aidan N. Gomez', 'Lukasz Kaiser', 'Illia Polosukhin'],
            published_at: '2017-06-12T17:57:34Z',
            year: 2017,
            primary_category: 'cs.CL',
            source_url: 'https://arxiv.org/abs/1706.03762',
            abstract: 'The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. We propose the Transformer, a model architecture eschewing recurrence and instead relying entirely on an attention mechanism to draw global dependencies between input and output.',
          },
        ],
        artifacts: [
          { id: 'art-1', name: 'attention-complexity-analysis.md', type: 'markdown', size: '3.4 KB', status: 'completed' },
        ],
      },
    ],
  },
  {
    id: 'demo-s2',
    title: 'nanoGPT 复现路线与环境构建',
    mode: NEXUS_MODES.RESEARCH,
    pinned: false,
    createdAt: Date.now() - 3600 * 1000 * 26, // 昨天
    updatedAt: Date.now() - 3600 * 1000 * 26,
    courseId: null,
    courseName: null,
    turns: [
      {
        question: '帮我规划一下 nanoGPT 的复现步骤',
        answer: '已根据预设库提取到 **nanoGPT (Karpathy, MIT License)** 的官方复现方案。这是最轻量、训练 GPT-2 结构最纯粹的代码库。下面是建议的执行路径：',
        toolEvents: [
          { kind: 'call', name: 'plan_reproduction', args: { target: 'nanogpt' } },
          { kind: 'result', name: 'plan_reproduction', status: 'success', content: '{"status": "success", "plan": {"preset_id": "nanogpt", "repo_url": "https://github.com/karpathy/nanoGPT", "repo_license": "MIT", "steps": ["git clone", "pip install -r requirements.txt", "python data/shakespeare_char/prepare.py", "python train.py config/train_shakespeare_char.py --device=cpu --compile=False --max_iters=20", "python sample.py --out_dir=out-shakespeare-char --device=cpu"]}}' },
        ],
        tokenCount: 280,
        reproductionPreset: {
          preset_id: 'nanogpt',
          paper_title: 'Language Models are Unsupervised Multitask Learners (GPT-2, Radford et al., 2019)',
          repo_url: 'https://github.com/karpathy/nanoGPT',
          repo_license: 'MIT',
          repo_stars: 62738,
          cpu_friendly: true,
          estimated_minutes: 5,
          language: 'python',
          steps: [
            'git clone https://github.com/karpathy/nanoGPT.git',
            'pip install torch numpy transformers datasets tiktoken wandb tqdm',
            'python data/shakespeare_char/prepare.py',
            'python train.py config/train_shakespeare_char.py --device=cpu --compile=False --eval_iters=5 --max_iters=20',
            'python sample.py --out_dir=out-shakespeare-char --device=cpu --max_new_tokens=100',
          ],
          expected_artifacts: ['ckpt.pt (训练权重)', 'shakespeare 生成文本样张'],
        },
      },
    ],
  },
  {
    id: 'demo-s3',
    title: '快速整理：Python 协程与异步 IO 机制',
    mode: NEXUS_MODES.GENERAL,
    pinned: false,
    createdAt: Date.now() - 3600 * 1000 * 72, // 3天前
    updatedAt: Date.now() - 3600 * 1000 * 72,
    courseId: 2,
    courseName: 'Python程序设计',
    turns: [],
  },
]

export function loadLocalSessions() {
  try {
    const raw = localStorage.getItem(DEMO_SESSIONS_KEY)
    if (!raw) {
      localStorage.setItem(DEMO_SESSIONS_KEY, JSON.stringify(DEFAULT_DEMO_SESSIONS))
      return DEFAULT_DEMO_SESSIONS
    }
    return JSON.parse(raw)
  } catch {
    return DEFAULT_DEMO_SESSIONS
  }
}

export function saveLocalSessions(sessions) {
  try {
    localStorage.setItem(DEMO_SESSIONS_KEY, JSON.stringify(sessions))
  } catch (e) {
    console.warn('saveLocalSessions error', e)
  }
}

/**
 * 获取上下文信息源概览数据（真实/演示）
 */
/**
 * 上下文概览。
 *
 * 【fail-closed 硬规则】返回体必须携带 source，取值三选一：
 *   'real'        —— 数字来自真实接口
 *   'demo'        —— 数字是演示数据（UI 必须显式标注）
 *   'unavailable' —— 真实接口调用失败，数字一律为 null
 *
 * 真实模式下接口失败时**绝不回落到硬编码数字**：
 * 一个看起来正常的假数字，比一个明确的"不可用"危险得多。
 */
export async function getContextOverview({ courseId = null } = {}) {
  if (nexusDataSourceMode.value === 'real') {
    try {
      const [kbOverview, coursesRes] = await Promise.all([
        getDisciplineKnowledgeOverview().catch(() => null),
        listFacadeCourses('learning', { page_size: 50 }).catch(() => null),
      ])
      let materialsCount = null
      if (courseId) {
        const matRes = await listBuildMaterials(courseId).catch(() => null)
        materialsCount = matRes?.total ?? matRes?.items?.length ?? null
      }
      return {
        source: 'real',
        disciplineKb: {
          nodeCount: kbOverview?.node_count ?? null,
          relationCount: kbOverview?.relation_count ?? null,
          coursesCount: kbOverview?.courses ? Object.keys(kbOverview.courses).length : null,
        },
        coursesList: coursesRes?.items || [],
        materialsCount,
      }
    } catch (err) {
      return {
        source: 'unavailable',
        error: err?.message || '上下文接口不可用',
        disciplineKb: { nodeCount: null, relationCount: null, coursesCount: null },
        coursesList: [],
        materialsCount: null,
      }
    }
  }

  // Demo 模式：数字是编的，source 必须如实标记
  return {
    source: 'demo',
    disciplineKb: {
      nodeCount: 42381,
      relationCount: 128940,
      coursesCount: 8,
    },
    coursesList: [
      { course_id: 1, title: '数据结构与算法', role: 'STUDENT', progress: 0.72 },
      { course_id: 2, title: 'Python程序设计', role: 'STUDENT', progress: 0.45 },
      { course_id: 3, title: '计算机体系结构', role: 'STUDENT', progress: 0.2 },
    ],
    materialsCount: courseId ? 156 : null,
  }
}

/**
 * Demo 模式下的流式事件模拟发射器
 */
export async function streamDemoMessage({ message, onEvent, signal }) {
  const isArxivQuery = /arxiv|paper|论文|gpt|transformer|attention|flash/i.test(message)
  const isReproQuery = /复现|reproduce|nanogpt|跑一下|实验/i.test(message)

  // 每次 sleep 只注册一个一次性 abort 监听，并在正常结束时移除，
  // 避免长回答累积上百个常驻 listener。
  const abortError = () => {
    const err = new Error('已中止')
    err.name = 'AbortError'
    return err
  }

  const sleep = (ms) => new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError())
      return
    }
    let timer = null
    const onAbort = () => {
      if (timer) clearTimeout(timer)
      reject(abortError())
    }
    timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    signal?.addEventListener('abort', onAbort, { once: true })
  })

  // 1. 发射规划
  await sleep(150)
  onEvent({
    event: 'tool_call',
    data: {
      name: isArxivQuery ? 'search_arxiv_papers' : 'web_search',
      args: { query: message, limit: 5 },
    },
  })

  await sleep(600)
  if (isArxivQuery) {
    onEvent({
      event: 'tool_result',
      data: {
        name: 'search_arxiv_papers',
        status: 'success',
        content: JSON.stringify({
          total: 2,
          provider: 'arxiv',
          items: [
            {
              paper_id: '1706.03762',
              title: 'Attention Is All You Need',
              authors: ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar'],
              year: 2017,
              source_url: 'https://arxiv.org/abs/1706.03762',
              abstract: 'The dominant sequence transduction models are based on complex recurrent or convolutional neural networks. We propose the Transformer architecture...',
            },
            {
              paper_id: '2205.14135',
              title: 'FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness',
              authors: ['Tri Dao', 'Daniel Y. Fu', 'Stefano Ermon'],
              year: 2022,
              source_url: 'https://arxiv.org/abs/2205.14135',
              abstract: 'Transformers are slow and memory-hungry on long sequences. We propose FlashAttention, an IO-aware exact attention algorithm...',
            },
          ],
        }),
      },
    })
  } else if (isReproQuery) {
    onEvent({
      event: 'tool_call',
      data: { name: 'plan_reproduction', args: { target: 'nanogpt' } },
    })
    await sleep(400)
    onEvent({
      event: 'tool_result',
      data: {
        name: 'plan_reproduction',
        status: 'success',
        content: JSON.stringify({
          status: 'success',
          plan: {
            preset_id: 'nanogpt',
            repo_url: 'https://github.com/karpathy/nanoGPT',
            repo_license: 'MIT',
            steps: ['git clone ...', 'pip install ...', 'python train.py ...'],
          },
        }),
      },
    })
  } else {
    onEvent({
      event: 'tool_result',
      data: {
        name: 'web_search',
        status: 'success',
        content: JSON.stringify({
          channel: 'searxng',
          total: 3,
          items: [
            { title: '深入理解 Transformer 架构与核心实现', url: 'https://example.edu/transformer-guide', snippet: '本文系统阐述自注意力机制、多头注意力与位置编码的核心数学推导与代码实现。' },
            { title: 'PyTorch 官方教程：从零实现自注意力', url: 'https://pytorch.org/tutorials', snippet: '详细讲解 torch.nn.MultiheadAttention 的内存排布与前向传播优化策略。' },
          ],
        }),
      },
    })
  }

  await sleep(300)

  // 2. Token 流式输出
  const answerParagraphs = isReproQuery
    ? [
        '根据你的复现需求，已匹配到 **nanoGPT** 官方预设验证脚本。',
        '\n\n```bash\n# 快速复现指令（CPU 验证档，预计 3 分钟）\ngit clone https://github.com/karpathy/nanoGPT.git\ncd nanoGPT\npip install torch numpy transformers datasets tiktoken wandb tqdm\npython data/shakespeare_char/prepare.py\npython train.py config/train_shakespeare_char.py --device=cpu --compile=False --max_iters=20\n```\n\n',
        '该仓库使用 **MIT 许可**，符合平台安全合规基线。你可以在下方卡片中点击「确认并开始复现」，或在 NexusLab 中查看实时日志与指标对比。',
      ]
    : [
        '已经为你检索并综合了相关资料与学术成果。',
        '\n\n### 核心要点归纳\n\n1. **机制与原理**：注意力机制本质上是加权动态检索，通过 Query 与 Key 的相似度计算得到 Value 的线性组合。\n2. **计算瓶颈**：标准注意力计算受制于高显存 IO 读写，现代推理优化方案（如 FlashAttention）核心在于 SRAM 分块流式累加。\n3. **课程与知识库关联**：在当前《数据结构与算法》课程的图与动态规划章节中，矩阵乘法的访存局部性是理解该优化的关键前置知识。\n\n',
        '如需导出报告或进入实验复现，请点击右侧 **Artifacts** 面板查看已生成的结构化材料。',
      ]

  for (const p of answerParagraphs) {
    const chars = p.split('')
    for (let i = 0; i < chars.length; i += 3) {
      const chunk = chars.slice(i, i + 3).join('')
      onEvent({ event: 'token', data: { content: chunk } })
      await sleep(25)
    }
  }

  await sleep(100)
  onEvent({
    event: 'done',
    data: { session_id: 'demo-stream', token_count: 350 },
  })
}

/**
 * 统一发送入口：按当前 nexusDataSourceMode 自动分发
 */
/**
 * 统一发送入口。
 *
 * 契约说明：`mode` 与 `context` 两个字段当前运行时会忽略（未知字段），
 * 但前端始终发送，以便运行时接线后前端零改动。
 * 运行时接线时应在 /chat/stream 请求体接收：
 *   { message, session_id, mode, context: { course_id } }
 */
export async function dispatchNexusMessage({
  message,
  sessionId,
  mode,
  courseId = null,
  onEvent,
  signal,
}) {
  if (nexusDataSourceMode.value === 'real') {
    return streamNexusMessage({
      message,
      sessionId,
      mode,
      courseId,
      onEvent,
      signal,
    })
  }
  return streamDemoMessage({ message, mode, courseId, onEvent, signal })
}
