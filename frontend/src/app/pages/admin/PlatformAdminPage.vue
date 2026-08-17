<script setup>
import { onMounted, reactive, ref } from 'vue'
import { RefreshCw, ShieldCheck, ShieldAlert, SlidersHorizontal, UsersRound, Cpu, ToggleLeft, Plus, Trash2 } from 'lucide-vue-next'
import { useSettingsStore } from '@/stores/userSettings'
import { getAdminCourseCapabilities, getAdminUsers, getIntegrations, getSafetyKeywords, createSafetyKeyword, updateSafetyKeyword, deleteSafetyKeyword, getTaskConcurrency, resetAdminPassword, testIntegration, updateAdminCourseCapabilities, updateAdminUser, updateIntegration, updateTaskConcurrency } from '@/api/admin_platform.js'
import { showToast } from '@/utils/toast.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const settings = useSettingsStore()

const loading = ref(true)
const error = ref('')
const users = ref([])
const integrations = ref([])
const total = ref(0)
const page = ref(1)
const saving = ref('')
const passwordFor = ref(null)
const password = ref('')
const filters = reactive({ user_id: '', query: '', role: '', is_active: '' })
const drafts = reactive({})
const concurrency = reactive({ developer_mode: false, max_total: 1, document_parse: 1, course_draft_build: 1, graphrag: 1, vector_index: 1, sandbox_execution: 1, graphrag_max_input_tokens: 0 })

// ---- 平台级安全屏蔽词（2026-08-17 新增）----
const keywordCategory = ref('')
const keywordItems = ref([])
const keywordDefaults = ref({})
const keywordForm = reactive({ keyword: '', category: 'cyber', risk_level: 'medium', description: '' })
const confirmingDelete = ref(null)
const savingKeywordRisk = ref(null)
const CATEGORY_META = {
  cyber: { label: '网络安全', caption: '网安攻击类（原关键词辅助表）' },
  political_high_risk: { label: '政治高危', caption: '主权/分裂/颠覆/极端类，任何课程命中即拒绝' },
  political_topic: { label: '政治话题', caption: '专业/网安课程拒绝，思政课放行教学' },
}
const CATEGORY_TABS = [
  { value: '', label: '全部' },
  { value: 'cyber', label: '网络安全' },
  { value: 'political_high_risk', label: '政治高危' },
  { value: 'political_topic', label: '政治话题' },
]

const CAPABILITY_FIELDS = [
    { key: 'learning', label: '学习' },
    { key: 'course_building', label: '建设' },
    { key: 'knowledge_graph', label: '图谱' },
    { key: 'evidence', label: '证据' },
    { key: 'experiment', label: '实验' },
    { key: 'coding_sandbox', label: '沙箱' },
    { key: 'cognitive_analysis', label: '认知' },
    { key: 'safety_policy', label: '安全' },
]
const ALL_CAPS_ON = Object.fromEntries(CAPABILITY_FIELDS.map(field => [field.key, true]))
const courseCaps = ref([])

function userPatch(user) {
    return { username: user.username || '', role: user.role, is_active: user.is_active }
}

function integrationDraft(item) {
    return { provider: item.provider || '', base_url: item.base_url || '', model_name: item.model_name || '', api_key: '', extra_config: JSON.stringify(item.extra_config || {}, null, 2), enabled: Boolean(item.enabled), expected_version: item.version }
}

async function loadUsers() {
    const params = { page: page.value, page_size: 20 }
    if (filters.user_id) params.user_id = filters.user_id
    if (filters.query) params.query = filters.query
    if (filters.role) params.role = filters.role
    if (filters.is_active !== '') params.is_active = filters.is_active === 'true'
    const result = await getAdminUsers(params)
    users.value = result.items || []
    total.value = result.total || 0
}

async function load() {
    loading.value = true
    error.value = ''
    try {
        const [userResult, integrationResult, concurrencyResult, capsResult] = await Promise.all([getAdminUsers({ page: page.value, page_size: 20 }), getIntegrations(), getTaskConcurrency(), getAdminCourseCapabilities()])
        users.value = userResult.items || []
        total.value = userResult.total || 0
        integrations.value = integrationResult.items || []
        integrations.value.forEach(item => { drafts[item.integration_key] = integrationDraft(item) })
        Object.assign(concurrency, concurrencyResult || {})
        courseCaps.value = (capsResult.items || []).map(item => ({ ...item, draft: { ...item.capabilities } }))
    } catch (caught) {
        error.value = caught?.response?.data?.detail?.message || caught?.message || '无法读取平台管理数据'
    } finally {
        loading.value = false
    }
}

