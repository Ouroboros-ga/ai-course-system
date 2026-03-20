import Cookies from 'js-cookie'

// 假设登录时后端写入了名为 'user-token' 的 Cookie
export const token = Cookies.get('user-token')

if (token) {
  console.log('获取到的 Token:', token)
  // 在这里进行后续处理，如存入 Vuex
} else {
  console.log('未登录或 Token 已过期')
}
