/**
 * In-memory store backed by Maps — used in tests and as a temporary fallback
 * until Phase 1.5 (Postgres-backed store) lands.
 * Issue #156
 */
import * as crypto from 'crypto';
import type { CodeChannel, CodePurpose } from '../code-channel/types';
import type { AppUser, CaptchaStore, CodeStore, UserStore } from './RegistrationService';

export class MemoryUserStore implements UserStore {
  private users = new Map<string, AppUser>();

  async findByIdentifier(channel: CodeChannel, recipient: string): Promise<AppUser | null> {
    for (const u of this.users.values()) {
      if (channel === 'sms' && u.phone === recipient) return u;
      if (channel === 'email' && u.email === recipient) return u;
    }
    return null;
  }

  async create(input: {
    channel: CodeChannel;
    recipient: string;
    passwordHash?: string;
    displayName?: string;
    registeredIp?: string;
    registeredUa?: string;
  }): Promise<AppUser> {
    const u: AppUser = {
      id: crypto.randomUUID(),
      phone: input.channel === 'sms' ? input.recipient : undefined,
      email: input.channel === 'email' ? input.recipient : undefined,
      passwordHash: input.passwordHash,
      displayName: input.displayName,
      role: 'user',
      status: 'active',
      createdAt: Date.now(),
    };
    this.users.set(u.id, u);
    return u;
  }

  async touchLogin(id: string, _ip?: string): Promise<void> {
    const u = this.users.get(id);
    if (u) u.lastLoginAt = Date.now();
  }
}

export class MemoryCaptchaStore implements CaptchaStore {
  private store = new Map<string, { hashedAnswer: string; expiresAt: number }>();

  async putAnswer(id: string, hashedAnswer: string, ttlSeconds: number): Promise<void> {
    this.store.set(id, { hashedAnswer, expiresAt: Date.now() + ttlSeconds * 1000 });
  }

  async takeAnswer(id: string): Promise<string | null> {
    const row = this.store.get(id);
    if (!row) return null;
    this.store.delete(id);
    if (row.expiresAt < Date.now()) return null;
    return row.hashedAnswer;
  }
}

interface CodeRow {
  channel: CodeChannel;
  recipient: string;
  purpose: CodePurpose;
  codeHash: string;
  expiresAt: number;
  consumed: boolean;
  createdAt: number;
  clientIp?: string;
}

export class MemoryCodeStore implements CodeStore {
  private rows: CodeRow[] = [];
  private registrationsByIp = new Map<string, number[]>();

  async putCode(input: {
    channel: CodeChannel;
    recipient: string;
    codeHash: string;
    purpose: CodePurpose;
    expiresAt: number;
    clientIp?: string;
  }): Promise<{ id: string }> {
    this.rows.push({ ...input, consumed: false, createdAt: Date.now() });
    return { id: crypto.randomUUID() };
  }

  async takeLatestActive(channel: CodeChannel, recipient: string, purpose: CodePurpose) {
    for (let i = this.rows.length - 1; i >= 0; i--) {
      const r = this.rows[i];
      if (r.channel === channel && r.recipient === recipient && r.purpose === purpose && !r.consumed) {
        return { codeHash: r.codeHash, expiresAt: r.expiresAt };
      }
    }
    return null;
  }

  async markConsumed(channel: CodeChannel, recipient: string, purpose: CodePurpose): Promise<void> {
    for (let i = this.rows.length - 1; i >= 0; i--) {
      const r = this.rows[i];
      if (r.channel === channel && r.recipient === recipient && r.purpose === purpose && !r.consumed) {
        r.consumed = true;
        if (purpose === 'register' && r.clientIp) {
          const list = this.registrationsByIp.get(r.clientIp) ?? [];
          list.push(Date.now());
          this.registrationsByIp.set(r.clientIp, list);
        }
        return;
      }
    }
  }

  async countRecentSends(channel: CodeChannel, recipient: string, sinceSeconds: number): Promise<number> {
    const cutoff = Date.now() - sinceSeconds * 1000;
    return this.rows.filter((r) => r.channel === channel && r.recipient === recipient && r.createdAt >= cutoff).length;
  }

  async countRecentSendsByIp(ip: string, sinceSeconds: number): Promise<number> {
    const cutoff = Date.now() - sinceSeconds * 1000;
    return this.rows.filter((r) => r.clientIp === ip && r.createdAt >= cutoff).length;
  }

  async countRegistrationsByIp(ip: string, sinceSeconds: number): Promise<number> {
    const cutoff = Date.now() - sinceSeconds * 1000;
    return (this.registrationsByIp.get(ip) ?? []).filter((t) => t >= cutoff).length;
  }
}
