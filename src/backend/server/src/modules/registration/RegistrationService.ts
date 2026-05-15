/**
 * Registration / passwordless-login service
 * Issue #156
 *
 * Orchestrates: captcha → rate-limit → generate-code → provider.send → store-hash
 *               → consume code → create-or-find user → issue token
 *
 * Storage is abstracted: in-memory by default (zero deps for tests),
 * pluggable PostgresStore later (TODO Phase 1.5).
 */
import * as crypto from 'crypto';
import { hashAnswer } from '../captcha/svg';
import { verifyTurnstile, type TurnstileResult } from '../captcha/turnstile';
import {
  type CodeChannel,
  type CodeProvider,
  type CodePurpose,
  generateNumericCode,
} from '../code-channel';

const CODE_TTL_SECONDS = 300;
const CODE_LENGTH = 6;
const SEND_COOLDOWN_SECONDS = 60;
const IP_DAILY_REG_LIMIT = 3;
const IP_HOURLY_SEND_LIMIT = 5;

export interface AppUser {
  id: string;
  phone?: string;
  email?: string;
  passwordHash?: string;
  displayName?: string;
  role: 'user' | 'admin';
  status: 'active' | 'disabled' | 'pending';
  createdAt: number;
  lastLoginAt?: number;
}

export interface UserStore {
  findByIdentifier(channel: CodeChannel, recipient: string): Promise<AppUser | null>;
  create(input: {
    channel: CodeChannel;
    recipient: string;
    passwordHash?: string;
    displayName?: string;
    registeredIp?: string;
    registeredUa?: string;
  }): Promise<AppUser>;
  touchLogin(id: string, ip?: string): Promise<void>;
}

export interface CaptchaStore {
  putAnswer(id: string, hashedAnswer: string, ttlSeconds: number): Promise<void>;
  takeAnswer(id: string): Promise<string | null>;
}

export interface CodeStore {
  putCode(input: {
    channel: CodeChannel;
    recipient: string;
    codeHash: string;
    purpose: CodePurpose;
    expiresAt: number;
    clientIp?: string;
  }): Promise<{ id: string }>;
  takeLatestActive(channel: CodeChannel, recipient: string, purpose: CodePurpose): Promise<{ codeHash: string; expiresAt: number } | null>;
  markConsumed(channel: CodeChannel, recipient: string, purpose: CodePurpose): Promise<void>;
  // Rate limit helpers
  countRecentSends(channel: CodeChannel, recipient: string, sinceSeconds: number): Promise<number>;
  countRecentSendsByIp(ip: string, sinceSeconds: number): Promise<number>;
  countRegistrationsByIp(ip: string, sinceSeconds: number): Promise<number>;
}

export interface SvgCaptchaIssued {
  id: string;
  svg: string;
}

export interface RegistrationConfig {
  turnstileSecret?: string;
  requireTurnstile: boolean;
}

export interface SendCodeInput {
  channel: CodeChannel;
  recipient: string;
  purpose: CodePurpose;
  captchaId: string;
  captchaAnswer: string;
  turnstileToken?: string;
  clientIp?: string;
  clientUa?: string;
}

export interface SendCodeOutcome {
  ok: boolean;
  reason?:
    | 'invalid-captcha'
    | 'invalid-turnstile'
    | 'cooldown'
    | 'ip-quota'
    | 'send-failed'
    | 'invalid-recipient';
  detail?: string;
  retryAfter?: number;
}

export interface VerifyCodeInput {
  channel: CodeChannel;
  recipient: string;
  code: string;
  purpose: CodePurpose;
}

export class RegistrationService {
  constructor(
    private readonly providers: { sms?: CodeProvider; email?: CodeProvider },
    private readonly userStore: UserStore,
    private readonly captchaStore: CaptchaStore,
    private readonly codeStore: CodeStore,
    private readonly cfg: RegistrationConfig,
    private readonly clock: () => number = () => Date.now(),
  ) {}

  /** Step 1 — issue SVG captcha; client posts captchaId+answer in subsequent send-code call */
  async issueCaptcha(generator: () => { id: string; svg: string; answer: string }): Promise<SvgCaptchaIssued> {
    const { id, svg, answer } = generator();
    await this.captchaStore.putAnswer(id, hashAnswer(answer), 300);
    return { id, svg };
  }

