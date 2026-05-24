import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: '/caiwu/',
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://localhost:9000',
    },
  },
  build: {
    outDir: '../backend/caiwu_frontend_dist',
    emptyOutDir: true,
  },
})
