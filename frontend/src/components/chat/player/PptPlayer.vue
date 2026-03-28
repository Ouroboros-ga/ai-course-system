<template>
  <div class="ppt-section">
    <PptHeader
      :file="file"
      :totalPages="totalPages"
      :current-page="currentPage"
    />

    <div class="ppt-display-area">
      <PptUpload v-if="!file" @click="triggerUpload" @drop="handleDrop" />
      <PptAnalyzing v-else-if="isAnalyzing" />

      <div v-else class="ppt-content-wrapper">
        <div class="ppt-content">
          <h3 class="page-title">{{ currentPageData?.title || '解析完成' }}</h3>
          <div class="page-content" v-html="currentPageData?.content || '等待AI解析内容...'"></div>
        </div>

        <PptControlBar
          :isPlaying="isPlaying"
          :progress="0"
          @toggle="togglePlay"
          @prev-page="() => currentPage = Math.max(1, currentPage - 1)"
          @next-page="() => currentPage = Math.min(totalPages, currentPage + 1)"
        />
      </div>

      <input
        type="file"
        ref="fileInput"
        @change="handleFileChange"
        class="hidden-input"
        accept=".ppt,.pptx,.pdf"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import PptHeader from './PptPlayer/PptHeader.vue'
import PptUpload from './PptPlayer/PptUpload.vue'
import PptAnalyzing from './PptPlayer/PptAnalyzing.vue'
import PptControlBar from './PptPlayer/PptControlBar.vue'
import { showToast } from '@/utils/toast'

import api from '@/api/index.js'

import { useCounterStore } from '@/stores/counter.js'
const counter = useCounterStore()

const emit = defineEmits(['file-upload', 'analysis-end'])

const file = ref(null)
const isAnalyzing = ref(false)
const isPlaying = ref(false)
const fileInput = ref(null)

const pages = ref([])
const currentPage = ref(1)
const totalPages = ref(1)

const currentPageData = computed(() => {
  return pages.value[currentPage.value - 1] || {}
})

const triggerUpload = () => fileInput.value.click()
const handleFileChange = (e) => startAnalysis(e.target.files[0])
const handleDrop = (e) => startAnalysis(e.dataTransfer.files[0])

const startAnalysis = async (f) => {
  if (!f) return
  file.value = f
  emit('file-upload', f)
  isAnalyzing.value = true

  try {
    // 调用上传接口
    const formData = new FormData()
    formData.append('file', f)
    formData.append('fileName', f.name)
    formData.append('userId', counter.userData.id)

    console.log('开始上传文件：', f.name)
    const res = await api.chat.uploadFile(formData)

    console.log('上传成功:', res)
    // 后端返回的数据结构：
    // { code, message, data: { markdownContent, scriptContent, summaryText, keywords, nodes } }
    // 优先使用AI生成的脚本内容(scriptContent)，其次使用Markdown内容(markdownContent)
    const scriptContent = res?.data?.scriptContent
    const markdownContent = res?.data?.markdownContent
    
    if (scriptContent && scriptContent.nodes && scriptContent.nodes.length > 0) {
      // 使用AI生成的脚本节点
      pages.value = scriptContent.nodes.map((node, i) => ({
        title: node.title || `第 ${i + 1} 节`,
        content: node.content?.replace(/\n/g, '<br>') || '',
        type: node.node_type,
        duration: node.duration,
        isKeyPoint: node.is_key_point
      }))
    } else if (markdownContent) {
      // 使用Markdown内容
      const paragraphs = markdownContent.split('\n\n').filter(p => p.trim())
      pages.value = paragraphs.map((p, i) => ({
        title: `第 ${i + 1} 页`,
        content: p.replace(/\n/g, '<br>')
      }))
    }
    totalPages.value = pages.value.length || 1
    currentPage.value = 1

  } catch (err) {
    console.error('上传失败', err)
    showToast(err, 'error')
    pages.value = []
    totalPages.value = 1
    currentPage.value = 1
  } finally {
    isAnalyzing.value = false
    isPlaying.value = true
    emit('analysis-end')
  }
}

const togglePlay = () => {
  isPlaying.value = !isPlaying.value
}
</script>

<style scoped>
.ppt-section {
  flex: 6.5;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
  height: 100%;
}

.ppt-display-area {
  flex: 1;
  background: white;
  border-radius: 16px;
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1);
  border: 1px solid #f3f4f6;
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 500px;
}

.ppt-content-wrapper {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.ppt-content {
  flex: 1;
  padding: 40px 32px;
  overflow-y: auto;
}
.page-title {
  font-size: 24px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 20px;
}
.page-content {
  font-size: 16px;
  line-height: 1.8;
  color: #4b5565;
}

.hidden-input {
  display: none;
}

/* 👇👇👇 这里我帮你改长了！！！ */
@media (max-width: 768px) {
  .ppt-section {
    flex: none;
    width: 100%;
    height: 75vh;  /* 👈 原来 45vh → 现在 60vh，变长了 */
    min-height: 300px;
  }
  .ppt-display-area {
    min-height: auto;
  }
}
</style>