async function saveConcurrency() {
    saving.value = 'task-concurrency'
    try {
        const updated = await updateTaskConcurrency({ ...concurrency })
        Object.assign(concurrency, updated || {})
        showToast('后台任务并发配置已保存', 'success')
    } catch (caught) {
        showToast(caught?.message || '并发配置保存失败', 'error')
    } finally { saving.value = '' }
}

async function saveUser(user) {
    saving.value = `user-${user.id}`
    try {
        const updated = await updateAdminUser(user.id, userPatch(user))
        Object.assign(user, updated)
        showToast('用户资料已更新', 'success')
    } catch (caught) {
        showToast(caught?.message || '用户更新失败', 'error')
    } finally { saving.value = '' }
}

async function setPassword(user) {
    if (!password.value || password.value.length < 8) return showToast('新密码至少需要 8 位', 'warning')
    saving.value = `password-${user.id}`
    try {
        await resetAdminPassword(user.id, password.value)
        password.value = ''
        passwordFor.value = null
        showToast('密码已重置，旧登录凭据已失效', 'success')
    } catch (caught) {
        showToast(caught?.message || '重置密码失败', 'error')
    } finally { saving.value = '' }
}

async function saveIntegration(item) {
    const draft = drafts[item.integration_key]
    saving.value = `integration-${item.integration_key}`
    try {
        const extra = draft.extra_config.trim() ? JSON.parse(draft.extra_config) : {}
        const updated = await updateIntegration(item.integration_key, { ...draft, extra_config: extra })
        Object.assign(item, updated)
        drafts[item.integration_key] = integrationDraft(item)
        showToast(`${item.integration_key.toUpperCase()} 配置已保存并热刷新`, 'success')
    } catch (caught) {
        showToast(caught instanceof SyntaxError ? '高级配置必须是 JSON 对象' : (caught?.message || 'Provider 保存失败'), 'error')
    } finally { saving.value = '' }
}

async function probe(item) {
    saving.value = `probe-${item.integration_key}`
    try {
        const result = await testIntegration(item.integration_key)
        item.health_status = result.status
        showToast(`连通性检查：${result.status}`, result.status === 'reachable' || result.status === 'configured' ? 'success' : 'warning')
    } catch (caught) {
        showToast(caught?.message || 'Provider 不可用', 'error')
    } finally { saving.value = '' }
}

async function toggleIntegration(item) {
    saving.value = `toggle-${item.integration_key}`
    const next = !item.enabled
    try {
        const updated = await updateIntegration(item.integration_key, { enabled: next, expected_version: item.version })
        Object.assign(item, updated)
        drafts[item.integration_key] = integrationDraft(item)
        showToast(next ? `${item.integration_key.toUpperCase()} 真实接入已开启` : `${item.integration_key.toUpperCase()} 真实接入已关闭`, 'success')
    } catch (caught) {
        const detail = caught?.response?.data?.detail
        const message = typeof detail === 'object' ? (detail.message || '') : (caught?.message || '切换失败')
        showToast(message || `开启 ${item.integration_key.toUpperCase()} 前请先完整填写 Provider 配置`, 'error')
    } finally { saving.value = '' }
}

async function saveCourseCaps(course) {
    saving.value = `caps-${course.course_id}`
    try {
        const updated = await updateAdminCourseCapabilities(course.course_id, course.draft)
        course.capabilities = updated.capabilities
        course.draft = { ...updated.capabilities }
        showToast(`课程「${course.title}」能力开关已保存`, 'success')
    } catch (caught) {
        showToast(caught?.message || '能力开关保存失败', 'error')
    } finally { saving.value = '' }
}

async function enableAllCaps(course) {
    course.draft = { ...ALL_CAPS_ON }
    await saveCourseCaps(course)
}

