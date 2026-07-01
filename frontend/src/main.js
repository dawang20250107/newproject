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

// 全局错误兜底：组件树外的异步异常（事件回调/promise）不至于静默丢失。
// 渲染期错误由 ErrorBoundary 组件就地兜底；这里仅记录，便于排查。
app.config.errorHandler = (err, _instance, info) => {
  console.error('[app error]', info, err)
}
window.addEventListener('unhandledrejection', (e) => {
  console.warn('[unhandled promise]', e.reason)
})

app.use(createPinia())
app.use(router)
app.mount('#app')

// 空闲预取最常用页面的代码块：登录后首次进入付款/审批管理近乎瞬开。
// 仅在浏览器空闲时拉取，不与首屏渲染争抢带宽。
const _idle = window.requestIdleCallback || ((cb) => setTimeout(cb, 1500))
_idle(() => {
  import('./views/Payments.vue')
  import('./views/ApprovalRecords.vue')
})
