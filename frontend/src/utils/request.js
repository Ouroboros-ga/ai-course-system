// src/api/request.js
import axios from 'axios'
import { showToast } from '@/utils/toast'
import { useCounterStore } from '@/stores/counter.js'

// 创建 axios 实例
const service = axios.create({
  baseURL: import.meta.env.DEV ? '/api/v1' : 'http://localhost:8000/api/v1',
  timeout: 180000
})

// 静态密钥（与后端保持一致）
const STATIC_KEY = 'dev-static-key-change-in-prod'

// 简单的 MD5 实现
function md5(string) {
  const rotateLeft = (lValue, iShiftBits) => (lValue << iShiftBits) | (lValue >>> (32 - iShiftBits))
  const addUnsigned = (lX, lY) => {
    let lX4, lY4, lX8, lY8, lResult
    lX8 = (lX & 0x80000000)
    lY8 = (lY & 0x80000000)
    lX4 = (lX & 0x40000000)
    lY4 = (lY & 0x40000000)
    lResult = (lX & 0x3FFFFFFF) + (lY & 0x3FFFFFFF)
    if (lX4 & lY4) return (lResult ^ 0x80000000 ^ lX8 ^ lY8)
    if (lX4 | lY4) {
      if (lResult & 0x40000000) return (lResult ^ 0xC0000000 ^ lX8 ^ lY8)
      return (lResult ^ 0x40000000 ^ lX8 ^ lY8)
    }
    return (lResult ^ lX8 ^ lY8)
  }
  const f = (x, y, z) => (x & y) | ((~x) & z)
  const g = (x, y, z) => (x & z) | (y & (~z))
  const h = (x, y, z) => (x ^ y ^ z)
  const i = (x, y, z) => (y ^ (x | (~z)))
  const ff = (a, b, c, d, x, s, ac) => {
    a = addUnsigned(a, addUnsigned(addUnsigned(f(b, c, d), x), ac))
    return addUnsigned(rotateLeft(a, s), b)
  }
  const gg = (a, b, c, d, x, s, ac) => {
    a = addUnsigned(a, addUnsigned(addUnsigned(g(b, c, d), x), ac))
    return addUnsigned(rotateLeft(a, s), b)
  }
  const hh = (a, b, c, d, x, s, ac) => {
    a = addUnsigned(a, addUnsigned(addUnsigned(h(b, c, d), x), ac))
    return addUnsigned(rotateLeft(a, s), b)
  }
  const ii = (a, b, c, d, x, s, ac) => {
    a = addUnsigned(a, addUnsigned(addUnsigned(i(b, c, d), x), ac))
    return addUnsigned(rotateLeft(a, s), b)
  }
  const convertToWordArray = (string) => {
    let lWordCount
    const lMessageLength = string.length
    const lNumberOfWordsTemp1 = lMessageLength + 8
    const lNumberOfWordsTemp2 = (lNumberOfWordsTemp1 - (lNumberOfWordsTemp1 % 64)) / 64
    const lNumberOfWords = (lNumberOfWordsTemp2 + 1) * 16
    const lWordArray = Array.from({ length: lNumberOfWords - 1 })
    let lBytePosition = 0
    let lByteCount = 0
    while (lByteCount < lMessageLength) {
      lWordCount = (lByteCount - (lByteCount % 4)) / 4
      lBytePosition = (lByteCount % 4) * 8
      lWordArray[lWordCount] = (lWordArray[lWordCount] | (string.charCodeAt(lByteCount) << lBytePosition))
      lByteCount++
    }
    lWordCount = (lByteCount - (lByteCount % 4)) / 4
    lBytePosition = (lByteCount % 4) * 8
    lWordArray[lWordCount] = lWordArray[lWordCount] | (0x80 << lBytePosition)
    lWordArray[lNumberOfWords - 2] = lMessageLength << 3
    lWordArray[lNumberOfWords - 1] = lMessageLength >>> 29
    return lWordArray
  }
  const wordToHex = (lValue) => {
    let wordToHexValue = '', wordToHexValueTemp = '', lByte, lCount
    for (lCount = 0; lCount <= 3; lCount++) {
      lByte = (lValue >>> (lCount * 8)) & 255
      wordToHexValueTemp = '0' + lByte.toString(16)
      wordToHexValue = wordToHexValue + wordToHexValueTemp.substr(wordToHexValueTemp.length - 2, 2)
    }
    return wordToHexValue
  }
  const utf8Encode = (string) => {
    string = string.replace(/\r\n/g, '\n')
    let utftext = ''
    for (let n = 0; n < string.length; n++) {
      const c = string.charCodeAt(n)
      if (c < 128) utftext += String.fromCharCode(c)
      else if ((c > 127) && (c < 2048)) {
        utftext += String.fromCharCode((c >> 6) | 192)
        utftext += String.fromCharCode((c & 63) | 128)
      } else {
        utftext += String.fromCharCode((c >> 12) | 224)
        utftext += String.fromCharCode(((c >> 6) & 63) | 128)
        utftext += String.fromCharCode((c & 63) | 128)
      }
    }
    return utftext
  }
  let x = []
  let k, AA, BB, CC, DD, a, b, c, d
  const S11 = 7, S12 = 12, S13 = 17, S14 = 22
  const S21 = 5, S22 = 9, S23 = 14, S24 = 20
  const S31 = 4, S32 = 11, S33 = 16, S34 = 23
  const S41 = 6, S42 = 10, S43 = 15, S44 = 21
  string = utf8Encode(string)
  x = convertToWordArray(string)
  a = 0x67452301; b = 0xEFCDAB89; c = 0x98BADCFE; d = 0x10325476
  for (k = 0; k < x.length; k += 16) {
    AA = a; BB = b; CC = c; DD = d
    a = ff(a, b, c, d, x[k + 0], S11, 0xD76AA478)
    d = ff(d, a, b, c, x[k + 1], S12, 0xE8C7B756)
    c = ff(c, d, a, b, x[k + 2], S13, 0x242070DB)
    b = ff(b, c, d, a, x[k + 3], S14, 0xC1BDCEEE)
    a = ff(a, b, c, d, x[k + 4], S11, 0xF57C0FAF)
    d = ff(d, a, b, c, x[k + 5], S12, 0x4787C62A)
    c = ff(c, d, a, b, x[k + 6], S13, 0xA8304613)
    b = ff(b, c, d, a, x[k + 7], S14, 0xFD469501)
    a = ff(a, b, c, d, x[k + 8], S11, 0x698098D8)
    d = ff(d, a, b, c, x[k + 9], S12, 0x8B44F7AF)
    c = ff(c, d, a, b, x[k + 10], S13, 0xFFFF5BB1)
    b = ff(b, c, d, a, x[k + 11], S14, 0x895CD7BE)
    a = ff(a, b, c, d, x[k + 12], S11, 0x6B901122)
    d = ff(d, a, b, c, x[k + 13], S12, 0xFD987193)
    c = ff(c, d, a, b, x[k + 14], S13, 0xA679438E)
    b = ff(b, c, d, a, x[k + 15], S14, 0x49B40821)
    a = gg(a, b, c, d, x[k + 1], S21, 0xF61E2562)
    d = gg(d, a, b, c, x[k + 6], S22, 0xC040B340)
    c = gg(c, d, a, b, x[k + 11], S23, 0x265E5A51)
    b = gg(b, c, d, a, x[k + 0], S24, 0xE9B6C7AA)
    a = gg(a, b, c, d, x[k + 5], S21, 0xD62F105D)
    d = gg(d, a, b, c, x[k + 10], S22, 0x2441453)
    c = gg(c, d, a, b, x[k + 15], S23, 0xD8A1E681)
    b = gg(b, c, d, a, x[k + 4], S24, 0xE7D3FBC8)
    a = gg(a, b, c, d, x[k + 9], S21, 0x21E1CDE6)
    d = gg(d, a, b, c, x[k + 14], S22, 0xC33707D6)
    c = gg(c, d, a, b, x[k + 3], S23, 0xF4D50D87)
    b = gg(b, c, d, a, x[k + 8], S24, 0x455A14ED)
    a = gg(a, b, c, d, x[k + 13], S21, 0xA9E3E905)
    d = gg(d, a, b, c, x[k + 2], S22, 0xFCEFA3F8)
    c = gg(c, d, a, b, x[k + 7], S23, 0x676F02D9)
    b = gg(b, c, d, a, x[k + 12], S24, 0x8D2A4C8A)
    a = hh(a, b, c, d, x[k + 5], S31, 0xFFFA3942)
    d = hh(d, a, b, c, x[k + 8], S32, 0x8771F681)
    c = hh(c, d, a, b, x[k + 11], S33, 0x6D9D6122)
    b = hh(b, c, d, a, x[k + 14], S34, 0xFDE5380C)
    a = hh(a, b, c, d, x[k + 1], S31, 0xA4BEEA44)
    d = hh(d, a, b, c, x[k + 4], S32, 0x4BDECFA9)
    c = hh(c, d, a, b, x[k + 7], S33, 0xF6BB4B60)
    b = hh(b, c, d, a, x[k + 10], S34, 0xBEBFBC70)
    a = hh(a, b, c, d, x[k + 13], S31, 0x289B7EC6)
    d = hh(d, a, b, c, x[k + 0], S32, 0xEAA127FA)
    c = hh(c, d, a, b, x[k + 3], S33, 0xD4EF3085)
    b = hh(b, c, d, a, x[k + 6], S34, 0x4881D05)
    a = hh(a, b, c, d, x[k + 9], S31, 0xD9D4D039)
    d = hh(d, a, b, c, x[k + 12], S32, 0xE6DB99E5)
    c = hh(c, d, a, b, x[k + 15], S33, 0x1FA27CF8)
    b = hh(b, c, d, a, x[k + 2], S34, 0xC4AC5665)
    a = ii(a, b, c, d, x[k + 0], S41, 0xF4292244)
    d = ii(d, a, b, c, x[k + 7], S42, 0x432AFF97)
    c = ii(c, d, a, b, x[k + 14], S43, 0xAB9423A7)
    b = ii(b, c, d, a, x[k + 5], S44, 0xFC93A039)
    a = ii(a, b, c, d, x[k + 12], S41, 0x655B59C3)
    d = ii(d, a, b, c, x[k + 3], S42, 0x8F0CCC92)
    c = ii(c, d, a, b, x[k + 10], S43, 0xFFEFF47D)
    b = ii(b, c, d, a, x[k + 1], S44, 0x85845DD1)
    a = ii(a, b, c, d, x[k + 8], S41, 0x6FA87E4F)
    d = ii(d, a, b, c, x[k + 15], S42, 0xFE2CE6E0)
    c = ii(c, d, a, b, x[k + 6], S43, 0xA3014314)
    b = ii(b, c, d, a, x[k + 13], S44, 0x4E0811A1)
    a = ii(a, b, c, d, x[k + 4], S41, 0xF7537E82)
    d = ii(d, a, b, c, x[k + 11], S42, 0xBD3AF235)
    c = ii(c, d, a, b, x[k + 2], S43, 0x2AD7D2BB)
    b = ii(b, c, d, a, x[k + 9], S44, 0xEB86D391)
    a = addUnsigned(a, AA)
    b = addUnsigned(b, BB)
    c = addUnsigned(c, CC)
    d = addUnsigned(d, DD)
  }
  const result = wordToHex(a) + wordToHex(b) + wordToHex(c) + wordToHex(d)
  return result.toUpperCase()
}