async function enableAllCoursesCaps() {
    if (!courseCaps.value.length) return
    saving.value = 'caps-all'
    try {
        for (const course of courseCaps.value) {
            const updated = await updateAdminCourseCapabilities(course.course_id, { ...ALL_CAPS_ON })
            course.capabilities = updated.capabilities
            course.draft = { ...updated.capabilities }
        }
        showToast('已为全部课程开启所有能力开关', 'success')
    } catch (caught) {
        showToast(caught?.message || '批量开启失败', 'error')
    } finally { saving.value = '' }
}

// ---- 安全屏蔽词操作 ----
async function loadKeywords() {
  try {
    const params = { page_size: 200 }
    if (keywordCategory.value) params.category = keywordCategory.value
    const result = await getSafetyKeywords(params)
    keywordItems.value = result.items || []
    keywordDefaults.value = result.defaults || {}
  } catch (caught) {
    showToast(caught?.message || '屏蔽词列表加载失败', 'error')
  }
}

function keywordCount(category) {
  return keywordItems.value.filter(item => !category || item.category === category).length
}

async function addKeyword() {
  const keyword = keywordForm.keyword.trim()
  if (!keyword) return showToast('请输入屏蔽词', 'warning')
  saving.value = 'keyword-add'
  try {
    await createSafetyKeyword({ keyword, category: keywordForm.category, risk_level: keywordForm.risk_level, description: keywordForm.description.trim() })
    keywordForm.keyword = ''
    keywordForm.description = ''
    keywordForm.risk_level = 'medium'
    showToast('屏蔽词已添加并即时生效', 'success')
    await loadKeywords()
  } catch (caught) {
    showToast(caught?.message || '添加屏蔽词失败', 'error')
  } finally { saving.value = '' }
}

async function updateKeywordRisk(item) {
  savingKeywordRisk.value = item.id
  try {
    const updated = await updateSafetyKeyword(item.id, { risk_level: item.risk_level })
    Object.assign(item, updated)
    showToast(`「${item.keyword}」风险等级已更新`, 'success')
  } catch (caught) {
    showToast(caught?.message || '风险等级更新失败', 'error')
  } finally { savingKeywordRisk.value = null }
}

async function toggleKeyword(item) {
  saving.value = `keyword-toggle-${item.id}`
  const next = !item.enabled
  try {
    const updated = await updateSafetyKeyword(item.id, { enabled: next })
    Object.assign(item, updated)
    showToast(next ? `「${item.keyword}」已启用` : `「${item.keyword}」已停用（不再拦截）`, 'success')
  } catch (caught) {
    showToast(caught?.message || '切换失败', 'error')
  } finally { saving.value = '' }
}

async function removeKeyword(item) {
  if (confirmingDelete.value !== item.id) {
    confirmingDelete.value = item.id
    return
  }
  confirmingDelete.value = null
  saving.value = `keyword-del-${item.id}`
  try {
    await deleteSafetyKeyword(item.id)
    showToast(`「${item.keyword}」已删除`, 'success')
    await loadKeywords()
  } catch (caught) {
    showToast(caught?.message || '删除失败', 'error')
  } finally { saving.value = '' }
}

onMounted(() => { load(); loadKeywords() })
</script>

