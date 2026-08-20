<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { House, BookOpen, FlaskConical, FolderOpen, Bell, ShieldCheck, UserRound, ChevronDown, LogOut, UserCircle, Menu, X } from 'lucide-vue-next'
import { useCounterStore } from '@/stores/counter.js'

const route = useRoute()
const router = useRouter()
const counter = useCounterStore()

const navItems = [
    { label: '首页', to: '/app', icon: House, exact: true },
    { label: '我的课程', to: '/app/courses/learning', icon: BookOpen, match: '/app/courses' },
    { label: '实验室', to: '/app/lab/hall', icon: FlaskConical, match: '/app/lab' },
    { label: '资源库', to: '/app/resources/files', icon: FolderOpen, match: '/app/resources' },
]

// page-design §2.1「智能体」一级空间尚无对应页面与后端能力，
// 按 §1.5「未具备能力的入口直接隐藏」不在本切片渲染。
const adminItem = computed(() =>
    counter.canManageUsers ? { label: '平台管理', to: '/app/admin', icon: ShieldCheck } : null
)

function isActive(item) {
    if (item.exact) return route.path === item.to
    return route.path.startsWith(item.match ?? item.to)
}

// 通知入口（§4.2 右侧）：进入任务中心查看待办与系统任务
function goTasks() {
    router.push('/app/tasks/todo')
}

// B2 修复：账号头像菜单（§4.2 右侧）。下拉点击外部关闭 + Esc 关闭。
const menuOpen = ref(false)
const menuRef = ref(null)

// 移动端汉堡抽屉（≤760px）：一级导航收纳为左侧滑出抽屉
const drawerOpen = ref(false)

function toggleMenu() {
    menuOpen.value = !menuOpen.value
}

function closeMenu() {
    menuOpen.value = false
}

// 路由切换自动收起抽屉，避免停留打开状态遮挡新页面
watch(() => route.path, () => { drawerOpen.value = false })

function handleDocClick(e) {
    if (menuRef.value && !menuRef.value.contains(e.target)) closeMenu()
}

function handleEsc(e) {
    if (e.key === 'Escape') closeMenu()
}

function goProfile() {
    closeMenu()
    router.push('/app/account')
}

function logout() {
    closeMenu()
    counter.clearAuth()
    router.push('/profile')
}

onMounted(() => {
    document.addEventListener('click', handleDocClick)
    document.addEventListener('keydown', handleEsc)
})

onBeforeUnmount(() => {
    document.removeEventListener('click', handleDocClick)
    document.removeEventListener('keydown', handleEsc)
})
</script>

<template>
    <header class="sfx-l1nav">
        <div class="sfx-l1nav-inner">
            <button type="button" class="sfx-l1nav-burger" aria-label="打开导航菜单" :aria-expanded="drawerOpen"
                @click="drawerOpen = true">
                <Menu :size="20" />
            </button>
            <RouterLink to="/app" class="sfx-l1nav-brand" aria-label="返回工作首页">
                <img src="@/assets/logo/logo-彩色.svg" alt="" class="sfx-l1nav-brand-logo" />
                <span class="sfx-l1nav-brand-name">SmartCarb</span>
            </RouterLink>

            <nav class="sfx-l1nav-links" aria-label="一级导航">
                <RouterLink v-for="item in navItems" :key="item.to" :to="item.to" class="sfx-l1nav-link"
                    :class="{ 'is-active': isActive(item) }">
                    <component :is="item.icon" :size="17" />
                    <span>{{ item.label }}</span>
                </RouterLink>
                <RouterLink v-if="adminItem" to="/app/admin" class="sfx-l1nav-link">
                    <component :is="adminItem.icon" :size="17" />
                    <span>{{ adminItem.label }}</span>
                </RouterLink>
            </nav>

            <div ref="menuRef" class="sfx-l1nav-right">
                <button type="button" class="sfx-l1nav-icon-btn"
                    :class="{ 'is-active': route.path.startsWith('/app/tasks') }" aria-label="任务中心" title="任务中心"
                    @click="goTasks">
                    <Bell :size="17" />
                </button>
                <button type="button" class="sfx-l1nav-user-btn" :aria-expanded="menuOpen" aria-haspopup="menu"
                    aria-label="账号菜单" @click="toggleMenu">
                    <UserRound :size="16" />
                    <span class="sfx-l1nav-username">{{ counter.displayName || '未登录' }}</span>
                    <ChevronDown :size="14" class="sfx-l1nav-caret" :class="{ 'is-open': menuOpen }" />
                </button>
                <div v-if="menuOpen" class="sfx-l1nav-menu" role="menu">
                    <button type="button" class="sfx-l1nav-menu-item" role="menuitem" @click="goProfile">
                        <UserCircle :size="15" /> 个人资料
                    </button>
                    <button type="button" class="sfx-l1nav-menu-item is-danger" role="menuitem" @click="logout">
                        <LogOut :size="15" /> 退出登录
                    </button>
                </div>
            </div>
        </div>

        <!-- 移动端导航抽屉（≤760px 显示，一级导航收纳为左侧滑出面板） -->
        <Transition name="sfx-drawer">
            <div v-if="drawerOpen" class="sfx-l1nav-drawer-layer" @click.self="drawerOpen = false">
                <div class="sfx-l1nav-drawer-mask" @click="drawerOpen = false"></div>
                <aside class="sfx-l1nav-drawer" role="dialog" aria-modal="true" aria-label="导航菜单">
                    <div class="sfx-l1nav-drawer-head">
                        <img src="@/assets/logo/logo-彩色.svg" alt="" class="sfx-l1nav-drawer-logo" />
                        <span class="sfx-l1nav-drawer-title">SmartCarb</span>
                        <button type="button" class="sfx-l1nav-drawer-close" aria-label="关闭导航菜单" @click="drawerOpen = false">
                            <X :size="18" />
                        </button>
                    </div>
                    <nav class="sfx-l1nav-drawer-links" aria-label="导航菜单">
                        <RouterLink v-for="item in navItems" :key="item.to" :to="item.to" class="sfx-l1nav-drawer-link"
                            :class="{ 'is-active': isActive(item) }" @click="drawerOpen = false">
                            <component :is="item.icon" :size="18" />
                            <span>{{ item.label }}</span>
                        </RouterLink>
                        <RouterLink v-if="adminItem" :to="adminItem.to" class="sfx-l1nav-drawer-link"
                            :class="{ 'is-active': isActive(adminItem) }" @click="drawerOpen = false">
                            <component :is="adminItem.icon" :size="18" />
                            <span>{{ adminItem.label }}</span>
                        </RouterLink>
                    </nav>
                    <div class="sfx-l1nav-drawer-foot">
                        <button type="button" class="sfx-l1nav-drawer-foot-item" @click="goProfile">
                            <UserCircle :size="16" /> 个人资料
                        </button>
                        <button type="button" class="sfx-l1nav-drawer-foot-item is-danger" @click="logout">
                            <LogOut :size="16" /> 退出登录
                        </button>
                    </div>
                </aside>
            </div>
        </Transition>
    </header>
