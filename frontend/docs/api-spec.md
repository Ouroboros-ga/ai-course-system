# API接口调用说明

## 1. 基础配置

### 1.1 基础URL
```javascript
baseURL: 'http://localhost:8000/api/v1'
```

### 1.2 请求超时时间
```javascript
timeout: 10000 // 10秒
```

### 1.3 请求拦截器
- 自动添加Authorization Bearer token
- 自动生成签名参数（time 和 enc）
- 签名生成规则：
  1. 获取当前时间字符串
  2. 合并所有请求参数
  3. 过滤空值和 enc 参数
  4. 按键名 ASCII 升序排序
  5. 拼接参数字符串
  6. 使用 MD5 算法计算签名：`md5(sortedStr + STATIC_KEY + time)`

### 1.4 响应拦截器
- 统一处理业务错误（code !== 200）
- 特殊处理 Token 过期（code === 401）
- 统一处理 HTTP 网络错误
- 自动显示错误提示

## 2. API接口列表

### 2.1 用户相关接口

#### 2.1.1 用户登录
```javascript
import api from '@/api'

const loginData = {
  username: 'your_username',
  password: 'your_password'
}

api.user.login(loginData)
  .then(response => {
    console.log('登录成功:', response)
    // 保存token到localStorage
    localStorage.setItem('token', response.token)
  })
  .catch(error => {
    console.error('登录失败:', error)
  })
```

**请求参数：**
- `username`: 用户名（必填）
- `password`: 密码（必填）

**返回数据：**
```javascript
{
  token: 'your_jwt_token',
  user: {
    id: 1,
    username: 'your_username'
  }
}
```

#### 2.1.2 用户注册
```javascript
import api from '@/api'

const registerData = {
  username: 'new_username',
  password: 'new_password'
}

api.user.register(registerData)
  .then(response => {
    console.log('注册成功:', response)
  })
  .catch(error => {
    console.error('注册失败:', error)
  })
```

**请求参数：**
- `username`: 用户名（必填）
- `password`: 密码（必填）

**返回数据：**
```javascript
{
  message: '注册成功',
  user: {
    id: 1,
    username: 'new_username'
  }
}
```

#### 2.1.3 用户信息修改
```javascript
import api from '@/api'

const modifyData = {
  id: 1,
  username: 'updated_username',
  password: 'updated_password'
}

api.user.modify(modifyData)
  .then(response => {
    console.log('修改成功:', response)
  })
  .catch(error => {
    console.error('修改失败:', error)
  })
```

**请求参数：**
- `id`: 用户ID（必填）
- `username`: 用户名（必填）
- `password`: 密码（必填）

**返回数据：**
```javascript
{
  message: '修改成功',
  user: {
    id: 1,
    username: 'updated_username'
  }
}
```

### 2.2 聊天相关接口

#### 2.2.1 发送聊天消息（支持文件）
```javascript
import api from '@/api'

const formData = new FormData()
formData.append('message', 'Hello AI')
formData.append('file', file) // 文件对象

api.chat.sendChatMessage(formData)
  .then(response => {
    console.log('消息发送成功:', response)
  })
  .catch(error => {
    console.error('消息发送失败:', error)
  })
```

**请求参数：**
- `message`: 消息内容（必填）
- `file`: 文件对象（可选）

**返回数据：**
```javascript
{
  message_id: 1,
  status: 'sent'
}
```

#### 2.2.2 接收AI回复
```javascript
import api from '@/api'

const messageData = {
  message_id: 1
}

api.chat.receiveChatMessage(messageData)
  .then(response => {
    console.log('AI回复:', response)
  })
  .catch(error => {
    console.error('获取回复失败:', error)
  })
```

**请求参数：**
- `message_id`: 消息ID（必填）

**返回数据：**
```javascript
{
  message: 'AI回复内容',
  status: 'received'
}
```

## 3. API调用示例

### 3.1 基本调用
```javascript
import api from '@/api'

// 用户登录
api.user.login({
  username: 'admin',
  password: 'password123'
})
.then(data => {
  localStorage.setItem('token', data.token)
  console.log('登录成功')
})
.catch(error => {
  console.error('登录失败:', error)
})
```

### 3.2 带文件上传的调用
```javascript
import api from '@/api'

const handleFileUpload = async (file) => {
  const formData = new FormData()
  formData.append('message', '请分析这个文件')
  formData.append('file', file)
  
  try {
    const response = await api.chat.sendChatMessage(formData)
    console.log('文件上传成功:', response)
  } catch (error) {
    console.error('文件上传失败:', error)
  }
}
```

### 3.3 错误处理
```javascript
import api from '@/api'
import { showToast } from '@/utils/toast'

const fetchUserData = async () => {
  try {
    const response = await api.user.getUserInfo()
    return response
  } catch (error) {
    showToast('获取用户信息失败', 'error')
    throw error
  }
}
```

## 4. 安全注意事项

### 4.1 Token管理
- 使用 localStorage 存储 JWT token
- 请求拦截器自动添加 Authorization header
- Token 过期时自动清除并提示用户重新登录

### 4.2 签名验证
- 所有请求都需要进行签名验证
- 签名算法使用 MD5
- 静态密钥存储在前端代码中（注意：生产环境应使用更安全的方式）

### 4.3 数据安全
- 密码等敏感信息使用 HTTPS 传输
- 避免在前端存储敏感信息
- 定期清理 localStorage 中的过期数据

## 5. 调试指南

### 5.1 查看请求日志
```javascript
// request.js 中已添加详细的调试日志
// 控制台会输出：
// - 原始参数
// - 请求方法和URL
// - 过滤后参数
// - 排序后键
// - 拼接字符串
// - 原始签名串
// - 生成的时间和签名
// - 最终请求数据
```

### 5.2 常见错误处理
1. **401 Unauthorized**: Token 过期或无效
2. **403 Forbidden**: 权限不足
3. **404 Not Found**: 请求资源不存在
4. **500 Internal Server Error**: 服务器错误
5. **Network Error**: 网络连接异常
6. **Timeout**: 请求超时

## 6. API扩展建议

1. **分页查询**: 为列表接口添加分页支持
2. **搜索功能**: 添加搜索接口支持
3. **批量操作**: 支持批量删除、更新等操作
4. **WebSocket**: 实现实时消息推送
5. **文件管理**: 扩展文件上传、下载、预览功能
