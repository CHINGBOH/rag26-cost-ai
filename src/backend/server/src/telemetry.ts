/**
 * OpenTelemetry 启动模块
 * 必须被 src/index.ts 顶部第一个 import，确保 SDK 在其他模块加载前注册全局 hooks
 *
 * Opt-in：仅在 runtimeConfig.telemetry.endpoint 存在时启用
 * 配套基础设施：infrastructure/docker-compose.tracing.yml (Tempo + Grafana + Prom)
 */

import { runtimeConfig } from './config/runtime';

const endpoint = runtimeConfig.telemetry.endpoint;

if (endpoint) {
  try {
    // 延迟 require 避免未启用时加载这些重依赖
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { NodeSDK } = require('@opentelemetry/sdk-node');
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-http');
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { getNodeAutoInstrumentations } = require('@opentelemetry/auto-instrumentations-node');
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { resourceFromAttributes } = require('@opentelemetry/resources');
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { ATTR_SERVICE_NAME } = require('@opentelemetry/semantic-conventions');

    const url = `${endpoint.replace(/\/$/, '')}/v1/traces`;
    const sdk = new NodeSDK({
      resource: resourceFromAttributes({
        [ATTR_SERVICE_NAME]: runtimeConfig.telemetry.serviceName,
      }),
      traceExporter: new OTLPTraceExporter({ url }),
      instrumentations: [
        getNodeAutoInstrumentations({
          // 关闭噪音过大的 fs 埋点
          '@opentelemetry/instrumentation-fs': { enabled: false },
        }),
      ],
    });

    sdk.start();
    // eslint-disable-next-line no-console
    console.log(`✅ OTEL active → ${url}`);

    process.on('SIGTERM', () => {
      sdk.shutdown().catch(() => {});
    });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn('[OTEL] init failed, continuing without tracing:', err);
  }
}
