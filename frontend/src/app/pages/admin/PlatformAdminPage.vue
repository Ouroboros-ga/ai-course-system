<script setup>
import { onMounted, reactive, ref } from 'vue'
import { RefreshCw, ShieldCheck, SlidersHorizontal, UsersRound, Cpu } from 'lucide-vue-next'
import { getAdminUsers, getIntegrations, getTaskConcurrency, resetAdminPassword, testIntegration, updateAdminUser, updateIntegration, updateTaskConcurrency } from '@/api/admin_platform.js'
import { showToast } from '@/utils/toast.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

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
const concurrency = reactive({ developer_mode: false, max_total: 1, document_parse: 1, course_draft_build: 1, graphrag: 1, vector_index: 1, sandbox_execution: 1 })

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
    const [userResult, integrationResult, concurrencyResult] = await Promise.all([getAdminUsers({ page: page.value, page_size: 20 }), getIntegrations(), getTaskConcurrency()])
    users.value = userResult.items || []
    total.value = userResult.total || 0
    integrations.value = integrationResult.items || []
    integrations.value.forEach(item => { drafts[item.integration_key] = integrationDraft(item) })
    Object.assign(concurrency, concurrencyResult || {})
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
    showToast(`连通性检查：${result.status}`, result.status === 'reachable' ? 'success' : 'warning')
  } catch (caught) {
    showToast(caught?.message || 'Provider 不可用', 'error')
  } finally { saving.value = '' }
}

onMounted(load)
</script>

