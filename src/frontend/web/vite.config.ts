import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import fs from 'fs';

// 开发环境下优先使用源码路径，避免必须预先构建 dist
function resolveSharedPath(): string {
  const distPath = path.resolve(__dirname, '../../../packages/shared/dist/index.js');
  const srcPath = path.resolve(__dirname, '../../../packages/shared/src/index.ts');
  return fs.existsSync(distPath) ? distPath : srcPath;
}

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@rag/shared': resolveSharedPath()
    }
  },
  server: {
    port: 3000,
    proxy: {
      // Agent API 代理到 Node.js 后端 (3001)
      // TODO: 待 Gateway 补充 /api/agent 路由后可统一走 /api -> 8080
      '/api/agent': {
        target: 'http://localhost:3001',
        changeOrigin: true
      },
      // /api/v1/* 直接代理到 retrieval-service (:8002)
      // Go Gateway (:8080) 与 llama-server 共用端口，开发时绕过
      '/api/v1': {
        target: 'http://localhost:8002',
        changeOrigin: true
      },
      // 其余 /api/* 尝试走 Go Gateway（生产用）
      '/api': {
        target: 'http://localhost:8090',
        changeOrigin: true
      },
      '/health': {
        target: 'http://localhost:8090',
        changeOrigin: true
      },
      '/metrics': {
        target: 'http://localhost:8090',
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
