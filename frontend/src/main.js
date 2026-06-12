import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router/index.js'
import './style.css'

// 性能模式：低配电脑滚动闪屏多由大面积毛玻璃(backdrop-filter)/动画在滚动时
// 强制 GPU 重绘导致。显式设置优先；未设置时按 CPU 核数自动判断（≤4核默认开）。
const perfPref = localStorage.getItem('pk_perf_lite')
if (perfPref === '1' || (perfPref === null && (navigator.hardwareConcurrency || 8) <= 4)) {
  document.documentElement.classList.add('perf-lite')
}

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
