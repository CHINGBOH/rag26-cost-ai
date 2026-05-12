/**
 * locales/learning.ts — 学习引擎后端返回的英文消息翻译层
 *
 * 规则：后端/DB 使用英文，前端统一在此做 pattern-match 翻译。
 * 组件直接渲染 `translateAlert(a.message)` / `translateAction(e.action)`，
 * 不在组件内硬编码任何翻译逻辑。
 */

/**
 * 翻译 dashboard alerts 里的 message 字段
 * 覆盖后端 api.py 里的固定模板：
 *   "System health score is {n}/100"
 *   "{n} projection drift item(s) across {m} canonical read model(s)"
 *   "{n} patches pending application"
 *   "{n} high-risk patches pending approval"
 */
export function translateAlert(msg: string): string {
  // "System health score is 41/100"
  let m = msg.match(/^System health score is (\d+)\/100$/i);
  if (m) return `系统健康评分 ${m[1]}/100`;

  // "22 projection drift item(s) across 2 canonical read model(s)"
  m = msg.match(/^(\d+) projection drift item\(s\) across (\d+) canonical read model\(s\)$/i);
  if (m) return `检测到 ${m[1]} 处数据漂移（涉及 ${m[2]} 个核心读模型）`;

  // "{n} patches pending application"
  m = msg.match(/^(\d+) patches? pending application$/i);
  if (m) return `${m[1]} 个补丁待应用`;

  // "{n} high-risk patches pending approval"
  m = msg.match(/^(\d+) high-risk patches? pending approval$/i);
  if (m) return `${m[1]} 个高风险补丁待审批`;

  // 兜底：原样返回（后端可能新增模板）
  return msg;
}

/**
 * 翻译 improvement events 里的 action 字段
 * 覆盖后端常见生成模板：
 *   "Triage unresolved knowledge gap: {description}"
 *   "backfill-pending-review"
 *   及其他技术性短语
 */
export function translateAction(action: string): string {
  if (!action) return '系统检测到可以改进的地方，想做一次调整';

  // "Triage unresolved knowledge gap: Continuous failures on R1_xxx: …"
  const triageM = action.match(
    /^Triage unresolved knowledge gap:\s*Continuous failures on (\S+):\s*(\d+) failures,\s*most common error=(\S+)\s*\(P95 latency=(\d+)ms\)$/i,
  );
  if (triageM) {
    const [, path, count, errCode, latencyMs] = triageM;
    const latencySec = (parseInt(latencyMs) / 1000).toFixed(1);
    return `知识空白待处理：${path} 持续失败 ${count} 次（最常见错误：${translateErrCode(errCode)}，P95 延迟 ${latencySec}s）`;
  }

  // 宽松匹配：以 "Triage unresolved knowledge gap:" 开头
  if (/^Triage unresolved knowledge gap:/i.test(action)) {
    const desc = action.replace(/^Triage unresolved knowledge gap:\s*/i, '');
    return `知识空白待处理：${desc}`;
  }

  // "backfill-pending-review" 或含 backfill 的技术 slug
  if (/backfill/i.test(action)) return '数据回填任务待审核';

  // 兜底
  return action;
}

/** 错误码 → 中文描述 */
function translateErrCode(code: string): string {
  const map: Record<string, string> = {
    ANSWERED_OK:                   '已回答但质量不足',
    REFUSED_INSUFFICIENT_EVIDENCE: '证据不足被拒绝',
    REFUSED_OUT_OF_SCOPE:          '超出范围被拒绝',
    TIMEOUT:                       '超时',
    ERROR:                         '系统错误',
  };
  return map[code] ?? code;
}
