<template>
  <Teleport to="body">
    <div v-if="visible" class="avatar-modal-overlay" @click="handleClose">
      <div class="avatar-modal" @click.stop>
        <div class="modal-header">
          <h3>教师数字人素材管理</h3>
          <button class="close-btn" @click="handleClose">✕</button>
        </div>

        <div class="modal-content">
          <!-- 人脸视频区域 -->
          <div class="asset-section">
            <div class="section-title">
              <span class="section-icon">🎬</span>
              人脸视频素材
              <span class="section-hint">（用于生成数字人讲课视频，支持 mp4/webm/mov）</span>
            </div>

            <!-- 已有素材列表 -->
            <div v-if="faceVideoList.length > 0" class="asset-list">
              <div
                v-for="item in faceVideoList"
                :key="item.id"
                class="asset-item"
                :class="{ 'is-default': item.is_default }"
              >
                <div class="asset-info">
                  <span class="asset-name">{{ item.file_name }}</span>
                  <span class="asset-size">{{ formatSize(item.file_size) }}</span>
                  <span v-if="item.is_default" class="default-badge">默认</span>
                </div>
                <div class="asset-actions">
                  <button
                    v-if="!item.is_default"
                    class="action-btn set-default"
                    @click="handleSetDefault(item.id)"
                    title="设为默认"
                  >设为默认</button>
                  <button
                    class="action-btn preview"
                    @click="handlePreview(item)"
                    title="预览"
                  >预览</button>
                  <button
                    class="action-btn delete"
                    @click="handleDelete(item.id, 'face_video')"
                    title="删除"
                  >删除</button>
                </div>
              </div>
            </div>
            <div v-else class="empty-hint">暂无人脸视频素材，请上传</div>

            <!-- 上传按钮 -->
            <div class="upload-row">
              <input
                ref="faceVideoInput"
                type="file"
                accept="video/mp4,video/webm,video/quicktime,.mp4,.webm,.mov"
                @change="handleUpload($event, 'face_video')"
                hidden
              />
              <button
                class="upload-btn"
                :disabled="uploading.face_video"
                @click="faceVideoInput?.click()"
              >
                {{ uploading.face_video ? '上传中...' : '+ 上传人脸视频' }}
              </button>
              <span v-if="uploadProgress.face_video" class="upload-progress">
                {{ uploadProgress.face_video }}%
              </span>
            </div>
          </div>

          <!-- 参考音频区域 -->
          <div class="asset-section">
            <div class="section-title">
              <span class="section-icon">🎵</span>
              参考音频素材
              <span class="section-hint">（用于TTS语音克隆，支持 mp3/wav/ogg）</span>
            </div>

            <!-- 已有素材列表 -->
            <div v-if="refAudioList.length > 0" class="asset-list">
              <div
                v-for="item in refAudioList"
                :key="item.id"
                class="asset-item"
                :class="{ 'is-default': item.is_default }"
              >
                <div class="asset-info">
                  <span class="asset-name">{{ item.file_name }}</span>
                  <span class="asset-size">{{ formatSize(item.file_size) }}</span>
                  <span v-if="item.is_default" class="default-badge">默认</span>
                  <span
                    v-if="item.clone_status === 'success'"
                    class="clone-badge success"
                    title="声音复刻完成"
                  >已克隆</span>
                  <span
                    v-else-if="item.clone_status === 'pending'"
                    class="clone-badge pending"
                  >复刻中...</span>
                  <span
                    v-else-if="item.clone_status === 'failed'"
                    class="clone-badge failed"
                  >复刻失败</span>
                </div>
                <div class="asset-actions">
                  <button
                    v-if="item.clone_status === 'none'"
                    class="action-btn clone"
                    :disabled="cloningAssetId === item.id"
                    @click="handleCloneVoice(item.id)"
                  >{{ cloningAssetId === item.id ? '复刻中...' : '声音复刻' }}</button>
                  <button
                    v-else-if="item.clone_status === 'failed'"
                    class="action-btn clone"
                    :disabled="cloningAssetId === item.id"
                    @click="handleCloneVoice(item.id)"
                  >重新复刻</button>
                  <button
                    v-if="!item.is_default"
                    class="action-btn set-default"
                    @click="handleSetDefault(item.id)"
                  >设为默认</button>
                  <button
                    class="action-btn preview"
                    @click="handlePreview(item)"
                  >预览</button>
                  <button
                    class="action-btn delete"
                    @click="handleDelete(item.id, 'ref_audio')"
                  >删除</button>
                </div>
              </div>
            </div>
            <div v-else class="empty-hint">暂无参考音频素材，请上传</div>

            <!-- 上传按钮 -->
            <div class="upload-row">
              <input
                ref="refAudioInput"
                type="file"
                accept="audio/mpeg,audio/wav,audio/ogg,.mp3,.wav,.ogg"
                @change="handleUpload($event, 'ref_audio')"
                hidden
              />
              <button
                class="upload-btn"
                :disabled="uploading.ref_audio"
                @click="refAudioInput?.click()"
              >
                {{ uploading.ref_audio ? '上传中...' : '+ 上传参考音频' }}
              </button>
              <span v-if="uploadProgress.ref_audio" class="upload-progress">
                {{ uploadProgress.ref_audio }}%
              </span>
            </div>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn-cancel" @click="handleClose">关闭</button>
        </div>

        <!-- 预览弹窗 -->
        <Teleport to="body">
          <div v-if="previewVisible" class="preview-overlay" @click="previewVisible = false">
            <div class="preview-container" @click.stop>
              <button class="preview-close" @click="previewVisible = false">✕</button>
              <video
                v-if="previewItem?.asset_type === 'face_video'"
                :src="getPreviewUrl(previewItem.id)"
                controls
                class="preview-media"
              ></video>
              <audio
                v-else-if="previewItem?.asset_type === 'ref_audio'"
                :src="getPreviewUrl(previewItem.id)"
                controls
                class="preview-media"
              ></audio>
            </div>
          </div>
        </Teleport>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { uploadAsset, getAssetList, setDefaultAsset, deleteAsset, getAssetPreviewUrl, cloneVoice } from '@/api/asset.js'
