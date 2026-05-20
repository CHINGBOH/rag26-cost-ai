/**
 * 腾讯云短信服务
 * 发送验证码短信，用 Redis 存储验证码（5分钟过期）
 */

import Redis from 'ioredis';
import * as crypto from 'crypto';

interface SmsConfig {
  secretId: string;
  secretKey: string;
  sdkAppId: string;
  signName: string;
  templateId: string;
  redisUrl: string;
}

const CODE_TTL_SECONDS = 300;
const CODE_KEY_PREFIX = 'sms:code:';
const RATE_KEY_PREFIX = 'sms:rate:';
const RATE_LIMIT_SECONDS = 60;

export class SmsService {
  private config: SmsConfig;
  private redis: Redis;

  constructor(config: SmsConfig) {
    this.config = config;
    this.redis = new Redis(config.redisUrl);
    this.redis.on('error', (err: Error) => {
      console.error('[SmsService] Redis 连接失败:', err.message);
    });
  }

  async sendCode(phone: string): Promise<true | string> {
    const rateKey = `${RATE_KEY_PREFIX}${phone}`;
    const exists = await this.redis.get(rateKey);
    if (exists) {
      return '发送太频繁，请60秒后再试';
    }

    const code = this.generateCode();
    const result = await this.callTencentSms(phone, code);
    if (result !== true) {
      return result;
    }

    const codeKey = `${CODE_KEY_PREFIX}${phone}`;
    await this.redis.setex(codeKey, CODE_TTL_SECONDS, code);
    await this.redis.setex(rateKey, RATE_LIMIT_SECONDS, '1');

    console.log(`[SmsService] 验证码已发送至 ${phone.slice(0, 3)}****${phone.slice(7)}`);
    return true;
  }

  async verifyCode(phone: string, code: string): Promise<boolean> {
    const codeKey = `${CODE_KEY_PREFIX}${phone}`;
    const stored = await this.redis.get(codeKey);

    if (!stored || stored !== code) {
      return false;
    }

    await this.redis.del(codeKey);
    return true;
  }

  private generateCode(): string {
    return String(crypto.randomInt(100000, 999999));
  }

  private async callTencentSms(phone: string, code: string): Promise<true | string> {
    const host = 'sms.tencentcloudapi.com';
    const service = 'sms';
    const version = '2021-01-11';
    const action = 'SendSms';
    const region = 'ap-guangzhou';
    const timestamp = Math.floor(Date.now() / 1000);
    const date = new Date(timestamp * 1000).toISOString().slice(0, 10);

    const payload = JSON.stringify({
      PhoneNumberSet: [`+86${phone}`],
      SmsSdkAppId: this.config.sdkAppId,
      SignName: this.config.signName,
      TemplateId: this.config.templateId,
      TemplateParamSet: [code, '5'],
    });

    const hashedPayload = crypto.createHash('sha256').update(payload).digest('hex');
    const canonicalRequest = [
      'POST', '/', '',
      `content-type:application/json\nhost:${host}\n`,
      'content-type;host',
      hashedPayload,
    ].join('\n');

    const credentialScope = `${date}/${service}/tc3_request`;
    const hashedCanonical = crypto.createHash('sha256').update(canonicalRequest).digest('hex');
    const stringToSign = `TC3-HMAC-SHA256\n${timestamp}\n${credentialScope}\n${hashedCanonical}`;

    const secretDate = crypto.createHmac('sha256', `TC3${this.config.secretKey}`).update(date).digest();
    const secretService = crypto.createHmac('sha256', secretDate).update(service).digest();
    const secretSigning = crypto.createHmac('sha256', secretService).update('tc3_request').digest();
    const signature = crypto.createHmac('sha256', secretSigning).update(stringToSign).digest('hex');

    const authorization = `TC3-HMAC-SHA256 Credential=${this.config.secretId}/${credentialScope}, SignedHeaders=content-type;host, Signature=${signature}`;

    try {
      const resp = await fetch(`https://${host}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Host': host,
          'Authorization': authorization,
          'X-TC-Action': action,
          'X-TC-Version': version,
          'X-TC-Timestamp': String(timestamp),
          'X-TC-Region': region,
        },
        body: payload,
      });

      const data = await resp.json() as any;
      const sendStatus = data?.Response?.SendStatusSet?.[0];

      if (sendStatus?.Code === 'Ok') {
        return true;
      }

      const errMsg = sendStatus?.Message || data?.Response?.Error?.Message || '短信发送失败';
      console.error('[SmsService] 腾讯云返回错误:', errMsg);
      return errMsg;
    } catch (err) {
      console.error('[SmsService] 请求失败:', (err as Error).message);
      return '短信服务暂时不可用，请稍后再试';
    }
  }

  async close(): Promise<void> {
    this.redis.disconnect();
  }
}
