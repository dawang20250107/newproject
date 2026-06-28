import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: '/paikuan/',
  server: {
    proxy: {
      '/api': 'http://localhost:9000',
    },
  },
  build: {
    outDir: '../backend/frontend_dist',
    emptyOutDir: true,
    // echarts canvas renderer 单块约 600KB（仅图表路由懒加载），放宽告警阈值避免噪音
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        // 把第三方库拆成稳定的长缓存分块：业务代码每次发版变更不再带着
        // vue/router/pinia/axios 一起失效，回访用户只重下小体积的应用代码。
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('echarts') || id.includes('zrender')) return 'echarts'
          if (id.includes('html2canvas')) return 'html2canvas'
          if (/[\\/]node_modules[\\/](@vue|vue|vue-router|pinia)[\\/]/.test(id)) return 'vendor-vue'
          if (id.includes('axios')) return 'vendor-axios'
          return 'vendor'
        },
      },
    },
  },
})
