/**
 * 后端服务名称本地化
 *
 * 原则：后端/数据库统一用英文 key，前端在这里集中翻译。
 * 组件不得内联硬编码中文服务名，统一从本文件导入。
 */

/** 服务 key → 展示图标（Emoji） */
export const SVC_ICONS: Record<string, string> = {
  go_gateway:    '🔀', // Go 反向代理网关
  retrieval:     '🔍', // 向量检索服务
  python_legacy: '🐍', // Python 旧版 API
  nodejs:        '⚙️', // Node.js 编排服务
  ocr:           '📄', // OCR 文字识别服务
  llama_server:  '🤖', // 本地大模型推理（llama.cpp / Ollama）
  postgresql:    '🐘', // PostgreSQL 关系数据库
  postgres:      '🐘', // 同上，兼容别名
  qdrant:        '🧭', // Qdrant 向量数据库
  elasticsearch: '🔎', // Elasticsearch 全文搜索
  neo4j:         '🕸️', // Neo4j 知识图谱数据库
  redis:         '⚡', // Redis 缓存与会话
  milvus:        '📡', // Milvus 备用向量数据库
};

/** 服务 key → { label（中文显示名）, port（默认端口）} */
export const SERVICE_LABELS: Record<string, { label: string; port: number }> = {
  go_gateway:    { label: 'Go 网关',      port: 8080 },
  retrieval:     { label: '检索服务',      port: 8002 },
  python_legacy: { label: 'Python (旧)',   port: 8000 },
  nodejs:        { label: 'Node 编排',     port: 3001 },
  ocr:           { label: 'OCR',           port: 8001 },
  llama_server:  { label: 'LLM',           port: 11434 },
  postgresql:    { label: 'PgSQL',         port: 5432 },
  qdrant:        { label: 'Qdrant',        port: 6333 },
  elasticsearch: { label: 'Elasticsearch', port: 9200 },
  neo4j:         { label: 'Neo4j',         port: 7474 },
  redis:         { label: 'Redis',         port: 6379 },
};

/**
 * 服务健康状态翻译
 * 后端返回英文 status，前端用此函数转为中文提示文本
 */
export function translateStatus(status: string): string {
  const map: Record<string, string> = {
    healthy:     '正常',
    degraded:    '降级',
    not_running: '未启用',
    unknown:     '未知',
    unhealthy:   '异常',
  };
  return map[status] ?? status; // 未匹配时原样显示，方便发现新状态值
}

/**
 * 服务健康状态 → CSS 类名
 * 后端英文 status 映射到样式类，集中管理避免组件内散落条件判断
 */
export function statusClass(status: string): string {
  const map: Record<string, string> = {
    healthy:     'healthy',
    degraded:    'degraded',
    not_running: 'not-running',
    unknown:     'unknown',
  };
  return map[status] ?? 'unhealthy';
}
