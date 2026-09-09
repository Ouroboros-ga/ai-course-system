/**
 * v-nav-slider —— 导航选中态「滑动指示器」指令。
 *
 * 在导航容器内自动生成一个指示器元素，测量当前选中项的位置与尺寸，
 * 用 transform + width/height 过渡实现「滑动到新选中项」的动画效果。
 * 适用于横向顶部导航、纵向侧栏/抽屉、以及胶囊式选中背景。
 *
 * 用法：
 *   <nav v-nav-slider>…</nav>
 *   <nav v-nav-slider="{ axis: 'y', variant: 'pill' }">…</nav>
 *
 * 选项：
 *   axis        'x'（默认，横向）| 'y'（纵向）
 *   variant     'line'（默认，指示线/条）| 'pill'（胶囊背景，置于内容之下）
 *   activeClass 选中项类名，默认 'is-active'（BuildLayout 等用 'active'）
 *   thickness   线形厚度(px)，横向默认 2、纵向默认 3
 *   inset       线形两端内缩(px)，默认 0
 *
 * 实现要点：
 * - 用 getBoundingClientRect 差值定位，不依赖 offsetParent，天然支持滚动容器；
 * - MutationObserver 监听 class/子节点变化（路由切换即触发），首帧不做动画避免「从 0 飞入」；
 * - ResizeObserver + window resize 处理宽度变化；容器滚动时同步（纵向 rail 常见）；
 * - 尊重 prefers-reduced-motion；容器隐藏时指示器自动隐藏。
 */
const STYLE_ID = 'sfx-nav-slider-style'
const state = new WeakMap()

const GLOBAL_CSS = `
.sfx-nav-slider {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
  opacity: 0;
  background: var(--ink-900, #1f2a37);
  border-radius: var(--radius-full, 999px);
  transition:
    transform var(--duration-normal, 200ms) var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1)),
    width var(--duration-normal, 200ms) var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1)),
    height var(--duration-normal, 200ms) var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1)),
    opacity var(--duration-fast, 120ms) var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1));
  will-change: transform, width, height;
}
.sfx-nav-slider[data-variant='pill'] {
  background: var(--ink-100, #eef2f6);
  border-radius: var(--radius-md, 8px);
  z-index: 0;
}
.sfx-nav-slider.is-instant { transition: none; }
@media (prefers-reduced-motion: reduce) {
  .sfx-nav-slider { transition: none; }
}
`

function ensureGlobalStyle() {
  if (typeof document === 'undefined') return
  if (document.getElementById(STYLE_ID)) return
  const style = document.createElement('style')
  style.id = STYLE_ID
  style.textContent = GLOBAL_CSS
  document.head.appendChild(style)
}

function scheduleSync(el, instant = false) {
  const st = state.get(el)
  if (!st) return
  if (instant) st.pendingInstant = true
  if (st.raf) return
  st.raf = requestAnimationFrame(() => {
    st.raf = 0
    sync(el, st.pendingInstant)
    st.pendingInstant = false
  })
}

