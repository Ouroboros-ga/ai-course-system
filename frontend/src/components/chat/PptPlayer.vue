<template>
  <div class="ppt-section">
    <!-- 👇 关键修复：传入 currentPage -->
    <PptHeader :file="file" :totalPages="totalPages" :current-page="currentPage" />

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
          :current-page="currentPage"
          :total-pages="totalPages"
          @toggle="togglePlay"
          @page-change="handlePageChange"
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
import { ref, defineEmits, computed } from 'vue'
import PptHeader from './PptPlayer/PptHeader.vue'
import PptUpload from './PptPlayer/PptUpload.vue'
import PptAnalyzing from './PptPlayer/PptAnalyzing.vue'
import PptControlBar from './PptPlayer/PptControlBar.vue'
import service from '@/utils/request'

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
    const formData = new FormData()
    formData.append('file', f)

    const res = await service.post('http://127.0.0.1:8000/api/somark/parse', formData)

    pages.value = res.data?.pages || []
    totalPages.value = pages.value.length || 1
    currentPage.value = 1

  } catch (err) {
    console.error('解析失败', err)
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

const handlePageChange = (page) => {
  if (page < 1 || page > totalPages.value) return
  currentPage.value = page
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
  color: #4b5563;
}

.hidden-input {
  display: none;
}

@media (max-width: 768px) {
  .ppt-section {
    flex: none;
    width: 100%;
    height: 45vh;
    min-height: 300px;
  }
  .ppt-display-area {
    min-height: auto;
  }
}
</style>
