# Stage 1: build
FROM node:20-alpine AS builder
WORKDIR /app

# Copy workspace root manifests so npm workspaces resolve correctly
COPY package.json package-lock.json ./
COPY packages/shared/package.json ./packages/shared/
COPY src/frontend/web/package.json ./src/frontend/web/

# Install all workspace deps
RUN npm ci --ignore-scripts

# Copy shared package source and build it first (web depends on @rag/shared)
COPY packages/shared/ ./packages/shared/
RUN cd packages/shared && npm run build

# Copy frontend source
COPY src/frontend/web/ ./src/frontend/web/

# Build the React app
WORKDIR /app/src/frontend/web
RUN npm run build

# Stage 2: serve with nginx
FROM nginx:1.27-alpine
COPY --from=builder /app/src/frontend/web/dist /usr/share/nginx/html
COPY src/frontend/web/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
