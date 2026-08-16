import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

import avatar1 from '@/assets/头像/智能体.svg'
import avatar2 from '@/assets/头像/螃蟹娘头像.png'

export const useSettingsStore = defineStore('settings', () => {
    // ----- 头像设置 -----
    // 当前选中的头像编号（0 ~ 3）
    const avatarIndex = ref(0)

    // 头像路径列表（顺序对应编号 0,1,2,3）
    const avatarPaths = ref([
        avatar1,
        avatar2,
    ])

    // 当前头像的完整路径（计算属性）
    const currentAvatarPath = computed(() => {
        const idx = avatarIndex.value
        const paths = avatarPaths.value
        return (idx >= 0 && idx < paths.length) ? paths[idx] : paths[0]
    })

    // ----- 操作函数 -----
    // 切换到下一个头像（循环：3 → 0，0 → 1 ……）
    function nextAvatar() {
        const total = avatarPaths.value.length
        avatarIndex.value = (avatarIndex.value + 1) % total
        saveSettings() // 自动保存
    }

    // 直接设置头像编号（0 ~ 3）
    function setAvatarIndex(index) {
        const total = avatarPaths.value.length
        if (index >= 0 && index < total) {
            avatarIndex.value = index
            saveSettings()
        }
    }

    // ----- 持久化（localStorage）-----
    function loadSettings() {
        const saved = localStorage.getItem('avatarIndex')
        if (saved !== null) {
            const idx = parseInt(saved, 10)
            const total = avatarPaths.value.length
            if (!isNaN(idx) && idx >= 0 && idx < total) {
                avatarIndex.value = idx
            }
        }
    }

    function saveSettings() {
        localStorage.setItem('avatarIndex', String(avatarIndex.value))
    }

    // 初始化时加载保存的设置
    loadSettings()

    // 返回所有状态和方法
    return {
        avatarIndex,          // 当前编号（ref）
        avatarPaths,          // 路径列表（ref）
        currentAvatarPath,    // 当前路径（computed）
        nextAvatar,           // 切换至下一个
        setAvatarIndex,       // 设置指定编号
        loadSettings,         // 重新加载设置（如需要）
        saveSettings          // 手动保存（一般自动调用）
    }
})