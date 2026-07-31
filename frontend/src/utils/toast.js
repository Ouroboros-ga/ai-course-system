// utils/toast.js
// 全局轻量提示（design.md Academic Ink 风格）。
// 通过给 toast 元素挂 .sfx class 复用影子设计令牌（--ink-* / --red-* / --space-* 等）。
// 浅底深字 + 语义图标 + 左侧色条，遵循 design.md §4.7「图标+文字+颜色」状态展示约束。
let toastTimer = null

// 各类型预设：图标 SVG path（lucide 风格 24x24 stroke=2.2）+ 浅底 + 深字 + 色条
const TOAST_PRESETS = {
  success: {
    icon: 'M5 13l4 4L19 7',
    bg: 'var(--green-100)',
    fg: 'var(--green-700)',
    accent: 'var(--green-700)',
  },
  error: {
    icon: 'M18 6L6 18M6 6l12 12',
    bg: 'var(--red-100)',
    fg: 'var(--red-700)',
    accent: 'var(--red-700)',
  },
  warning: {
    icon: 'M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z',
    bg: 'var(--amber-100)',
    fg: 'var(--amber-700)',
    accent: 'var(--amber-700)',
  },
  info: {
    icon: 'M12 16v-4m0-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
    bg: 'var(--ink-100)',
    fg: 'var(--ink-700)',
    accent: 'var(--ink-700)',
  },
}

export function showToast(message, type = 'warning') {
  // 清除之前的提示
  if (toastTimer) clearTimeout(toastTimer)

  // 移除已存在的提示框
  const existingToast = document.querySelector('.custom-toast')
  if (existingToast) existingToast.remove()

  const preset = TOAST_PRESETS[type] || TOAST_PRESETS.warning

  // 创建提示元素：.sfx 让令牌作用域生效；role 由类型决定
  const toast = document.createElement('div')
  toast.className = `sfx custom-toast toast-${type}`
  toast.setAttribute('role', type === 'error' ? 'alert' : 'status')
  toast.setAttribute('aria-live', type === 'error' ? 'assertive' : 'polite')

  // 文本走 textContent，防止调用方传入的 message 触发 XSS
  toast.textContent = message

  // 内联样式（工具函数无法用 <style scoped>）
  Object.assign(toast.style, {
    position: 'fixed',
    top: '24px',
    left: '50%',
    transform: 'translateX(-50%)',
    padding: 'var(--space-3) var(--space-4)',
    background: preset.bg,
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-md)',
    fontFamily: 'var(--font-sans)',
    fontSize: 'var(--ui-md-size)',
    fontWeight: 'var(--ui-md-weight)',
    lineHeight: 'var(--ui-md-line)',
    color: 'var(--text-primary)',
    zIndex: '9999',
    maxWidth: '90vw',
    animation: 'sfxToastIn 0.24s var(--ease-out)',
  })

  document.body.appendChild(toast)

  // 3 秒后自动移除
  toastTimer = setTimeout(() => {
    toast.style.animation = 'sfxToastOut 0.24s var(--ease-out) forwards'
    setTimeout(() => toast.remove(), 240)
  }, 3000)
}

// 注入动画样式（仅一次）。Quiet Technology：120~240ms + --ease-out，无位移抖动。
if (!document.querySelector('#sfx-toast-styles')) {
  const style = document.createElement('style')
  style.id = 'sfx-toast-styles'
  style.textContent = `
    @keyframes sfxToastIn {
      from { opacity: 0; transform: translate(-50%, -12px); }
      to   { opacity: 1; transform: translate(-50%, 0); }
    }
    @keyframes sfxToastOut {
      from { opacity: 1; transform: translate(-50%, 0); }
      to   { opacity: 0; transform: translate(-50%, -12px); }
    }
    @media (prefers-reduced-motion: reduce) {
      .custom-toast { animation-duration: 0.01ms !important; }
    }
  `
  document.head.appendChild(style)
}
