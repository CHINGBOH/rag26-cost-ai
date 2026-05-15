/**
 * Cloudflare Turnstile 服务端校验（云端第二道闸）
 * Issue #156
 * Docs: https://developers.cloudflare.com/turnstile/get-started/server-side-validation/
 */

const TURNSTILE_VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify';

export interface TurnstileResult {
  success: boolean;
  challenge_ts?: string;
  hostname?: string;
  action?: string;
  cdata?: string;
  'error-codes'?: string[];
}

export async function verifyTurnstile(
  token: string,
  secret: string,
  remoteIp?: string,
  fetchImpl: typeof fetch = fetch,
): Promise<TurnstileResult> {
  if (!secret) {
    return { success: true, 'error-codes': ['secret-not-configured'] };
  }
  if (!token) {
    return { success: false, 'error-codes': ['missing-input-response'] };
  }

  const form = new URLSearchParams();
  form.set('secret', secret);
  form.set('response', token);
  if (remoteIp) form.set('remoteip', remoteIp);

  try {
    const resp = await fetchImpl(TURNSTILE_VERIFY_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form.toString(),
    });
    if (!resp.ok) {
      return { success: false, 'error-codes': [`http-${resp.status}`] };
    }
    return (await resp.json()) as TurnstileResult;
  } catch (err) {
    return { success: false, 'error-codes': ['network-error'] };
  }
}
