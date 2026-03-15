import request from '@/utils/request.js'

// 发送聊天信息,附带文件

export function sendChatMessage(formData) {
  return request({
    url: '/chat/send',
    method: 'post',
    data: formData,
    // 注意：不要手动设置 Content-Type，让浏览器自动处理
  })
}


// 接收ai回复
export function receiveChatMessage(message) {
  return request({
    url: '/chat/receive',
    method: 'post',
    data: message,
  })
}
