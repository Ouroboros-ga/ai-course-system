# 火山引擎TTS配置指南

## 📋 配置步骤

### 1. 打开配置文件

打开 `backend/.env` 文件（如果不存在，从 `.env.example` 复制）

### 2. 填写火山引擎配置

```env
# --------------------------
# 语音合成API配置
# --------------------------
# 选择的TTS提供商
TTS_PROVIDER=volcengine

# 音频参数（通常不需要修改）
TTS_SAMPLE_RATE=16000
TTS_FORMAT=mp3

# 火山引擎TTS配置
VOLCENGINE_TTS_APP_ID=你的APP_ID
VOLCENGINE_TTS_ACCESS_TOKEN=你的Access_Token
VOLCENGINE_TTS_SECRET_KEY=你的Secret_Key

# 音色选择
TTS_VOICE=zh_female_shuangkuaisisi_moon_bigtts
```

## 🔑 获取火山引擎API密钥

### 步骤1：注册火山引擎账号

访问：https://www.volcengine.com/

### 步骤2：开通语音技术服务

1. 登录火山引擎控制台
2. 访问：https://console.volcengine.com/speech/app
3. 点击"创建新应用"

### 步骤3：获取配置信息

创建应用后，你会获得：

- **APP ID**：应用唯一标识
- **Access Token**：访问令牌
- **Secret Key**：密钥

### 步骤4：填写配置

将获取的信息填入 `.env` 文件：

```env
VOLCENGINE_TTS_APP_ID=1234567890
VOLCENGINE_TTS_ACCESS_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
VOLCENGINE_TTS_SECRET_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## 🎯 完整配置示例

```env
# ===========================================
# 超星AI互动智课系统 - 环境变量配置
# ===========================================

# --------------------------
# 签名校验配置
# --------------------------
STATIC_KEY=your-static-key-here
SIGN_TIMEOUT_MINUTES=5

# --------------------------
# JWT身份认证配置
# --------------------------
JWT_SECRET_KEY=your-jwt-secret-key-very-long-random-string
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=120

# --------------------------
# 大模型API配置
# --------------------------
LLM_PROVIDER=doubao
DOUBAO_API_KEY=your-doubao-api-key
DOUBAO_ENDPOINT_ID=your-doubao-endpoint-id

# --------------------------
# 语音合成API配置（火山引擎）
# --------------------------
TTS_PROVIDER=volcengine
TTS_SAMPLE_RATE=16000
TTS_FORMAT=mp3

# 火山引擎TTS配置
VOLCENGINE_TTS_APP_ID=1234567890
VOLCENGINE_TTS_ACCESS_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
VOLCENGINE_TTS_SECRET_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TTS_VOICE=zh_female_shuangkuaisisi_moon_bigtts
```

## 🎨 可选音色列表

### 女声

| 音色代码 | 特点 |
|---------|------|
| `zh_female_shuangkuaisisi_moon_bigtts` | 爽快思思（推荐） |
| `zh_female_tianmei_xiaoyuan_moon_bigtts` | 甜美小媛 |
| `zh_female_wanwanxiaohe_moon_bigtts` | 弯弯小荷 |
| `zh_female_qingxinwenrou_nvxia_moon_bigtts` | 清新温柔女侠 |

### 男声

| 音色代码 | 特点 |
|---------|------|
| `zh_male_chunhou_zhiboshuangkuai` | 醇厚智博爽快 |
| `zh_male_qingnianyushi_xianfeng` | 青年宇视先锋 |
| `zh_male_chunhoushuisheng` | 醇厚水声 |

### 使用方法

在 `.env` 文件中修改 `TTS_VOICE` 配置：

```env
# 使用女声
TTS_VOICE=zh_female_shuangkuaisisi_moon_bigtts

# 或使用男声
TTS_VOICE=zh_male_chunhou_zhiboshuangkuai
```

## ⚙️ 高级配置

### 调整语速

在代码调用时传入参数：

```python
await tts_client.synthesize(
    text="你好世界",
    speed_ratio=1.2,  # 语速比例，1.0为正常，1.2为快20%
    volume_ratio=1.0,  # 音量比例
    pitch_ratio=1.0    # 音调比例
)
```

### 音频格式

支持以下格式：

```env
TTS_FORMAT=mp3   # MP3格式（推荐）
TTS_FORMAT=wav   # WAV格式（无损）
TTS_FORMAT=pcm   # PCM格式（原始音频）
```

## 🧪 测试配置

### 方法1：启动后端查看日志

```bash
cd backend
python run.py
```

查看控制台输出：

```
INFO:     初始化TTS客户端: volcengine
```

如果看到警告：

```
WARNING:  火山引擎TTS配置不完整，请在.env中设置VOLCENGINE_TTS相关配置
```

说明配置有误，需要检查。

### 方法2：使用Mock模式测试

如果暂时没有API密钥，可以使用Mock模式：

```env
TTS_PROVIDER=mock
```

Mock模式会返回虚拟音频数据，无需真实API Key。

## ⚠️ 常见问题

### Q1: 提示"火山引擎TTS配置不完整"

**原因**：缺少必要的配置项

**解决**：
1. 检查 `.env` 文件是否存在
2. 确认三个必填项都已填写：
   - VOLCENGINE_TTS_APP_ID
   - VOLCENGINE_TTS_ACCESS_TOKEN
   - VOLCENGINE_TTS_SECRET_KEY

### Q2: 语音合成失败

**原因**：API密钥无效或权限不足

**解决**：
1. 检查API密钥是否正确
2. 确认已开通语音合成服务
3. 检查账号余额是否充足

### Q3: 音色不存在

**原因**：使用了错误的音色代码

**解决**：
使用本文档中列出的标准音色代码

### Q4: 音频格式不支持

**原因**：使用了不支持的音频格式

**解决**：
使用 `mp3`、`wav` 或 `pcm` 格式

## 🔒 安全提示

1. **不要提交 `.env` 文件到Git**
   ```bash
   # .gitignore 已包含
   .env
   .env.local
   ```

2. **定期更换API Key**
   - 建议每3-6个月更换一次
   - 如果泄露立即更换

3. **使用子账号**
   - 不要使用主账号密钥
   - 创建只有TTS权限的子账号

## 📞 火山引擎官方文档

- [语音合成产品文档](https://www.volcengine.com/docs/6561/79823)
- [API参考文档](https://www.volcengine.com/docs/6561/79824)
- [控制台](https://console.volcengine.com/speech/app)

## 💰 计费说明

火山引擎TTS按字符计费：

- 免费额度：每月100万字符
- 超出后：约0.002元/100字符

建议：
1. 开发测试时使用Mock模式
2. 生产环境监控使用量
3. 设置用量告警

---

**配置完成后，重启后端服务即可生效！** ✅
