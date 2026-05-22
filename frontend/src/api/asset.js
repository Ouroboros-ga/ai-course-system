import request from '@/utils/request.js'

/**
 * 素材管理API
 */

// 上传素材
export function uploadAsset(file, assetType, onProgress) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('asset_type', assetType)

  return request.post('/assets/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000, // 5分钟，大文件上传
    onUploadProgress: onProgress || null,
  })
}

// 获取素材列表
export function getAssetList(assetType) {
  const params = {}
  if (assetType) params.asset_type = assetType
  return request.get('/assets/', { params })
}

// 设为默认素材
export function setDefaultAsset(assetId) {
  return request.put(`/assets/${assetId}/default`)
}

// 删除素材
export function deleteAsset(assetId) {
  return request.delete(`/assets/${assetId}`)
}

// 获取素材预览URL
export function getAssetPreviewUrl(assetId) {
  const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'
  return `${baseUrl}/assets/${assetId}/preview`
}
