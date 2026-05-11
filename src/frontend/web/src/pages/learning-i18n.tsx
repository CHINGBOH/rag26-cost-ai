export type QualityFilter = 'all' | 'good' | 'weak' | 'failure';
export type MainTab = 'status' | 'qa-issues' | 'improvements';

export const QUALITY_ZH: Record<string, string> = {
  good: '优质',
  weak: '弱',
  failure: '失败',
  non_task: '非任务',
  validated: '已验证',
};

export const TYPE_ZH: Record<string, string> = {
  standard_ref: '标准查询',
  price: '价格查询',
  trend_chart: '趋势图表',
  comparison: '对比分析',
  calculation: '计算推理',
  semantic: '语义检索',
};

export const OUTCOME_FAMILY_ZH: Record<string, string> = {
  answered: '已回答',
  refused: '拒答',
  failed: '失败',
  non_task: '非任务',
  early_exit: '早停',
  cancelled: '取消',
};

export const RUN_TYPE_ZH: Record<string, string> = {
  manual: '手动',
  scheduled: '定时',
  auto_threshold: '阈值触发',
  feedback_analysis: '反馈分析',
};

export const ENGINE_TRIGGER_MODE_ZH: Record<string, string> = {
  manual: '手动',
  hybrid: '手动 + 运行态监控',
  scheduled: '定时',
  automated: '自动',
};

export const GAP_SCOPE_ZH: Record<string, string> = {
  user: '用户',
  agent: 'Agent',
  project: '项目',
  global: '全局',
};

export const CAUSE_TYPE_ZH: Record<string, string> = {
  prompt_drift: '提示漂移',
  retrieval_miss: '检索缺失',
  tool_failure: '工具失败',
  routing_error: '路由错误',
  data_gap: '数据缺失',
  policy_mismatch: '策略不符',
  low_quality_output: '输出质量低',
  diversity_low: '多样性不足',
  unknown: '未知',
};

export const GAP_ACTION_ZH: Record<string, string> = {
  retest: '复测',
  live_retest: '实时复测',
  start_repair: '开始修复',
  block: '标记阻塞',
  unblock: '解除阻塞',
  link_event: '关联事件',
  resolve: '标记已解决',
  reopen: '重新打开',
  inspect_evidence: '查看证据',
  mark_observing: '加入观察期',
  close: '关闭',
};

export const GAP_BUCKETS: Array<{
  key: 'active' | 'observing' | 'blocked' | 'resolved';
  title: string;
  hint: string;
}> = [
  { key: 'active', title: '还在弄', hint: '系统还没搞定，正在想办法' },
  { key: 'observing', title: '观察一阵', hint: '看起来好了，再观察几天确认不会复发' },
  { key: 'blocked', title: '搞不定', hint: '太难了或者超出能力范围' },
  { key: 'resolved', title: '已搞定', hint: '问题已经解决' },
];

export function renderGapStatusBadge(status?: string) {
  if (status === 'resolved') return <span className="badge status-resolved">✅ 已搞定</span>;
  if (status === 'observing') return <span className="badge status-observing">👀 观察中</span>;
  if (status === 'in_progress') return <span className="badge status-in-progress">🔄 正在弄</span>;
  if (status === 'open') return <span className="badge status-open">❌ 还没弄</span>;
  if (status === 'blocked') return <span className="badge status-blocked">🚫 搞不定</span>;
  return null;
}

export function renderLearningRunStatusBadge(status?: string) {
  if (status === 'completed') return <span className="badge status-resolved">完成</span>;
  if (status === 'running') return <span className="badge status-in-progress">运行中</span>;
  if (status === 'failed') return <span className="badge status-open">失败</span>;
  if (status === 'blocked') return <span className="badge status-blocked">阻塞</span>;
  return status ? <span className="badge status-neutral">{status}</span> : null;
}