// 生成签名
function generateSignature(params) {
  // 1. 获取当前时间
  const now = new Date()
  const timeStr = now.getFullYear() + '-' +
    String(now.getMonth() + 1).padStart(2, '0') + '-' +
    String(now.getDate()).padStart(2, '0') + ' ' +
    String(now.getHours()).padStart(2, '0') + ':' +
    String(now.getMinutes()).padStart(2, '0') + ':' +
    String(now.getSeconds()).padStart(2, '0')

  // 2. 合并参数
  const allParams = { ...params, time: timeStr }

  // 3. 过滤空值和 enc 参数
  const filteredParams = {}
  for (const [key, value] of Object.entries(allParams)) {
    if (key !== 'enc' && value !== null && value !== undefined && String(value).trim() !== '') {
      filteredParams[key] = String(value)
    }
  }

  // 4. ASCII 升序排序
  const sortedKeys = Object.keys(filteredParams).sort()

  // 5. 拼接字符串
  let sortedStr = ''
  for (const key of sortedKeys) {
    sortedStr += key + filteredParams[key]
  }

  // 6. 计算签名: sortedStr + STATIC_KEY + time
  const rawSign = sortedStr + STATIC_KEY + timeStr
  const enc = md5(rawSign)

  return { time: timeStr, enc }
}