import { showToast } from '@/utils/toast.js'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:visible', 'confirm'])

// 素材列表
const assets = ref([])
const faceVideoList = computed(() => assets.value.filter(a => a.asset_type === 'face_video'))
const refAudioList = computed(() => assets.value.filter(a => a.asset_type === 'ref_audio'))

// 上传状态
const uploading = ref({ face_video: false, ref_audio: false })
const uploadProgress = ref({ face_video: 0, ref_audio: 0 })

// 声音复刻状态
const cloningAssetId = ref(null)

// 预览
const previewVisible = ref(false)
const previewItem = ref(null)

// 文件输入引用
const faceVideoInput = ref(null)
const refAudioInput = ref(null)

// 弹窗打开时加载素材列表
watch(() => props.visible, (val) => {
  if (val) {
    loadAssets()
  }
})

async function loadAssets() {
  try {
    const data = await getAssetList()
    assets.value = data?.assets || []
  } catch (e) {
    console.error('加载素材列表失败:', e)
  }
}

async function handleUpload(event, assetType) {
  const file = event.target.files?.[0]
  if (!file) return

  // 前端大小校验（
  const maxMB = assetType === 'face_video' ? 200 : 50
  if (file.size > maxMB * 1024 * 1024) {
    showToast(`文件大小超过 ${maxMB}MB 限制`, 'error')
    return
  }

  uploading.value[assetType] = true
  uploadProgress.value[assetType] = 0

  try {
    await uploadAsset(file, assetType, (progressEvent) => {
      if (progressEvent.total) {
        const pct = Math.round((progressEvent.loaded * 100) / progressEvent.total)
        uploadProgress.value[assetType] = pct
      }
    })
    showToast('素材上传成功', 'success')
    await loadAssets()
  } catch (e) {
    showToast('素材上传失败: ' + (e.message || '未知错误'), 'error')
  } finally {
    uploading.value[assetType] = false
    uploadProgress.value[assetType] = 0
    // 重置input
    if (assetType === 'face_video' && faceVideoInput.value) faceVideoInput.value.value = ''
    if (assetType === 'ref_audio' && refAudioInput.value) refAudioInput.value.value = ''
  }
}

async function handleSetDefault(assetId) {
  try {
    await setDefaultAsset(assetId)
    showToast('已设为默认素材', 'success')
    await loadAssets()
  } catch (e) {
    showToast('操作失败', 'error')
  }
}

