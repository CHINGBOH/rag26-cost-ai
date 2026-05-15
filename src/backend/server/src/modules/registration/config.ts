/**
 * Registration / auth-extension config loader
 * Issue #156
 *
 * Reads from process.env (already populated by bootstrap-env) and validates
 * with Zod. Following project precedence: default < .env / env var.
 *
 * NOTE: This is an isolated, domain-specific config surface. It complements
 * `src/config/runtime.ts` rather than replacing it. When mature, sections
 * should migrate into RuntimeConfigSchema.
 */
import { z } from 'zod';

const NumLike = (defaultValue: number) =>
  z
    .union([z.string(), z.number()])
    .transform((v) => Number(v))
    .pipe(z.number().int().positive())
    .default(defaultValue);

const BoolLike = (defaultValue: boolean) =>
  z
    .union([z.string(), z.boolean()])
    .transform((v) => (typeof v === 'boolean' ? v : v === 'true' || v === '1'))
    .default(defaultValue);

const SmsSchema = z
  .object({
    enabled: BoolLike(false),
    secretId: z.string().default(''),
    secretKey: z.string().default(''),
    region: z.string().default('ap-guangzhou'),
    smsSdkAppId: z.string().default(''),
    signName: z.string().default(''),
    templateId: z.string().default(''),
  })
  .transform((v) => ({
    ...v,
    // auto-disable when required fields missing
    enabled: v.enabled && !!v.secretId && !!v.secretKey && !!v.smsSdkAppId && !!v.signName && !!v.templateId,
  }));

const EmailSchema = z
  .object({
    enabled: BoolLike(false),
    host: z.string().default(''),
    port: NumLike(465),
    secure: BoolLike(true),
    user: z.string().default(''),
    pass: z.string().default(''),
    fromAddress: z.string().default(''),
    fromName: z.string().default('RAG Dashboard'),
    appName: z.string().default('RAG Dashboard'),
  })
  .transform((v) => ({
    ...v,
    enabled: v.enabled && !!v.host && !!v.user && !!v.fromAddress,
  }));

const CaptchaSchema = z.object({
  turnstileSecret: z.string().default(''),
  turnstileSiteKey: z.string().default(''),
  requireTurnstile: BoolLike(false),
});

const RegistrationSchema = z.object({
  enabled: BoolLike(true),
  // 配合 Phase 1：未提供凭证时仍走 mock，便于测试
  allowMockInProduction: BoolLike(false),
  cookieName: z.string().default('rag_auth_token'),
  cookieSecure: BoolLike(false),
  cookieSameSite: z.enum(['lax', 'strict', 'none']).default('lax'),
});

const AuthExtConfigSchema = z.object({
  sms: SmsSchema,
  email: EmailSchema,
  captcha: CaptchaSchema,
  registration: RegistrationSchema,
});

export type AuthExtConfig = z.output<typeof AuthExtConfigSchema>;

export function loadAuthExtConfig(env: NodeJS.ProcessEnv = process.env): AuthExtConfig {
  return AuthExtConfigSchema.parse({
    sms: {
      enabled: env.TENCENT_SMS_ENABLED,
      secretId: env.TENCENT_SMS_SECRET_ID,
      secretKey: env.TENCENT_SMS_SECRET_KEY,
      region: env.TENCENT_SMS_REGION,
      smsSdkAppId: env.TENCENT_SMS_SDK_APP_ID,
      signName: env.TENCENT_SMS_SIGN_NAME,
      templateId: env.TENCENT_SMS_TEMPLATE_ID,
    },
    email: {
      enabled: env.SMTP_ENABLED,
      host: env.SMTP_HOST,
      port: env.SMTP_PORT,
      secure: env.SMTP_SECURE,
      user: env.SMTP_USER,
      pass: env.SMTP_PASS,
      fromAddress: env.SMTP_FROM_ADDRESS,
      fromName: env.SMTP_FROM_NAME,
      appName: env.AUTH_APP_NAME,
    },
    captcha: {
      turnstileSecret: env.TURNSTILE_SECRET,
      turnstileSiteKey: env.TURNSTILE_SITE_KEY,
      requireTurnstile: env.TURNSTILE_REQUIRED,
    },
    registration: {
      enabled: env.REGISTRATION_ENABLED,
      allowMockInProduction: env.REGISTRATION_ALLOW_MOCK,
      cookieName: env.AUTH_COOKIE_NAME,
      cookieSecure: env.AUTH_COOKIE_SECURE,
      cookieSameSite: (env.AUTH_COOKIE_SAMESITE as any) ?? undefined,
    },
  });
}
