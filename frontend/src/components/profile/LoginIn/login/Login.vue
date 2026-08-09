<script setup>
import { computed, reactive, ref, watch } from 'vue'
import {
  ArrowRight,
  BookOpenCheck,
  Check,
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  Sparkles,
  UserRound,
} from 'lucide-vue-next'

const props = defineProps({
  loading: {
    type: Boolean,
    default: false,
  },
  serverError: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['loginSend', 'registerSend'])

const isLoginMode = ref(true)
const showPassword = ref(false)
const showConfirmPassword = ref(false)
const form = reactive({
  username: '',
  password: '',
  confirmPassword: '',
})
const errors = reactive({
  username: '',
  password: '',
  confirmPassword: '',
})

const title = computed(() => (isLoginMode.value ? '登录工作空间' : '创建工作空间账号'))
const description = computed(() => (
  isLoginMode.value
    ? '继续管理课程材料、教学草稿与已发布版本。'
    : '创建账号后即可开始建立第一门课程。'
))
const submitLabel = computed(() => (isLoginMode.value ? '登录并继续' : '创建账号'))
const identityLabel = computed(() => (isLoginMode.value ? '用户名或用户 ID' : '用户名'))
const identityPlaceholder = computed(() => (isLoginMode.value ? '请输入用户名或数字 ID' : '3-50 位英文、数字或 . _ -'))
const identityHint = computed(() => (isLoginMode.value ? '可使用用户名或数字 ID 登录。' : '用户名支持 3-50 位英文、数字或 . _ -。'))
const passwordHint = computed(() => (isLoginMode.value ? '请输入账户密码。' : '密码长度为 8-200 位。'))

function clearErrors() {
  errors.username = ''
  errors.password = ''
  errors.confirmPassword = ''
}

function switchMode(loginMode) {
  if (isLoginMode.value === loginMode || props.loading) return
  isLoginMode.value = loginMode
  form.confirmPassword = ''
  clearErrors()
}

function validate() {
  clearErrors()
  const usernameRegex = /^[a-zA-Z0-9._-]{3,50}$/

  if (!form.username) {
    errors.username = '请输入用户名。'
  } else if (!isLoginMode.value && !usernameRegex.test(form.username)) {
    errors.username = '用户名支持 3-50 位英文、数字或 . _ -。'
  }

  if (!form.password) {
    errors.password = '请输入密码。'
  } else if (!isLoginMode.value && (form.password.length < 8 || form.password.length > 200)) {
    errors.password = '密码长度需为 8-200 位。'
  }

  if (!isLoginMode.value) {
    if (!form.confirmPassword) {
      errors.confirmPassword = '请再次输入密码。'
    } else if (form.password !== form.confirmPassword) {
      errors.confirmPassword = '两次输入的密码不一致。'
    }
  }

  return !errors.username && !errors.password && !errors.confirmPassword
}

function handleSubmit() {
  if (props.loading || !validate()) return
  const credentials = { username: form.username, password: form.password }
  emit(isLoginMode.value ? 'loginSend' : 'registerSend', credentials)
}

watch(() => props.serverError, (value) => {
  if (value) clearErrors()
})
</script>

<template>
  <main class="auth-page">
    <section class="auth-introduction" aria-labelledby="auth-brand-title">
      <div class="brand-lockup">
        <div class="brand-mark" aria-hidden="true"><BookOpenCheck :size="24" /></div>
        <span>智课工作空间</span>
      </div>

      <div class="introduction-copy">
        <p class="eyebrow"><Sparkles :size="15" /> Evidence-driven teaching</p>
        <h1 id="auth-brand-title">让课程回应学习</h1>
        <p>
          从材料解析到课程发布，在同一个可追溯的教学工作空间中完成。
        </p>
      </div>

      <ol class="workflow" aria-label="课程建设流程">
        <li>
          <span class="workflow-index">01</span>
          <div><strong>汇集材料</strong><small>保留原文、版本与解析证据</small></div>
        </li>
        <li>
          <span class="workflow-index">02</span>
          <div><strong>组织教学</strong><small>审核课程结构、讲稿与知识关联</small></div>
        </li>
        <li>
          <span class="workflow-index">03</span>
          <div><strong>正式发布</strong><small>让学生只读取教师确认的课程版本</small></div>
        </li>
      </ol>

      <p class="introduction-note">
        <Check :size="16" /> AI 建议始终保留来源，教师始终拥有最终决定权。
      </p>
    </section>

    <section class="auth-panel" aria-labelledby="auth-form-title">
      <div class="auth-panel__inner">
        <header class="auth-heading">
          <p class="auth-heading__label">课程建设入口</p>
          <h2 id="auth-form-title">{{ title }}</h2>
          <p>{{ description }}</p>
        </header>

        <div class="mode-switch" role="tablist" aria-label="身份验证方式">
          <button
            id="login-tab"
            type="button"
            role="tab"
            :aria-selected="isLoginMode"
            :class="{ active: isLoginMode }"
            :disabled="loading"
            @click="switchMode(true)"
          >
            登录
          </button>
          <button
            id="register-tab"
            type="button"
            role="tab"
            :aria-selected="!isLoginMode"
            :class="{ active: !isLoginMode }"
            :disabled="loading"
            @click="switchMode(false)"
          >
            注册
          </button>
        </div>

        <form class="auth-form" novalidate @submit.prevent="handleSubmit">
          <p v-if="serverError" class="form-alert" role="alert">
            <KeyRound :size="17" /> {{ serverError }}
          </p>

          <div class="field-group">
            <label for="auth-username">{{ identityLabel }}</label>
            <div class="field-control" :class="{ invalid: errors.username }">
              <UserRound :size="18" aria-hidden="true" />
              <input
                id="auth-username"
                v-model.trim="form.username"
                name="username"
                autocomplete="username"
                maxlength="80"
                :placeholder="identityPlaceholder"
                :aria-invalid="Boolean(errors.username)"
                :aria-describedby="errors.username ? 'username-error' : 'username-hint'"
                @input="errors.username = ''"
              />
            </div>
            <p id="username-hint" class="field-hint">{{ identityHint }}</p>
            <p v-if="errors.username" id="username-error" class="field-error" role="alert">{{ errors.username }}</p>
          </div>

          <div class="field-group">
            <label for="auth-password">密码</label>
            <div class="field-control" :class="{ invalid: errors.password }">
              <LockKeyhole :size="18" aria-hidden="true" />
              <input
                id="auth-password"
                v-model="form.password"
                name="password"
                :type="showPassword ? 'text' : 'password'"
                autocomplete="current-password"
                maxlength="200"
                placeholder="请输入密码"
                :aria-invalid="Boolean(errors.password)"
                :aria-describedby="errors.password ? 'password-error' : 'password-hint'"
                @input="errors.password = ''"
              />
              <button
                type="button"
                class="password-toggle"
                :aria-label="showPassword ? '隐藏密码' : '显示密码'"
                @click="showPassword = !showPassword"
              >
                <EyeOff v-if="showPassword" :size="19" />
                <Eye v-else :size="19" />
              </button>
            </div>
            <p id="password-hint" class="field-hint">{{ passwordHint }}</p>
            <p v-if="errors.password" id="password-error" class="field-error" role="alert">{{ errors.password }}</p>
          </div>

          <div v-if="!isLoginMode" class="field-group">
            <label for="auth-confirm-password">确认密码</label>
            <div class="field-control" :class="{ invalid: errors.confirmPassword }">
              <LockKeyhole :size="18" aria-hidden="true" />
              <input
                id="auth-confirm-password"
                v-model="form.confirmPassword"
                name="confirm-password"
                :type="showConfirmPassword ? 'text' : 'password'"
                autocomplete="new-password"
                maxlength="200"
                placeholder="再次输入密码"
                :aria-invalid="Boolean(errors.confirmPassword)"
                :aria-describedby="errors.confirmPassword ? 'confirm-password-error' : undefined"
                @input="errors.confirmPassword = ''"
              />
              <button
                type="button"
                class="password-toggle"
                :aria-label="showConfirmPassword ? '隐藏确认密码' : '显示确认密码'"
                @click="showConfirmPassword = !showConfirmPassword"
              >
                <EyeOff v-if="showConfirmPassword" :size="19" />
                <Eye v-else :size="19" />
              </button>
            </div>
            <p v-if="errors.confirmPassword" id="confirm-password-error" class="field-error" role="alert">{{ errors.confirmPassword }}</p>
          </div>

          <button type="submit" class="submit-button" :disabled="loading">
            <LoaderCircle v-if="loading" class="is-spinning" :size="18" />
            <template v-else>{{ submitLabel }} <ArrowRight :size="18" /></template>
          </button>
        </form>

        <p class="auth-footer">
          {{ isLoginMode ? '还没有账号？' : '已有账号？' }}
          <button type="button" :disabled="loading" @click="switchMode(!isLoginMode)">
            {{ isLoginMode ? '创建账号' : '返回登录' }}
          </button>
        </p>
      </div>
    </section>
  </main>
</template>

<style scoped>
.auth-page {
  --ink-950: #101A31;
  --ink-900: #14213D;
  --ink-700: #203A5F;
  --ink-500: #355C7D;
  --ink-100: #E8EEF4;
  --surface-page: #F7F5EF;
  --surface-panel: #FFFFFF;
  --surface-cool: #F7F8FA;
  --border-default: #DDE2E8;
  --border-strong: #C9CFD8;
  --text-primary: #172033;
  --text-secondary: #4E5969;
  --text-muted: #7B8494;
  --red-700: #8B3A3A;
  --red-100: #FAEEEE;
  --font-ui: Inter, "HarmonyOS Sans SC", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(440px, 0.9fr);
  min-height: 100vh;
  background: var(--surface-page);
  color: var(--text-primary);
  font-family: var(--font-ui);
}

.auth-introduction {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 100vh;
  padding: 64px clamp(48px, 9vw, 144px);
  background: var(--ink-900);
  color: #FFFFFF;
  overflow: hidden;
}

.auth-introduction::before,
.auth-introduction::after {
  position: absolute;
  content: "";
  pointer-events: none;
}

.auth-introduction::before {
  width: min(48vw, 620px);
  height: min(48vw, 620px);
  right: -28%;
  bottom: -28%;
  border: 1px solid rgba(232, 238, 244, 0.18);
  border-radius: 50%;
  box-shadow: 0 0 0 42px rgba(232, 238, 244, 0.04), 0 0 0 84px rgba(232, 238, 244, 0.03);
}

.auth-introduction::after {
  width: 1px;
  inset: 0 auto 0 42%;
  background: rgba(232, 238, 244, 0.08);
}

.brand-lockup,
.introduction-copy,
.workflow,
.introduction-note {
  position: relative;
  z-index: 1;
}

.brand-lockup {
  position: absolute;
  top: 32px;
  left: clamp(48px, 9vw, 144px);
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.brand-mark {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  border: 1px solid rgba(232, 238, 244, 0.42);
  border-radius: 10px;
  background: rgba(232, 238, 244, 0.08);
}

.introduction-copy { max-width: 560px; }

.eyebrow,
.auth-heading__label {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 16px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}

.eyebrow { color: #C9D6E4; }
.auth-heading__label { color: var(--ink-500); }

h1,
h2,
p { margin-top: 0; }

h1 {
  max-width: 9em;
  margin-bottom: 20px;
  font-size: clamp(38px, 4.2vw, 60px);
  line-height: 1.17;
  letter-spacing: -0.04em;
}

.introduction-copy > p:last-child {
  max-width: 31em;
  margin-bottom: 44px;
  color: #D7E0EA;
  font-size: 18px;
  line-height: 1.7;
}

.workflow {
  display: grid;
  width: min(100%, 560px);
  border-top: 1px solid rgba(232, 238, 244, 0.22);
}

.workflow li {
  display: grid;
  grid-template-columns: 42px 1fr;
  gap: 16px;
  padding: 18px 0;
  border-bottom: 1px solid rgba(232, 238, 244, 0.16);
}

.workflow-index {
  color: #9CB2C7;
  font-family: "JetBrains Mono", Consolas, monospace;
  font-size: 13px;
  line-height: 21px;
}

.workflow strong,
.workflow small { display: block; }
.workflow strong { margin-bottom: 3px; font-size: 16px; font-weight: 600; }
.workflow small { color: #B7C7D6; font-size: 14px; line-height: 20px; }

.introduction-note {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  width: min(100%, 560px);
  margin: 28px 0 0;
  color: #C9D6E4;
  font-size: 14px;
  line-height: 22px;
}

.introduction-note svg { flex: 0 0 auto; margin-top: 3px; color: #A8C3A5; }

.auth-panel {
  display: grid;
  min-height: 100vh;
  place-items: center;
  padding: 48px;
  background: var(--surface-page);
}

.auth-panel__inner { width: min(100%, 420px); }

.auth-heading { margin-bottom: 32px; }
.auth-heading__label { margin-bottom: 12px; }
.auth-heading h2 { margin-bottom: 10px; color: var(--ink-950); font-size: 32px; line-height: 40px; letter-spacing: -0.025em; }
.auth-heading > p:last-child { color: var(--text-secondary); font-size: 16px; line-height: 26px; }

.mode-switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  margin-bottom: 28px;
  border-bottom: 1px solid var(--border-default);
}

.mode-switch button {
  min-height: 44px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-muted);
  font-size: 14px;
  font-weight: 600;
  transition: color 160ms ease, border-color 160ms ease;
}

.mode-switch button:hover:not(:disabled) { color: var(--ink-700); }
.mode-switch button.active { border-color: var(--ink-900); color: var(--ink-900); }

.auth-form { display: grid; gap: 20px; }

.form-alert {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 0;
  padding: 12px;
  border: 1px solid #D9A3A3;
  border-radius: 10px;
  background: var(--red-100);
  color: var(--red-700);
  font-size: 14px;
  line-height: 20px;
}

.form-alert svg { flex: 0 0 auto; margin-top: 1px; }
.field-group { display: grid; gap: 7px; }
.field-group > label { color: var(--text-primary); font-size: 14px; font-weight: 600; line-height: 20px; }

.field-control {
  display: flex;
  align-items: center;
  height: 42px;
  border: 1px solid var(--border-default);
  border-radius: 10px;
  background: var(--surface-panel);
  color: var(--text-muted);
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

.field-control:focus-within { border: 2px solid var(--ink-500); box-shadow: 0 0 0 3px var(--ink-100); }
.field-control.invalid { border-color: #B85C5C; }
.field-control > svg { flex: 0 0 auto; margin-left: 13px; }

.field-control input {
  min-width: 0;
  width: 100%;
  height: 100%;
  padding: 0 12px;
  border: 0;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  font-size: 16px;
  outline: none;
}

.field-control input::placeholder { color: var(--text-muted); }

.password-toggle {
  display: grid;
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  place-items: center;
  border: 0;
  background: transparent;
  color: var(--text-muted);
  transition: color 160ms ease, background-color 160ms ease;
}

.password-toggle:hover { color: var(--ink-700); background: var(--surface-cool); }
.field-hint,
.field-error { margin: 0; font-size: 13px; line-height: 18px; }
.field-hint { color: var(--text-muted); }
.field-error { color: var(--red-700); }

.submit-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 42px;
  margin-top: 4px;
  border: 1px solid var(--ink-900);
  border-radius: 10px;
  background: var(--ink-900);
  color: #FFFFFF;
  font-size: 14px;
  font-weight: 600;
  transition: background-color 160ms ease, transform 100ms ease;
}

.submit-button:hover:not(:disabled) { background: var(--ink-700); }
.submit-button:active:not(:disabled) { transform: translateY(1px); }
.submit-button:disabled,
.mode-switch button:disabled,
.auth-footer button:disabled { cursor: not-allowed; opacity: 0.62; }
.is-spinning { animation: spin 0.8s linear infinite; }

.auth-footer { margin: 24px 0 0; color: var(--text-secondary); font-size: 14px; line-height: 20px; text-align: center; }
.auth-footer button { padding: 0; border: 0; background: transparent; color: var(--ink-500); font-size: inherit; font-weight: 600; text-decoration: underline; text-underline-offset: 3px; }
.auth-footer button:hover:not(:disabled) { color: var(--ink-900); }

button:focus-visible,
input:focus-visible { outline: 2px solid var(--ink-500); outline-offset: 2px; }

@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 920px) {
  .auth-page { grid-template-columns: 1fr; }
  .auth-introduction { min-height: auto; padding: 32px 40px; }
  .brand-lockup { position: static; margin-bottom: 44px; }
  .introduction-copy > p:last-child { margin-bottom: 28px; }
  .workflow { display: none; }
  .introduction-note { margin-top: 22px; }
  .auth-panel { min-height: auto; padding: 48px 40px 64px; }
}

@media (max-width: 540px) {
  .auth-introduction { padding: 24px; }
  .brand-lockup { margin-bottom: 32px; }
  h1 { font-size: 34px; }
  .introduction-copy > p:last-child { margin-bottom: 0; font-size: 16px; line-height: 26px; }
  .introduction-note { display: none; }
  .auth-panel { min-height: calc(100vh - 198px); padding: 40px 24px; }
  .auth-heading { margin-bottom: 24px; }
  .auth-heading h2 { font-size: 28px; line-height: 36px; }
}
</style>
