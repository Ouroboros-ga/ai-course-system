import { defineAsyncComponent, h } from 'vue'

/**
 * JSAVPlayer 懒加载包装
 *
 * 使用 defineAsyncComponent 按需加载 JSAVPlayer.vue，
 * 不影响主应用和普通问答的初始加载性能。
 *
 * JSAVPlayer 内部会动态加载同源、部署锁定的 JSAV 静态资源，
 * 本包装仅负责组件代码分割（code-splitting）。
 */
const LazyJSAVPlayer = defineAsyncComponent({
  loader: () => import('./JSAVPlayer.vue'),
  loadingComponent: {
    name: 'LazyJSAVPlayerLoading',
    render() {
      return h('div', {
        class: 'jsav-player-lazy-loading',
        role: 'status',
        'aria-label': '加载可视化组件',
      }, [
        h('span', { class: 'jsav-player-lazy-loading__spinner' }),
      ])
    },
  },
  errorComponent: {
    name: 'LazyJSAVPlayerError',
    render() {
      return h('div', {
        class: 'jsav-player-lazy-loading jsav-player-lazy-loading--error',
        role: 'alert',
      }, '可视化组件加载失败')
    },
  },
  delay: 200,
  timeout: 15000,
})

export default LazyJSAVPlayer
