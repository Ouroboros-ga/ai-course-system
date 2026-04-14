<template>
  <Teleport to="body">
    <div v-if="visible" class="avatar-modal-overlay" @click="handleClose">
      <div class="avatar-modal" @click.stop>
        <div class="modal-header">
          <h3>教师数字人设置</h3>
          <button class="close-btn" @click="handleClose">✕</button>
        </div>

        <div class="modal-content">
          <div class="ref-section">
            <p class="ref-title">数字人参考图片：</p>
            <div class="ref-upload" @click="triggerImageUpload">
              <input
                ref="imageInput"
                type="file"
                accept="image/*"
                @change="handleImageUpload"
                hidden
              />
              <div v-if="!imageFile" class="ref-placeholder">
                <span>点击上传参考图</span>
              </div>
              <div v-else class="ref-preview">
                <img :src="imagePreview" alt="参考图预览" />
                <span class="file-name">{{ imageFile.name }}</span>
              </div>
            </div>
          </div>

          <div class="ref-section">
            <p class="ref-title">数字人音频参考：</p>
            <div class="ref-upload" @click="triggerAudioUpload">
              <input
                ref="audioInput"
                type="file"
                accept="audio/*"
                @change="handleAudioUpload"
                hidden
              />
              <div v-if="!audioFile" class="ref-placeholder">
                <span>点击上传音频文件</span>
              </div>
              <div v-else class="ref-audio-preview">
                <span class="audio-icon">🎵</span>
                <span class="file-name">{{ audioFile.name }}</span>
              </div>
            </div>
          </div>

          <div class="default-option">
            <label class="radio-label">
              <input
                type="radio"
                name="avatarType"
                v-model="selectedType"
                value="default"
              />
              <span>使用默认数字人</span>
            </label>
            <label class="radio-label">
              <input
                type="radio"
                name="avatarType"
                v-model="selectedType"
                value="custom"
              />
              <span>使用自定义数字人</span>
            </label>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn-cancel" @click="handleClose">取消</button>
          <button class="btn-confirm" @click="handleConfirm">确认</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, defineProps, defineEmits } from 'vue'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:visible', 'confirm'])

const selectedType = ref('default')
const imageFile = ref(null)
const audioFile = ref(null)
const imagePreview = ref('')

const imageInput = ref(null)
const audioInput = ref(null)

const triggerImageUpload = () => {
  imageInput.value?.click()
}

const triggerAudioUpload = () => {
  audioInput.value?.click()
}

const handleImageUpload = (e) => {
  const file = e.target.files[0]
  if (!file) return
  imageFile.value = file
  const reader = new FileReader()
  reader.onload = (res) => {
    imagePreview.value = res.target.result
  }
  reader.readAsDataURL(file)
}

const handleAudioUpload = (e) => {
  const file = e.target.files[0]
  if (!file) return
  audioFile.value = file
}

const handleClose = () => {
  emit('update:visible', false)
  imageFile.value = null
  audioFile.value = null
  imagePreview.value = ''
  selectedType.value = 'default'
  if (imageInput.value) imageInput.value.value = ''
  if (audioInput.value) audioInput.value.value = ''
}

const handleConfirm = () => {
  emit('confirm', {
    type: selectedType.value,
    image: imageFile.value,
    audio: audioFile.value
  })
  handleClose()
}
</script>

<style scoped>
.avatar-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  animation: fadeIn 0.2s ease;
  box-sizing: border-box;
}

.avatar-modal {
  width: 90%;
  max-width: 520px;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  overflow: hidden;
  animation: slideUp 0.3s cubic-bezier(0.24, 1, 0.32, 1);
  display: flex;
  flex-direction: column;
  max-height: 85vh;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
  flex-shrink: 0;
}

.modal-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #333;
}

.close-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  font-size: 20px;
  color: #999;
  cursor: pointer;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.close-btn:hover {
  background: #f5f5f5;
  color: #333;
}

.modal-content {
  padding: 20px;
  overflow-y: auto;
  flex: 1;
}

.ref-section {
  margin-bottom: 20px;
}

.ref-title {
  margin: 0 0 12px 0;
  font-size: 15px;
  color: #333;
  font-weight: 500;
}

.ref-upload {
  width: 100%;
  display: block;
  cursor: pointer;
}

.ref-placeholder {
  width: 100%;
  height: 100px;
  border: 2px dashed #ddd;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #999;
  font-size: 14px;
  transition: all 0.2s ease;
  background: #fafafa;
}

.ref-placeholder:hover {
  border-color: #667eea;
  color: #667eea;
  background: rgba(102, 126, 234, 0.05);
}

.ref-preview {
  width: 100%;
  height: 100px;
  border: 1px solid #eee;
  border-radius: 8px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 12px;
  background: #fafafa;
}

.ref-preview img {
  height: 80px;
  width: auto;
  max-width: 120px;
  border-radius: 4px;
  object-fit: cover;
}

.ref-preview .file-name {
  font-size: 14px;
  color: #666;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ref-audio-preview {
  width: 100%;
  height: 100px;
  border: 1px solid #eee;
  border-radius: 8px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 12px;
  background: #fafafa;
}

.audio-icon {
  font-size: 32px;
  color: #667eea;
}

.ref-audio-preview .file-name {
  font-size: 14px;
  color: #666;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.default-option {
  display: flex;
  gap: 24px;
  margin-top: 8px;
}

.radio-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  color: #444;
  cursor: pointer;
}

.radio-label input[type="radio"] {
  width: 16px;
  height: 16px;
  accent-color: #667eea;
  cursor: pointer;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid #f0f0f0;
  background: #fafafa;
  flex-shrink: 0;
}

.btn-cancel {
  padding: 8px 20px;
  border: 1px solid #ddd;
  background: #fff;
  border-radius: 8px;
  font-size: 14px;
  color: #666;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-cancel:hover {
  border-color: #999;
  color: #333;
}

.btn-confirm {
  padding: 8px 20px;
  border: none;
  background: #667eea;
  color: #fff;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-confirm:hover {
  background: #5568d3;
  transform: translateY(-1px);
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.modal-content::-webkit-scrollbar {
  width: 6px;
}

.modal-content::-webkit-scrollbar-thumb {
  background: #ddd;
  border-radius: 3px;
}

.modal-content::-webkit-scrollbar-thumb:hover {
  background: #bbb;
}
</style>