async function handleDelete(assetId, assetType) {
  if (!confirm('确定要删除该素材吗？')) return
  try {
    await deleteAsset(assetId)
    showToast('素材已删除', 'success')
    await loadAssets()
  } catch (e) {
    showToast('删除失败', 'error')
  }
}

async function handleCloneVoice(assetId) {
  cloningAssetId.value = assetId
  try {
    const res = await cloneVoice(assetId)
    if (res?.clone_status === 'success') {
      showToast('声音复刻成功！可在脚本编辑中使用克隆音色', 'success')
    } else {
      showToast(res?.message || '声音复刻失败', 'error')
    }
    await loadAssets()
  } catch (e) {
    showToast('声音复刻失败: ' + (e.message || '未知错误'), 'error')
  } finally {
    cloningAssetId.value = null
  }
}

function handlePreview(item) {
  previewItem.value = item
  previewVisible.value = true
}

function getPreviewUrl(assetId) {
  return getAssetPreviewUrl(assetId)
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return size.toFixed(1) + ' ' + units[i]
}

function handleClose() {
  emit('update:visible', false)
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
}

.avatar-modal {
  width: 90%;
  max-width: 600px;
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

.asset-section {
  margin-bottom: 24px;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: #333;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.section-icon {
  font-size: 18px;
}

.section-hint {
  font-size: 12px;
  color: #999;
  font-weight: 400;
}

.asset-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}

.asset-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border: 1px solid #eee;
  border-radius: 8px;
  background: #fafafa;
  transition: all 0.2s ease;
}

.asset-item.is-default {
  border-color: #667eea;
  background: rgba(102, 126, 234, 0.05);
}

.asset-info {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.asset-name {
  font-size: 14px;
  color: #333;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.asset-size {
  font-size: 12px;
  color: #999;
  flex-shrink: 0;
}

.default-badge {
  font-size: 11px;
  padding: 2px 8px;
  background: #667eea;
  color: #fff;
  border-radius: 10px;
  flex-shrink: 0;
}

.clone-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  flex-shrink: 0;
}

.clone-badge.success {
  background: #52c41a;
  color: #fff;
}

.clone-badge.pending {
  background: #faad14;
  color: #fff;
}

.clone-badge.failed {
  background: #ff4d4f;
  color: #fff;
}

.asset-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.action-btn {
  padding: 4px 10px;
  border: 1px solid #ddd;
  background: #fff;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn.set-default:hover {
  border-color: #667eea;
  color: #667eea;
}

.action-btn.clone {
  border-color: #722ed1;
  color: #722ed1;
}

.action-btn.clone:hover:not(:disabled) {
  background: #722ed1;
  color: #fff;
}

.action-btn.clone:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.action-btn.preview:hover {
  border-color: #52c41a;
  color: #52c41a;
}

.action-btn.delete:hover {
  border-color: #ff4d4f;
  color: #ff4d4f;
}

.empty-hint {
  font-size: 13px;
  color: #bbb;
  text-align: center;
  padding: 16px 0;
  margin-bottom: 12px;
  border: 1px dashed #eee;
  border-radius: 8px;
}

.upload-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.upload-btn {
  padding: 8px 16px;
  border: 2px dashed #ddd;
  background: #fafafa;
  border-radius: 8px;
  font-size: 14px;
  color: #667eea;
  cursor: pointer;
  transition: all 0.2s ease;
}

.upload-btn:hover:not(:disabled) {
  border-color: #667eea;
  background: rgba(102, 126, 234, 0.05);
}

.upload-btn:disabled {
  color: #999;
  cursor: not-allowed;
}

.upload-progress {
  font-size: 13px;
  color: #667eea;
  font-weight: 500;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
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

/* 预览弹窗 */
.preview-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10001;
}

.preview-container {
  position: relative;
  max-width: 80vw;
  max-height: 80vh;
}

.preview-close {
  position: absolute;
  top: -12px;
  right: -12px;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: none;
  background: #fff;
  font-size: 18px;
  cursor: pointer;
  z-index: 1;
  box-shadow: 0 2px 8px rgba(0,0,0,0.2);
}

.preview-media {
  max-width: 100%;
  max-height: 80vh;
  border-radius: 8px;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes slideUp {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

.modal-content::-webkit-scrollbar {
  width: 6px;
}

.modal-content::-webkit-scrollbar-thumb {
  background: #ddd;
  border-radius: 3px;
}
</style>
