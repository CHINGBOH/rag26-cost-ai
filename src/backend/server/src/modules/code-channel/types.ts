/**
 * 验证码发送通道抽象 — 短信 / 邮箱 / mock
 * Issue #156
 */

export type CodeChannel = 'sms' | 'email';
export type CodePurpose = 'register' | 'login' | 'reset' | 'bind';

export interface SendCodeRequest {
  channel: CodeChannel;
  recipient: string;
  code: string;
  purpose: CodePurpose;
}

export interface SendCodeResult {
  success: boolean;
  provider: string;
  messageId?: string;
  error?: string;
}

export interface CodeProvider {
  readonly name: string;
  readonly channel: CodeChannel;
  send(req: SendCodeRequest): Promise<SendCodeResult>;
}

export function generateNumericCode(length = 6): string {
  let code = '';
  for (let i = 0; i < length; i++) {
    code += Math.floor(Math.random() * 10);
  }
  return code;
}
