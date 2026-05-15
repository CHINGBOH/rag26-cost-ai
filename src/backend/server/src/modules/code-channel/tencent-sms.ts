/**
 * 腾讯云短信 Provider — TC3-HMAC-SHA256 直连，无 SDK 依赖
 * Issue #156
 * Docs: https://cloud.tencent.com/document/product/382/55981
 */
import * as crypto from 'crypto';
import type { CodeProvider, SendCodeRequest, SendCodeResult } from './types';

export interface TencentSmsConfig {
  secretId: string;
  secretKey: string;
  region: string;
  smsSdkAppId: string;
  signName: string;
  templateId: string;
  endpoint?: string;
}

const DEFAULT_ENDPOINT = 'sms.tencentcloudapi.com';

function sha256Hex(s: string): string {
  return crypto.createHash('sha256').update(s).digest('hex');
}
function hmacSha256(key: Buffer | string, msg: string): Buffer {
  return crypto.createHmac('sha256', key).update(msg, 'utf8').digest();
}
function getDate(timestamp: number): string {
  return new Date(timestamp * 1000).toISOString().slice(0, 10);
}

export class TencentSmsProvider implements CodeProvider {
  public readonly name = 'tencent-sms';
  public readonly channel = 'sms' as const;
  private readonly endpoint: string;

  constructor(private readonly config: TencentSmsConfig, private readonly fetchImpl: typeof fetch = fetch) {
    this.endpoint = config.endpoint ?? DEFAULT_ENDPOINT;
    if (!config.secretId || !config.secretKey || !config.smsSdkAppId || !config.signName || !config.templateId) {
      throw new Error('[TencentSmsProvider] missing required config');
    }
  }

  async send(req: SendCodeRequest): Promise<SendCodeResult> {
    const phone = this.normalizePhone(req.recipient);
    if (!phone) return { success: false, provider: this.name, error: 'invalid-phone' };

    const body = {
      PhoneNumberSet: [phone],
      SmsSdkAppId: this.config.smsSdkAppId,
      SignName: this.config.signName,
      TemplateId: this.config.templateId,
      TemplateParamSet: [req.code, '5'],
    };

    const payload = JSON.stringify(body);
    const timestamp = Math.floor(Date.now() / 1000);
    const date = getDate(timestamp);
    const service = 'sms';
    const algorithm = 'TC3-HMAC-SHA256';

    const canonicalHeaders = `content-type:application/json; charset=utf-8\nhost:${this.endpoint}\n`;
    const signedHeaders = 'content-type;host';
    const hashedPayload = sha256Hex(payload);
    const canonicalRequest = ['POST', '/', '', canonicalHeaders, signedHeaders, hashedPayload].join('\n');
    const credentialScope = `${date}/${service}/tc3_request`;
    const stringToSign = [algorithm, timestamp, credentialScope, sha256Hex(canonicalRequest)].join('\n');

    const kDate = hmacSha256(`TC3${this.config.secretKey}`, date);
    const kService = hmacSha256(kDate, service);
    const kSigning = hmacSha256(kService, 'tc3_request');
    const signature = crypto.createHmac('sha256', kSigning).update(stringToSign, 'utf8').digest('hex');

    const authorization = `${algorithm} Credential=${this.config.secretId}/${credentialScope}, SignedHeaders=${signedHeaders}, Signature=${signature}`;

    try {
      const resp = await this.fetchImpl(`https://${this.endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json; charset=utf-8',
          Host: this.endpoint,
          'X-TC-Action': 'SendSms',
          'X-TC-Timestamp': String(timestamp),
          'X-TC-Version': '2021-01-11',
          'X-TC-Region': this.config.region,
          Authorization: authorization,
        },
        body: payload,
      });
      const data: any = await resp.json();
      if (data?.Response?.Error) {
        return { success: false, provider: this.name, error: `${data.Response.Error.Code}: ${data.Response.Error.Message}` };
      }
      const status = data?.Response?.SendStatusSet?.[0];
      if (status && status.Code !== 'Ok') {
        return { success: false, provider: this.name, error: `${status.Code}: ${status.Message}` };
      }
      return { success: true, provider: this.name, messageId: status?.SerialNo ?? data?.Response?.RequestId };
    } catch (err: any) {
      return { success: false, provider: this.name, error: err?.message ?? 'network-error' };
    }
  }

  private normalizePhone(phone: string): string | null {
    const trimmed = phone.replace(/\s+/g, '').trim();
    if (/^\+\d{6,15}$/.test(trimmed)) return trimmed;
    if (/^1[3-9]\d{9}$/.test(trimmed)) return `+86${trimmed}`;
    return null;
  }
}
