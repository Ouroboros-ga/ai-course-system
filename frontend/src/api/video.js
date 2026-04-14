import request from '@/utils/request.js'

export async function list() {
  return request.get('/video/list')
}

export async function getVideoInfo(filename) {
  return request.get(`/video/info/${filename}`)
}

export async function getVideoUrl(filename) {
  return `/api/v1/video/stream/${filename}`
}

export async function addVideo(fileUrl) {
  return request.post('/video/upload', null, {
    params: { file_url: fileUrl }
  })
}

export async function playRemote(url) {
  return request.get('/video/remote', {
    params: { url }
  })
}
