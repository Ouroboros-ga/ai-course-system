<script setup>
import ResourceList from '@/app/components/resources/ResourceList.vue'
</script>
<template><div class="sfx-page sfx-page--narrow"><header class="sfx-page-header"><div><h1 class="sfx-t-title1">我的文件</h1><p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">管理自己的资源；删除会进入回收站，不会静默销毁。</p></div></header><ResourceList scope="mine" /></div></template>
