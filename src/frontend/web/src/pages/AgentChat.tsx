/**
 * RAG 问答页 — 3-panel layout
 * Left: config | Center: chat | Right: process visualization
 */

import { useState, useRef, useEffect, useMemo } from 'react';
import { useAgent, ChatMessage, AgentConfig } from '../hooks/useAgent';
import {
  useRunStore,
  PresentationPayload,
  PresentationPoint,
  PresentationCalculationStep,
  PresentationBlock,
} from '../stores/useRunStore';
import { submitFeedback } from '../services/metricsApi';
import { evaluate } from 'mathjs';
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  Radar,
  ResponsiveContainer,
  Tooltip,
  BarChart,
  Bar,
  LabelList,
  CartesianGrid,
  XAxis,
  YAxis,
  LineChart,
  Line,
} from 'recharts';
import './AgentChat.css';

/* ── Simple Markdown Renderer ───────────────────────── */
/** Converts **bold**, `code`, and line-breaks to HTML. No external deps. */
function renderMarkdown(text: string): string {
  return text
    // bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // inline code
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // line breaks
    .replace(/\n/g, '<br />');
}

function formatPresentationValue(value?: number, unit?: string): string {
  if (value == null || Number.isNaN(value)) return '—';
  return `${value.toFixed(2)}${unit ? ` 元/${unit}` : ''}`;
}

function formatPointRange(point: PresentationPoint, unit?: string): string {
  if (
    point.min_value != null &&
    point.max_value != null &&
    Math.abs(point.max_value - point.min_value) > 0.001
  ) {
    return `${formatPresentationValue(point.min_value, unit)} - ${formatPresentationValue(point.max_value, unit)}`;
  }
  return formatPresentationValue(point.value, unit);
}

function formatSandboxNumber(value: number): string {
  if (!Number.isFinite(value)) return '计算错误';
  const rounded = Math.round(value * 1000000) / 1000000;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toString();
}

function getTrendAxisConfig(points: PresentationPoint[]): {
  domain?: [number, number];
  ticks?: number[];
} {
  const values = points.map((point) => point.value).filter((value) => Number.isFinite(value));
  if (values.length === 0) return {};

  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const valueSpan = maxValue - minValue;
  const padding = valueSpan < 0.001 ? Math.max(Math.abs(maxValue) * 0.02, 0.02) : Math.max(valueSpan * 0.6, 0.02);
  const lowerBound = Number((minValue - padding).toFixed(4));
  const upperBound = Number((maxValue + padding).toFixed(4));

  if (!Number.isFinite(lowerBound) || !Number.isFinite(upperBound) || lowerBound >= upperBound) {
    return {};
  }

  const tickCount = 4;
  const step = (upperBound - lowerBound) / (tickCount - 1);
  const ticks = Array.from({ length: tickCount }, (_, index) =>
    Number((lowerBound + step * index).toFixed(4)),
  );

  return {
    domain: [lowerBound, upperBound],
    ticks,
  };
}

function getDeltaSummary(delta?: number | null, deltaPercent?: number | null, unit?: string): string {
  if (delta == null || Number.isNaN(delta)) return '暂无变化数据';
  const amount = `${delta > 0 ? '+' : ''}${delta.toFixed(2)}${unit ? ` 元/${unit}` : ''}`;
  if (deltaPercent == null || Number.isNaN(deltaPercent)) return amount;
  return `${amount}（${deltaPercent > 0 ? '+' : ''}${deltaPercent.toFixed(2)}%）`;
}

function getTrendDirectionText(delta?: number | null): string {
  if (delta == null || Number.isNaN(delta) || Math.abs(delta) < 0.001) return '持平';
  return delta > 0 ? '上涨' : '下跌';
}

function getTrendDirectionClass(delta?: number | null): string {
  if (delta == null || Number.isNaN(delta) || Math.abs(delta) < 0.001) return 'flat';
  return delta > 0 ? 'up' : 'down';
}

function getHighlightBaseLabel(kind?: string, queryType?: string): string {
  const kindMap: Record<string, string> = {
    scope: '适用范围',
    exclusion: '不计范围',
    method: '计量方式',
    labor: '人工费',
    material: '材料费',
    machine: '机械费',
    metric: '关键数值',
    hint: '提示',
    rule: queryType === 'standard_ref' ? '规则要点' : '关键信息',
    detail: '关键信息',
  };

  return (kind && kindMap[kind]) || '关键信息';
}

function getSectionBaseLabel(kind?: string, queryType?: string): string {
  if (kind === 'analysis') {
    const labels: Record<string, string> = {
      standard_ref: '依据说明',
      price: '价格解析',
      fee_rate: '费率解析',
      formula: '公式推导',
      comparison: '对比分析',
    };
    return (queryType && labels[queryType]) || '核心说明';
  }
  return '补充说明';
}

function buildDisplayLabels(
  items: Array<{ label?: string; kind?: string }>,
  resolver: (kind?: string) => string,
): string[] {
  // Prefer LLM-supplied labels; fall back to kind-resolved label without "01/02" numbering.
  // Kept only as fallback for legacy payloads that lack `layout[]`.
  return items.map((item) => item.label?.trim() || resolver(item.kind));
}

const LayoutBlocks: React.FC<{ blocks: PresentationBlock[] }> = ({ blocks }) => {
  if (!blocks || blocks.length === 0) return null;
  return (
    <div className="answer-layout-flow">
      {blocks.map((block) => {
        const hint = block.hint || 'paragraph';
        const body = block.body || '';
        if (hint === 'list') {
          // Split bullet markers into list items so the LLM-authored list renders natively.
          const items = body
            .split(/\n+|(?:^|\s)(?:\d+[、.)]|[•▶◆■]|[-－]|\*)\s+/g)
            .map((s) => s.trim())
            .filter(Boolean);
          return (
            <div key={block.id} className={`answer-layout-block hint-${hint}`}>
              <div className="answer-layout-title">{block.title}</div>
              <ul className="answer-layout-list">
                {items.map((item, idx) => (
                  <li
                    key={`${block.id}-item-${idx}`}
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(item) }}
                  />
                ))}
              </ul>
            </div>
          );
        }
        return (
          <div key={block.id} className={`answer-layout-block hint-${hint}`}>
            {block.title && <div className="answer-layout-title">{block.title}</div>}
            <div
              className="answer-layout-body"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(body) }}
            />
          </div>
        );
      })}
    </div>
  );
};

