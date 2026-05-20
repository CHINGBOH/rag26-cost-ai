/**
 * EmailAuthService — 邮箱注册 + 邮箱验证码登录
 *
 * 与 AuthService 协作：复用其 hashPassword / verifyPassword / generateTokenFor /
 * trackSession，保证 JWT 校验逻辑一致。
 *
 * 用户与验证码持久化到 PostgreSQL（rag-postgres）。
 * 邮件发送：
 * - 若配置了 SMTP_* 环境变量，则通过 MailerService 真发邮件。
 * - 否则回退到日志（[EMAIL CODE]），保留开发期可用性。
 */

import * as crypto from 'crypto';
import type { Pool } from 'pg';
import { AuthService } from './AuthService';
import { logger } from './LoggerService';
import { sendVerificationCode, isMailerEnabled } from './MailerService';

export interface RegisteredUser {
  id: string;
  email: string;
  role: 'admin' | 'user';
  emailVerified: boolean;
  createdAt: number;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const CODE_TTL_SECONDS = 5 * 60;        // 验证码 5 分钟有效
const CODE_RESEND_SECONDS = 60;          // 同一邮箱 60s 内不能重复请求
const MAX_PENDING_PER_EMAIL = 5;         // 同一邮箱最多 5 个未使用未过期的验证码

export class EmailAuthService {
  constructor(private readonly pool: Pool, private readonly authService: AuthService) {}

  /** 建表（应用启动时调一次） */
  async initialize(): Promise<void> {
    const client = await this.pool.connect();
    try {
      await client.query(`
        CREATE TABLE IF NOT EXISTS users (
          id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          email          TEXT UNIQUE NOT NULL,
          password_hash  TEXT NOT NULL,
          role           TEXT NOT NULL DEFAULT 'user',
          email_verified BOOLEAN NOT NULL DEFAULT FALSE,
          created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          last_login_at  TIMESTAMPTZ
        );
      `);
      await client.query(`
        CREATE TABLE IF NOT EXISTS email_codes (
          id          BIGSERIAL PRIMARY KEY,
          email       TEXT NOT NULL,
          code        TEXT NOT NULL,
          purpose     TEXT NOT NULL,
          expires_at  TIMESTAMPTZ NOT NULL,
          used        BOOLEAN NOT NULL DEFAULT FALSE,
          created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
      `);
      await client.query(
        `CREATE INDEX IF NOT EXISTS email_codes_lookup_idx
           ON email_codes (email, purpose, used, expires_at);`
      );
      logger.info('✅ EmailAuthService 表已就绪 (users, email_codes)');
    } finally {
      client.release();
    }
  }

  /**
   * 发送验证码（注册 / 重置密码）。
   * - 邮件 SMTP 暂未接入，验证码会打印到后端日志。
   * - 60s 节流；同一邮箱待用码上限 5 个。
   */
  async sendCode(emailRaw: string, purpose: 'signup' | 'reset'): Promise<{ ok: true } | { ok: false; reason: string }> {
    const email = normalizeEmail(emailRaw);
    if (!EMAIL_RE.test(email)) {
      return { ok: false, reason: '邮箱格式不正确' };
    }

    const client = await this.pool.connect();
    try {
      // 节流：60s 内同一邮箱+用途不能重发
      const recent = await client.query<{ created_at: Date }>(
        `SELECT created_at FROM email_codes
          WHERE email = $1 AND purpose = $2
          ORDER BY created_at DESC LIMIT 1`,
        [email, purpose]
      );
      if (recent.rows.length > 0) {
        const ageMs = Date.now() - recent.rows[0].created_at.getTime();
        if (ageMs < CODE_RESEND_SECONDS * 1000) {
          const wait = Math.ceil((CODE_RESEND_SECONDS * 1000 - ageMs) / 1000);
          return { ok: false, reason: `请求过于频繁，请 ${wait}s 后再试` };
        }
      }

      // 上限：未过期未使用的验证码不能超过 5 个
      const pending = await client.query<{ n: string }>(
        `SELECT COUNT(*)::TEXT AS n FROM email_codes
          WHERE email = $1 AND purpose = $2 AND used = FALSE AND expires_at > NOW()`,
        [email, purpose]
      );
      if (Number(pending.rows[0].n) >= MAX_PENDING_PER_EMAIL) {
        return { ok: false, reason: '该邮箱待用验证码过多，请稍后再试' };
      }

      const code = generateNumericCode(6);
      await client.query(
        `INSERT INTO email_codes (email, code, purpose, expires_at)
         VALUES ($1, $2, $3, NOW() + ($4 || ' seconds')::interval)`,
        [email, code, purpose, String(CODE_TTL_SECONDS)]
      );

      // 发送邮件 — 配了 SMTP 走 SMTP，否则回退日志（开发期）
      if (isMailerEnabled()) {
        const result = await sendVerificationCode(email, code, purpose, CODE_TTL_SECONDS);
        if (!result.sent) {
          logger.warn(`[EmailAuth] SMTP 发送失败，回退日志: ${result.error ?? 'unknown'}`);
          logger.info(`[EMAIL CODE] purpose=${purpose} email=${email} code=${code} ttl=${CODE_TTL_SECONDS}s`);
        }
      } else {
        logger.info(`[EMAIL CODE] purpose=${purpose} email=${email} code=${code} ttl=${CODE_TTL_SECONDS}s`);
      }

      return { ok: true };
    } finally {
      client.release();
    }
  }