// 请求拦截器
service.interceptors.request.use(
  config => {
    const token = localStorage.getItem('token')
    if (token) {
      // 检查Token是否即将过期（提前10分钟预警）
      if (_isTokenExpiringSoon(token)) {
        showToast('⚠️ 登录即将过期，请尽快完成操作或重新登录', 'warning')
      }

      config.headers['Authorization'] = `Bearer ${token}`
    }

    // Some endpoints accept a signed raw binary body (for example avatar
    // portrait/voice source uploads).  Serializing a File into the legacy
    // request signature payload corrupts that body.  Those endpoints already
    // carry their own short-lived server signature in the URL, so callers can
    // explicitly opt out while the Authorization header above remains intact.
    if (config.skipRequestSigning) {
      return config
    }

    // 添加签名参数
    const params = config.params || {}
    const data = config.data || {}
    const allParams = { ...params, ...data }

    const { time, enc } = generateSignature(allParams)

    // 将签名添加到请求参数中
    if (config.method === 'get') {
      config.params = { ...config.params, time, enc }
    } else {
      // 如果是 FormData，追加到 FormData 中而不是替换
      if (config.data instanceof FormData) {
        config.data.append('time', time)
        config.data.append('enc', enc)
      } else {
        config.data = { ...config.data, time, enc }
      }
    }

    return config
  },
  error => {
    return Promise.reject(error)
  }
)

