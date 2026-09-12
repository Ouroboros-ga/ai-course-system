import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { navSlider } from './directives/navSlider.js'

import './styles/tokens.css'
import './styles/dark.css'
import './styles/teacher-workspace.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
// 导航选中态滑动指示器：<nav v-nav-slider>
app.directive('nav-slider', navSlider)

app.mount('#app')
