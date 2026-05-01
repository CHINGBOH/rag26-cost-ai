/**
 * 客户端文档检索 — 对 SYSTEM_DOCS 做关键词 TF 评分
 * 无需后端，纯前端实现，供 SystemAssistant 注入上下文使用。
 */

import { DocSection, SYSTEM_DOCS } from '../config/system-docs';

/**
 * 对单个段落计算查询相关度分数
 * 综合：关键词命中数 / 标题匹配 / 字段权重
 */
function scoreSection(section: DocSection, tokens: string[]): number {
  let score = 0;
  const titleLower = section.title.toLowerCase();
  const contentLower = section.content.toLowerCase();

  for (const token of tokens) {
    if (!token) continue;
    // 标题命中权重最高
    if (titleLower.includes(token)) score += 4;
    // keywords 精确匹配权重次之
    if (section.keywords.some(k => k.includes(token) || token.includes(k))) score += 3;
    // 正文命中
    const matches = (contentLower.match(new RegExp(token, 'g')) || []).length;
    score += Math.min(matches, 5); // cap at 5 to avoid keyword stuffing
  }

  return score;
}

/**
 * 对 query 分词（简单中文字符 n-gram + 空格分词）
 */
function tokenize(query: string): string[] {
  const normalized = query.toLowerCase().replace(/[，。！？、：；""''（）【】《》]/g, ' ');
  // Split on whitespace
  const words = normalized.split(/\s+/).filter(w => w.length >= 2);
  // Also add 2-gram characters for Chinese
  const chars = normalized.replace(/\s/g, '');
  const bigrams: string[] = [];
  for (let i = 0; i < chars.length - 1; i++) {
    bigrams.push(chars.slice(i, i + 2));
  }
  return [...new Set([...words, ...bigrams])];
}

/**
 * 检索最相关的文档段落，返回格式化的上下文字符串
 * @param query 用户问题
 * @param topN 最多返回几个段落（默认3）
 * @param minScore 最低分数阈值（默认2）
 */
export function retrieveDocs(query: string, topN = 3, minScore = 2): string {
  const tokens = tokenize(query);
  if (tokens.length === 0) return '';

  const scored = SYSTEM_DOCS
    .map(section => ({ section, score: scoreSection(section, tokens) }))
    .filter(({ score }) => score >= minScore)
    .sort((a, b) => b.score - a.score)
    .slice(0, topN);

  if (scored.length === 0) return '';

  return scored
    .map(({ section }) => `## ${section.title}\n${section.content}`)
    .join('\n\n---\n\n');
}
