import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import fs from 'fs';

// 开发环境下优先使用源码路径，避免必须预先构建 dist
function resolveSharedPath(): string {
  const distPath = path.resolve(__dirname, '../../../packages/shared/dist/index.js');
  const srcPath = path.resolve(__dirname, '../../../packages/shared/src/index.ts');
  return fs.existsSync(distPath) ? distPath : srcPath;
}

function getNumericEnv(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export default defineConfig(({ mode }) => {
  const repoRoot = path.resolve(__dirname, '../../..');
  const env = loadEnv(mode, repoRoot, 'VITE_');

  const webPort = getNumericEnv(env.VITE_WEB_PORT, 3000);
  const nodeUrl = env.VITE_NODE_URL || 'http://localhost:3001';
  const retrievalUrl = env.VITE_RETRIEVAL_URL || 'http://localhost:8002';
  const gatewayUrl = env.VITE_GATEWAY_URL || 'http://localhost:8080';
  const wsGatewayUrl = env.VITE_WS_GATEWAY_URL || 'ws://localhost:8081';

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@rag/shared': resolveSharedPath()
      }
    },
    server: {
      port: webPort,
      proxy: {
        // Agent API 代理到 Node.js 后端
        // TODO: 待 Gateway 补充 /api/agent 路由后可统一走 /api -> 8080
        '/api/agent': {
          target: nodeUrl,
          changeOrigin: true
        },
        // /api/v1/* 直接代理到 retrieval-service
        // Go Gateway (:8080) 与 llama-server 共用端口，开发时绕过
        '/api/v1': {
          target: retrievalUrl,
          changeOrigin: true
        },
        // 其余 /api/* 走 Go Gateway
        '/api': {
          target: gatewayUrl,
          changeOrigin: true
        },
        '/health': {
          target: gatewayUrl,
          changeOrigin: true
        },
        '/metrics': {
          target: gatewayUrl,
          changeOrigin: true
        },
        // WebSocket 代理到 Go WebSocket Gateway
        '/ws': {
          target: wsGatewayUrl,
          ws: true,
          changeOrigin: true
        }
      }
    }
  };
});