</template>

<style scoped>
.sfx-l1nav {
    height: var(--nav-l1-height);
    background: var(--surface-panel);
    border-bottom: 1px solid var(--border-default);
    flex-shrink: 0;
    position: relative;
    z-index: 40;
}

.sfx-l1nav-inner {
    height: 100%;
    max-width: var(--content-max-width);
    margin: 0 auto;
    padding: 0 var(--space-6);
    display: flex;
    align-items: center;
    gap: var(--space-8);
}

.sfx-l1nav-brand {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--ink-900);
    font-weight: 650;
    font-size: var(--body-md-size);
}

.sfx-l1nav-brand-logo {
    width: 24px;
    height: 24px;
    flex-shrink: 0;
    display: block;
}

/* 汉堡按钮：桌面端隐藏，≤760px 显示 */
.sfx-l1nav-burger {
    display: none;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
}

.sfx-l1nav-burger:hover {
    background: var(--surface-cool);
    color: var(--ink-700);
}

.sfx-l1nav-links {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    height: 100%;
    flex: 1;
}

.sfx-l1nav-link {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    height: 100%;
    padding: 0 var(--space-4);
    color: var(--text-secondary);
    font-size: var(--ui-md-size);
    font-weight: var(--ui-md-weight);
    transition: color var(--duration-fast) var(--ease-out);
}

.sfx-l1nav-link:hover {
    color: var(--ink-700);
}

/* 当前项：墨蓝文字 + 2px 底部状态线（design.md 4.6） */
.sfx-l1nav-link.is-active {
    color: var(--ink-900);
}

.sfx-l1nav-link.is-active::after {
    content: '';
    position: absolute;
    left: var(--space-4);
    right: var(--space-4);
    bottom: -1px;
    height: 2px;
    background: var(--ink-900);
}

.sfx-l1nav-right {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    position: relative;
}

.sfx-l1nav-icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
}

.sfx-l1nav-icon-btn:hover {
    background: var(--surface-cool);
    color: var(--ink-700);
}

.sfx-l1nav-icon-btn.is-active {
    color: var(--ink-900);
    background: var(--ink-100);
}

.sfx-l1nav-user-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    height: 36px;
    padding: 0 var(--space-3);
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    font-size: var(--ui-sm-size);
}

.sfx-l1nav-user-btn:hover {
    background: var(--surface-cool);
    color: var(--ink-700);
}

.sfx-l1nav-username {
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.sfx-l1nav-caret {
    transition: transform var(--duration-fast) var(--ease-out);
}

.sfx-l1nav-caret.is-open {
    transform: rotate(180deg);
}

.sfx-l1nav-menu {
    position: absolute;
    top: calc(100% + 4px);
    right: 0;
    min-width: 180px;
    background: var(--surface-panel);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-md);
    padding: var(--space-1);
    z-index: 50;
}

