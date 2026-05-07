type ProviderId = 'deepseek' | 'kimi' | 'openai';

function parsePositiveInt(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }

  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function parseBoolean(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined) {
    return fallback;
  }

  const normalized = value.trim().toLowerCase();
  if (normalized === 'true' || normalized === '1' || normalized === 'yes' || normalized === 'on') {
    return true;
  }
  if (normalized === 'false' || normalized === '0' || normalized === 'no' || normalized === 'off') {
    return false;
  }

  return fallback;
}

function parseProvider(value: string | undefined, fallback: ProviderId): ProviderId {
  return value === 'deepseek' || value === 'kimi' || value === 'openai' ? value : fallback;
}

export interface FrontendRuntimeConfig {
  isDev: boolean;
  apiBaseUrl: string;
  wsUrl: string;
  wsReconnectDelayMs: number;
  activeProvider: ProviderId;
  providers: Record<
    ProviderId,
    {
      apiKey: string;
      baseURL: string;
    }
  >;
  retrievalRequest: {
    topK: number;
    enableRerank: boolean;
    enableFusion: boolean;
  };
}

export const frontendRuntimeConfig: FrontendRuntimeConfig = Object.freeze({
  isDev: Boolean(import.meta.env.DEV),
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || '',
  wsUrl: import.meta.env.VITE_WS_URL || '',
  wsReconnectDelayMs: parsePositiveInt(import.meta.env.VITE_WS_RECONNECT_DELAY_MS, 3000),
  activeProvider: parseProvider(import.meta.env.VITE_ACTIVE_LLM_PROVIDER, 'deepseek'),
  providers: {
    deepseek: {
      apiKey: import.meta.env.VITE_DEEPSEEK_API_KEY || '',
      baseURL: import.meta.env.VITE_DEEPSEEK_BASE_URL || 'https://api.deepseek.com',
    },
    kimi: {
      apiKey: import.meta.env.VITE_KIMI_API_KEY || '',
      baseURL: import.meta.env.VITE_KIMI_BASE_URL || 'https://api.moonshot.cn',
    },
    openai: {
      apiKey: import.meta.env.VITE_OPENAI_API_KEY || '',
      baseURL: import.meta.env.VITE_OPENAI_BASE_URL || 'https://api.openai.com',
    },
  },
  retrievalRequest: {
    topK: parsePositiveInt(import.meta.env.VITE_RAG_TOP_K, 10),
    enableRerank: parseBoolean(import.meta.env.VITE_RAG_ENABLE_RERANK, true),
    enableFusion: parseBoolean(import.meta.env.VITE_RAG_ENABLE_FUSION, true),
  },
});

export function getApiBaseUrl(): string {
  return frontendRuntimeConfig.apiBaseUrl;
}

export function resolveWebSocketUrl(room: string = 'dashboard'): string {
  const explicitUrl = frontendRuntimeConfig.wsUrl.trim();
  if (explicitUrl) {
    return explicitUrl;
  }

  const protocol =
    typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss' : 'ws';
  const host = typeof window !== 'undefined' ? window.location.host : 'localhost';
  return `${protocol}://${host}/ws?room=${encodeURIComponent(room)}`;
}