<template>
  <div class="sfx-page admin-page">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1"><ShieldCheck :size="25" /> 平台管理</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">管理平台用户账号与系统配置；课程内的教学角色由各课程单独授权。</p>
      </div>
      <SfxButton variant="secondary" size="sm" :disabled="loading" @click="load"><RefreshCw :size="15" /> 刷新</SfxButton>
    </header>

    <SfxSkeleton v-if="loading" :lines="8" block />
    <SfxError v-else-if="error" :description="error" @retry="load" />
    <template v-else>
      <section class="sfx-panel admin-section">
        <div class="section-head"><h2 class="sfx-t-title3"><UsersRound :size="19" /> 用户管理</h2><span class="sfx-t-caption">{{ total }} 个账号</span></div>
        <form class="filters" @submit.prevent="page = 1; loadUsers()">
          <input v-model="filters.user_id" class="sfx-input" inputmode="numeric" placeholder="用户 ID" />
          <input v-model="filters.query" class="sfx-input" placeholder="用户名搜索" />
          <select v-model="filters.role" class="sfx-select"><option value="">全部角色</option><option value="user">用户</option><option value="admin">管理员</option></select>
          <select v-model="filters.is_active" class="sfx-select"><option value="">全部状态</option><option value="true">启用</option><option value="false">停用</option></select>
          <SfxButton type="submit" size="sm" variant="secondary">筛选</SfxButton>
        </form>
        <SfxEmpty v-if="!users.length" title="没有匹配账号" description="调整搜索条件后再试。" />
        <div v-else class="sfx-table-wrap">
          <table class="sfx-table"><thead><tr><th>ID</th><th>用户名</th><th>角色</th><th>状态</th><th>操作</th></tr></thead>
            <tbody><template v-for="user in users" :key="user.id"><tr><td>{{ user.id }}</td>
              <td><input v-model="user.username" class="sfx-input compact" maxlength="50" aria-label="用户名" /></td>
              <td><select v-model="user.role" class="sfx-select compact"><option value="user">用户</option><option value="admin">管理员</option></select></td>
              <td><label class="state-check"><input v-model="user.is_active" type="checkbox" /> {{ user.is_active ? '启用' : '停用' }}</label></td>
              <td><span class="actions"><SfxButton size="sm" variant="secondary" :loading="saving === `user-${user.id}`" @click="saveUser(user)">保存</SfxButton><SfxButton size="sm" variant="tertiary" @click="passwordFor = user.id; password = ''">重置密码</SfxButton></span></td></tr>
              <tr v-if="passwordFor === user.id" class="password-row"><td colspan="5"><span class="password-row-actions"><input v-model="password" class="sfx-input" type="password" autocomplete="new-password" placeholder="输入至少 8 位的新密码" /><SfxButton size="sm" :loading="saving === `password-${user.id}`" @click="setPassword(user)">确认重置</SfxButton><SfxButton size="sm" variant="tertiary" @click="passwordFor = null">取消</SfxButton></span></td></tr></template>
            </tbody>
          </table>
        </div>
      </section>

      <section class="sfx-panel admin-section">
        <div class="section-head"><h2 class="sfx-t-title3"><Cpu :size="19" /> 后台任务并发</h2><span class="sfx-t-caption">开发者模式下可限制后台任务的并发数量，避免本机资源过载。</span></div>
        <div class="concurrency-grid">
          <label class="checkbox-line"><input v-model="concurrency.developer_mode" type="checkbox" /> 开发者模式</label>
          <label>总并发上限<input v-model.number="concurrency.max_total" class="sfx-input" type="number" min="1" max="32" /></label>
          <label>文件解析<input v-model.number="concurrency.document_parse" class="sfx-input" type="number" min="1" max="32" /></label>
          <label>课程备课<input v-model.number="concurrency.course_draft_build" class="sfx-input" type="number" min="1" max="32" /></label>
          <label>代码沙箱评测<input v-model.number="concurrency.sandbox_execution" class="sfx-input" type="number" min="1" max="32" /></label>
          <label>GraphRAG<input v-model.number="concurrency.graphrag" class="sfx-input" type="number" min="1" max="32" /></label>
          <label>向量检索索引<input v-model.number="concurrency.vector_index" class="sfx-input" type="number" min="1" max="32" /></label>
        </div>
        <div class="section-actions"><SfxButton size="sm" :loading="saving === 'task-concurrency'" @click="saveConcurrency">保存并发配置</SfxButton></div>
      </section>

      <section class="sfx-panel admin-section">
        <div class="section-head"><h2 class="sfx-t-title3"><SlidersHorizontal :size="19" /> Provider 配置</h2><span class="sfx-t-caption">密钥仅显示配置状态；留空保存会保留旧密钥。</span></div>
        <div class="provider-grid"><article v-for="item in integrations" :key="item.integration_key" class="provider-card"><header><h3>{{ item.integration_key.toUpperCase() }}</h3><span class="health" :data-status="item.health_status">{{ item.health_status || 'not_configured' }}</span></header>
          <label>Provider<input v-model="drafts[item.integration_key].provider" class="sfx-input" placeholder="openai / volcengine / xfyun" /></label>
          <label>Base URL<input v-model="drafts[item.integration_key].base_url" class="sfx-input" placeholder="https://…" /></label>
          <label>Model Name<input v-model="drafts[item.integration_key].model_name" class="sfx-input" placeholder="模型或端点名称" /></label>
          <label>API Key<input v-model="drafts[item.integration_key].api_key" class="sfx-input" type="password" :placeholder="item.key_configured ? `已配置（末四位 ${item.key_last4 || '****'}）` : '输入新密钥'" /></label>
          <label class="checkbox-line"><input v-model="drafts[item.integration_key].enabled" type="checkbox" /> 启用该 Provider</label>
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
.provider-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:var(--space-4); }.provider-card { display:grid; gap:var(--space-3); padding:var(--space-4); border:1px solid var(--border-default); background:var(--surface-panel); }.provider-card header { justify-content:space-between; }.provider-card h3 { margin:0; }.provider-card label { display:grid; gap:var(--space-1); font-size:var(--ui-sm-size); color:var(--text-secondary); }.provider-card footer { justify-content:flex-end; flex-wrap:wrap; }.health { padding:2px 8px; border-radius:999px; background:var(--amber-100); color:var(--amber-700); font-size:var(--caption-size); }.health[data-status="healthy"],.health[data-status="reachable"],.health[data-status="configured"] { background:var(--green-100); color:var(--green-700); }.health[data-status="unavailable"],.health[data-status="not_configured"] { background:var(--red-100); color:var(--red-700); }.json-input { font-family:var(--font-mono,monospace); resize:vertical; }
.concurrency-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:var(--space-4); align-items:end; }.concurrency-grid label { display:grid; gap:var(--space-1); font-size:var(--ui-sm-size); color:var(--text-secondary); }.section-actions { display:flex; justify-content:flex-end; margin-top:var(--space-4); }
</style>
