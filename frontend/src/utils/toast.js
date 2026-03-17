// utils/toast.js
let toastTimer = null

export function showToast(message, type = 'warning') {
  // 清除之前的提示
  if (toastTimer) {
    clearTimeout(toastTimer)
  }

  // 移除已存在的提示框
  const existingToast = document.querySelector('.custom-toast')
  if (existingToast) {
    existingToast.remove()
  }

  // 创建提示元素
  const toast = document.createElement('div')
  toast.className = `custom-toast toast-${type}`
  toast.textContent = message

  // 设置样式
  Object.assign(toast.style, {
    position: 'fixed',
    top: '20%',
    left: '50%',
    transform: 'translateX(-50%)',
    padding: '12px 24px',
    borderRadius: '8px',
    color: '#fff',
    fontSize: '14px',
    fontWeight: '500',
    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
    zIndex: '9999',
    animation: 'slideDown 0.3s ease',
    maxWidth: '90%',
    textAlign: 'center'
  })

  // 根据类型设置背景色
  const colors = {
    warning: 'linear-gradient(135deg, #f59e0b, #d97706)',
    error: 'linear-gradient(135deg, #ef4444, #dc2626)',
    success: 'linear-gradient(135deg, #10b981, #059669)',
    info: 'linear-gradient(135deg, #3b82f6, #2563eb)'
  }
  toast.style.background = colors[type] || colors.warning

  // 添加到页面
  document.body.appendChild(toast)

  // 3 秒后自动移除
  toastTimer = setTimeout(() => {
    toast.style.animation = 'slideUp 0.3s ease'
    setTimeout(() => toast.remove(), 300)
  }, 3000)
}

// 添加动画样式（如果不存在）
if (!document.querySelector('#toast-styles')) {
  const style = document.createElement('style')
  style.id = 'toast-styles'
  style.textContent = `
    @keyframes slideDown {
      from { opacity: 0; transform: translate(-50%, -20px); }
      to { opacity: 1; transform: translate(-50%, 0); }
    }
    @keyframes slideUp {
      from { opacity: 1; transform: translate(-50%, 0); }
      to { opacity: 0; transform: translate(-50%, -20px); }
    }
  `
  document.head.appendChild(style)
}