<template>
    <div class="sfx-page admin-page">
        <header class="sfx-page-header">
            <div>
                <h1 class="sfx-t-title1">
                    <ShieldCheck :size="25" /> 平台管理
                </h1>
                <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">管理平台用户账号与系统配置；课程内的教学角色由各课程单独授权。</p>
            </div>
            <div class="header-actions">
                <SfxButton variant="secondary" size="sm" @click="settings.nextAvatar">
                    <span>切换头像 ({{ settings.avatarIndex }})</span>
                </SfxButton>
                <SfxButton variant="secondary" size="sm" :disabled="loading" @click="load">
                    <RefreshCw :size="15" /> 刷新
                </SfxButton>
            </div>
        </header>

        <SfxSkeleton v-if="loading" :lines="8" block />
        <SfxError v-else-if="error" :description="error" @retry="load" />
        <template v-else>
            <section class="sfx-panel admin-section">
                <div class="section-head">
                    <h2 class="sfx-t-title3">
                        <UsersRound :size="19" /> 用户管理
                    </h2><span class="sfx-t-caption">{{ total }} 个账号</span>
                </div>
                <form class="filters" @submit.prevent="page = 1; loadUsers()">
                    <input v-model="filters.user_id" class="sfx-input" inputmode="numeric" placeholder="用户 ID" />
                    <input v-model="filters.query" class="sfx-input" placeholder="用户名搜索" />
                    <select v-model="filters.role" class="sfx-select">
                        <option value="">全部角色</option>
                        <option value="user">用户</option>
                        <option value="admin">管理员</option>
                    </select>
                    <select v-model="filters.is_active" class="sfx-select">
                        <option value="">全部状态</option>
                        <option value="true">启用</option>
                        <option value="false">停用</option>
                    </select>
                    <SfxButton type="submit" size="sm" variant="secondary">筛选</SfxButton>
                </form>
                <SfxEmpty v-if="!users.length" title="没有匹配账号" description="调整搜索条件后再试。" />
                <div v-else class="sfx-table-wrap">
                    <table class="sfx-table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>用户名</th>
                                <th>角色</th>
                                <th>状态</th>
                                <th>操作</th>
                            </tr>
                        </thead>
                        <tbody><template v-for="user in users" :key="user.id">
                                <tr>
                                    <td>{{ user.id }}</td>
                                    <td><input v-model="user.username" class="sfx-input compact" maxlength="50"
                                            aria-label="用户名" /></td>
                                    <td><select v-model="user.role" class="sfx-select compact">
                                            <option value="user">用户</option>
                                            <option value="admin">管理员</option>
                                        </select></td>
                                    <td><label class="state-check"><input v-model="user.is_active" type="checkbox" /> {{
                                        user.is_active ? '启用' : '停用' }}</label></td>
                                    <td><span class="actions">
                                            <SfxButton size="sm" variant="secondary"
                                                :loading="saving === `user-${user.id}`" @click="saveUser(user)">保存
                                            </SfxButton>
                                            <SfxButton size="sm" variant="tertiary"
                                                @click="passwordFor = user.id; password = ''">重置密码</SfxButton>
                                        </span></td>
                                </tr>
                                <tr v-if="passwordFor === user.id" class="password-row">
                                    <td colspan="5"><span class="password-row-actions"><input v-model="password"
                                                class="sfx-input" type="password" autocomplete="new-password"
                                                placeholder="输入至少 8 位的新密码" />
                                            <SfxButton size="sm" :loading="saving === `password-${user.id}`"
                                                @click="setPassword(user)">确认重置</SfxButton>
                                            <SfxButton size="sm" variant="tertiary" @click="passwordFor = null">取消
                                            </SfxButton>
                                        </span></td>
                                </tr>
                            </template>
                        </tbody>
                    </table>
                </div>
            </section>

            <section class="sfx-panel admin-section">
                <div class="section-head">
                    <h2 class="sfx-t-title3">
                        <ToggleLeft :size="19" /> 课程能力开关
                    </h2><span class="sfx-t-caption">能力开关门控课程权限；关闭后对应接口返回 403。平台管理员可在此一键解锁全部课程。</span>
                </div>
                <div class="caps-toolbar">
                    <SfxButton size="sm" variant="primary" :loading="saving === 'caps-all'"
                        @click="enableAllCoursesCaps">一键开启全部课程能力
                    </SfxButton>
                </div>
                <SfxEmpty v-if="!courseCaps.length" title="暂无课程" description="平台还没有任何课程。" />
                <div v-else class="sfx-table-wrap">
                    <table class="sfx-table caps-table">
                        <thead>
                            <tr>
                                <th>课程</th>
                                <th v-for="field in CAPABILITY_FIELDS" :key="field.key" class="caps-th">{{ field.label
                                }}</th>
                                <th>操作</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="course in courseCaps" :key="course.course_id">
                                <td class="caps-title">#{{ course.course_id }} {{ course.title }}<span
                                        class="sfx-t-caption caps-status">{{ course.status }}</span></td>
                                <td v-for="field in CAPABILITY_FIELDS" :key="field.key" class="caps-td"><label
                                        class="caps-check"><input v-model="course.draft[field.key]" type="checkbox"
                                            :aria-label="field.label" /></label></td>
                                <td><span class="actions">
                                        <SfxButton size="sm" variant="secondary"
                                            :loading="saving === `caps-${course.course_id}`"
                                            @click="saveCourseCaps(course)">保存</SfxButton>
                                        <SfxButton size="sm" variant="tertiary" @click="enableAllCaps(course)">全开
                                        </SfxButton>
                                    </span></td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </section>

            <section class="sfx-panel admin-section">
                <div class="section-head">
                    <h2 class="sfx-t-title3">
                        <Cpu :size="19" /> 后台任务并发
                    </h2><span class="sfx-t-caption">开发者模式下可限制后台任务的并发数量，避免本机资源过载。</span>
                </div>
                <div class="concurrency-grid">
                    <label class="checkbox-line"><input v-model="concurrency.developer_mode" type="checkbox" />
                        开发者模式</label>
                    <label>总并发上限<input v-model.number="concurrency.max_total" class="sfx-input" type="number" min="1"
                            max="32" /></label>
                    <label>文件解析<input v-model.number="concurrency.document_parse" class="sfx-input" type="number"
                            min="1" max="32" /></label>
                    <label>课程备课<input v-model.number="concurrency.course_draft_build" class="sfx-input" type="number"
                            min="1" max="32" /></label>
                    <label>代码沙箱评测<input v-model.number="concurrency.sandbox_execution" class="sfx-input" type="number"
                            min="1" max="32" /></label>
                    <label>GraphRAG<input v-model.number="concurrency.graphrag" class="sfx-input" type="number" min="1"
                            max="32" /></label>
                    <label>向量检索索引<input v-model.number="concurrency.vector_index" class="sfx-input" type="number"
                            min="1" max="32" /></label>
                    <label class="budget-line">GraphRAG 单次输入 token 上限<input
                            v-model.number="concurrency.graphrag_max_input_tokens" class="sfx-input" type="number"
                            min="0" step="1000" /><small class="sfx-t-caption">0 = 使用服务器环境默认值；按
                            token 计，不按美元估算。</small></label>
                </div>
                <div class="section-actions">
                    <SfxButton size="sm" :loading="saving === 'task-concurrency'" @click="saveConcurrency">保存并发配置
                    </SfxButton>
                </div>
            </section>

      <section class="sfx-panel admin-section">
        <div class="section-head">
          <h2 class="sfx-t-title3"><ShieldAlert :size="19" /> 安全屏蔽词</h2>
          <span class="sfx-t-caption">平台级输入审核词库，增删改即时生效；按课程类型分流：网安课/思政课可答对应类别内容。</span>
        </div>
        <div class="keyword-tabs">
          <SfxButton v-for="tab in CATEGORY_TABS" :key="tab.value" size="sm" :variant="keywordCategory === tab.value ? 'primary' : 'tertiary'" @click="keywordCategory = tab.value; loadKeywords()">{{ tab.label }}<span v-if="tab.value" class="kw-count">{{ keywordCount(tab.value) }}</span></SfxButton>
        </div>
        <form class="keyword-add" @submit.prevent="addKeyword">
          <input v-model="keywordForm.keyword" class="sfx-input" maxlength="100" placeholder="屏蔽词（如：漏洞利用 / 台独）" />
          <select v-model="keywordForm.category" class="sfx-select">
            <option v-for="(meta, key) in CATEGORY_META" :key="key" :value="key">{{ meta.label }}</option>
          </select>
          <select v-if="keywordForm.category === 'cyber'" v-model="keywordForm.risk_level" class="sfx-select">
            <option value="medium">中风险（教学语境放行）</option>
            <option value="high">高风险（教学语境需确认）</option>
          </select>
          <input v-model="keywordForm.description" class="sfx-input" maxlength="200" placeholder="说明（可选）" />
          <SfxButton type="submit" size="sm" :loading="saving === 'keyword-add'"><Plus :size="15" /> 添加</SfxButton>
        </form>
        <div class="keyword-captions">
          <span v-for="(meta, key) in CATEGORY_META" :key="key" class="keyword-caption"><span class="kw-cat-tag" :data-cat="key">{{ meta.label }}</span>{{ meta.caption }}<span v-if="keywordDefaults[key]" class="sfx-t-caption">默认 {{ keywordDefaults[key].length }} 词</span></span>
        </div>
        <SfxEmpty v-if="!keywordItems.length" title="当前类别下没有屏蔽词" description="可通过上方表单添加；未配置的类别使用系统默认词库。" />
        <div v-else class="sfx-table-wrap">
          <table class="sfx-table"><thead><tr><th>关键词</th><th>类别</th><th>风险</th><th>状态</th><th>说明</th><th>操作</th></tr></thead>
            <tbody><tr v-for="item in keywordItems" :key="item.id">
              <td class="kw-keyword">{{ item.keyword }}</td>
              <td><span class="kw-cat-tag" :data-cat="item.category">{{ CATEGORY_META[item.category]?.label || item.category }}</span></td>
              <td><select v-if="item.category === 'cyber'" v-model="item.risk_level" class="sfx-select compact" :disabled="savingKeywordRisk === item.id" @change="updateKeywordRisk(item)"><option value="medium">中风险</option><option value="high">高风险</option></select><span v-else class="kw-risk-fixed">高</span></td>
              <td><label class="state-check"><input v-model="item.enabled" type="checkbox" :disabled="saving === `keyword-toggle-${item.id}`" @change="toggleKeyword(item)" /> {{ item.enabled ? '启用' : '停用' }}</label></td>
              <td class="sfx-t-caption">{{ item.description || '—' }}</td>
              <td><SfxButton size="sm" :variant="confirmingDelete === item.id ? 'danger' : 'tertiary'" :loading="saving === `keyword-del-${item.id}`" @click="removeKeyword(item)"><Trash2 :size="14" /> {{ confirmingDelete === item.id ? '确认删除' : '删除' }}</SfxButton></td>
            </tr></tbody>
          </table>
        </div>
      </section>

      <section class="sfx-panel admin-section">
        <div class="section-head"><h2 class="sfx-t-title3"><SlidersHorizontal :size="19" /> Provider 配置</h2><span class="sfx-t-caption">密钥仅显示配置状态；留空保存会保留旧密钥。</span></div>
        <div class="provider-grid"><article v-for="item in integrations" :key="item.integration_key" class="provider-card"><header>
            <h3>{{ item.integration_key.toUpperCase() }}<span v-if="['llm', 'tts', 'asr'].includes(item.integration_key)" class="toggle-caption">{{ item.enabled ? '真实接入' : '已关闭' }}</span></h3>
            <span class="card-actions"><span class="health" :data-status="item.health_status">{{ item.health_status || 'not_configured' }}</span>
              <SfxButton v-if="['llm', 'tts', 'asr'].includes(item.integration_key)" size="sm" :variant="item.enabled ? 'secondary' : 'primary'" :loading="saving === `toggle-${item.integration_key}`" @click="toggleIntegration(item)">{{ item.enabled ? '关闭真实接入' : '开启真实接入' }}</SfxButton>
            </span>
          </header>
          <label>Provider<input v-model="drafts[item.integration_key].provider" class="sfx-input" placeholder="openai / volcengine / xfyun" /></label>
          <label>Base URL<input v-model="drafts[item.integration_key].base_url" class="sfx-input" placeholder="https://…" /></label>
          <label>Model Name<input v-model="drafts[item.integration_key].model_name" class="sfx-input" placeholder="模型或端点名称" /></label>
          <label>API Key<input v-model="drafts[item.integration_key].api_key" class="sfx-input" type="password" :placeholder="item.key_configured ? `已配置（末四位 ${item.key_last4 || '****'}）` : '输入新密钥'" /></label>
          <label class="checkbox-line"><input v-model="drafts[item.integration_key].enabled" type="checkbox" /> 保存后启用该 Provider</label>
          <details><summary>高级配置（JSON）</summary><textarea v-model="drafts[item.integration_key].extra_config" class="sfx-input json-input" rows="4" /></details>
          <footer><SfxButton size="sm" :loading="saving === `integration-${item.integration_key}`" @click="saveIntegration(item)">保存并热刷新</SfxButton><SfxButton size="sm" variant="secondary" :loading="saving === `probe-${item.integration_key}`" @click="probe(item)">测试</SfxButton></footer>
        </article></div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.admin-page { overflow: auto; }
