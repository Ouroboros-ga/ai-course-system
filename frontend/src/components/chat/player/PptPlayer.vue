<template>
  <div class="ppt-section">
    <PptHeader
      :file="file"
      :mindMapData="currentData.mindMapJson"
    />

    <div class="ppt-display-area">
      <PptUpload
        v-if="!file"
        @click="triggerUpload"
        @open-config="openConfigModal"
        @drop-with-config="handleDropStoreFile"
      />
      <PptAnalyzing v-else-if="isAnalyzing" />

      <div v-else class="ppt-content-wrapper">
        <div class="ppt-content">
          <h3 class="page-title">{{ currentData?.title || '解析完成' }}</h3>
          <PptContent :content="currentData?.content"/>
        </div>

        <!-- ✅ 修复：正确闭合 audio 标签 -->
        <audio
          ref="audioRef"
          :src="currentData.audioUrl"
          @timeupdate="onTimeUpdate"
          @loadedmetadata="onLoadedMetadata"
          @ended="onEnded"
          style="display: none;"
        ></audio>

        <PptControlBar
          :is-playing="isPlaying"
          :current-time="currentTime"
          :duration="duration"
          :volume="currentVolume"
          @toggle="togglePlay"
          @seek="handleSeek"
          @speed-change="changeSpeed"
          @volume-change="changeVolume"
          @loop="toggleLoop"
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

    <FileConfigModal
      :visible="showConfigModal"
      @close="showConfigModal = false"
      @confirm="handleConfigConfirm"
    />
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import PptHeader from './PptPlayer/PptHeader.vue'
import PptUpload from './PptPlayer/PptUpload.vue'
import PptAnalyzing from './PptPlayer/PptAnalyzing.vue'
import PptControlBar from './PptPlayer/PptControlBar.vue'
import PptContent from './PptPlayer/PptContent.vue'
import { showToast } from '@/utils/toast'
import api from '@/api/index.js'
import { useCounterStore } from '@/stores/counter.js'
const counter = useCounterStore()

import FileConfigModal from '@/components/chat/Fileconfigmodal/FileConfigModal.vue'

const props = defineProps(['initialData', 'resetTrigger'])
const emit = defineEmits(['file-upload', 'analysis-complete'])

const file = ref(null)
const isAnalyzing = ref(false)
const isPlaying = ref(false)
const fileInput = ref(null)
const isRestoredData = ref(false)

const audioRef = ref(null)
const currentVolume = ref(1)
const currentTime = ref(0)
const duration = ref(0)
const isLoop = ref(false)

const currentData = ref({
  title: '',
  content: '',
  chatId: '',
  audioUrl: '',
  mindMapJson: {"text": "根"},
})

const showConfigModal = ref(false)
const userConfig = ref(null)
const pendingDropFile = ref(null)

const openConfigModal = () => {
  showConfigModal.value = true
}

const handleDropStoreFile = (file) => {
  pendingDropFile.value = file
  openConfigModal()
}

const handleConfigConfirm = (config) => {
  userConfig.value = config
  showConfigModal.value = false

  if (pendingDropFile.value) {
    startAnalysis(pendingDropFile.value)
    pendingDropFile.value = null
  } else {
    triggerUpload()
  }
}

watch(() => props.resetTrigger, () => {
  file.value = null
  isAnalyzing.value = false
  isPlaying.value = false
  currentData.value = {
    title: '',
    content: '',
    chatId: '',
    audioUrl: '',
    mindMapJson: {"text": "根"},
  }
  currentTime.value = 0
  duration.value = 0
  pendingDropFile.value = null

  if (audioRef.value) {
    audioRef.value.pause()
    audioRef.value.currentTime = 0
  }
}, { immediate: false })

watch(() => props.initialData, (newData) => {
  if (newData && newData.chatId) {
    currentData.value = { ...newData }
    file.value = { name: newData.title || '已恢复的文件', size: 0, type: 'restored' }
    isRestoredData.value = true
    isAnalyzing.value = false
  }
}, { immediate: true })

const triggerUpload = () => fileInput.value.click()
const handleFileChange = (e) => startAnalysis(e.target.files[0])

const startAnalysis = async (f) => {
  if (!f) return
  file.value = f
  emit('file-upload', f)
  isAnalyzing.value = true

  try {
    const formData = new FormData()
    formData.append('file', f)
    formData.append('fileName', f.name)
    formData.append('userId', counter.userData.id)

    if (userConfig.value) {
      formData.append('aiConfig', JSON.stringify(userConfig.value))
    }

    const res = await api.chat.uploadFile(formData)
    if (res) {
      currentData.value = {
        title: res.title || '解析完成',
        content: res.fullContent,
        chatId: res.chatId,
        courseId: res.courseId,
        mindMapJson: res.mindMapJson,
        audioUrl: res.audioUrl || '/assets/audio/girl.mp3',
      }
      emit('analysis-complete', { ...currentData.value })
    }
  } catch (err) {
    console.error('上传失败', err)
    showToast(err, 'error')
    file.value = null
    isAnalyzing.value = false
    currentData.value = { title: '', content: '', chatId: '', audioUrl: '', mindMapJson: {"text": "根"} }
  }
}

const togglePlay = () => {
  if (!audioRef.value || !currentData.value.audioUrl) return
  if (isPlaying.value) {
    audioRef.value.pause()
  } else {
    audioRef.value.play()
  }
  isPlaying.value = !isPlaying.value
}

const onTimeUpdate = () => {
  if (audioRef.value) {
    currentTime.value = audioRef.value.currentTime
  }
}

const onLoadedMetadata = () => {
  if (audioRef.value) {
    duration.value = audioRef.value.duration
  }
}

const onEnded = () => {
  isPlaying.value = false
  currentTime.value = 0
}

const handleSeek = (time) => {
  if (audioRef.value) {
    audioRef.value.currentTime = time
    currentTime.value = time
  }
}

const changeSpeed = (speed) => {
  if (audioRef.value) {
    audioRef.value.playbackRate = speed
  }
}

const changeVolume = (value) => {
  if (audioRef.value) {
    currentVolume.value = value;
    audioRef.value.volume = value;
    audioRef.value.muted = (value === 0);
  }
};

const toggleLoop = () => {
  if (audioRef.value) {
    isLoop.value = !isLoop.value
    audioRef.value.loop = isLoop.value
    showToast(isLoop.value ? '已开启循环播放' : '已关闭循环播放', 'info')
  }
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

.hidden-input {
  display: none;
}

@media (max-width: 768px) {
  .ppt-section {
    flex: none;
    width: 100%;
    height: 75vh;
    min-height: 300px;
  }
  .ppt-display-area {
    min-height: auto;
  }
}
</style>