.sfx-l1nav-menu-item {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    width: 100%;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    font-size: var(--ui-sm-size);
    text-align: left;
}

.sfx-l1nav-menu-item:hover {
    background: var(--surface-cool);
}

.sfx-l1nav-menu-item.is-danger {
    color: var(--red-700);
}

.sfx-l1nav-menu-item.is-danger:hover {
    background: var(--red-100);
}

/* B4 修复：窄屏适配（§24.2）—— L1 文字隐藏只留图标，账号菜单保留 */
@media (max-width: 768px) {
    .sfx-l1nav-inner {
        gap: var(--space-3);
        padding: 0 var(--space-3);
    }

    .sfx-l1nav-brand-name {
        display: none;
    }

    .sfx-l1nav-link span {
        display: none;
    }

    .sfx-l1nav-link {
        padding: 0 var(--space-2);
    }

    .sfx-l1nav-username {
        display: none;
    }
}

/* ── 移动端导航抽屉（≤760px） ── */
@media (max-width: 760px) {
    .sfx-l1nav-burger {
        display: inline-flex;
    }

    /* 一级横向链接收纳进抽屉 */
    .sfx-l1nav-links {
        display: none;
    }
}

/* 抽屉层级：fixed 覆盖全屏，mask + 左侧面板 */
.sfx-l1nav-drawer-layer {
    position: fixed;
    inset: 0;
    z-index: 80;
}

.sfx-l1nav-drawer-mask {
    position: absolute;
    inset: 0;
    background: var(--surface-overlay);
}

.sfx-l1nav-drawer {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    width: min(var(--rail-width), 84vw);
    background: var(--surface-panel);
    box-shadow: var(--shadow-md);
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
}

.sfx-l1nav-drawer-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-4) var(--space-5);
    border-bottom: 1px solid var(--border-default);
    flex-shrink: 0;
}

.sfx-l1nav-drawer-logo {
    width: 26px;
    height: 26px;
    flex-shrink: 0;
    display: block;
}

.sfx-l1nav-drawer-title {
    flex: 1;
    font-weight: 650;
    font-size: var(--body-md-size);
    color: var(--ink-900);
}

.sfx-l1nav-drawer-close {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
}

.sfx-l1nav-drawer-close:hover {
    background: var(--surface-cool);
    color: var(--ink-700);
}

.sfx-l1nav-drawer-links {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding: var(--space-3);
    flex: 1;
}

.sfx-l1nav-drawer-link {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-height: 44px;
    padding: 0 var(--space-3);
    border-radius: var(--radius-md);
    color: var(--text-secondary);
    font-size: var(--ui-md-size);
    font-weight: var(--ui-md-weight);
}

.sfx-l1nav-drawer-link:hover {
    background: var(--surface-cool);
    color: var(--ink-700);
}

/* 当前项：墨蓝文字 + 墨蓝背景，左侧 3px 状态线（design.md 4.6/§12.5） */
.sfx-l1nav-drawer-link.is-active {
    background: var(--ink-100);
    color: var(--ink-900);
    position: relative;
}

.sfx-l1nav-drawer-link.is-active::before {
    content: '';
    position: absolute;
    left: 0;
    top: var(--space-2);
    bottom: var(--space-2);
    width: 3px;
    border-radius: var(--radius-full);
    background: var(--ink-900);
}

.sfx-l1nav-drawer-foot {
    border-top: 1px solid var(--border-default);
    padding: var(--space-3);
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    flex-shrink: 0;
}

.sfx-l1nav-drawer-foot-item {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-height: 44px;
    padding: 0 var(--space-3);
    border-radius: var(--radius-md);
    color: var(--text-primary);
    font-size: var(--ui-md-size);
    text-align: left;
}

.sfx-l1nav-drawer-foot-item:hover {
    background: var(--surface-cool);
}

.sfx-l1nav-drawer-foot-item.is-danger {
    color: var(--red-700);
}

.sfx-l1nav-drawer-foot-item.is-danger:hover {
    background: var(--red-100);
}

/* 抽屉过渡：mask 淡入淡出 + 面板左侧滑入 */
.sfx-drawer-enter-active,
.sfx-drawer-leave-active {
    transition: opacity var(--duration-normal) var(--ease-out);
}

.sfx-drawer-enter-active .sfx-l1nav-drawer,
.sfx-drawer-leave-active .sfx-l1nav-drawer {
    transition: transform var(--duration-normal) var(--ease-out);
}

.sfx-drawer-enter-from,
.sfx-drawer-leave-to {
    opacity: 0;
}

.sfx-drawer-enter-from .sfx-l1nav-drawer,
.sfx-drawer-leave-to .sfx-l1nav-drawer {
    transform: translateX(-100%);
}
</style>
