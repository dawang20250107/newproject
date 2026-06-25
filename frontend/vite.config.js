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
  },
})
