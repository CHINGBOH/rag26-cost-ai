/**
 * SMTP 邮箱验证码 provider — 兼容腾讯企业邮 / 阿里云邮 / Gmail
 * Issue #156
 */
import type { CodeProvider, SendCodeRequest, SendCodeResult } from './types';

export interface SmtpEmailConfig {
  host: string;
  port: number;
  secure: boolean;
  user: string;
  pass: string;
  fromAddress: string;
  fromName?: string;
  appName?: string;
}

type SendMailFn = (opts: {
  from: string;
  to: string;
  subject: string;
  text: string;
  html: string;
}) => Promise<{ messageId?: string }>;

export class SmtpEmailProvider implements CodeProvider {
  public readonly name = 'smtp-email';
  public readonly channel = 'email' as const;

  constructor(private readonly config: SmtpEmailConfig, private readonly sendMail?: SendMailFn) {
    if (!config.host || !config.user || !config.fromAddress) {
      throw new Error('[SmtpEmailProvider] missing required config (host/user/fromAddress)');
    }
  }

  async send(req: SendCodeRequest): Promise<SendCodeResult> {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(req.recipient)) {
      return { success: false, provider: this.name, error: 'invalid-email' };
    }

    const app = this.config.appName ?? 'RAG Dashboard';
    const subject = `【${app}】您的验证码：${req.code}`;
    const text = `您的验证码是：${req.code}，5 分钟内有效。如非本人操作，请忽略此邮件。`;
    const html = `<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.6;color:#333">
      <p>您好，</p>
      <p>您正在使用 <strong>${app}</strong>，验证码为：</p>
      <p style="font-size:24px;font-weight:bold;letter-spacing:4px;color:#1a73e8">${req.code}</p>
      <p>验证码 5 分钟内有效。如非本人操作，请忽略此邮件。</p>
    </div>`;
    const from = this.config.fromName ? `${this.config.fromName} <${this.config.fromAddress}>` : this.config.fromAddress;

    try {
      const sender = this.sendMail ?? (await this.lazyNodemailer());
      const info = await sender({ from, to: req.recipient, subject, text, html });
      return { success: true, provider: this.name, messageId: info.messageId };
    } catch (err: any) {
      return { success: false, provider: this.name, error: err?.message ?? 'smtp-error' };
    }
  }

  private async lazyNodemailer(): Promise<SendMailFn> {
    const mod = await import('nodemailer').catch(() => null);
    if (!mod) {
      throw new Error('nodemailer not installed; run: npm i nodemailer');
    }
    const transporter = (mod as any).createTransport({
      host: this.config.host,
      port: this.config.port,
      secure: this.config.secure,
      auth: { user: this.config.user, pass: this.config.pass },
    });
    return (opts) => transporter.sendMail(opts);
  }
}