.sfx-page-header h1, .section-head, .provider-card header, .provider-card footer { display:flex; align-items:center; gap:var(--space-2); }
.actions, .password-row-actions { display:flex; align-items:center; gap:var(--space-2); flex-wrap:wrap; }
.section-head { justify-content:space-between; margin-bottom:var(--space-4); }.admin-section { margin-bottom:var(--space-6); padding:var(--space-6); }.filters { display:flex; flex-wrap:wrap; gap:var(--space-2); margin-bottom:var(--space-4); }.filters .sfx-input,.filters .sfx-select { min-width:150px; }
.sfx-table-wrap { overflow-x:auto; }.compact { min-width:110px; max-width:160px; }.state-check,.checkbox-line { display:flex; align-items:center; gap:var(--space-2); }.password-row td { white-space:normal; background:var(--surface-cool); }.password-row .sfx-input { max-width:300px; }
.provider-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:var(--space-4); }.provider-card { display:grid; gap:var(--space-3); padding:var(--space-4); border:1px solid var(--border-default); background:var(--surface-panel); }.provider-card header { justify-content:space-between; }.provider-card h3 { margin:0; display:flex; align-items:center; gap:var(--space-2); }.card-actions { display:flex; align-items:center; gap:var(--space-2); }.toggle-caption { font-size:var(--caption-size); font-weight:400; color:var(--text-secondary); background:var(--surface-cool); padding:1px 8px; border-radius:999px; }.provider-card label { display:grid; gap:var(--space-1); font-size:var(--ui-sm-size); color:var(--text-secondary); }.provider-card footer { justify-content:flex-end; flex-wrap:wrap; }.health { padding:2px 8px; border-radius:999px; background:var(--amber-100); color:var(--amber-700); font-size:var(--caption-size); }.health[data-status="healthy"],.health[data-status="reachable"],.health[data-status="configured"] { background:var(--green-100); color:var(--green-700); }.health[data-status="unavailable"],.health[data-status="not_configured"] { background:var(--red-100); color:var(--red-700); }.health[data-status="disabled"] { background:var(--surface-cool); color:var(--text-secondary); }.json-input { font-family:var(--font-mono,monospace); resize:vertical; }
.concurrency-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:var(--space-4); align-items:end; }.concurrency-grid label { display:grid; gap:var(--space-1); font-size:var(--ui-sm-size); color:var(--text-secondary); }.concurrency-grid .budget-line { grid-column:1/-1; }.section-actions { display:flex; justify-content:flex-end; margin-top:var(--space-4); }
.caps-toolbar { display:flex; justify-content:flex-start; margin-bottom:var(--space-4); }
.caps-table { min-width:760px; }.caps-th { text-align:center; white-space:nowrap; }.caps-td { text-align:center; }.caps-check { display:inline-flex; align-items:center; justify-content:center; cursor:pointer; }.caps-check input { width:16px; height:16px; accent-color:var(--ink-700); }.caps-title { white-space:nowrap; }.caps-status { margin-left:var(--space-2); padding:1px 6px; border-radius:999px; background:var(--surface-cool); }
.keyword-tabs { display:flex; flex-wrap:wrap; gap:var(--space-2); margin-bottom:var(--space-4); }.kw-count { margin-left:var(--space-1); padding:0 6px; border-radius:999px; background:var(--surface-cool); font-size:var(--caption-size); }
.keyword-add { display:flex; flex-wrap:wrap; gap:var(--space-2); margin-bottom:var(--space-4); }.keyword-add .sfx-input { min-width:180px; flex:1 1 160px; }.keyword-add .sfx-select { min-width:150px; }
.keyword-captions { display:flex; flex-direction:column; gap:var(--space-1); margin-bottom:var(--space-4); }.keyword-caption { display:flex; align-items:center; gap:var(--space-2); font-size:var(--ui-sm-size); color:var(--text-secondary); }
.kw-cat-tag { display:inline-flex; align-items:center; padding:1px 8px; border-radius:999px; background:var(--surface-cool); font-size:var(--caption-size); white-space:nowrap; }.kw-cat-tag[data-cat="cyber"] { background:var(--blue-100); color:var(--blue-700); }.kw-cat-tag[data-cat="political_high_risk"] { background:var(--red-100); color:var(--red-700); }.kw-cat-tag[data-cat="political_topic"] { background:var(--amber-100); color:var(--amber-700); }
.kw-keyword { font-weight:500; white-space:nowrap; }.kw-risk-fixed { font-size:var(--caption-size); color:var(--text-secondary); }
</style>
