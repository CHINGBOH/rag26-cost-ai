import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@rag/shared': path.resolve(__dirname, '../../../packages/shared/dist/index.js')
    }
  },
  server: {
    port: 3000,
    proxy: {
      // Agent API 代理到 Node.js 后端 (3001)
      '/api/agent': {
        target: 'http://localhost:3001',
        changeOrigin: true
      },
      // 搜索 API 代理到 Python 后端 (8000)
      '/api/search': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/api/v1': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      // 所有 API 和 health 请求统一代理到 Go Gateway (8080)
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true
      },
      '/health': {
        target: 'http://localhost:8080',
        changeOrigin: true
      },
      '/metrics': {
        target: 'http://localhost:8080',
        changeOrigin: true
      },
      // WebSocket 代理到 Go WebSocket Gateway (8081)
      '/ws': {
        target: 'ws://localhost:8081',
        ws: true,
        changeOrigin: true
      }
    }
  }
});
