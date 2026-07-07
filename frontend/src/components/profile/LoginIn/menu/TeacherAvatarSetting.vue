<template>
  <Teleport to="body">
    <div v-if="visible" class="avatar-modal-overlay" @click="handleClose">
      <div class="avatar-modal" @click.stop>
        <div class="modal-header">
          <h3>教师数字人设置</h3>
          <button class="close-btn" @click="handleClose"><X :size="20" /></button>
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
                <Music :size="32" class="audio-icon" />
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
import { X, Music } from 'lucide-vue-next'

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
  z-index: var(--z-modal);
  animation: fadeIn var(--duration-normal) var(--ease);
  box-sizing: border-box;
}

.avatar-modal {
  width: 90%;
  max-width: 520px;
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  animation: slideUp var(--duration-slow) cubic-bezier(0.24, 1, 0.32, 1);
  display: flex;
  flex-direction: column;
  max-height: 85vh;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
}

.modal-header h3 {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--color-text);
}

.close-btn {
  width: var(--space-6);
  height: var(--space-6);
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--duration-normal) var(--ease);
}

.close-btn:hover {
  background: var(--color-surface-2);
  color: var(--color-text);
}

.modal-content {
  padding: var(--space-5);
  overflow-y: auto;
  flex: 1;
}

.ref-section {
  margin-bottom: var(--space-5);
}

.ref-title {
  margin: 0 0 var(--space-3) 0;
  font-size: 15px;
  color: var(--color-text);
  font-weight: var(--font-medium);
}

.ref-upload {
  width: 100%;
  display: block;
  cursor: pointer;
}

.ref-placeholder {
  width: 100%;
  height: 100px;
  border: 2px dashed var(--color-border);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  transition: all var(--duration-normal) var(--ease);
  background: var(--color-surface-2);
}

.ref-placeholder:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-light);
}

.ref-preview {
  width: 100%;
  height: 100px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--space-3);
  background: var(--color-surface-2);
}

.ref-preview img {
  height: 80px;
  width: auto;
  max-width: 120px;
  border-radius: var(--radius-sm);
  object-fit: cover;
}

.ref-preview .file-name {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ref-audio-preview {
  width: 100%;
  height: 100px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--space-3);
  background: var(--color-surface-2);
}

.audio-icon {
  color: var(--color-primary);
  flex-shrink: 0;
}

.ref-audio-preview .file-name {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.default-option {
  display: flex;
  gap: var(--space-5);
  margin-top: var(--space-2);
}

.radio-label {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
}

.radio-label input[type="radio"] {
  width: var(--space-4);
  height: var(--space-4);
  accent-color: var(--color-primary);
  cursor: pointer;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-2);
  flex-shrink: 0;
}

.btn-cancel {
  padding: var(--space-2) var(--space-5);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease);
}

.btn-cancel:hover {
  border-color: var(--color-text-muted);
  color: var(--color-text);
}

.btn-confirm {
  padding: var(--space-2) var(--space-5);
  border: none;
  background: var(--color-primary);
  color: var(--color-text-inverse);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease);
}

.btn-confirm:hover {
  background: var(--color-primary-hover);
  transform: translateY(-2px);
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
  background: var(--color-border);
  border-radius: var(--radius-sm);
}

.modal-content::-webkit-scrollbar-thumb:hover {
  background: var(--color-text-muted);
}

@media (max-width: 768px) {
  .avatar-modal {
    width: 95%;
    max-height: 90vh;
  }

  .default-option {
    flex-direction: column;
    gap: var(--space-2);
  }
}
</style>