  /** Step 2 — send verification code through chosen channel after captcha checks */
  async sendCode(input: SendCodeInput): Promise<SendCodeOutcome> {
    // ----- captcha check (always required) -----
    const expected = await this.captchaStore.takeAnswer(input.captchaId);
    if (!expected || expected !== hashAnswer(input.captchaAnswer)) {
      return { ok: false, reason: 'invalid-captcha' };
    }

    // ----- turnstile (optional second layer) -----
    if (this.cfg.requireTurnstile) {
      const t = await this.verifyTurnstile(input.turnstileToken, input.clientIp);
      if (!t.success) {
        return { ok: false, reason: 'invalid-turnstile', detail: (t['error-codes'] ?? []).join(',') };
      }
    }

    // ----- recipient validation -----
    if (!this.validateRecipient(input.channel, input.recipient)) {
      return { ok: false, reason: 'invalid-recipient' };
    }

    // ----- per-recipient cooldown -----
    const cooldownHits = await this.codeStore.countRecentSends(input.channel, input.recipient, SEND_COOLDOWN_SECONDS);
    if (cooldownHits > 0) {
      return { ok: false, reason: 'cooldown', retryAfter: SEND_COOLDOWN_SECONDS };
    }

    // ----- per-IP hourly quota -----
    if (input.clientIp) {
      const ipHits = await this.codeStore.countRecentSendsByIp(input.clientIp, 3600);
      if (ipHits >= IP_HOURLY_SEND_LIMIT) {
        return { ok: false, reason: 'ip-quota', detail: 'hourly-send-limit-reached', retryAfter: 3600 };
      }
    }

    // ----- send -----
    const provider = input.channel === 'sms' ? this.providers.sms : this.providers.email;
    if (!provider) {
      return { ok: false, reason: 'send-failed', detail: `no-provider-for-${input.channel}` };
    }

    const code = generateNumericCode(CODE_LENGTH);
    const codeHash = hashCode(code);
    const expiresAt = this.clock() + CODE_TTL_SECONDS * 1000;

    await this.codeStore.putCode({
      channel: input.channel,
      recipient: input.recipient,
      codeHash,
      purpose: input.purpose,
      expiresAt,
      clientIp: input.clientIp,
    });

    const result = await provider.send({
      channel: input.channel,
      recipient: input.recipient,
      code,
      purpose: input.purpose,
    });

    if (!result.success) {
      return { ok: false, reason: 'send-failed', detail: result.error };
    }
    return { ok: true };
  }

  /** Step 3a — register new user using code */
  async registerWithCode(input: {
    channel: CodeChannel;
    recipient: string;
    code: string;
    password?: string;
    displayName?: string;
    clientIp?: string;
    clientUa?: string;
  }): Promise<{ ok: true; user: AppUser } | { ok: false; reason: string }> {
    const codeOk = await this.consumeCode({
      channel: input.channel,
      recipient: input.recipient,
      code: input.code,
      purpose: 'register',
    });
    if (!codeOk.ok) return { ok: false, reason: codeOk.reason };

    // 同 IP 单日注册上限
    if (input.clientIp) {
      const dailyRegs = await this.codeStore.countRegistrationsByIp(input.clientIp, 86400);
      if (dailyRegs >= IP_DAILY_REG_LIMIT) {
        return { ok: false, reason: 'ip-registration-quota' };
      }
    }

    const existing = await this.userStore.findByIdentifier(input.channel, input.recipient);
    if (existing) {
      return { ok: false, reason: 'already-registered' };
    }

    const passwordHash = input.password ? hashPassword(input.password) : undefined;
    const user = await this.userStore.create({
      channel: input.channel,
      recipient: input.recipient,
      passwordHash,
      displayName: input.displayName,
      registeredIp: input.clientIp,
      registeredUa: input.clientUa,
    });
    return { ok: true, user };
  }

  /** Step 3b — passwordless login via code */
  async loginWithCode(input: VerifyCodeInput & { clientIp?: string }): Promise<{ ok: true; user: AppUser } | { ok: false; reason: string }> {
    const codeOk = await this.consumeCode({ ...input, purpose: 'login' });
    if (!codeOk.ok) return { ok: false, reason: codeOk.reason };

    const user = await this.userStore.findByIdentifier(input.channel, input.recipient);
    if (!user) return { ok: false, reason: 'user-not-found' };
    if (user.status !== 'active') return { ok: false, reason: 'account-disabled' };

    await this.userStore.touchLogin(user.id, input.clientIp);
    return { ok: true, user };
  }

  private async consumeCode(input: VerifyCodeInput): Promise<{ ok: true } | { ok: false; reason: string }> {
    const row = await this.codeStore.takeLatestActive(input.channel, input.recipient, input.purpose);
    if (!row) return { ok: false, reason: 'no-pending-code' };
    if (row.expiresAt < this.clock()) return { ok: false, reason: 'code-expired' };
    if (row.codeHash !== hashCode(input.code)) return { ok: false, reason: 'invalid-code' };
    await this.codeStore.markConsumed(input.channel, input.recipient, input.purpose);
    return { ok: true };
  }

  private validateRecipient(channel: CodeChannel, recipient: string): boolean {
    if (channel === 'sms') {
      return /^\+\d{6,15}$/.test(recipient) || /^1[3-9]\d{9}$/.test(recipient);
    }
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(recipient);
  }

  private async verifyTurnstile(token: string | undefined, ip?: string): Promise<TurnstileResult> {
    if (!this.cfg.turnstileSecret) return { success: true, 'error-codes': ['secret-not-configured'] };
    return verifyTurnstile(token ?? '', this.cfg.turnstileSecret, ip);
  }
}

// ----- helpers -----

function hashCode(code: string): string {
  return crypto.createHash('sha256').update(code).digest('hex');
}

export function hashPassword(password: string, salt = crypto.randomBytes(16).toString('hex')): string {
  const hash = crypto.pbkdf2Sync(password, salt, 10000, 64, 'sha256').toString('hex');
  return `${salt}$${hash}`;
}

export function verifyPassword(password: string, stored: string): boolean {
  const [salt, hash] = stored.split('$');
  if (!salt || !hash) return false;
  const computed = crypto.pbkdf2Sync(password, salt, 10000, 64, 'sha256').toString('hex');
  try {
    return crypto.timingSafeEqual(Buffer.from(hash, 'hex'), Buffer.from(computed, 'hex'));
  } catch {
    return false;
  }
}
