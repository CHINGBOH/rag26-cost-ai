/**
 * locales/stores.ts — 数据库 / 存储引擎的显示元数据
 *
 * 规则：后端 / DB 使用英文 key，前端从此文件做 key → 中文展示 的映射。
 * 组件不得直接内联这些映射，统一从此处 import。
 */

/** 存储引擎 emoji + 中文显示名 */
export const STORE_DISPLAY: Record<string, { label: string; emoji: string }> = {
  postgresql:    { label: 'PostgreSQL（结构化）', emoji: '🐘' },
  postgres:      { label: 'PostgreSQL（结构化）', emoji: '🐘' },
  qdrant:        { label: 'Qdrant（向量）',        emoji: '🧭' },
  elasticsearch: { label: 'Elasticsearch（全文）', emoji: '🔎' },
  neo4j:         { label: 'Neo4j（知识图谱）',     emoji: '🕸️' },
  redis:         { label: 'Redis（缓存）',          emoji: '⚡' },
  milvus:        { label: 'Milvus（向量备选）',     emoji: '📡' },
};

/** 图表区域的用户可见标签 */
export const CHART_LABELS = {
  trendView:      '趋势图',       // 原英文：TREND VIEW
  marketPriceLine:'市场价格走势', // 原英文：Market price line
  topK:           '参考数量',     // 原英文：Top K（RAG 检索条数）
} as const;
