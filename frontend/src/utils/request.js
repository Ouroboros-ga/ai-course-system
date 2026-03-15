// src/api/request.js
import axios from 'axios'

// 创建 axios 实例
const service = axios.create({
  // TODO 从环境变量读取 api 地址
  baseURL: import.meta.env.VITE_APP_BASE_API, // 从环境变量读取 api 地址
  timeout: 5000 // 请求超时时间
})

// 请求拦截器
service.interceptors.request.use(
  config => {
    // 在发送请求之前做些什么
    // 例如：在 headers 中添加 token
    const token = localStorage.getItem('token')
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  },
  error => {
    // 对请求错误做些什么
    console.log('Request Error:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器
service.interceptors.response.use(
  response => {
    // 对响应数据做点什么
    const res = response.data

    // 这里根据后端约定的状态码进行判断
    // 假设后端返回格式为 { code: 200, data: {}, message: 'success' }
    if (res.code !== 200) {
      // 例如：token 过期，跳转登录页
      if (res.code === 401) {
        console.error('Token过期，请重新登录')
        // 这里可以触发退出的 action
      }

      // 返回错误信息给页面 catch
      return Promise.reject(new Error(res.message || 'Error'))
    } else {
      // 正常返回数据
      return res
    }
  },
  error => {
    // 对响应错误做点什么 (如 HTTP 网络错误)
    console.log('Response Error:', error.message)
    return Promise.reject(error)
  }
)

export default service
