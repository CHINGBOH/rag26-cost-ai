/**
 * ARITHMETIC_ONLY fast-path evaluator for the calculator tool.
 *
 * Replaces the Function()-based evaluator to eliminate eval-like escapes
 * such as `(1).toString.call(this)`.
 *
 * AST nodes allowed:
 *   BinaryExpression (+, -, *, /, %, **)
 *   UnaryExpression  (-, +)
 *   Literal          (number)
 *   ParenthesisedExpression (implicit via grouping in the recursive parser)
 *
 * Everything else is rejected with a ValidationError before any evaluation.
 */

export interface ArithmeticResult {
  ok: boolean
  value?: number
  error?: string
}

// ── Tokeniser ─────────────────────────────────────────────────────────────────

type Token =
  | { kind: 'num'; value: number }
  | { kind: 'op'; value: string }
  | { kind: 'lparen' }
  | { kind: 'rparen' }

function tokenise(expr: string): Token[] | string {
  const tokens: Token[] = []
  let i = 0
  while (i < expr.length) {
    const ch = expr[i]
    if (/\s/.test(ch)) { i++; continue }
    if (/[0-9]/.test(ch) || (ch === '.' && /[0-9]/.test(expr[i + 1] ?? ''))) {
      let num = ''
      while (i < expr.length && /[0-9.]/.test(expr[i])) num += expr[i++]
      const n = parseFloat(num)
      if (isNaN(n)) return `无效数字: ${num}`
      tokens.push({ kind: 'num', value: n })
      continue
    }
    if ('+-*/%'.includes(ch)) {
      // Handle ** (power)
      if (ch === '*' && expr[i + 1] === '*') {
        tokens.push({ kind: 'op', value: '**' })
        i += 2; continue
      }
      tokens.push({ kind: 'op', value: ch })
      i++; continue
    }
    if (ch === '(') { tokens.push({ kind: 'lparen' }); i++; continue }
    if (ch === ')') { tokens.push({ kind: 'rparen' }); i++; continue }
    return `不允许的字符: '${ch}'`
  }
  return tokens
}

// ── Recursive-descent parser / evaluator ─────────────────────────────────────

class Parser {
  private tokens: Token[]
  private pos = 0

  constructor(tokens: Token[]) { this.tokens = tokens }

  private peek(): Token | undefined { return this.tokens[this.pos] }

  private consume(): Token {
    const t = this.tokens[this.pos++]
    if (!t) throw new Error('表达式不完整')
    return t
  }

  /** additive: term (('+' | '-') term)* */
  parseExpr(): number {
    let left = this.parseTerm()
    while (true) {
      const t = this.peek()
      if (!t || t.kind !== 'op' || (t.value !== '+' && t.value !== '-')) break
      this.pos++
      const right = this.parseTerm()
      left = t.value === '+' ? left + right : left - right
    }
    return left
  }

  /** term: power (('*' | '/' | '%') power)* */
  private parseTerm(): number {
    let left = this.parsePower()
    while (true) {
      const t = this.peek()
      if (!t || t.kind !== 'op' || !['*', '/', '%'].includes(t.value)) break
      this.pos++
      const right = this.parsePower()
      if (t.value === '*') left *= right
      else if (t.value === '/') {
        if (right === 0) throw new Error('除数为零')
        left /= right
      } else left %= right
    }
    return left
  }

  /** power: unary ('**' unary)* (right-associative) */
  private parsePower(): number {
    const base = this.parseUnary()
    const t = this.peek()
    if (t?.kind === 'op' && t.value === '**') {
      this.pos++
      const exp = this.parsePower() // right-associative
      return Math.pow(base, exp)
    }
    return base
  }

  /** unary: ('-' | '+')? atom */
  private parseUnary(): number {
    const t = this.peek()
    if (t?.kind === 'op' && (t.value === '-' || t.value === '+')) {
      this.pos++
      const val = this.parseUnary()
      return t.value === '-' ? -val : val
    }
    return this.parseAtom()
  }

  /** atom: number | '(' expr ')' */
  private parseAtom(): number {
    const t = this.consume()
    if (t.kind === 'num') return t.value
    if (t.kind === 'lparen') {
      const val = this.parseExpr()
      const close = this.consume()
      if (close.kind !== 'rparen') throw new Error('缺少右括号')
      return val
    }
    throw new Error(`意外的 token: ${JSON.stringify(t)}`)
  }
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Evaluate an arithmetic expression safely without using Function() or eval().
 *
 * @param expression - raw user input, e.g. "2 + 3 * (4 - 1)"
 * @returns ArithmeticResult with ok=true and value, or ok=false and error
 */
export function evaluateArithmetic(expression: string): ArithmeticResult {
  if (!expression || !expression.trim()) {
    return { ok: false, error: '表达式为空' }
  }

  const tokens = tokenise(expression.trim())
  if (typeof tokens === 'string') {
    return { ok: false, error: tokens }
  }

  try {
    const parser = new Parser(tokens)
    const value = parser.parseExpr()
    // Ensure all tokens were consumed (no trailing garbage)
    if (parser['pos'] < tokens.length) {
      return { ok: false, error: `表达式解析不完整，剩余: ${expression.slice(parser['pos'])}` }
    }
    if (!isFinite(value)) {
      return { ok: false, error: `结果不是有限数: ${value}` }
    }
    return { ok: true, value }
  } catch (e) {
    return { ok: false, error: String(e instanceof Error ? e.message : e) }
  }
}
