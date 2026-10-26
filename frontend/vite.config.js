import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发模式下 /api 代理到 FastAPI 后端，前端代码里用同源相对路径即可，
// 不需要任何环境变量。后端端口可用 API_PROXY_TARGET 覆盖。
const API_PROXY_TARGET = process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5500,
    strictPort: false,
    proxy: {
      '/api': {
        target: API_PROXY_TARGET,
        changeOrigin: true
      }
    }
  },
  preview: {
    host: '127.0.0.1',
    port: 5500
  }
})
