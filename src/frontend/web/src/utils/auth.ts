/**
 * 认证工具
 * 管理 JWT Token 的获取、存储和自动注入
 */

const TOKEN_KEY = 'rag_dashboard_token';
const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export interface LoginResponse {
  success: boolean;
  data?: {
    token: string;
    user: {
      id: string;
      username: string;
      role: string;
    };
  };
  error?: {
    code: string;
    message: string;
  };
}

/**
 * 获取当前存储的 token
 */
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * 设置 token
 */
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

/**
 * 清除 token
 */
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

/**
 * 获取带认证的请求 headers
 */
export function getAuthHeaders(contentType?: string): Record<string, string> {
  const headers: Record<string, string> = {};
  if (contentType) {
    headers['Content-Type'] = contentType;
  }
  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

/**
 * 执行登录请求
 */
export async function login(username: string, password: string): Promise<string | null> {
  try {
    const response = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ username, password })
    });

    const result: LoginResponse = await response.json();

    if (response.ok && result.success && result.data?.token) {
      setToken(result.data.token);
      console.log(`[Auth] 登录成功: ${result.data.user.username}`);
      return result.data.token;
    } else {
      console.error('[Auth] 登录失败:', result.error?.message || '未知错误');
      return null;
    }
  } catch (err) {
    console.error('[Auth] 登录请求异常:', err);
    return null;
  }
}

/**
 * 使用默认凭据自动静默登录
 */
export async function autoLogin(): Promise<string | null> {
  return login('admin', 'admin123');
}

/**
 * 确保已认证（如果没有 token 则自动登录）
 */
export async function ensureAuth(): Promise<string | null> {
  const token = getToken();
  if (token) return token;
  return autoLogin();
}

/**
 * 带认证的 fetch 封装
 * 自动注入 Authorization header
 */
export async function authFetch(
  input: RequestInfo | URL,
  init?: RequestInit
): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init?.headers || {});

  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  return fetch(input, {
    ...init,
    headers
  });
}