function _isTokenExpiringSoon(token) {
  try {
    const base64Url = token.split('.')[1]
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/')
    const jsonPayload = decodeURIComponent(atob(base64).split('').map(function(c) {
      return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)
    }).join(''))
    const payload = JSON.parse(jsonPayload)

    if (payload.exp) {
      const expirationTime = payload.exp * 1000
      const currentTime = Date.now()
      const timeUntilExpiration = expirationTime - currentTime
      const tenMinutesInMs = 10 * 60 * 1000

      return timeUntilExpiration > 0 && timeUntilExpiration < tenMinutesInMs
    }

    return false
  } catch {
    return false
  }
}

// 响应拦截器
service.interceptors.response.use(
  response => {
    if (response.data instanceof Blob) {
      if (response.data.type && response.data.type.includes('application/json')) {
        return response.data.text().then(text => {
          const res = JSON.parse(text)
          showToast(res.message || '请求失败', 'error')
          return Promise.reject(new Error(res.message || 'Error'))
        })
      }
      return response.data
    }

    const res = response.data

    if (response.config?.allowFlatResponse && (res === null || typeof res !== 'object' || !Object.prototype.hasOwnProperty.call(res, 'code'))) {
      return res
    }

    // The backend envelope uses 200 for reads and 201 for successful creates.
    // Treat the full 2xx range as success so create-run/attempt/diagnosis
    // calls are not rejected after the HTTP request itself succeeded.
    if (typeof res.code !== 'number' || res.code < 200 || res.code >= 300) {

      // 特殊状态码处理：Token 过期
      if (res.code === 401) {
        showToast('登录信息过期，请重新登录', 'error')

        // 清除所有认证信息并跳转登录页
        _handleUnauthorized()
      } else if (!res.config?.skipErrorToast && !response.config?.skipErrorToast) {
        // 普通业务错误，直接弹出后端返回的错误信息
        showToast(res.message || '请求失败', 'error')
      }

      return Promise.reject(new Error(res.message || 'Error'))
    } else {
      // 正常返回 data 数据，剥离 code/message 层
      return res.data
    }
  },
  error => {
    // 处理 HTTP 网络错误 (如 404, 500, 超时)
    let message = '网络连接异常，请稍后再试'
    let backendMessage = ''

    if (error.response) {
      const responseData = error.response.data
      const detail = responseData?.detail
      backendMessage = (
        (typeof detail === 'string' ? detail : detail?.message)
        || responseData?.message
      )
      switch (error.response.status) {
        case 401:
          message = '登录已过期，请重新登录'
          _handleUnauthorized()
          break
        case 403:
          message = '拒绝访问，权限不足'
          break
        case 404:
          message = '请求资源不存在'
          break
        case 500:
          message = backendMessage || '服务器暂时出了点问题，请稍后重试'
          break
        case 503:
          message = backendMessage || '服务暂不可用，请稍后重试'
          break
        case 504:
          message = backendMessage || '请求超时，请稍后重试'
          break
        default:
          message = backendMessage || '未知错误'
      }
    } else if (error.message.includes('timeout')) {
      message = '请求超时，请检查网络'
    } else if (error.message.includes('Network Error')) {
      message = '网络断开，请检查连接'
    }

    // skipErrorToast：调用方声明本次请求失败由自身处理（如 Agent 503 回退 V1），
    // 不向用户弹错误提示，避免降级场景造成「先报错再成功」的误导。
    if (!error.config?.skipErrorToast) {
      showToast(message, 'error')
    }
    // Callers that render their own status must receive the server detail too.
    // Keep the structured backend message available for publish/check flows;
    // only use the generic text when the server supplied no useful detail.
    error.message = backendMessage || message
    return Promise.reject(error)
  }
)

function _handleUnauthorized() {
  localStorage.removeItem('token')
  localStorage.removeItem('userId')
  localStorage.removeItem('username')
  localStorage.removeItem('userRole')

  try {
    const counter = useCounterStore()
    counter.clearAuth()
  } catch (e) {
    // store may not be initialized yet
  }

  setTimeout(() => {
    window.location.href = '/profile'
  }, 1500)
}

export default service
