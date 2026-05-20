export interface AuthUser {
  id: string;
  username: string;
  role: string;
}

export interface AuthState {
  token: string;
  user: AuthUser;
}

export const AUTH_STORAGE_KEY = 'rag.auth';

export function readAuthState(): AuthState | null {
  if (typeof window === 'undefined') {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as AuthState) : null;
  } catch {
    return null;
  }
}

export function clearAuthState(): void {
  if (typeof window === 'undefined') {
    return;
  }

  window.localStorage.removeItem(AUTH_STORAGE_KEY);
  window.dispatchEvent(new Event('rag-auth-changed'));
}

function extractUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') {
    return input;
  }
  if (input instanceof URL) {
    return input.toString();
  }
  return input.url;
}

function isAuthExempt(url: string): boolean {
  return url.includes('/api/auth/login');
}

export function installAuthFetchInterceptor(): void {
  if (typeof window === 'undefined') {
    return;
  }

  const fetchWithFlag = window.fetch as typeof window.fetch & { __ragAuthInstalled?: boolean };
  if (fetchWithFlag.__ragAuthInstalled) {
    return;
  }

  const nativeFetch = window.fetch.bind(window);
  const wrappedFetch: typeof window.fetch & { __ragAuthInstalled?: boolean } = async (input, init) => {
    const url = extractUrl(input);
    const exempt = isAuthExempt(url);
    const headers = new Headers(
      init?.headers ?? (input instanceof Request ? input.headers : undefined)
    );
    const auth = readAuthState();

    if (!exempt && auth?.token && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${auth.token}`);
    }

    const response = await nativeFetch(input, {
      ...init,
      headers,
    });

    if (response.status === 401 && !exempt) {
      clearAuthState();
      if (window.location.pathname !== '/login') {
        window.location.replace('/login');
      }
    }

    return response;
  };

  wrappedFetch.__ragAuthInstalled = true;
  window.fetch = wrappedFetch;
}
