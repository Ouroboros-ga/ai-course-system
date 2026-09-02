<script setup>
import { onMounted, reactive, ref } from 'vue'
import { UserRound } from 'lucide-vue-next'

import { useCounterStore } from '@/stores/counter.js'
import { updateMyProfile } from '@/api/user.js'
import { showToast } from '@/utils/toast.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxField from '@/app/ui/SfxField.vue'

const counter = useCounterStore()
const profileForm = reactive({ username: '', current_password: '', new_password: '', confirm_password: '' })
const profileSaving = ref(false)
const profileError = ref('')

function syncProfileForm() {
  profileForm.username = counter.userData.username || ''
}

async function saveProfile() {
  profileError.value = ''
  const currentUsername = counter.userData.username || ''
  const usernameChanged = profileForm.username.trim() !== currentUsername
  const newPassword = (profileForm.new_password || '').trim()
  const passwordChanged = Boolean(newPassword)
  const currentPassword = (profileForm.current_password || '').trim()
  const confirmPassword = (profileForm.confirm_password || '').trim()
  const hasAnyInput = usernameChanged || passwordChanged || Boolean(currentPassword) || Boolean(confirmPassword)
  if (!hasAnyInput) return showToast('没有可保存的资料变更', 'warning')
  if (usernameChanged && !profileForm.username.trim()) return showToast('用户名不能为空', 'warning')
  if (!passwordChanged && (currentPassword || confirmPassword)) return showToast('请输入新密码', 'warning')
  if (passwordChanged && !currentPassword) return showToast('修改密码前请输入原密码', 'warning')
  if (passwordChanged && newPassword.length < 8) return showToast('新密码至少 8 位', 'warning')
  if (passwordChanged && newPassword !== confirmPassword) return showToast('两次输入的新密码不一致', 'warning')
  profileSaving.value = true
  try {
    const result = await updateMyProfile({
      username: usernameChanged ? profileForm.username.trim() : undefined,
      current_password: passwordChanged ? currentPassword : undefined,
      new_password: passwordChanged ? newPassword : undefined,
    })
    counter.setAuth({ token: result.token, userInfo: result.userInfo, role: result.userInfo.role, platform_permissions: result.userInfo.platform_permissions })
    profileForm.current_password = ''
    profileForm.new_password = ''
    profileForm.confirm_password = ''
    showToast('个人资料已更新', 'success')
  } catch (caught) {
    profileError.value = caught?.message || '个人资料更新失败'
  } finally { profileSaving.value = false }
}

onMounted(() => {
  syncProfileForm()
})
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header"><div><h1 class="sfx-t-title1"><UserRound :size="25" /> 个人中心</h1><p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">管理账户信息（数字人预设已下线，仅保留账户资料与 TTS 讲解）。</p></div></header>
    <section class="sfx-panel account-summary"><span class="sfx-t-ui">账户</span><strong>{{ counter.displayName || '—' }}</strong><span class="sfx-t-caption sfx-t-secondary">ID {{ counter.userData.id || '—' }}</span><SfxBadge tone="ink">{{ counter.userData.role || 'member' }}</SfxBadge></section>
    <section class="sfx-panel profile-settings"><h2 class="sfx-panel-title"><UserRound :size="18" /> 账户资料</h2><p class="sfx-t-ui sfx-t-secondary">账号 ID 始终不变；用户名同时用于登录、右上角显示和平台管理。</p><SfxField label="用户名"><input v-model="profileForm.username" class="sfx-input" maxlength="50" autocomplete="username" /></SfxField><div class="password-fields"><SfxField label="原密码（修改密码时必填）"><input v-model="profileForm.current_password" class="sfx-input" type="password" autocomplete="current-password" /></SfxField><SfxField label="新密码"><input v-model="profileForm.new_password" class="sfx-input" type="password" autocomplete="new-password" minlength="8" /></SfxField><SfxField label="确认新密码"><input v-model="profileForm.confirm_password" class="sfx-input" type="password" autocomplete="new-password" minlength="8" /></SfxField></div><SfxButton variant="primary" :loading="profileSaving" @click="saveProfile">保存资料</SfxButton><p v-if="profileError" class="account-error" role="alert">{{ profileError }}</p></section>
  </div>
</template>

<style scoped>
.sfx-page-header h1, .sfx-panel-title { display: flex; align-items: center; gap: var(--space-2); }
.account-summary { display: flex; align-items: center; gap: var(--space-3); }
.profile-settings { align-items: stretch; }
.password-fields { width: 100%; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-3); }
.sfx-panel { display: flex; flex-direction: column; align-items: flex-start; gap: var(--space-3); margin-bottom: var(--space-6); }
.sfx-input { width: 100%; }
.account-error { color: var(--red-700); }
@media (max-width: 720px) { .password-fields { grid-template-columns: 1fr; } }
</style>
