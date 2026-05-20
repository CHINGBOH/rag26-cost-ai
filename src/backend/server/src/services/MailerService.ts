/**
 * MailerService — 极简 SMTP 邮件发送（用于邮箱验证码）。
 *
 * 行为：
 * - 若环境变量 SMTP_HOST 未配置，sendVerificationCode() 返回 sent=false，
 *   调用方应回退到日志（保持开发期可用）。
 * - 若配置完整，则用 nodemailer 真发邮件。
 *
 * 必需 env：
 *   SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
 * 可选 env：
 *   SMTP_SECURE       (true|false，默认 端口 465 时为 true，其它 false)
 *   SMTP_FROM_NAME    (默认 'ThreeFireStone')
 *   SMTP_FROM_ADDR    (默认 = SMTP_USER)
 */

import * as nodemailer from 'nodemailer';
import type { Transporter } from 'nodemailer';
import { logger } from './LoggerService';

let cachedTransporter: Transporter | null = null;
let smtpEnabled = false;

function initTransporter(): Transporter | null {
  if (cachedTransporter) return cachedTransporter;

  const host = process.env.SMTP_HOST;
  const portStr = process.env.SMTP_PORT;
  const user = process.env.SMTP_USER;
  const pass = process.env.SMTP_PASS;

  if (!host || !portStr || !user || !pass) {
    smtpEnabled = false;
    return null;
  }

  const port = Number(portStr);
  if (!Number.isFinite(port) || port <= 0) {
    logger.warn(`[Mailer] SMTP_PORT 非法: ${portStr}，禁用 SMTP 发送`);
    smtpEnabled = false;
    return null;
  }

  const secureEnv = (process.env.SMTP_SECURE ?? '').toLowerCase();
  const secure = secureEnv ? secureEnv === 'true' || secureEnv === '1' : port === 465;

  cachedTransporter = nodemailer.createTransport({
    host,
    port,
    secure,
    auth: { user, pass },
  });
  smtpEnabled = true;
  logger.info(`[Mailer] SMTP 已启用 host=${host} port=${port} secure=${secure} user=${user}`);
  return cachedTransporter;
}

export function isMailerEnabled(): boolean {
  if (!cachedTransporter) initTransporter();
  return smtpEnabled;
}

/**
 * 发送验证码邮件。
 * @returns sent=true 表示已通过 SMTP 投递；sent=false 表示未配置 SMTP，调用方应回退日志。
 */
export async function sendVerificationCode(
  toEmail: string,
  code: string,
  purpose: 'signup' | 'reset',
  ttlSeconds: number
): Promise<{ sent: boolean; error?: string }> {
  const transporter = initTransporter();
  if (!transporter) return { sent: false };

  const fromName = process.env.SMTP_FROM_NAME || 'ThreeFireStone';
  const fromAddr = process.env.SMTP_FROM_ADDR || process.env.SMTP_USER!;
  const ttlMinutes = Math.max(1, Math.round(ttlSeconds / 60));
  const subject = purpose === 'signup' ? '【ThreeFireStone】注册验证码' : '【ThreeFireStone】重置密码验证码';
  const action = purpose === 'signup' ? '注册' : '重置密码';

  const text = [
    `您好，`,
    ``,
    `您的${action}验证码是： ${code}`,
    ``,
    `验证码 ${ttlMinutes} 分钟内有效，请勿泄露给他人。`,
    `若非本人操作，请忽略此邮件。`,
    ``,
    `— ThreeFireStone`,
  ].join('\n');

  const html = `
    <div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#111;max-width:480px;margin:0 auto;padding:32px 24px;">
      <h2 style="margin:0 0 16px;font-weight:600;font-size:18px;color:#111;">ThreeFireStone</h2>
      <p style="margin:0 0 16px;color:#333;font-size:14px;line-height:1.6;">
        您的${action}验证码：
      </p>
      <div style="font-size:28px;font-weight:700;letter-spacing:6px;color:#111;background:#f5f5f7;padding:16px 20px;border-radius:12px;text-align:center;">
        ${code}
      </div>
      <p style="margin:16px 0 0;color:#666;font-size:12px;line-height:1.6;">
        ${ttlMinutes} 分钟内有效。若非本人操作，请忽略此邮件。
      </p>
    </div>
  `;

  try {
    await transporter.sendMail({
      from: `"${fromName}" <${fromAddr}>`,
      to: toEmail,
      subject,
      text,
      html,
    });
    return { sent: true };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    logger.error(`[Mailer] 邮件发送失败 to=${toEmail}: ${msg}`);
    return { sent: false, error: msg };
  }
}