  /**
   * 邮箱注册：校验验证码 → 哈希密码 → 建用户 → 直接发 JWT
   */
  async register(emailRaw: string, password: string, code: string):
    Promise<{ ok: true; token: string; user: RegisteredUser } | { ok: false; reason: string }>
  {
    const email = normalizeEmail(emailRaw);
    if (!EMAIL_RE.test(email)) return { ok: false, reason: '邮箱格式不正确' };
    if (password.length < 8) return { ok: false, reason: '密码长度不能少于 8 位' };
    if (!/^\d{6}$/.test(code)) return { ok: false, reason: '验证码格式不正确' };

    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');

      // 1. 校验验证码（同时锁行，防并发用一码注册多账号）
      const codeRow = await client.query<{ id: number }>(
        `SELECT id FROM email_codes
          WHERE email = $1 AND code = $2 AND purpose = 'signup'
            AND used = FALSE AND expires_at > NOW()
          ORDER BY id DESC LIMIT 1
          FOR UPDATE`,
        [email, code]
      );
      if (codeRow.rows.length === 0) {
        await client.query('ROLLBACK');
        return { ok: false, reason: '验证码错误或已过期' };
      }

      // 2. 邮箱唯一
      const existing = await client.query(
        `SELECT id FROM users WHERE email = $1 LIMIT 1`,
        [email]
      );
      if (existing.rows.length > 0) {
        await client.query('ROLLBACK');
        return { ok: false, reason: '该邮箱已注册，请直接登录' };
      }

      // 3. 创建用户
      const passwordHash = this.authService.hashPassword(password);
      const inserted = await client.query<{ id: string; created_at: Date }>(
        `INSERT INTO users (email, password_hash, role, email_verified, last_login_at)
         VALUES ($1, $2, 'user', TRUE, NOW())
         RETURNING id, created_at`,
        [email, passwordHash]
      );
      const userRow = inserted.rows[0];

      // 4. 标记验证码已用
      await client.query(`UPDATE email_codes SET used = TRUE WHERE id = $1`, [codeRow.rows[0].id]);

      await client.query('COMMIT');

      // 5. 签发 token（用户名即邮箱）
      const user: RegisteredUser = {
        id: userRow.id,
        email,
        role: 'user',
        emailVerified: true,
        createdAt: userRow.created_at.getTime(),
      };
      const token = await this.authService.generateTokenFor({
        id: user.id, username: user.email, role: user.role,
      });
      this.authService.trackSession(token, user.id);

      logger.info(`[EmailAuth] 新用户注册成功: ${email}`);
      return { ok: true, token, user };
    } catch (err) {
      await client.query('ROLLBACK').catch(() => {});
      logger.error(`[EmailAuth] 注册失败 ${email}: ${(err as Error).message}`);
      return { ok: false, reason: '注册失败，请稍后重试' };
    } finally {
      client.release();
    }
  }

  /**
   * 邮箱 + 密码登录（无验证码，已注册用户）
   */
  async loginWithEmail(emailRaw: string, password: string):
    Promise<{ ok: true; token: string; user: RegisteredUser } | { ok: false; reason: string }>
  {
    const email = normalizeEmail(emailRaw);
    if (!EMAIL_RE.test(email)) return { ok: false, reason: '邮箱格式不正确' };

    const client = await this.pool.connect();
    try {
      const res = await client.query<{
        id: string; email: string; password_hash: string;
        role: 'admin' | 'user'; email_verified: boolean; created_at: Date;
      }>(
        `SELECT id, email, password_hash, role, email_verified, created_at
           FROM users WHERE email = $1 LIMIT 1`,
        [email]
      );
      if (res.rows.length === 0) return { ok: false, reason: '邮箱或密码错误' };
      const row = res.rows[0];

      if (!this.authService.verifyPassword(password, row.password_hash)) {
        return { ok: false, reason: '邮箱或密码错误' };
      }

      await client.query(`UPDATE users SET last_login_at = NOW() WHERE id = $1`, [row.id]);

      const user: RegisteredUser = {
        id: row.id,
        email: row.email,
        role: row.role,
        emailVerified: row.email_verified,
        createdAt: row.created_at.getTime(),
      };
      const token = await this.authService.generateTokenFor({
        id: user.id, username: user.email, role: user.role,
      });
      this.authService.trackSession(token, user.id);

      logger.info(`[EmailAuth] 用户登录: ${email}`);
      return { ok: true, token, user };
    } finally {
      client.release();
    }
  }
}

function normalizeEmail(input: string): string {
  return (input || '').trim().toLowerCase();
}

function generateNumericCode(len: number): string {
  let out = '';
  while (out.length < len) {
    const byte = crypto.randomBytes(1)[0];
    if (byte < 250) out += (byte % 10).toString();
  }
  return out;
}
