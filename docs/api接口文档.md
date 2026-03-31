## **API接口文档**

### **1. 用户模块接口**

#### **1.1 用户登录**

**接口地址**: /user/login
**请求方法**: POST
**请求参数**:

```
{
  "username": "用户名",
  "password": "密码" 
}
```
**返回结果**:
```
{ 
  "code": 200,
  "message": "登录成功", 
  "data": { 
    "token": "用户令牌",
    "userInfo": { 
      "id": "用户ID"
    }
  }
}
```
**错误处理**:
```
{
  "code": 401,
  "message": "用户名密码错误",
  "data": null
}
```

#### **1.2 用户注册**

**接口地址**: /user/register
**请求方法**: POST
**请求参数**:
```
{
  "username": "用户名",
  "password": "密码"
}
```
**返回结果**:
```
{ 
  "code": 200,
  "message": "注册并登录成功", 
  "data": { 
    "token": "用户令牌",
    "userInfo": { 
      "id": "用户ID"
    }
  }
}
```
**错误处理**:
```
{
  "code": 409,
  "message": "用户名已存在",
  "data": null
}
```
### **1.3 用户信息修改**
#### **接口描述**
用于用户修改自己的用户名或密码。修改成功后，服务端会颁发新的Token，旧Token立即失效，客户端需更新本地存储的Token。
#### **基本信息**
**接口地址**: /user/modify
**请求方法**: POST
**Content-Type**: application/json
#### **请求参数**
| **参数名**    | **类型** | **必填** | **说明**                                                    |
| ------------- | -------- | -------- | ----------------------------------------------------------- |
| id            | String   | 是       | 当前登录用户的ID（建议从Token中解析，此处保留作为参数传递） |
| username      | String   | 是       | 用户当前的用户名（用于身份校验）                            |
| password      | String   | 是       | 用户当前的密码                                              |
| newUsername   | String   | 否       | 修改后的新用户名。若不修改用户名，此项传空字符串            |
| newPassword   | String   | 否       | 修改后的新密码。若不修改密码，此项传空字符串                |
| **请求示例**: |          |          |     |
```
{
  "id": "1001",
  "username": "old_name",
  "password": "old_pass_123",
  "newUsername": "new_name_2024",
  "newPassword": "new_pass_456"
}
```
**成功响应示例**:
```
{
  "code": 200,
  "message": "修改成功",
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "userInfo": {
      "id": "1001",
      "username": "new_name_2024"
    }
  }
}
```

## **2 聊天模块接口**
### **2.1 获取历史聊天记录**
#### **接口描述**
用于分页获取当前用户的 **侧栏** 历史聊天记录。
#### **基本信息**

**接口地址**: /chat/history
**请求方法**: GET
**身份验证**: 需要在请求头中携带Token（Authorization: Bearer <token>）

#### **请求参数（Query）**

| **参数名** | **类型** | **必填** | **说明**                  |
| ---------- | -------- | -------- | ------------------------- |
| userId     | Integer  | 是       | 用户 ID                   |
| page       | Integer  | 否       | 页码，从1开始，默认1      |
| pageSize   | Integer  | 否       | 每页数量，默认20，最大100 |

**请求示例**:
```
GET /chat/history?userId=12&page=1&pageSize=20
```
#### **成功响应示例**
```
{
  "code": 200,
  "message": "获取成功",
  "data": {
    "total": 105,
    "page": 1,
    "pageSize": 20,
    "list": [
      {
        "userId": 12,
        "id": 1651516,
        "content": "雷锋精神ppt解析",
        "createTime": "2025-01-15 10:30:25"
      },
      {
        "userId": 12,
        "id": 65165,
        "content": "绍兴理工word文档解读",
        "createTime": "2025-01-15 10:30:25"
      }
    ]
  }
}
```
#### **错误处理**

**未授权访问**（未携带或Token无效）:
```
{
  "code": 401,
  "message": "未授权，请先登录",
  "data": null
}
```
### **2.2 用户上传文件**

#### **接口描述**

用于用户上传文件（图片、文档等），后端自动解析文件内容，生成内容摘要（10字以内），并利用TTS技术生成语音音频文件，同时创建或关联一个会话，返回解析结果及语音文件地址。

#### **基本信息**
**接口地址**: /chat/file/upload
**请求方法**: POST
**Content-Type**: multipart/form-data
**身份验证**: 需要在请求头中携带Token（Authorization: Bearer <token>）

#### **请求参数（Form Data）**

| **参数名**  | **类型**  | **必填** | **说明**                               |
|----------|---------|--------|--------------------------------------|
| file     | File    | 是      | 上传的文件（支持图片、PDF、Word等常见格式），单个文件最大50MB |
| fileName | String  | 是      | 用户指定的文件名称（用于展示）                      |
| userId   | Integer | 是      | 用户ID，用于关联上传记录                        |
**请求示例**:
```
POST /file/upload HTTP/1.1
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary
 
------WebKitFormBoundary
Content-Disposition: form-data; name="file"; filename="contract.pdf"
Content-Type: application/pdf
 
[二进制文件数据]
------WebKitFormBoundary
Content-Disposition: form-data; name="fileName"
 
采购合同.pdf
------WebKitFormBoundary
Content-Disposition: form-data; name="userId"
 
1001
------WebKitFormBoundary--
```
#### **成功响应示例**
```json
{
  "code": 200,
  "message": "上传并解析成功",
  "data": {
    "fullContent": "本合同由甲方（采购方）与乙方（供应方）就...（完整解析文本.md格式）",
    "title": "采购合同解析（标题）",
    "audioUrl": "https://yourdomain.com/audio/session_abc123.mp3（语音音频存放地点）",
    "mindMapJson": {
      "text": "思维导图绘制格式json，可自由搭配",
      "children": [
        { "text": "数学" },
        { "text": "英语" },
        { "text": "编程" },
        { "text": "阅读" }
      ]
    },
    "ChatId": 651651
  }
}
```
#### **错误处理**

**文件大小超限**:
```
{
  "code": 400,
  "message": "文件大小超过限制（最大50MB）",
  "data": null
}
```
**文件类型不支持**:
```
{
  "code": 400,
  "message": "不支持的文件类型，仅支持 jpg/png/pdf/docx 等格式",
  "data": null
}
```
**参数缺失**:
```
{
  "code": 400,
  "message": "缺少必填参数：file/fileName/userId",
  "data": null
}
```
**解析失败**:
```
{
  "code": 500,
  "message": "文件解析失败，请检查文件内容是否完整",
  "data": null
}
```
**语音生成失败**:
```
{
  "code": 500,
  "message": "语音生成失败，请稍后重试",
  "data": null
}
```