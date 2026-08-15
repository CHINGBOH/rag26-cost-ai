#185 — [授权] 全部 issue 排队执行 + 16题验收自动化

## 授权范围
- 所有 rag26-cost-ai open issues 排队执行，无需逐项确认
- 每个 fix 完成后自动跑 16 题测试验收
- 答案不达标（包含拒绝回答模式）→ 自动修复 → 再测 → 循环到全部通过
- 用户睡觉，零打扰模式

## 执行规则
1. 按 issue 优先级顺序执行（bug > enhancement > feat > plan）
2. 每完成一个 issue，立即跑 `agent_test_16_results.json` 验收
3. 验收标准参照 HOOD AGENT 规则：拒绝回答、无法回答、N/A 等 = FAIL
4. 不合格答案追溯到 root cause，修正后重测

## 开始时间
2026-05-21 开始排队
