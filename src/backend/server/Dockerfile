FROM node:20-alpine AS builder

WORKDIR /app

# 切换 npm 镜像加速（国内服务器）
RUN npm config set registry https://registry.npmmirror.com

# 安装构建依赖
RUN apk add --no-cache python3 make g++

# --- 1. 构建 @rag/shared（路径需与 package.json file: 引用一致）---
COPY packages/shared/package.json ./packages/shared/package.json
RUN cd packages/shared && npm install
COPY packages/shared/ ./packages/shared/
RUN sed -i 's/"module": "ES2022"/"module": "CommonJS"/' packages/shared/tsconfig.json && \
    sed -i 's/"moduleResolution": "bundler"/"moduleResolution": "node"/' packages/shared/tsconfig.json
RUN cd packages/shared && npm run build

# --- 2. 构建 node-server ---
COPY src/backend/server/package.json ./src/backend/server/package.json
RUN cd src/backend/server && npm install
COPY src/backend/server/ ./src/backend/server/
RUN cd src/backend/server && npm run build

# --- 3. 生产镜像 ---
FROM node:20-alpine
WORKDIR /app

RUN apk add --no-cache python3

COPY --from=builder /app/packages/shared/dist ./packages/shared/dist
COPY --from=builder /app/packages/shared/package.json ./packages/shared/package.json
COPY --from=builder /app/packages/shared /packages/shared
COPY --from=builder /app/src/backend/server/dist ./src/backend/server/dist
COPY --from=builder /app/src/backend/server/config ./src/backend/server/config
COPY --from=builder /app/src/backend/server/node_modules ./src/backend/server/node_modules
COPY --from=builder /app/src/backend/server/package.json ./src/backend/server/package.json

WORKDIR /app/src/backend/server

EXPOSE 3001

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:3001/health || exit 1

CMD ["node", "dist/index.js"]
