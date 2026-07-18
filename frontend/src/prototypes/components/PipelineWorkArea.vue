<script setup>
import { computed, ref } from 'vue'
import {
  AlertCircle, BookOpen, Check, FileSearch, FileText, Layers3, MoreVertical,
  Play, RefreshCw, Save, Sparkles, UploadCloud
} from 'lucide-vue-next'
import PrototypeStatusBadge from './PrototypeStatusBadge.vue'

const props = defineProps({
  step: { type: Object, required: true },
  chapters: { type: Array, required: true },
  scriptBlocks: { type: Array, required: true },
  activeBlockId: { type: String, default: '' }
})

const emit = defineEmits(['select-block', 'update-block', 'regenerate', 'retry-task', 'confirm-step'])
const selectedChapter = ref(0)

const title = computed(() => props.step.title)

const workDescription = computed(() => ({
  basic: '确认课程面向对象、教学目标和基本信息。',
  materials: '上传、预览并管理当前课程版本使用的教学资料。',
  parsing: '检查页、块和警告；解析成功不等于教师确认完成。',
  structure: '调整章节顺序，确认资料与课程结构的对应关系。',
  knowledge: '检查知识点标题、来源和前置关系。',
  mapping: '把脚本块与 PPT 页建立可人工修正的映射。',
  audio: '查看分段音频任务、错误原因并按失败节点重试。',
  avatar: '数字人任务将在音频确认后开放。',
  preview: '在发布前按学生视角检查完整课程。',
  publish: '逐项解决阻断项后才能发布当前版本。'
}[props.step.key] || '编辑并检查当前步骤产物。'))
</script>

<template>
  <main class="fd-work-area" aria-labelledby="work-area-title">
    <header class="fd-work-area__header">
      <div>
        <p class="fd-eyebrow">当前制作步骤</p>
        <h1 id="work-area-title">{{ title }}</h1>
        <p>{{ workDescription }}</p>
      </div>
      <div class="fd-work-area__actions">
        <button class="fd-secondary-button" type="button"><Play :size="16" />预览本节</button>
        <button
          class="fd-primary-button"
          type="button"
          :disabled="step.status === 'processing' || step.status === 'failed'"
          :title="step.status === 'failed' ? '请先处理失败任务' : ''"
          @click="emit('confirm-step')"
        ><Check :size="16" />标记为已确认</button>
      </div>
    </header>

    <div v-if="step.key === 'script'" class="fd-editor-layout">
      <aside class="fd-chapter-strip" aria-label="章节与知识点">
        <header>
          <span><Layers3 :size="16" />章节 / 知识点</span>
        </header>
        <section v-for="(chapter, index) in chapters" :key="chapter.title">
          <button type="button" :class="{ 'is-active': selectedChapter === index }" @click="selectedChapter = index">
            <span>{{ chapter.title }}</span>
            <small>{{ chapter.points.length }}</small>
          </button>
          <ul v-if="selectedChapter === index">
            <li v-for="point in chapter.points" :key="point">
              <button type="button">{{ point }}</button>
            </li>
          </ul>
        </section>
      </aside>

      <section class="fd-script-editor" aria-label="教学脚本编辑器">
        <div class="fd-inline-notice">
          <Sparkles :size="16" />
          <span>AI 已生成初稿。请核对准确性、来源和讲解节奏，再进行教师确认。</span>
        </div>
        <article
          v-for="(block, index) in scriptBlocks"
          :key="block.id"
          class="fd-script-block"
          :class="{ 'is-active': activeBlockId === block.id }"
          @click="emit('select-block', block.id)"
        >
          <div class="fd-script-block__number">{{ index + 1 }}</div>
          <div class="fd-script-block__content">
            <header>
              <span>{{ block.time }}</span>
              <PrototypeStatusBadge :status="block.review" :label="block.review === 'confirmed' ? '教师已确认' : 'AI 生成 · 待确认'" compact />
              <button type="button" aria-label="更多脚本操作"><MoreVertical :size="16" /></button>
            </header>
            <textarea
              :value="block.text"
              :aria-label="'脚本块 ' + (index + 1)"
              @input="emit('update-block', { id: block.id, text: $event.target.value })"
            ></textarea>
            <footer>
              <span><FileText :size="14" />映射 PPT 第 {{ block.slide }} 页</span>
              <div>
                <button class="fd-text-button" type="button" @click.stop="emit('regenerate', block.id)">
                  <RefreshCw :size="14" />局部重新生成
                </button>
                <button class="fd-text-button" type="button"><Save :size="14" />保存</button>
              </div>
            </footer>
          </div>
        </article>
      </section>
    </div>

    <section v-else-if="step.key === 'materials'" class="fd-step-placeholder fd-upload-zone">
      <UploadCloud :size="42" />
      <h2>上传教学资料</h2>
      <p>当前代码已支持教学资料上传与预览；原型不发起真实接口请求。</p>
      <button class="fd-primary-button" type="button">选择本地文件</button>
      <small>PDF、PPT、Word 的实际支持范围以现有后端配置为准</small>
    </section>

    <section v-else-if="step.key === 'parsing'" class="fd-parsing-preview">
      <div class="fd-document-page">
        <FileSearch :size="32" />
        <strong>算法设计与分析.pdf</strong>
        <span>正在解析第 126 / 194 页</span>
        <div class="fd-progress-line"><i style="width: 65%"></i></div>
      </div>
      <div class="fd-parsing-summary">
        <h2>解析过程</h2>
        <p>当前正式代码存在文档分析能力；页块质量、bbox 与 Evidence 契约仍处于 Shadow/规划阶段。</p>
        <PrototypeStatusBadge status="processing" label="长任务 65%" />
      </div>
    </section>

    <section v-else-if="step.key === 'audio'" class="fd-step-placeholder fd-step-placeholder--error">
      <AlertCircle :size="42" />
      <h2>1 个音频任务失败</h2>
      <p>语音合成服务超时（503）。可仅重试失败节点，不影响已完成的脚本与映射。</p>
      <button class="fd-primary-button" type="button" @click="emit('retry-task')"><RefreshCw :size="16" />重试失败任务</button>
    </section>

    <section v-else class="fd-step-placeholder">
      <BookOpen :size="42" />
      <h2>{{ title }}</h2>
      <p>{{ workDescription }}</p>
      <PrototypeStatusBadge :status="step.status" />
    </section>
  </main>
</template>
