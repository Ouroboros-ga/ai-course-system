// src/api/request.js
import axios from 'axios'
// 1. 引入 toast 工具
import { showToast } from '@/utils/toast'

// 创建 axios 实例
const service = axios.create({
  baseURL: import.meta.env.VITE_APP_BASE_API,
  timeout: 10000 // 建议稍微设长一点
})

// 请求拦截器
service.interceptors.request.use(
  config => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  },
  error => {
    console.log('Request Error:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器
service.interceptors.response.use(
  response => {
    const res = response.data

    // 2. 处理业务逻辑错误 (后端返回 code 非 200)
    if (res.code !== 200) {

      // 特殊状态码处理：Token 过期
      if (res.code === 401) {
        showToast('登录状态已过期，请重新登录', 'error')

        // 清除 token 并跳转登录页
        localStorage.removeItem('token')
        // window.location.href = '/login' // 建议结合路由跳转
      } else {
        // 3. 普通业务错误，直接弹出后端返回的错误信息
        showToast(res.message || '请求失败', 'error')
      }

      return Promise.reject(new Error(res.message || 'Error'))
    } else {
      // 正常返回数据 (剥离 data 层)
      return res.data
    }
  },
  error => {
    // 4. 处理 HTTP 网络错误 (如 404, 500, 超时)
    let message = '网络连接异常，请稍后再试'

    if (error.response) {
      // 有响应，但状态码不对
      switch (error.response.status) {
        case 401:
          message = '未授权，请重新登录'
          break
        case 403:
          message = '拒绝访问'
          break
        case 404:
          message = '请求资源不存在'
          break
        case 500:
          message = '服务器开小差了'
          break
        default:
          message = error.response.data?.message || '未知错误'
      }
    } else if (error.message.includes('timeout')) {
      message = '请求超时，请检查网络'
    } else if (error.message.includes('Network Error')) {
      message = '网络断开，请检查连接'
    }

    // 5. 弹出错误提示
    showToast(message, 'error')

    console.error('Response Error:', error)
    return Promise.reject(error)
  }
)

export default service