function sync(el, instant = false) {
  const st = state.get(el)
  if (!st || !st.el || !st.indicator) return
  const { activeClass, axis, variant, thickness, inset } = st
  const slider = st.indicator

  const active = el.querySelector('.' + activeClass)
  if (!active) {
    slider.style.opacity = '0'
    return
  }
  // inset: 'padding' —— 指示线内缩选中项的内边距，视觉上与原 ::after
  // 「left/right: var(--space-4)」保持一致
  let pad = inset
  if (inset === 'padding' || inset === 'auto') {
    const cs = getComputedStyle(active)
    pad = parseFloat(cs.paddingLeft) || 0
  }
  const rect = active.getBoundingClientRect()
  const host = el.getBoundingClientRect()
  // 容器不可见（如移动端导航被 display:none）时不做定位，避免残留错位
  if (!rect.width || !rect.height || !host.width) {
    slider.style.opacity = '0'
    return
  }

  const x = rect.left - host.left + el.scrollLeft
  const y = rect.top - host.top + el.scrollTop

  if (instant) slider.classList.add('is-instant')

  if (variant === 'pill') {
    slider.style.width = `${rect.width}px`
    slider.style.height = `${rect.height}px`
    slider.style.transform = `translate3d(${x}px, ${y}px, 0)`
  } else if (axis === 'y') {
    slider.style.width = `${thickness}px`
    slider.style.height = `${Math.max(0, rect.height - pad * 2)}px`
    slider.style.transform = `translate3d(${x}px, ${y + pad}px, 0)`
  } else {
    slider.style.width = `${Math.max(0, rect.width - pad * 2)}px`
    slider.style.height = `${thickness}px`
    // 全局样式固定了 top:0；横向指示线必须显式解除 top，否则 top/bottom 同时
    // 指定且高度确定时 bottom 被忽略，指示线会跑到导航顶部（实测回归）。
    slider.style.top = 'auto'
    // -1px 压住导航容器的 1px 底边框，与原 ::after 的视觉一致
    slider.style.bottom = '-1px'
    slider.style.transform = `translate3d(${x + pad}px, 0, 0)`
  }
  slider.style.opacity = '1'

  if (instant) {
    // 强制回流后再恢复过渡，确保首帧是「就位」而不是「滑入」
    void slider.offsetWidth
    slider.classList.remove('is-instant')
  }
}

function setup(el, options = {}) {
  ensureGlobalStyle()
  if (getComputedStyle(el).position === 'static') el.style.position = 'relative'

  const axis = options.axis === 'y' ? 'y' : 'x'
  const variant = options.variant === 'pill' ? 'pill' : 'line'
  const activeClass = options.activeClass || 'is-active'
  const thickness = Number.isFinite(options.thickness)
    ? options.thickness
    : (variant === 'pill' ? 0 : axis === 'y' ? 3 : 2)
  const inset = options.inset === 'padding' || options.inset === 'auto'
    ? options.inset
    : (Number.isFinite(options.inset) ? options.inset : 0)

  const indicator = document.createElement('span')
  indicator.className = 'sfx-nav-slider'
  indicator.dataset.variant = variant
  indicator.dataset.axis = axis
  indicator.setAttribute('aria-hidden', 'true')
  // 胶囊在内容之下（首个子元素），指示线浮在底部（追加即可，2-3px 不遮文字）
  if (variant === 'pill' && el.firstChild) el.insertBefore(indicator, el.firstChild)
  else el.appendChild(indicator)

  const st = {
    el,
    indicator,
    axis,
    variant,
    activeClass,
    thickness,
    inset,
    raf: 0,
    pendingInstant: true,
    mo: null,
    ro: null,
    onResize: null,
    onScroll: null,
  }
  state.set(el, st)

  // 忽略指示器自身样式变更引起的回调，避免 sync → 改样式 → 再 sync 的空转
  st.mo = new MutationObserver((records) => {
    if (records.every((r) => r.target === indicator)) return
    scheduleSync(el)
  })
  st.mo.observe(el, { subtree: true, childList: true, attributes: true, attributeFilter: ['class'] })

  if (typeof ResizeObserver !== 'undefined') {
    st.ro = new ResizeObserver(() => scheduleSync(el, true))
    st.ro.observe(el)
  }
  st.onResize = () => scheduleSync(el, true)
  st.onScroll = () => scheduleSync(el, true)
  window.addEventListener('resize', st.onResize)
  el.addEventListener('scroll', st.onScroll, { passive: true })

  scheduleSync(el, true)
}

function teardown(el) {
  const st = state.get(el)
  if (!st) return
  st.mo?.disconnect()
  st.ro?.disconnect()
  if (st.onResize) window.removeEventListener('resize', st.onResize)
  if (st.onScroll) el.removeEventListener('scroll', st.onScroll)
  if (st.raf) cancelAnimationFrame(st.raf)
  st.indicator?.remove()
  state.delete(el)
}

export const navSlider = {
  mounted(el, binding) {
    setup(el, binding.value || {})
  },
  updated(el, binding) {
    // 选项或列表变化时重新就位；class 变化由 MutationObserver 兜底
    scheduleSync(el)
    void binding
  },
  unmounted(el) {
    teardown(el)
  },
}

export default navSlider