const TrendTooltipContent: React.FC<{
  active?: boolean;
  payload?: Array<{ value?: number; payload?: { label?: string } }>;
  label?: string;
  unit?: string;
}> = ({ active, payload, label, unit }) => {
  if (!active || !payload || payload.length === 0) return null;
  const value = Number(payload[0]?.value);
  return (
    <div className="trend-tooltip-card">
      <div className="trend-tooltip-label">{label}</div>
      <div className="trend-tooltip-value">{formatPresentationValue(value, unit)}</div>
    </div>
  );
};

function normalizeSandboxExpression(expression: string): string {
  return expression
    .replace(/（/g, '(')
    .replace(/）/g, ')')
    .replace(/＋/g, '+')
    .replace(/－/g, '-')
    .replace(/×/g, '*')
    .replace(/÷/g, '/')
    .replace(/％/g, '%')
    .replace(/—|–/g, '-');
}

function sanitizeSandboxExpression(expression: string): string {
  return normalizeSandboxExpression(expression)
    .replace(/(\d+(?:\.\d+)?)\s*%/g, (_, num: string) => `${Number(num) / 100}`)
    .replace(/万元|万|元|人民币/g, '')
    .replace(/[^0-9.+\-*/() ]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function isValidSandboxExpression(expression: string): boolean {
  if (!expression || !/\d/.test(expression) || !/[+\-*/]/.test(expression)) return false;
  if (!/^[0-9.+\-*/() ]+$/.test(expression)) return false;

  let balance = 0;
  for (const char of expression) {
    if (char === '(') balance += 1;
    if (char === ')') balance -= 1;
    if (balance < 0) return false;
  }
  return balance === 0;
}

function extractSandboxExpression(step: PresentationCalculationStep): string {
  const candidates = [step.copy_expression, ...step.substituted.split(/\s*=\s*/)]
    .map((part) => sanitizeSandboxExpression(part))
    .filter((part) => isValidSandboxExpression(part));

  if (candidates.length === 0) return step.copy_expression;

  return candidates.sort((left, right) => right.length - left.length)[0];
}

const CalculationStepCard: React.FC<{ step: PresentationCalculationStep }> = ({ step }) => {
  const [copied, setCopied] = useState<'formula' | 'substituted' | null>(null);
  const safeExpression = extractSandboxExpression(step);

  // Parse numeric variables from substituted expression so user can tweak.
  // Example substituted: "(100 + 50 * 0.1) * 20.44% = ..."
  // We extract numbers (excluding pure decimals like 0.1 only when paired with operators).
  const numericTokens = useMemo(() => {
    const tokens: { value: string; index: number; raw: string }[] = [];
    const regex = /(\d+(?:\.\d+)?)/g;
    let m: RegExpExecArray | null;
    while ((m = regex.exec(safeExpression)) !== null) {
      tokens.push({ value: m[1], index: m.index, raw: m[0] });
    }
    return tokens;
  }, [safeExpression]);

  const [vars, setVars] = useState<string[]>(() => numericTokens.map((t) => t.value));

  useEffect(() => {
    setVars(numericTokens.map((t) => t.value));
  }, [numericTokens]);

  const liveExpression = useMemo(() => {
    if (numericTokens.length === 0) return safeExpression;
    let out = '';
    let cursor = 0;
    numericTokens.forEach((tok, i) => {
      out += safeExpression.slice(cursor, tok.index);
      out += vars[i] ?? tok.value;
      cursor = tok.index + tok.raw.length;
    });
    out += safeExpression.slice(cursor);
    return out;
  }, [safeExpression, numericTokens, vars]);

  const liveResult = useMemo(() => {
    if (!liveExpression || !isValidSandboxExpression(liveExpression)) return null;
    try {
      const r = evaluate(liveExpression);
      return formatSandboxNumber(typeof r === 'number' ? r : Number(r));
    } catch {
      return null;
    }
  }, [liveExpression]);

  const agentResult = useMemo(() => {
    const m = step.result_text?.match(/-?\d+(?:\.\d+)?/);
    return m ? Number(m[0]) : null;
  }, [step.result_text]);

  const liveNumeric = useMemo(() => {
    if (!liveResult) return null;
    const n = Number(liveResult.replace(/,/g, ''));
    return Number.isFinite(n) ? n : null;
  }, [liveResult]);

  const mismatch =
    agentResult != null && liveNumeric != null && Math.abs(liveNumeric - agentResult) > 0.01;

  const copyTo = async (text: string, kind: 'formula' | 'substituted') => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(kind);
      window.setTimeout(() => setCopied(null), 1200);
    } catch {
      // ignore clipboard errors
    }
  };

  return (
    <div className="calc-step-card">
      <div className="calc-step-header">
        <div className="calc-step-order">Step {step.order}</div>
        <div className="calc-step-title">{step.title}</div>
      </div>

      <div className="calc-step-grid">
        <div className="calc-step-block">
          <span className="calc-step-label">公式</span>
          <code className="calc-step-code">{step.formula}</code>
          <button
            className="calc-action-btn"
            onClick={() => copyTo(step.formula, 'formula')}
            type="button"
          >
            {copied === 'formula' ? '已复制' : '📋 复制公式'}
          </button>
        </div>
        <div className="calc-step-block">
          <span className="calc-step-label">代入</span>
          <code className="calc-step-code">{step.substituted}</code>
          <button
            className="calc-action-btn"
            onClick={() => copyTo(`${liveExpression} = ${liveResult ?? ''}`, 'substituted')}
            type="button"
          >
            {copied === 'substituted' ? '已复制' : '📋 复制带数据公式'}
          </button>
        </div>
        <div className="calc-step-block result">
          <span className="calc-step-label">Agent 结果</span>
          <strong className="calc-step-result">{step.result_text}</strong>
        </div>
      </div>

      {numericTokens.length > 0 && (
        <div className="calc-sandbox">
          <div className="calc-sandbox-header">
            <span className="calc-sandbox-title">🧮 内置计算器（可改变量重算）</span>
          </div>
          <div className="calc-sandbox-vars">
            {numericTokens.map((tok, i) => (
              <label key={`${tok.index}-${i}`} className="calc-sandbox-var">
                <span className="calc-sandbox-var-label">x{i + 1}</span>
                <input
                  className="calc-sandbox-var-input"
                  type="text"
                  inputMode="decimal"
                  value={vars[i] ?? ''}
                  onChange={(e) =>
                    setVars((prev) => {
                      const next = [...prev];
                      next[i] = e.target.value;
                      return next;
                    })
                  }
                />
                <span className="calc-sandbox-var-orig">原值 {tok.value}</span>
              </label>
            ))}
          </div>
          <code className="calc-sandbox-expression">{liveExpression}</code>
          <div className={`calc-sandbox-result ${mismatch ? 'mismatch' : ''}`}>
            {liveResult != null ? (
              <>
                本地结果：<strong>{liveResult}</strong>
                {mismatch && (
                  <span className="calc-sandbox-warn">
                    ⚠ 与 Agent 结果差 {(liveNumeric! - agentResult!).toFixed(4)}
                  </span>
                )}
                {!mismatch && agentResult != null && (
                  <span className="calc-sandbox-ok">✓ 与 Agent 结果一致</span>
                )}
              </>
            ) : (
              <span className="calc-sandbox-warn">表达式无法计算</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

const PresentationCard: React.FC<{ presentation: PresentationPayload }> = ({ presentation }) => {
  const [activeTrendIndex, setActiveTrendIndex] = useState(0);

  useEffect(() => {
    if (presentation.type === 'price_trend') {
      const pointCount = presentation.points?.length ?? 0;
      setActiveTrendIndex(pointCount > 1 ? pointCount - 1 : 0);
    }
  }, [presentation.type, presentation.points?.length]);

  if (presentation.type === 'answer_sections') {
    const hasLayout = presentation.layout && presentation.layout.length > 0;
    const highlightLabels = hasLayout
      ? []
      : buildDisplayLabels(
          presentation.highlights ?? [],
          (kind) => getHighlightBaseLabel(kind, presentation.query_type),
        );
    const sectionLabels = hasLayout
      ? []
      : buildDisplayLabels(
          presentation.sections ?? [],
          (kind) => getSectionBaseLabel(kind, presentation.query_type),
        );

    return (
      <div className="presentation-card answer-sections">
        {presentation.summary && (
          <div className="conversation-answer-card">
            {presentation.note && <div className="conversation-answer-context">{presentation.note}</div>}
            <div
              className="conversation-answer-text"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(presentation.summary) }}
            />
          </div>
        )}

        {(hasLayout) ||
        (presentation.highlights && presentation.highlights.length > 0) ||
        (presentation.sections && presentation.sections.length > 0) ||
            (presentation.sources && presentation.sources.length > 0) ? (
          <div className="presentation-support-block">
            <div className="presentation-support-kicker">
              {presentation.support_kicker || '补充说明'}
            </div>

            {hasLayout ? (
              <LayoutBlocks blocks={presentation.layout!} />
            ) : (
              <>
                {presentation.highlights && presentation.highlights.length > 0 && (
                  <div className="answer-highlight-grid">
                    {presentation.highlights.map((item, index) => (
                      <div
                        key={`${item.kind ?? item.label ?? 'highlight'}-${index}`}
                        className="answer-highlight-item"
                      >
                        <span className="answer-highlight-label">{highlightLabels[index]}</span>
                        <div
                          className="answer-highlight-value"
                          dangerouslySetInnerHTML={{ __html: renderMarkdown(item.value) }}
                        />
                      </div>
                    ))}
                  </div>
                )}

                {presentation.sections && presentation.sections.length > 0 && (
                  <div className="answer-sections-list">
                    {presentation.sections.map((section, index) => (
                      <div
                        key={`${section.kind ?? section.label ?? 'section'}-${index}`}
                        className="answer-section-item"
                      >
                        <div className="answer-section-label">{sectionLabels[index]}</div>
                        <div
                          className="answer-section-body"
                          dangerouslySetInnerHTML={{ __html: renderMarkdown(section.body) }}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}

            {presentation.sources && presentation.sources.length > 0 && (
              <div className="presentation-footnotes">
                {presentation.sources.map((source) => (
                  <div key={`${source.index}-${source.title}-${source.page}`} className="presentation-footnote">
                    <span className="presentation-footnote-label">来源 {source.index}</span>
                    <span>{source.title} P{source.page}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : null}
      </div>
    );
  }

  if (presentation.type === 'calculation_steps') {
    return (
      <div className="presentation-card calculation-steps">
        {presentation.summary && (
          <div className="conversation-answer-card calculation-summary">
            {presentation.note && <div className="conversation-answer-context">{presentation.note}</div>}
            <div
              className="conversation-answer-text"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(presentation.summary) }}
            />
          </div>
        )}

        {(presentation.layout && presentation.layout.length > 0) ||
        (presentation.highlights && presentation.highlights.length > 0) ||
        (presentation.steps && presentation.steps.length > 0) ||
        (presentation.sources && presentation.sources.length > 0) ? (
          <div className="presentation-support-block">
            <div className="presentation-support-kicker">
              {presentation.support_kicker || '计算说明'}
            </div>

            {presentation.layout && presentation.layout.length > 0 ? (
              <LayoutBlocks blocks={presentation.layout} />
            ) : (
              presentation.highlights && presentation.highlights.length > 0 && (
                <div className="answer-highlight-grid">
                  {presentation.highlights.map((item, index) => (
                    <div key={`${item.kind ?? item.label ?? 'highlight'}-${index}`} className="answer-highlight-item">
                      <span className="answer-highlight-label">
                        {item.label || getHighlightBaseLabel(item.kind, presentation.query_type)}
                      </span>
                      <div
                        className="answer-highlight-value"
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(item.value) }}
                      />
                    </div>
                  ))}
                </div>
              )
            )}

            {presentation.steps && presentation.steps.length > 0 && (
              <div className="calc-steps-list">
                {presentation.steps.map((step) => (
                  <CalculationStepCard key={`${step.order}-${step.title}`} step={step} />
                ))}
              </div>
            )}

            {presentation.sources && presentation.sources.length > 0 && (
              <div className="presentation-footnotes">
                {presentation.sources.map((source) => (
                  <div key={`${source.index}-${source.title}-${source.page}`} className="presentation-footnote">
                    <span className="presentation-footnote-label">来源 {source.index}</span>
                    <span>{source.title} P{source.page}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : null}
      </div>
    );
  }

  const chartData = (presentation.points ?? []).map((point) => ({
    label: point.label,
    value: point.value,
  }));
  const isTrendPresentation = presentation.type === 'price_trend';
  const trendPoints = presentation.type === 'price_trend' ? presentation.points ?? [] : [];
  const trendAxisConfig = getTrendAxisConfig(trendPoints);
  const activePointIndex = Math.min(activeTrendIndex, Math.max(trendPoints.length - 1, 0));
  const activePoint = trendPoints[activePointIndex] ?? null;
  const previousPoint = activePointIndex > 0 ? trendPoints[activePointIndex - 1] : null;
  const activePointDelta =
    activePoint && previousPoint ? activePoint.value - previousPoint.value : presentation.delta ?? null;
  const activePointDeltaPercent =
    activePoint && previousPoint && Math.abs(previousPoint.value) > 0.001
      ? (activePointDelta! / previousPoint.value) * 100
      : presentation.delta_percent ?? null;

  return (
    <div className={`presentation-card ${isTrendPresentation ? 'presentation-card-trend' : ''}`}>
      <div className="presentation-header">
        <div>
          <div className="presentation-title">{presentation.title}</div>
          {presentation.note && <div className="presentation-note">{presentation.note}</div>}
        </div>
        {presentation.unit && <span className="presentation-unit">单位：元/{presentation.unit}</span>}
      </div>

      {presentation.type === 'price_comparison' && (
        <div className="presentation-metrics">
          {(presentation.points ?? []).map((point) => (
            <div key={point.label} className="presentation-metric">
              <span className="presentation-metric-label">{point.label}</span>
              <strong>{formatPointRange(point, presentation.unit)}</strong>
            </div>
          ))}
          {presentation.delta != null && (
            <div className={`presentation-metric ${presentation.delta >= 0 ? 'up' : 'down'}`}>
              <span className="presentation-metric-label">差值</span>
              <strong>
                {presentation.delta > 0 ? '+' : ''}
                {formatPresentationValue(presentation.delta, presentation.unit)}
              </strong>
              {presentation.delta_percent != null && (
                <span className="presentation-metric-sub">
                  {presentation.delta_percent > 0 ? '+' : ''}
                  {presentation.delta_percent.toFixed(2)}%
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {presentation.type === 'price_trend' && trendPoints.length >= 2 && (
        <>
          <div className="presentation-metrics trend-metrics">
            <div className="presentation-metric">
              <span className="presentation-metric-label">起点</span>
              <strong>{formatPresentationValue(trendPoints[0].value, presentation.unit)}</strong>
              <span className="presentation-metric-sub">{trendPoints[0].label}</span>
            </div>
            <div className="presentation-metric">
              <span className="presentation-metric-label">终点</span>
              <strong>
                {formatPresentationValue(trendPoints[trendPoints.length - 1].value, presentation.unit)}
              </strong>
              <span className="presentation-metric-sub">
                {trendPoints[trendPoints.length - 1].label}
              </span>
            </div>
            <div
              className={`presentation-metric trend-emphasis ${getTrendDirectionClass(
                presentation.delta,
              )}`}
            >
              <span className="presentation-metric-label">趋势结论</span>
              <strong>{getTrendDirectionText(presentation.delta)}</strong>
              <span className="presentation-metric-sub">
                {getDeltaSummary(presentation.delta, presentation.delta_percent, presentation.unit)}
              </span>
            </div>
          </div>

          {activePoint && (
            <div className="trend-active-panel">
              <div className="trend-active-header">
                <div>
                  <div className="trend-active-label">当前查看</div>
                  <div className="trend-active-title">{activePoint.label}</div>
                </div>
                <div
                  className={`trend-active-badge ${getTrendDirectionClass(activePointDelta)}`}
                >
                  {getTrendDirectionText(activePointDelta)}
                </div>
              </div>

              <div className="trend-active-grid">
                <div className="trend-active-item">
                  <span className="trend-active-item-label">价格</span>
                  <strong>{formatPresentationValue(activePoint.value, presentation.unit)}</strong>
                </div>
                <div className="trend-active-item">
                  <span className="trend-active-item-label">相邻变化</span>
                  <strong>
                    {getDeltaSummary(
                      activePointDelta,
                      activePointDeltaPercent,
                      presentation.unit,
                    )}
                  </strong>
                </div>
                <div className="trend-active-item">
                  <span className="trend-active-item-label">来源</span>
                  <strong>
                    {activePoint.sources?.length ? activePoint.sources.join(' / ') : '知识库记录'}
                    {activePoint.pages?.length ? ` · P${activePoint.pages.join(', P')}` : ''}
                  </strong>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      <div className="presentation-chart-shell">
        {presentation.type === 'price_trend' && trendPoints.length > 0 && (
          <div className="presentation-chart-head">
            <div>
              <div className="presentation-chart-kicker">TREND VIEW</div>
              <div className="presentation-chart-caption">
                {trendPoints[0].label}
                {trendPoints.length > 1 ? ` - ${trendPoints[trendPoints.length - 1].label}` : ''}
              </div>
            </div>
            <div className="presentation-chart-legend">
              <span className="presentation-chart-legend-dot" />
              <span className="presentation-chart-legend-text">Market price line</span>
            </div>
          </div>
        )}

        <div className="presentation-chart">
          <ResponsiveContainer width="100%" height={220}>
            {presentation.type === 'price_trend' ? (
              <LineChart
                data={chartData}
                margin={{ top: 18, right: 16, left: 4, bottom: 8 }}
                onMouseMove={(state) => {
                  if (typeof state?.activeTooltipIndex === 'number') {
                    setActiveTrendIndex(state.activeTooltipIndex);
                  }
                }}
              >
                <defs>
                  <linearGradient id="trendLineGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="#38bdf8" />
                    <stop offset="55%" stopColor="#3b82f6" />
                    <stop offset="100%" stopColor="#8b5cf6" />
                  </linearGradient>
                  <filter id="trendLineGlow" x="-20%" y="-20%" width="140%" height="140%">
                    <feDropShadow
                      dx="0"
                      dy="8"
                      stdDeviation="8"
                      floodColor="#3b82f6"
                      floodOpacity="0.18"
                    />
                  </filter>
                </defs>
                <CartesianGrid
                  vertical={false}
                  strokeDasharray="4 6"
                  stroke="rgba(148, 163, 184, 0.28)"
                />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickMargin={8} axisLine={false} tickLine={false} />
                <YAxis
                  tick={{ fontSize: 11, fill: 'var(--text-muted)' }}
                  width={72}
                  domain={trendAxisConfig.domain}
                  ticks={trendAxisConfig.ticks}
                  tickFormatter={(value: number) => value.toFixed(2)}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  cursor={{ stroke: 'rgba(59, 130, 246, 0.75)', strokeDasharray: '4 4', strokeWidth: 1.25 }}
                  content={<TrendTooltipContent unit={presentation.unit} />}
                />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="url(#trendLineGradient)"
                  strokeWidth={3.5}
                  filter="url(#trendLineGlow)"
                  dot={{ r: 4.5, strokeWidth: 2.5, fill: '#f8fafc', stroke: '#2563eb' }}
                  activeDot={{ r: 7, strokeWidth: 3, fill: '#ffffff', stroke: '#1d4ed8' }}
                />
              </LineChart>
            ) : (
              <BarChart
                data={chartData}
                margin={{ top: 22, right: 16, left: 4, bottom: 8 }}
                barCategoryGap="42%"
              >
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" opacity={0.55} />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickMargin={8} />
                <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} width={72} />
                <Tooltip formatter={(value: number) => formatPresentationValue(value, presentation.unit)} />
                <Bar
                  dataKey="value"
                  fill="var(--color-primary)"
                  radius={[8, 8, 0, 0]}
                  barSize={26}
                  maxBarSize={30}
                >
                  <LabelList
                    dataKey="value"
                    position="top"
                    offset={8}
                    formatter={(value: number) => value.toFixed(2)}
                    style={{ fill: 'var(--text-secondary)', fontSize: 11, fontWeight: 600 }}
                  />
                </Bar>
              </BarChart>
            )}
          </ResponsiveContainer>
        </div>
      </div>

      {presentation.type === 'price_trend' && trendPoints.length > 0 && (
        <div className="trend-point-tabs">
          {trendPoints.map((point, index) => (
            <button
              key={point.label}
              type="button"
              className={`trend-point-tab ${index === activeTrendIndex ? 'active' : ''}`}
              onClick={() => setActiveTrendIndex(index)}
            >
              <span className="trend-point-tab-label">{point.label}</span>
              <strong>{formatPresentationValue(point.value, presentation.unit)}</strong>
            </button>
          ))}
        </div>
      )}

      {presentation.type === 'price_trend' && trendPoints.length >= 2 && (
        <div className="trend-summary-strip">
          <span className={`trend-summary-chip ${getTrendDirectionClass(presentation.delta)}`}>
            {getTrendDirectionText(presentation.delta)}
          </span>
          <span>
            {trendPoints[0].label} → {trendPoints[trendPoints.length - 1].label}
          </span>
          <strong>{getDeltaSummary(presentation.delta, presentation.delta_percent, presentation.unit)}</strong>
        </div>
      )}

      <div className="presentation-footnotes">
        {(presentation.points ?? []).map((point) => (
          <div key={`${point.label}-refs`} className="presentation-footnote">
            <span className="presentation-footnote-label">{point.label}</span>
            <span>
              {point.sources?.length ? point.sources.join(' / ') : '知识库记录'}
              {point.pages?.length ? ` P${point.pages.join(', P')}` : ''}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};

/* ── Config State ────────────────────────────────────── */

interface ConfigState {
  searchMode: string;
  maxIterations: number;
  scoreThreshold: number;
  topK: number;
  docTypes: string[];
  llmRoute: 'auto' | 'local' | 'deepseek';
  llmModel: string;
  llmEngine: string;
}

const DEFAULT_CONFIG: ConfigState = {
  searchMode: 'hybrid',
  maxIterations: 3,
  scoreThreshold: 0.6,
  topK: 8,
  docTypes: [],
  llmRoute: 'deepseek',
  llmModel: 'deepseek-chat',
  llmEngine: 'api',
};

const DOC_TYPE_OPTIONS = ['信息价', '定额', '费率', '指南', '划分'];
const LLM_ROUTE_OPTIONS: Array<ConfigState['llmRoute']> = ['auto', 'local', 'deepseek'];

function getDefaultModel(route: ConfigState['llmRoute']): string {
  if (route === 'local') return 'Qwen2.5-14B-Instruct';
  if (route === 'auto') return 'Qwen2.5-14B-Instruct';
  return 'deepseek-chat';
}

function getDefaultEngine(route: ConfigState['llmRoute']): string {
  return route === 'deepseek' ? 'api' : 'llama.cpp';
}

/* ── Main Component ──────────────────────────────────── */

export const AgentChat: React.FC = () => {
  const { messages, isLoading, sendMessage, clearMessages, cancelStream, sessionId } = useAgent();
  const [input, setInput] = useState('');
  const [config, setConfig] = useState<ConfigState>(DEFAULT_CONFIG);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = () => {
    if (!input.trim() || isLoading) return;
    const agentConfig: AgentConfig = {
      maxIterations: config.maxIterations,
      scoreThreshold: config.scoreThreshold,
      topK: config.topK,
      searchMode: config.searchMode,
      docTypes: config.docTypes,
      llmRoute: config.llmRoute,
      llmProvider: config.llmRoute === 'auto' ? undefined : config.llmRoute,
      llmModel: config.llmModel,
      llmEngine: config.llmEngine,
    };
    sendMessage(input, agentConfig);
    setInput('');
    inputRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const toggleDocType = (dt: string) => {
    setConfig((c) => ({
      ...c,
      docTypes: c.docTypes.includes(dt) ? c.docTypes.filter((x) => x !== dt) : [...c.docTypes, dt],
    }));
  };

  return (
    <div className="agent-chat-3panel">
      {/* ── Left Panel ── */}
      <aside className="left-panel">
        <div className="panel-section">
          <h3 className="panel-title">会话</h3>
          <div className="session-info">
            <span className="session-id">{sessionId ? sessionId.slice(0, 8) + '…' : '新会话'}</span>
            <button className="new-session-btn" onClick={clearMessages}>+ 新对话</button>
          </div>
        </div>

        <div className="panel-section">
          <h3 className="panel-title">推理路由</h3>
          <div className="mode-select">
            {LLM_ROUTE_OPTIONS.map((route) => (
              <button
                key={route}
                className={`mode-btn ${config.llmRoute === route ? 'active' : ''}`}
                onClick={() =>
                  setConfig((c) => ({
                    ...c,
                    llmRoute: route,
                    llmModel: getDefaultModel(route),
                    llmEngine: getDefaultEngine(route),
                  }))
                }
              >
                {route}
              </button>
            ))}
          </div>
        </div>

        <div className="panel-section">
          <h3 className="panel-title">模型</h3>
          <input
            className="panel-input"
            value={config.llmModel}
            onChange={(e) => setConfig((c) => ({ ...c, llmModel: e.target.value }))}
          />
        </div>

        <div className="panel-section">
          <h3 className="panel-title">引擎</h3>
          <div className="mode-select">
            {['api', 'llama.cpp'].map((engine) => (
              <button
                key={engine}
                className={`mode-btn ${config.llmEngine === engine ? 'active' : ''}`}
                onClick={() => setConfig((c) => ({ ...c, llmEngine: engine }))}
              >
                {engine}
              </button>
            ))}
          </div>
        </div>

        <div className="panel-section">
          <h3 className="panel-title">检索模式</h3>
          <div className="mode-select">
            {['hybrid', 'vector', 'text', 'price'].map((m) => (
              <button
                key={m}
                className={`mode-btn ${config.searchMode === m ? 'active' : ''}`}
                onClick={() => setConfig((c) => ({ ...c, searchMode: m }))}
              >
                {m}
              </button>
            ))}
          </div>
        </div>

        <div className="panel-section">
          <h3 className="panel-title">最大迭代次数</h3>
          <div className="slider-row">
            <input
              type="range"
              min={1}
              max={5}
              value={config.maxIterations}
              onChange={(e) => setConfig((c) => ({ ...c, maxIterations: Number(e.target.value) }))}
              className="config-slider"
            />
            <span className="slider-val">{config.maxIterations}</span>
          </div>
        </div>

        <div className="panel-section">
          <h3 className="panel-title">评分阈值</h3>
          <div className="slider-row">
            <input
              type="range"
              min={50}
              max={90}
              value={Math.round(config.scoreThreshold * 100)}
              onChange={(e) =>
                setConfig((c) => ({ ...c, scoreThreshold: Number(e.target.value) / 100 }))
              }
              className="config-slider"
            />
            <span className="slider-val">{(config.scoreThreshold * 100).toFixed(0)}%</span>
          </div>
        </div>

        <div className="panel-section">
          <h3 className="panel-title">Top K</h3>
          <div className="slider-row">
            <input
              type="range"
              min={3}
              max={20}
              value={config.topK}
              onChange={(e) => setConfig((c) => ({ ...c, topK: Number(e.target.value) }))}
              className="config-slider"
            />
            <span className="slider-val">{config.topK}</span>
          </div>
        </div>

        <div className="panel-section">
          <h3 className="panel-title">文档类型</h3>
          <div className="doctype-filters">
            {DOC_TYPE_OPTIONS.map((dt) => (
              <label key={dt} className="doctype-label">
                <input
                  type="checkbox"
                  checked={config.docTypes.includes(dt)}
                  onChange={() => toggleDocType(dt)}
                />
                {dt}
              </label>
            ))}
          </div>
        </div>
      </aside>

      {/* ── Center Panel ── */}
      <main className="center-panel">
        <div className="chat-messages">
          {messages.length === 0 ? (
            <WelcomeScreen onQuickAsk={(q) => sendMessage(q, config)} />
          ) : (
            messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} sessionId={sessionId} />
            ))
          )}
          {isLoading && <StreamingBubble />}
          <div ref={messagesEndRef} />
        </div>

        <div className="chat-input-area">
          <div className="chat-input-shell">
            <div className="input-wrapper">
              <textarea
                ref={inputRef}
                className="chat-textarea"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="输入造价相关问题…"
                rows={1}
                disabled={isLoading}
              />
              {isLoading ? (
                <button className="cancel-btn" onClick={cancelStream}>停止</button>
              ) : (
                <button
                  className="send-btn"
                  onClick={handleSend}
                  disabled={!input.trim()}
                  aria-label="发送"
                >
                  <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M8 13V3M3 8l5-5 5 5" />
                  </svg>
                </button>
              )}
            </div>
          </div>
          <div className="input-hints">
            <span className="hint-text">Enter 发送 · Shift+Enter 换行</span>
            <div className="input-meta-actions">
              {input.length > 0 && <span className="char-count">{input.length}</span>}
              {messages.length > 0 && (
                <button className="clear-btn" onClick={clearMessages}>清空对话</button>
              )}
            </div>
          </div>
        </div>
      </main>

      {/* ── Right Panel ── */}
      <aside className="right-panel">
        <ProcessVisualization />
      </aside>
    </div>
  );
};

/* ── Welcome Screen ──────────────────────────────────── */

const QUICK_QUESTIONS = [
  '2025版费率标准中，企业管理费的计算方法是什么？',
  '某工程人工费500万，按2025版费率计算企业管理费是多少？',
  '2026年1月普通硅酸盐水泥P.O 42.5的含税价格是多少？',
  '一般计税与简易计税的适用条件分别是什么？',
];

const WelcomeScreen: React.FC<{ onQuickAsk: (q: string) => void }> = ({ onQuickAsk }) => (
  <div className="welcome-screen">
    <div className="welcome-content">
      <h1 className="welcome-title">造价知识问答</h1>
      <p className="welcome-desc">深圳市建设工程定额 · 费率标准 · 信息价</p>
      <div className="quick-questions">
        {QUICK_QUESTIONS.map((q, i) => (
          <button key={i} className="quick-question-btn" onClick={() => onQuickAsk(q)}>
            {q}
          </button>
        ))}
      </div>
    </div>
  </div>
);

/* ── Message Bubble ──────────────────────────────────── */

const MessageBubble: React.FC<{ message: ChatMessage; sessionId: string | null }> = ({
  message,
  sessionId,
}) => {
  const [showDetail, setShowDetail] = useState(false);
  const [feedbackSent, setFeedbackSent] = useState<number | null>(null);

  const sendFeedback = async (rating: number) => {
    if (!sessionId || feedbackSent !== null) return;
    try {
      await submitFeedback({
        session_id: sessionId,
        message_id: message.id,
        rating,
        query: undefined,
        answer_summary: message.content.slice(0, 200),
      });
      setFeedbackSent(rating);
    } catch (e) {
      console.error('Feedback error', e);
    }
  };

  if (message.error) {
    return (
      <div className="message-row assistant">
        <div className="message-bubble error">❌ {message.error}</div>
      </div>
    );
  }

  return (
    <div className={`message-row ${message.role}`}>
        <div className={`message-bubble ${message.role}`}>
          {message.role === 'assistant' && message.presentation && (
            <PresentationCard presentation={message.presentation} />
          )}
        {(!message.presentation || !['answer_sections', 'calculation_steps'].includes(message.presentation.type)) && (
          <div
            className={`message-content ${message.presentation ? 'with-presentation' : ''}`}
            dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }}
          />
        )}

        {message.role === 'assistant' && (
          <div className="message-meta">
            {message.evalScores && (
              <span className="meta-tag confidence">
                置信度 {(message.evalScores.confidence * 100).toFixed(0)}%
              </span>
            )}
            {message.iterations != null && (
              <span className="meta-tag iterations">迭代 {message.iterations} 轮</span>
            )}
            {message.chunks && (
              <span className="meta-tag chunks">引用 {message.chunks.length} 篇</span>
            )}
            {message.latencyMs && (
              <span className="meta-tag latency">{(message.latencyMs / 1000).toFixed(1)}s</span>
            )}
            {message.routeMode && (
              <span className="meta-tag">路由 {message.routeMode}</span>
            )}
            {message.provider && (
              <span className="meta-tag">{message.provider}</span>
            )}
            {message.engine && (
              <span className="meta-tag">{message.engine}</span>
            )}
            {message.model && (
              <span className="meta-tag">{message.model}</span>
            )}

            {/* Feedback buttons */}
            <div className="feedback-btns">
              <button
                className={`feedback-btn ${feedbackSent === 1 ? 'active' : ''}`}
                onClick={() => sendFeedback(1)}
                title="有帮助"
                disabled={feedbackSent !== null}
              >
                👍
              </button>
              <button
                className={`feedback-btn ${feedbackSent === -1 ? 'active' : ''}`}
                onClick={() => sendFeedback(-1)}
                title="没帮助"
                disabled={feedbackSent !== null}
              >
                👎
              </button>
            </div>

            {message.chunks && message.chunks.length > 0 && (
              <button className="detail-toggle" onClick={() => setShowDetail(!showDetail)}>
                {showDetail ? '收起 ▲' : '详情 ▼'}
              </button>
            )}
          </div>
        )}

        {showDetail && message.role === 'assistant' && message.chunks && (
          <div className="message-detail">
            <h4>📎 引用文档</h4>
            {message.chunks.slice(0, 5).map((chunk, i) => (
              <div key={i} className="chunk-item">
                <span className="chunk-score">{(chunk.score * 100).toFixed(1)}%</span>
                <span className="chunk-content">
                  {chunk.content.slice(0, 200)}
                  {chunk.content.length > 200 && '…'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

/* ── Streaming Bubble ────────────────────────────────── */

const StreamingBubble: React.FC = () => {
  const streamingAnswer = useRunStore((s) => s.streamingAnswer);
  const queryAnalysis = useRunStore((s) => s.queryAnalysis);
  const statusMessage = useRunStore((s) => s.statusMessage);
  const runtimeInfo = useRunStore((s) => s.runtimeInfo);
  const presentation = useRunStore((s) => s.presentation);

  if (!streamingAnswer && !queryAnalysis && !presentation) {
    return (
      <div className="message-row assistant">
        <div className="message-bubble thinking">
          <div className="thinking-dots">
            <span /><span /><span />
          </div>
          <span className="thinking-text">{statusMessage || '正在检索和分析…'}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="message-row assistant">
      <div className="message-bubble assistant streaming">
        {presentation && <PresentationCard presentation={presentation} />}
        {(!presentation || !['answer_sections', 'calculation_steps'].includes(presentation.type)) && (
          <div className={`message-content ${presentation ? 'with-presentation' : ''}`}>
            {streamingAnswer
              ? <span dangerouslySetInnerHTML={{ __html: renderMarkdown(streamingAnswer) }} />
              : <span className="thinking-text">{statusMessage || '正在生成回答…'}</span>}
          </div>
        )}
        {runtimeInfo?.model && (
          <div className="message-meta">
            <span className="meta-tag">{runtimeInfo.routeMode || 'default'}</span>
            <span className="meta-tag">{runtimeInfo.engine || runtimeInfo.provider || 'model'}</span>
            <span className="meta-tag">{runtimeInfo.model}</span>
          </div>
        )}
        <span className="streaming-cursor" />
      </div>
    </div>
  );
};

/* ── Process Visualization (Right Panel) ─────────────── */

const ProcessVisualization: React.FC = () => {
  const runStore = useRunStore();
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const toggle = (key: string) =>
    setCollapsed((c) => ({ ...c, [key]: !c[key] }));

  const Section: React.FC<{
    id: string;
    title: string;
    count?: number;
    children: React.ReactNode;
  }> = ({ id, title, count, children }) => (
    <div className="proc-section">
      <button className="proc-section-header" onClick={() => toggle(id)}>
        <span>{title}</span>
        {count != null && count > 0 && <span className="proc-badge">{count}</span>}
        <span className="proc-chevron">{collapsed[id] ? '▶' : '▼'}</span>
      </button>
      {!collapsed[id] && <div className="proc-section-body">{children}</div>}
    </div>
  );

  return (
    <div className="process-viz">
      <div className="proc-header">
        <span>⚙ 执行过程</span>
        {runStore.isStreaming && <span className="proc-live">● LIVE</span>}
      </div>

      <Section id="runtime" title="运行引擎" count={runStore.runtimeInfo ? 1 : 0}>
        {runStore.runtimeInfo ? (
          <div className="qa-display">
            <div className="qa-entity"><span className="qa-key">路由:</span><span>{runStore.runtimeInfo.routeMode || '–'}</span></div>
            <div className="qa-entity"><span className="qa-key">引擎:</span><span>{runStore.runtimeInfo.engine || '–'}</span></div>
            <div className="qa-entity"><span className="qa-key">Provider:</span><span>{runStore.runtimeInfo.provider || '–'}</span></div>
            <div className="qa-entity"><span className="qa-key">Model:</span><span>{runStore.runtimeInfo.model || '–'}</span></div>
            {runStore.statusMessage && (
              <div className="qa-subquery">↳ {runStore.statusMessage}</div>
            )}
          </div>
        ) : (
          <p className="proc-empty">{runStore.statusMessage || '等待模型选择…'}</p>
        )}
      </Section>

      {/* 1. Query Analysis */}
      <Section id="qa" title="查询分析" count={runStore.queryAnalysis ? 1 : 0}>
        {runStore.queryAnalysis ? (
          <div className="qa-display">
            <div className="qa-intent">
              <span className="qa-label">意图</span>
              <span className="qa-badge">{runStore.queryAnalysis.intent || '–'}</span>
            </div>
            {runStore.queryAnalysis.entities &&
              Object.entries(runStore.queryAnalysis.entities).map(([k, v]) => (
                <div key={k} className="qa-entity">
                  <span className="qa-key">{k}:</span>
                  <span>{String(v)}</span>
                </div>
              ))}
            {runStore.queryAnalysis.sub_queries && runStore.queryAnalysis.sub_queries.length > 0 && (
              <div className="qa-subqueries">
                {runStore.queryAnalysis.sub_queries.map((q, i) => (
                  <div key={i} className="qa-subquery">↳ {q}</div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <p className="proc-empty">等待查询分析…</p>
        )}
      </Section>

      {/* 1b. Execution Plan */}
      {runStore.planSteps.length > 0 && (
        <Section id="plan" title="执行计划" count={runStore.planSteps.length}>
          <ol className="plan-list">
            {runStore.planSteps.map((step, i) => (
              <li key={i} className="plan-step">{step}</li>
            ))}
          </ol>
        </Section>
      )}

      {/* 2. Retrieval Results */}
      <Section id="ret" title="检索结果" count={runStore.retrievalChunks.length}>
        {runStore.retrievalChunks.length > 0 ? (
          <div className="ret-list">
            {runStore.retrievalChunks.slice(0, 8).map((c, i) => (
              <div key={i} className={`ret-chunk ${c.passed_threshold ? 'passed' : 'filtered'}`}>
                <div className="ret-chunk-header">
                  <span className="ret-doc">{c.doc_id.slice(0, 20)}</span>
                  <span className="ret-score">{(c.score * 100).toFixed(0)}%</span>
                </div>
                <div className="ret-score-bar">
                  <div
                    className="ret-score-fill"
                    style={{ width: `${c.score * 100}%` }}
                  />
                </div>
                <div className="ret-content">{c.content.slice(0, 80)}…</div>
              </div>
            ))}
          </div>
        ) : (
          <p className="proc-empty">等待检索…</p>
        )}
      </Section>

      {/* 3. Tool Calls */}
      <Section id="tools" title="工具调用" count={runStore.toolCalls.length}>
        {runStore.toolCalls.length > 0 ? (
          <div className="tool-timeline">
            {runStore.toolCalls.map((tc, i) => (
              <div key={i} className={`tool-item status-${tc.status}`}>
                <div className="tool-header">
                  <span className="tool-name">{tc.tool}</span>
                  <span className={`tool-status-badge ${tc.status}`}>
                    {tc.status === 'running' ? '⏳' : tc.status === 'done' ? '✓' : '✗'}
                  </span>
                  {tc.duration_ms != null && tc.duration_ms > 0 && (
                    <span className="tool-duration">{tc.duration_ms}ms</span>
                  )}
                </div>
                {tc.result != null && (
                  <div className="tool-result">{JSON.stringify(tc.result).slice(0, 100)}</div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="proc-empty">无工具调用</p>
        )}
      </Section>

      {/* 4. Sandbox Execution */}
      {runStore.sandboxExecs.length > 0 && (
        <Section id="sandbox" title="沙箱执行" count={runStore.sandboxExecs.length}>
          {runStore.sandboxExecs.map((ex, i) => (
            <div key={i} className="sandbox-item">
              <code className="sandbox-code">{ex.code}</code>
              <div className="sandbox-result">= {ex.result}</div>
              <div className="sandbox-meta">{ex.duration_ms}ms · {ex.safe ? '✓ 安全' : '⚠ 不安全'}</div>
            </div>
          ))}
        </Section>
      )}

      {/* 5. Iteration State */}
      <Section id="loops" title="迭代状态" count={runStore.loopStates.length}>
        {runStore.loopStates.length > 0 ? (
          <div className="loop-list">
            {runStore.loopStates.map((ls, i) => (
              <div key={i} className="loop-item">
                <span className="loop-iter">#{ls.iteration}</span>
                <div className="loop-score-bar-wrap">
                  <div className="loop-score-bar">
                    <div className="loop-score-fill" style={{ width: `${ls.eval_score * 100}%` }} />
                  </div>
                  <span className="loop-score-val">{(ls.eval_score * 100).toFixed(0)}%</span>
                </div>
                {ls.rewrite_reason && (
                  <div className="loop-reason">{ls.rewrite_reason}</div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="proc-empty">等待迭代…</p>
        )}
      </Section>

      {/* 6. Evaluator Scores */}
      <Section id="eval" title="评估分数" count={runStore.evalScores ? 7 : 0}>
        {runStore.evalScores ? (
          <EvalRadarChart scores={runStore.evalScores} />
        ) : (
          <p className="proc-empty">等待评估…</p>
        )}
      </Section>

      {/* 7. Performance Stats */}
      <Section id="perf" title="性能统计" count={runStore.finalLatencyMs > 0 ? 1 : 0}>
        {runStore.finalLatencyMs > 0 ? (
          <table className="perf-table">
            <tbody>
              <tr><td>总延迟</td><td>{runStore.finalLatencyMs}ms</td></tr>
              <tr><td>迭代次数</td><td>{runStore.finalIterations}</td></tr>
              {runStore.tokensIn > 0 && <tr><td>输入 tokens</td><td>{runStore.tokensIn}</td></tr>}
              {runStore.tokensOut > 0 && <tr><td>输出 tokens</td><td>{runStore.tokensOut}</td></tr>}
              {runStore.tokensThink > 0 && <tr><td>思考 tokens</td><td>{runStore.tokensThink}</td></tr>}
            </tbody>
          </table>
        ) : (
          <p className="proc-empty">运行完成后显示统计</p>
        )}
      </Section>
    </div>
  );
};

/* ── Eval Radar Chart ────────────────────────────────── */

import type { EvalScores } from '../stores/useRunStore';

const EVAL_LABELS: Record<keyof EvalScores, string> = {
  completeness: '完整性',
  consistency: '一致性',
  confidence: '置信度',
  information_gain: '信息增益',
  source_diversity: '来源多样',
  fact_consistency: '事实一致',
  coverage_estimate: '覆盖估计',
};

const EvalRadarChart: React.FC<{ scores: EvalScores }> = ({ scores }) => {
  const data = (Object.keys(scores) as Array<keyof EvalScores>).map((k) => ({
    subject: EVAL_LABELS[k],
    value: Math.round(scores[k] * 100),
    fullMark: 100,
  }));

  return (
    <div className="eval-radar">
      <ResponsiveContainer width="100%" height={200}>
        <RadarChart data={data}>
          <PolarGrid />
          <PolarAngleAxis dataKey="subject" tick={{ fontSize: 10 }} />
          <Radar
            name="评分"
            dataKey="value"
            stroke="var(--color-primary)"
            fill="var(--color-primary)"
            fillOpacity={0.25}
          />
          <Tooltip formatter={(v) => [`${v}%`]} />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
};
