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
      // 最小可跑集：仅保留 retrieval-service (:8002)
      // 已删除：Node 编排 (:3001)、Go Gateway (:8080)、Go WebSocket (:8081)
      // 所有 /api/*、/health、/metrics 一律打到 retrieval-service
      '/api': {
        target: 'http://localhost:8002',
        changeOrigin: true
      },
      '/health': {
        target: 'http://localhost:8002',
        changeOrigin: true
      },
      '/metrics': {
        target: 'http://localhost:8002',
        changeOrigin: true
      }
    }
  }
});
