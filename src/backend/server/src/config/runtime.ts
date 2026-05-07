import './bootstrap-env';

import config from 'config';
import { Command } from 'commander';
import { z } from 'zod';

const RuntimeConfigSchema = z.object({
  app: z.object({
    environment: z.enum(['development', 'test', 'production']),
  }),
  logging: z.object({
    level: z.enum(['debug', 'info', 'warn', 'error']),
    outputFile: z.string().min(1),
    enableConsole: z.boolean(),
    enableFile: z.boolean(),
    prettyPrint: z.boolean(),
    flushIntervalMs: z.coerce.number().int().positive(),
  }),
  telemetry: z.object({
    endpoint: z.string(),
    serviceName: z.string().min(1),
  }),
  databases: z.object({
    qdrantUrl: z.string().url(),
    neo4jUrl: z.string().min(1),
    neo4jUsername: z.string().min(1),
    neo4jPassword: z.string(),
    elasticsearchUrl: z.string().url(),
    elasticsearchUsername: z.string(),
    elasticsearchPassword: z.string(),
    postgresHost: z.string().min(1),
    postgresPort: z.coerce.number().int().positive(),
    postgresDatabase: z.string().min(1),
    postgresUser: z.string().min(1),
    postgresPassword: z.string(),
  }),
  embeddings: z.object({
    model: z.string().min(1),
    dimensions: z.coerce.number().int().positive(),
    batchSize: z.coerce.number().int().positive(),
  }),
  retrieval: z.object({
    sessionContextCollection: z.string().min(1),
    documentsCollection: z.string().min(1),
    documentsIndexName: z.string().min(1),
    timeoutMs: z.coerce.number().int().positive(),
    defaultTopK: z.coerce.number().int().positive(),
    enableRerank: z.boolean(),
    enableFusion: z.boolean(),
    vectorWeight: z.coerce.number().min(0),
    textWeight: z.coerce.number().min(0),
    rerankWeight: z.coerce.number().min(0),
    graphWeight: z.coerce.number().min(0),
  }),
  cascadeRetrieval: z.object({
    enableNeo4j: z.boolean(),
    enableElasticsearch: z.boolean(),
    enablePostgres: z.boolean(),
    defaultTopK: z.coerce.number().int().positive(),
    vectorWeight: z.coerce.number().min(0),
    graphWeight: z.coerce.number().min(0),
    keywordWeight: z.coerce.number().min(0),
  }),
  ocr: z.object({
    language: z.string().min(1),
    dpi: z.coerce.number().int().positive(),
    timeoutMs: z.coerce.number().int().positive(),
    useGpu: z.boolean(),
    chunkSize: z.coerce.number().int().positive(),
    chunkOverlap: z.coerce.number().int().min(0),
    minChunkSize: z.coerce.number().int().positive(),
  }),
  storage: z.object({
    queueName: z.string().min(1),
    storeKeyPrefix: z.string().min(1),
    redisMaxRetriesPerRequest: z.coerce.number().int().min(0),
    redisRetryMaxDelayMs: z.coerce.number().int().positive(),
  }),
  persistence: z.object({
    enabled: z.boolean(),
    connectionString: z.string(),
    ssl: z.boolean(),
  }),
  expertJudgment: z.object({
    baseUrl: z.string().url(),
    apiKey: z.string(),
    model: z.string().min(1),
    temperature: z.coerce.number().min(0),
    maxTokens: z.coerce.number().int().positive(),
  }),
  server: z.object({
    host: z.string().min(1),
    port: z.coerce.number().int().min(1).max(65535),
    corsOrigins: z.array(z.string().min(1)).min(1),
    wsPublicUrl: z.string().url(),
    requestTimeoutMs: z.coerce.number().int().positive(),
    connectionTimeoutMs: z.coerce.number().int().positive(),
  }),
  rateLimit: z.object({
    max: z.coerce.number().int().positive(),
    timeWindow: z.string().min(1),
  }),
  heartbeat: z.object({
    broadcastIntervalMs: z.coerce.number().int().positive(),
    silenceThresholdMs: z.coerce.number().int().positive(),
    statusLogIntervalMs: z.coerce.number().int().positive(),
  }),
  llm: z.object({
    provider: z.enum(['openai', 'claude', 'kimi', 'ollama', 'custom', 'deepseek']),
    baseUrl: z.string().url(),
    model: z.string().min(1),
    apiKey: z.string(),
    deepseekApiKey: z.string(),
    openaiApiKey: z.string(),
    temperature: z.coerce.number().min(0),
    maxTokens: z.coerce.number().int().positive(),
  }),
  services: z.object({
    redisUrl: z.string().min(1),
    pythonApiUrl: z.string().url(),
    ocrApiUrl: z.string().url(),
    retrievalApiUrl: z.string().url(),
    wsBroadcastUrl: z.string().url(),
  }),
  cache: z.object({
    defaultTtlSeconds: z.coerce.number().int().positive(),
    keyPrefix: z.string().min(1),
  }),
  taskQueue: z.object({
    concurrency: z.coerce.number().int().positive(),
    evaluationConcurrency: z.coerce.number().int().positive(),
    ocrConcurrency: z.coerce.number().int().positive(),
  }),
  pipeline: z.object({
    uploadDir: z.string().min(1),
    maxConcurrent: z.coerce.number().int().positive(),
    processingLoopIntervalMs: z.coerce.number().int().positive(),
  }),
  recursion: z.object({
    cleanupIntervalMs: z.coerce.number().int().positive(),
    completedSessionMaxAgeMs: z.coerce.number().int().positive(),
    hardSessionMaxAgeMs: z.coerce.number().int().positive(),
    requestTimeoutMs: z.coerce.number().int().positive(),
  }),
  auth: z.object({
    serviceSecret: z.string(),
    jwtSecret: z.string(),
    tokenExpirySeconds: z.coerce.number().int().positive(),
    jwtExpiresInSeconds: z.coerce.number().int().positive(),
    jwtRefreshExpiresInSeconds: z.coerce.number().int().positive(),
    defaultAdminUsername: z.string().min(1),
    defaultAdminPassword: z.string(),
  }),
});

type RuntimeConfig = z.output<typeof RuntimeConfigSchema>;

interface RuntimeConfigOverrides {
  app?: {
    environment?: 'development' | 'test' | 'production';
  };
  logging?: {
    level?: 'debug' | 'info' | 'warn' | 'error';
    outputFile?: string;
    enableConsole?: boolean;
    enableFile?: boolean;
    prettyPrint?: boolean;
    flushIntervalMs?: string | number;
  };
  telemetry?: {
    endpoint?: string;
    serviceName?: string;
  };
  databases?: {
    qdrantUrl?: string;
    neo4jUrl?: string;
    neo4jUsername?: string;
    neo4jPassword?: string;
    elasticsearchUrl?: string;
    elasticsearchUsername?: string;
    elasticsearchPassword?: string;
    postgresHost?: string;
    postgresPort?: string | number;
    postgresDatabase?: string;
    postgresUser?: string;
    postgresPassword?: string;
  };
  embeddings?: {
    model?: string;
    dimensions?: string | number;
    batchSize?: string | number;
  };
  retrieval?: {
    sessionContextCollection?: string;
    documentsCollection?: string;
    documentsIndexName?: string;
    timeoutMs?: string | number;
    defaultTopK?: string | number;
    enableRerank?: boolean;
    enableFusion?: boolean;
    vectorWeight?: string | number;
    textWeight?: string | number;
    rerankWeight?: string | number;
    graphWeight?: string | number;
  };
  cascadeRetrieval?: {
    enableNeo4j?: boolean;
    enableElasticsearch?: boolean;
    enablePostgres?: boolean;
    defaultTopK?: string | number;
    vectorWeight?: string | number;
    graphWeight?: string | number;
    keywordWeight?: string | number;
  };
  ocr?: {
    language?: string;
    dpi?: string | number;
    timeoutMs?: string | number;
    useGpu?: boolean;
    chunkSize?: string | number;
    chunkOverlap?: string | number;
    minChunkSize?: string | number;
  };
  storage?: {
    queueName?: string;
    storeKeyPrefix?: string;
    redisMaxRetriesPerRequest?: string | number;
    redisRetryMaxDelayMs?: string | number;
  };
  persistence?: {
    enabled?: boolean;
    connectionString?: string;
    ssl?: boolean;
  };
  expertJudgment?: {
    baseUrl?: string;
    apiKey?: string;
    model?: string;
    temperature?: string | number;
    maxTokens?: string | number;
  };
  server?: {
    host?: string;
    port?: string | number;
    corsOrigins?: string[];
    wsPublicUrl?: string;
    requestTimeoutMs?: string | number;
    connectionTimeoutMs?: string | number;
  };
  rateLimit?: {
    max?: string | number;
    timeWindow?: string;
  };
  heartbeat?: {
    broadcastIntervalMs?: string | number;
    silenceThresholdMs?: string | number;
    statusLogIntervalMs?: string | number;
  };
  llm?: {
    provider?: 'openai' | 'claude' | 'kimi' | 'ollama' | 'custom' | 'deepseek';
    baseUrl?: string;
    model?: string;
    apiKey?: string;
    deepseekApiKey?: string;
    openaiApiKey?: string;
    temperature?: string | number;
    maxTokens?: string | number;
  };
  services?: {
    redisUrl?: string;
    pythonApiUrl?: string;
    ocrApiUrl?: string;
    retrievalApiUrl?: string;
    wsBroadcastUrl?: string;
  };
  cache?: {
    defaultTtlSeconds?: string | number;
    keyPrefix?: string;
  };
  taskQueue?: {
    concurrency?: string | number;
    evaluationConcurrency?: string | number;
    ocrConcurrency?: string | number;
  };
  pipeline?: {
    uploadDir?: string;
    maxConcurrent?: string | number;
    processingLoopIntervalMs?: string | number;
  };
  recursion?: {
    cleanupIntervalMs?: string | number;
    completedSessionMaxAgeMs?: string | number;
    hardSessionMaxAgeMs?: string | number;
    requestTimeoutMs?: string | number;
  };
  auth?: {
    serviceSecret?: string;
    jwtSecret?: string;
    tokenExpirySeconds?: string | number;
    jwtExpiresInSeconds?: string | number;
    jwtRefreshExpiresInSeconds?: string | number;
    defaultAdminUsername?: string;
    defaultAdminPassword?: string;
  };
}

interface RuntimeConfigOptions {
  baseConfig?: unknown;
  env?: NodeJS.ProcessEnv;
  argv?: string[];
}

function parseCsvList(value?: string): string[] | undefined {
  if (!value) {
    return undefined;
  }

  const parts = value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);

  return parts.length > 0 ? parts : undefined;
}

function parseBoolean(value?: string): boolean | undefined {
  if (value === undefined) {
    return undefined;
  }

  const normalized = value.trim().toLowerCase();
  if (normalized === 'true' || normalized === '1' || normalized === 'yes' || normalized === 'on') {
    return true;
  }
  if (normalized === 'false' || normalized === '0' || normalized === 'no' || normalized === 'off') {
    return false;
  }

  return undefined;
}

function mergeSection<T extends Record<string, unknown>>(
  base: T,
  override?: Partial<Record<keyof T, unknown>>,
): T {
  if (!override) {
    return base;
  }

  const filteredOverride = Object.fromEntries(
    Object.entries(override).filter(([, value]) => value !== undefined),
  ) as Partial<Record<keyof T, unknown>>;

  return {
    ...base,
    ...filteredOverride,
  };
}

function mergeRuntimeConfig(base: RuntimeConfig, override: RuntimeConfigOverrides): RuntimeConfig {
  return RuntimeConfigSchema.parse({
    app: mergeSection(base.app, override.app),
    logging: mergeSection(base.logging, override.logging),
    telemetry: mergeSection(base.telemetry, override.telemetry),
    databases: mergeSection(base.databases, override.databases),
    embeddings: mergeSection(base.embeddings, override.embeddings),
    retrieval: mergeSection(base.retrieval, override.retrieval),
    cascadeRetrieval: mergeSection(base.cascadeRetrieval, override.cascadeRetrieval),
    ocr: mergeSection(base.ocr, override.ocr),
    storage: mergeSection(base.storage, override.storage),
    persistence: mergeSection(base.persistence, override.persistence),
    expertJudgment: mergeSection(base.expertJudgment, override.expertJudgment),
    server: mergeSection(base.server, override.server),
    rateLimit: mergeSection(base.rateLimit, override.rateLimit),
    heartbeat: mergeSection(base.heartbeat, override.heartbeat),
    llm: mergeSection(base.llm, override.llm),
    services: mergeSection(base.services, override.services),
    cache: mergeSection(base.cache, override.cache),
    taskQueue: mergeSection(base.taskQueue, override.taskQueue),
    pipeline: mergeSection(base.pipeline, override.pipeline),
    recursion: mergeSection(base.recursion, override.recursion),
    auth: mergeSection(base.auth, override.auth),
  });
}

function firstDefined(...values: Array<string | undefined>): string | undefined {
  return values.find((value) => value !== undefined);
}

function parseCliOverrides(argv: string[]): RuntimeConfigOverrides {
  const program = new Command();

  program
    .allowUnknownOption(true)
    .allowExcessArguments(true)
    .option('--node-env <environment>')
    .option('--log-level <logLevel>')
    .option('--log-output-file <logOutputFile>')
    .option('--log-enable-console <logEnableConsole>')
    .option('--log-enable-file <logEnableFile>')
    .option('--log-pretty-print <logPrettyPrint>')
    .option('--log-flush-interval-ms <logFlushIntervalMs>')
    .option('--otel-endpoint <otelEndpoint>')
    .option('--otel-service-name <otelServiceName>')
    .option('--qdrant-url <qdrantUrl>')
    .option('--neo4j-url <neo4jUrl>')
    .option('--neo4j-username <neo4jUsername>')
    .option('--neo4j-password <neo4jPassword>')
    .option('--elasticsearch-url <elasticsearchUrl>')
    .option('--elasticsearch-username <elasticsearchUsername>')
    .option('--elasticsearch-password <elasticsearchPassword>')
    .option('--pg-host <pgHost>')
    .option('--pg-port <pgPort>')
    .option('--pg-database <pgDatabase>')
    .option('--pg-user <pgUser>')
    .option('--pg-password <pgPassword>')
    .option('--embedding-model <embeddingModel>')
    .option('--embedding-dimensions <embeddingDimensions>')
    .option('--embedding-batch-size <embeddingBatchSize>')
    .option('--retrieval-session-context-collection <retrievalSessionContextCollection>')
    .option('--retrieval-documents-collection <retrievalDocumentsCollection>')
    .option('--retrieval-documents-index-name <retrievalDocumentsIndexName>')
    .option('--retrieval-timeout-ms <retrievalTimeoutMs>')
    .option('--retrieval-default-top-k <retrievalDefaultTopK>')
    .option('--retrieval-enable-rerank <retrievalEnableRerank>')
    .option('--retrieval-enable-fusion <retrievalEnableFusion>')
    .option('--retrieval-vector-weight <retrievalVectorWeight>')
    .option('--retrieval-text-weight <retrievalTextWeight>')
    .option('--retrieval-rerank-weight <retrievalRerankWeight>')
    .option('--retrieval-graph-weight <retrievalGraphWeight>')
    .option('--cascade-enable-neo4j <cascadeEnableNeo4j>')
    .option('--cascade-enable-elasticsearch <cascadeEnableElasticsearch>')
    .option('--cascade-enable-postgres <cascadeEnablePostgres>')
    .option('--cascade-default-top-k <cascadeDefaultTopK>')
    .option('--cascade-vector-weight <cascadeVectorWeight>')
    .option('--cascade-graph-weight <cascadeGraphWeight>')
    .option('--cascade-keyword-weight <cascadeKeywordWeight>')
    .option('--ocr-language <ocrLanguage>')
    .option('--ocr-dpi <ocrDpi>')
    .option('--ocr-timeout-ms <ocrTimeoutMs>')
    .option('--ocr-use-gpu <ocrUseGpu>')
    .option('--ocr-chunk-size <ocrChunkSize>')
    .option('--ocr-chunk-overlap <ocrChunkOverlap>')
    .option('--ocr-min-chunk-size <ocrMinChunkSize>')
    .option('--storage-queue-name <storageQueueName>')
    .option('--storage-store-key-prefix <storageStoreKeyPrefix>')
    .option('--storage-redis-max-retries <storageRedisMaxRetries>')
    .option('--storage-redis-retry-max-delay-ms <storageRedisRetryMaxDelayMs>')
    .option('--persistence-enabled <persistenceEnabled>')
    .option('--persistence-connection-string <persistenceConnectionString>')
    .option('--persistence-ssl <persistenceSsl>')
    .option('--expert-judgment-base-url <expertJudgmentBaseUrl>')
    .option('--expert-judgment-api-key <expertJudgmentApiKey>')
    .option('--expert-judgment-model <expertJudgmentModel>')
    .option('--expert-judgment-temperature <expertJudgmentTemperature>')
    .option('--expert-judgment-max-tokens <expertJudgmentMaxTokens>')
    .option('--host <host>')
    .option('--port <port>')
    .option('--cors-origin <origins>', 'Comma-separated allowed origins')
    .option('--ws-public-url <wsPublicUrl>')
    .option('--request-timeout-ms <requestTimeoutMs>')
    .option('--connection-timeout-ms <connectionTimeoutMs>')
    .option('--rate-limit-max <rateLimitMax>')
    .option('--rate-limit-window <rateLimitWindow>')
    .option('--heartbeat-broadcast-interval-ms <heartbeatBroadcastIntervalMs>')
    .option('--heartbeat-silence-threshold-ms <heartbeatSilenceThresholdMs>')
    .option('--status-log-interval-ms <statusLogIntervalMs>')
    .option('--llm-provider <llmProvider>')
    .option('--llm-base-url <llmBaseUrl>')
    .option('--llm-model <llmModel>')
    .option('--llm-temperature <llmTemperature>')
    .option('--llm-max-tokens <llmMaxTokens>')
    .option('--redis-url <redisUrl>')
    .option('--python-api-url <pythonApiUrl>')
    .option('--ocr-api-url <ocrApiUrl>')
    .option('--retrieval-api-url <retrievalApiUrl>')
    .option('--ws-broadcast-url <wsBroadcastUrl>')
    .option('--cache-default-ttl-seconds <cacheDefaultTtlSeconds>')
    .option('--cache-key-prefix <cacheKeyPrefix>')
    .option('--task-queue-concurrency <taskQueueConcurrency>')
    .option('--task-queue-evaluation-concurrency <taskQueueEvaluationConcurrency>')
    .option('--task-queue-ocr-concurrency <taskQueueOcrConcurrency>')
    .option('--upload-dir <uploadDir>')
    .option('--pipeline-max-concurrent <pipelineMaxConcurrent>')
    .option('--pipeline-loop-interval-ms <pipelineLoopIntervalMs>')
    .option('--recursion-cleanup-interval-ms <recursionCleanupIntervalMs>')
    .option('--recursion-completed-session-max-age-ms <recursionCompletedSessionMaxAgeMs>')
    .option('--recursion-hard-session-max-age-ms <recursionHardSessionMaxAgeMs>')
    .option('--recursion-request-timeout-ms <recursionRequestTimeoutMs>')
    .option('--auth-token-expiry-seconds <authTokenExpirySeconds>')
    .option('--jwt-expires-in-seconds <jwtExpiresInSeconds>')
    .option('--jwt-refresh-expires-in-seconds <jwtRefreshExpiresInSeconds>')
    .option('--default-admin-username <defaultAdminUsername>');

  program.parse(argv, { from: 'node' });
  const options = program.opts<{
    nodeEnv?: 'development' | 'test' | 'production';
    logLevel?: 'debug' | 'info' | 'warn' | 'error';
    logOutputFile?: string;
    logEnableConsole?: string;
    logEnableFile?: string;
    logPrettyPrint?: string;
    logFlushIntervalMs?: string;
    otelEndpoint?: string;
    otelServiceName?: string;
    qdrantUrl?: string;
    neo4jUrl?: string;
    neo4jUsername?: string;
    neo4jPassword?: string;
    elasticsearchUrl?: string;
    elasticsearchUsername?: string;
    elasticsearchPassword?: string;
    pgHost?: string;
    pgPort?: string;
    pgDatabase?: string;
    pgUser?: string;
    pgPassword?: string;
    embeddingModel?: string;
    embeddingDimensions?: string;
    embeddingBatchSize?: string;
    retrievalSessionContextCollection?: string;
    retrievalDocumentsCollection?: string;
    retrievalDocumentsIndexName?: string;
    retrievalTimeoutMs?: string;
    retrievalDefaultTopK?: string;
    retrievalEnableRerank?: string;
    retrievalEnableFusion?: string;
    retrievalVectorWeight?: string;
    retrievalTextWeight?: string;
    retrievalRerankWeight?: string;
    retrievalGraphWeight?: string;
    cascadeEnableNeo4j?: string;
    cascadeEnableElasticsearch?: string;
    cascadeEnablePostgres?: string;
    cascadeDefaultTopK?: string;
    cascadeVectorWeight?: string;
    cascadeGraphWeight?: string;
    cascadeKeywordWeight?: string;
    ocrLanguage?: string;
    ocrDpi?: string;
    ocrTimeoutMs?: string;
    ocrUseGpu?: string;
    ocrChunkSize?: string;
    ocrChunkOverlap?: string;
    ocrMinChunkSize?: string;
    storageQueueName?: string;
    storageStoreKeyPrefix?: string;
    storageRedisMaxRetries?: string;
    storageRedisRetryMaxDelayMs?: string;
    persistenceEnabled?: string;
    persistenceConnectionString?: string;
    persistenceSsl?: string;
    expertJudgmentBaseUrl?: string;
    expertJudgmentApiKey?: string;
    expertJudgmentModel?: string;
    expertJudgmentTemperature?: string;
    expertJudgmentMaxTokens?: string;
    host?: string;
    port?: string;
    corsOrigin?: string;
    wsPublicUrl?: string;
    requestTimeoutMs?: string;
    connectionTimeoutMs?: string;
    rateLimitMax?: string;
    rateLimitWindow?: string;
    heartbeatBroadcastIntervalMs?: string;
    heartbeatSilenceThresholdMs?: string;
    statusLogIntervalMs?: string;
    llmProvider?: 'openai' | 'claude' | 'kimi' | 'ollama' | 'custom' | 'deepseek';
    llmBaseUrl?: string;
    llmModel?: string;
    llmTemperature?: string;
    llmMaxTokens?: string;
    redisUrl?: string;
    pythonApiUrl?: string;
    ocrApiUrl?: string;
    retrievalApiUrl?: string;
    wsBroadcastUrl?: string;
    cacheDefaultTtlSeconds?: string;
    cacheKeyPrefix?: string;
    taskQueueConcurrency?: string;
    taskQueueEvaluationConcurrency?: string;
    taskQueueOcrConcurrency?: string;
    uploadDir?: string;
    pipelineMaxConcurrent?: string;
    pipelineLoopIntervalMs?: string;
    recursionCleanupIntervalMs?: string;
    recursionCompletedSessionMaxAgeMs?: string;
    recursionHardSessionMaxAgeMs?: string;
    recursionRequestTimeoutMs?: string;
    authTokenExpirySeconds?: string;
    jwtExpiresInSeconds?: string;
    jwtRefreshExpiresInSeconds?: string;
    defaultAdminUsername?: string;
  }>();

  return {
    app: {
      environment: options.nodeEnv,
    },
    logging: {
      level: options.logLevel,
      outputFile: options.logOutputFile,
      enableConsole: parseBoolean(options.logEnableConsole),
      enableFile: parseBoolean(options.logEnableFile),
      prettyPrint: parseBoolean(options.logPrettyPrint),
      flushIntervalMs: options.logFlushIntervalMs,
    },
    telemetry: {
      endpoint: options.otelEndpoint,
      serviceName: options.otelServiceName,
    },
    databases: {
      qdrantUrl: options.qdrantUrl,
      neo4jUrl: options.neo4jUrl,
      neo4jUsername: options.neo4jUsername,
      neo4jPassword: options.neo4jPassword,
      elasticsearchUrl: options.elasticsearchUrl,
      elasticsearchUsername: options.elasticsearchUsername,
      elasticsearchPassword: options.elasticsearchPassword,
      postgresHost: options.pgHost,
      postgresPort: options.pgPort,
      postgresDatabase: options.pgDatabase,
      postgresUser: options.pgUser,
      postgresPassword: options.pgPassword,
    },
    embeddings: {
      model: options.embeddingModel,
      dimensions: options.embeddingDimensions,
      batchSize: options.embeddingBatchSize,
    },
    retrieval: {
      sessionContextCollection: options.retrievalSessionContextCollection,
      documentsCollection: options.retrievalDocumentsCollection,
      documentsIndexName: options.retrievalDocumentsIndexName,
      timeoutMs: options.retrievalTimeoutMs,
      defaultTopK: options.retrievalDefaultTopK,
      enableRerank: parseBoolean(options.retrievalEnableRerank),
      enableFusion: parseBoolean(options.retrievalEnableFusion),
      vectorWeight: options.retrievalVectorWeight,
      textWeight: options.retrievalTextWeight,
      rerankWeight: options.retrievalRerankWeight,
      graphWeight: options.retrievalGraphWeight,
    },
    cascadeRetrieval: {
      enableNeo4j: parseBoolean(options.cascadeEnableNeo4j),
      enableElasticsearch: parseBoolean(options.cascadeEnableElasticsearch),
      enablePostgres: parseBoolean(options.cascadeEnablePostgres),
      defaultTopK: options.cascadeDefaultTopK,
      vectorWeight: options.cascadeVectorWeight,
      graphWeight: options.cascadeGraphWeight,
      keywordWeight: options.cascadeKeywordWeight,
    },
    ocr: {
      language: options.ocrLanguage,
      dpi: options.ocrDpi,
      timeoutMs: options.ocrTimeoutMs,
      useGpu: parseBoolean(options.ocrUseGpu),
      chunkSize: options.ocrChunkSize,
      chunkOverlap: options.ocrChunkOverlap,
      minChunkSize: options.ocrMinChunkSize,
    },
    storage: {
      queueName: options.storageQueueName,
      storeKeyPrefix: options.storageStoreKeyPrefix,
      redisMaxRetriesPerRequest: options.storageRedisMaxRetries,
      redisRetryMaxDelayMs: options.storageRedisRetryMaxDelayMs,
    },
    persistence: {
      enabled: parseBoolean(options.persistenceEnabled),
      connectionString: options.persistenceConnectionString,
      ssl: parseBoolean(options.persistenceSsl),
    },
    expertJudgment: {
      baseUrl: options.expertJudgmentBaseUrl,
      apiKey: options.expertJudgmentApiKey,
      model: options.expertJudgmentModel,
      temperature: options.expertJudgmentTemperature,
      maxTokens: options.expertJudgmentMaxTokens,
    },
    server: {
      host: options.host,
      port: options.port,
      corsOrigins: parseCsvList(options.corsOrigin),
      wsPublicUrl: options.wsPublicUrl,
      requestTimeoutMs: options.requestTimeoutMs,
      connectionTimeoutMs: options.connectionTimeoutMs,
    },
    rateLimit: {
      max: options.rateLimitMax,
      timeWindow: options.rateLimitWindow,
    },
    heartbeat: {
      broadcastIntervalMs: options.heartbeatBroadcastIntervalMs,
      silenceThresholdMs: options.heartbeatSilenceThresholdMs,
      statusLogIntervalMs: options.statusLogIntervalMs,
    },
    llm: {
      provider: options.llmProvider,
      baseUrl: options.llmBaseUrl,
      model: options.llmModel,
      temperature: options.llmTemperature,
      maxTokens: options.llmMaxTokens,
    },
    services: {
      redisUrl: options.redisUrl,
      pythonApiUrl: options.pythonApiUrl,
      ocrApiUrl: options.ocrApiUrl,
      retrievalApiUrl: options.retrievalApiUrl,
      wsBroadcastUrl: options.wsBroadcastUrl,
    },
    cache: {
      defaultTtlSeconds: options.cacheDefaultTtlSeconds,
      keyPrefix: options.cacheKeyPrefix,
    },
    taskQueue: {
      concurrency: options.taskQueueConcurrency,
      evaluationConcurrency: options.taskQueueEvaluationConcurrency,
      ocrConcurrency: options.taskQueueOcrConcurrency,
    },
    pipeline: {
      uploadDir: options.uploadDir,
      maxConcurrent: options.pipelineMaxConcurrent,
      processingLoopIntervalMs: options.pipelineLoopIntervalMs,
    },
    recursion: {
      cleanupIntervalMs: options.recursionCleanupIntervalMs,
      completedSessionMaxAgeMs: options.recursionCompletedSessionMaxAgeMs,
      hardSessionMaxAgeMs: options.recursionHardSessionMaxAgeMs,
      requestTimeoutMs: options.recursionRequestTimeoutMs,
    },
    auth: {
      tokenExpirySeconds: options.authTokenExpirySeconds,
      jwtExpiresInSeconds: options.jwtExpiresInSeconds,
      jwtRefreshExpiresInSeconds: options.jwtRefreshExpiresInSeconds,
      defaultAdminUsername: options.defaultAdminUsername,
    },
  };
}

function parseEnvOverrides(env: NodeJS.ProcessEnv): RuntimeConfigOverrides {
  const qdrantHost = env.QDRANT_HOST;
  const qdrantPort = env.QDRANT_PORT;
  const qdrantUrl =
    env.QDRANT_URL ??
    (qdrantHost ? `http://${qdrantHost}:${qdrantPort ?? '6333'}` : undefined);
  const retrievalTimeoutMs =
    env.RETRIEVAL_TIMEOUT_MS ??
    (env.QDRANT_TIMEOUT ? String(Number(env.QDRANT_TIMEOUT) * 1000) : undefined);

  return {
    app: {
      environment:
        env.NODE_ENV === 'development' || env.NODE_ENV === 'test' || env.NODE_ENV === 'production'
          ? env.NODE_ENV
          : undefined,
    },
    logging: {
      level:
        env.LOG_LEVEL === 'debug' ||
        env.LOG_LEVEL === 'info' ||
        env.LOG_LEVEL === 'warn' ||
        env.LOG_LEVEL === 'error'
          ? env.LOG_LEVEL
          : undefined,
      outputFile: env.LOG_OUTPUT_FILE,
      enableConsole: parseBoolean(env.LOG_ENABLE_CONSOLE),
      enableFile: parseBoolean(env.ENABLE_FILE_LOG),
      prettyPrint: parseBoolean(
        firstDefined(env.LOG_PRETTY_PRINT, env.NODE_ENV === 'development' ? 'true' : undefined),
      ),
      flushIntervalMs: env.LOG_FLUSH_INTERVAL_MS,
    },
    telemetry: {
      endpoint: env.OTEL_EXPORTER_OTLP_ENDPOINT,
      serviceName: env.OTEL_SERVICE_NAME,
    },
    databases: {
      qdrantUrl,
      neo4jUrl: firstDefined(env.NEO4J_URL, env.NEO4J_URI),
      neo4jUsername: env.NEO4J_USERNAME,
      neo4jPassword: env.NEO4J_PASSWORD,
      elasticsearchUrl: firstDefined(env.ELASTICSEARCH_URL, env.ES_HOST),
      elasticsearchUsername: firstDefined(env.ELASTICSEARCH_USERNAME, env.ES_USERNAME),
      elasticsearchPassword: firstDefined(env.ELASTICSEARCH_PASSWORD, env.ES_PASSWORD),
      postgresHost: firstDefined(env.PG_HOST, env.POSTGRES_HOST),
      postgresPort: firstDefined(env.PG_PORT, env.POSTGRES_PORT),
      postgresDatabase: firstDefined(env.PG_DB, env.POSTGRES_DB),
      postgresUser: firstDefined(env.PG_USER, env.POSTGRES_USER),
      postgresPassword: firstDefined(env.PG_PASSWORD, env.POSTGRES_PASSWORD),
    },
    embeddings: {
      model: firstDefined(env.EMBEDDING_MODEL, env.EMBEDDING_MODEL_NAME),
      dimensions: env.EMBEDDING_DIMENSIONS,
      batchSize: env.EMBEDDING_BATCH_SIZE,
    },
    retrieval: {
      sessionContextCollection: env.RETRIEVAL_SESSION_CONTEXT_COLLECTION,
      documentsCollection: firstDefined(
        env.RETRIEVAL_DOCUMENTS_COLLECTION,
        env.QDRANT_COLLECTION_NAME,
      ),
      documentsIndexName: firstDefined(
        env.RETRIEVAL_DOCUMENTS_INDEX_NAME,
        env.ES_INDEX_NAME,
      ),
      timeoutMs: retrievalTimeoutMs,
      defaultTopK: firstDefined(env.RETRIEVAL_DEFAULT_TOP_K, env.RETRIEVAL_VECTOR_TOP_K),
      enableRerank: parseBoolean(env.RETRIEVAL_ENABLE_RERANK),
      enableFusion: parseBoolean(env.RETRIEVAL_ENABLE_FUSION),
      vectorWeight: firstDefined(env.RETRIEVAL_VECTOR_WEIGHT, env.FUSION_WEIGHT_VECTOR),
      textWeight: firstDefined(env.RETRIEVAL_TEXT_WEIGHT, env.FUSION_WEIGHT_KEYWORD),
      rerankWeight: env.FUSION_WEIGHT_RERANK,
      graphWeight: env.FUSION_WEIGHT_GRAPH,
    },
    cascadeRetrieval: {
      enableNeo4j: parseBoolean(env.CASCADE_RETRIEVAL_ENABLE_NEO4J),
      enableElasticsearch: parseBoolean(env.CASCADE_RETRIEVAL_ENABLE_ELASTICSEARCH),
      enablePostgres: parseBoolean(env.CASCADE_RETRIEVAL_ENABLE_POSTGRES),
      defaultTopK: env.CASCADE_RETRIEVAL_DEFAULT_TOP_K,
      vectorWeight: firstDefined(env.CASCADE_RETRIEVAL_VECTOR_WEIGHT, env.FUSION_WEIGHT_VECTOR),
      graphWeight: firstDefined(env.CASCADE_RETRIEVAL_GRAPH_WEIGHT, env.FUSION_WEIGHT_GRAPH),
      keywordWeight: firstDefined(
        env.CASCADE_RETRIEVAL_KEYWORD_WEIGHT,
        env.FUSION_WEIGHT_KEYWORD,
      ),
    },
    ocr: {
      language: env.OCR_LANGUAGE,
      dpi: env.OCR_DPI,
      timeoutMs: firstDefined(env.OCR_TIMEOUT_MS, env.OCR_SERVICE_TIMEOUT_MS),
      useGpu: parseBoolean(firstDefined(env.OCR_USE_GPU, env.SERVICE_OCR_GPU)),
      chunkSize: env.OCR_CHUNK_SIZE,
      chunkOverlap: env.OCR_CHUNK_OVERLAP,
      minChunkSize: env.OCR_MIN_CHUNK_SIZE,
    },
    storage: {
      queueName: env.STORAGE_REDIS_QUEUE_NAME,
      storeKeyPrefix: env.STORAGE_REDIS_STORE_KEY_PREFIX,
      redisMaxRetriesPerRequest: firstDefined(
        env.STORAGE_REDIS_MAX_RETRIES_PER_REQUEST,
        env.REDIS_MAX_RETRIES_PER_REQUEST,
      ),
      redisRetryMaxDelayMs: firstDefined(
        env.STORAGE_REDIS_RETRY_MAX_DELAY_MS,
        env.REDIS_RETRY_MAX_DELAY_MS,
      ),
    },
    persistence: {
      enabled: parseBoolean(env.PERSISTENCE_ENABLED),
      connectionString: firstDefined(env.PERSISTENCE_CONNECTION_STRING, env.DATABASE_URL),
      ssl: parseBoolean(firstDefined(env.PERSISTENCE_SSL, env.POSTGRES_SSL, env.PG_SSL)),
    },
    expertJudgment: {
      baseUrl: env.EXPERT_JUDGMENT_BASE_URL,
      apiKey: firstDefined(env.EXPERT_JUDGMENT_API_KEY, env.KIMI_API_KEY),
      model: firstDefined(env.EXPERT_JUDGMENT_MODEL, env.KIMI_MODEL),
      temperature: env.EXPERT_JUDGMENT_TEMPERATURE,
      maxTokens: env.EXPERT_JUDGMENT_MAX_TOKENS,
    },
    server: {
      host: env.HOST,
      port: env.PORT,
      corsOrigins: parseCsvList(env.CORS_ORIGIN),
      wsPublicUrl: env.WS_PUBLIC_URL,
      requestTimeoutMs: env.SERVER_REQUEST_TIMEOUT_MS,
      connectionTimeoutMs: env.SERVER_CONNECTION_TIMEOUT_MS,
    },
    rateLimit: {
      max: env.RATE_LIMIT_MAX,
      timeWindow: env.RATE_LIMIT_TIME_WINDOW,
    },
    heartbeat: {
      broadcastIntervalMs: env.HEARTBEAT_BROADCAST_INTERVAL_MS,
      silenceThresholdMs: env.HEARTBEAT_SILENCE_THRESHOLD_MS,
      statusLogIntervalMs: env.SYSTEM_STATUS_LOG_INTERVAL_MS,
    },
    llm: {
      provider:
        env.LLM_PROVIDER === 'openai' ||
        env.LLM_PROVIDER === 'claude' ||
        env.LLM_PROVIDER === 'kimi' ||
        env.LLM_PROVIDER === 'ollama' ||
        env.LLM_PROVIDER === 'custom' ||
        env.LLM_PROVIDER === 'deepseek'
          ? env.LLM_PROVIDER
          : undefined,
      baseUrl: env.LLM_BASE_URL,
      model: env.LLM_MODEL,
      apiKey: env.LLM_API_KEY,
      deepseekApiKey: env.DEEPSEEK_API_KEY,
      openaiApiKey: env.OPENAI_API_KEY,
      temperature: env.LLM_TEMPERATURE,
      maxTokens: env.LLM_MAX_TOKENS,
    },
    services: {
      redisUrl: env.REDIS_URL,
      pythonApiUrl: firstDefined(env.PYTHON_API_URL, env.PYTHON_URL),
      ocrApiUrl: firstDefined(env.OCR_API_URL, env.OCR_URL),
      retrievalApiUrl: firstDefined(env.RETRIEVAL_API_URL, env.RETRIEVAL_URL),
      wsBroadcastUrl: env.WS_GATEWAY_URL,
    },
    cache: {
      defaultTtlSeconds: env.CACHE_DEFAULT_TTL_SECONDS,
      keyPrefix: env.CACHE_KEY_PREFIX,
    },
    taskQueue: {
      concurrency: env.TASK_QUEUE_CONCURRENCY,
      evaluationConcurrency: env.TASK_QUEUE_EVALUATION_CONCURRENCY,
      ocrConcurrency: env.TASK_QUEUE_OCR_CONCURRENCY,
    },
    pipeline: {
      uploadDir: firstDefined(env.PIPELINE_UPLOAD_DIR, env.UPLOAD_DIR),
      maxConcurrent: env.PIPELINE_MAX_CONCURRENT,
      processingLoopIntervalMs: env.PIPELINE_LOOP_INTERVAL_MS,
    },
    recursion: {
      cleanupIntervalMs: env.RECURSION_CLEANUP_INTERVAL_MS,
      completedSessionMaxAgeMs: env.RECURSION_COMPLETED_SESSION_MAX_AGE_MS,
      hardSessionMaxAgeMs: env.RECURSION_HARD_SESSION_MAX_AGE_MS,
      requestTimeoutMs: env.RECURSION_REQUEST_TIMEOUT_MS,
    },
    auth: {
      serviceSecret: env.AUTH_SECRET,
      jwtSecret: env.JWT_SECRET,
      tokenExpirySeconds: env.AUTH_TOKEN_EXPIRY_SECONDS,
      jwtExpiresInSeconds: env.JWT_EXPIRES_IN_SECONDS,
      jwtRefreshExpiresInSeconds: env.JWT_REFRESH_EXPIRES_IN_SECONDS,
      defaultAdminUsername: env.DEFAULT_ADMIN_USERNAME,
      defaultAdminPassword: env.DEFAULT_ADMIN_PASSWORD,
    },
  };
}

export function createRuntimeConfig(options: RuntimeConfigOptions = {}): RuntimeConfig {
  const fileConfig = RuntimeConfigSchema.parse(options.baseConfig ?? config.get('runtime'));
  const envConfig = parseEnvOverrides(options.env ?? process.env);
  const withEnv = mergeRuntimeConfig(fileConfig, envConfig);
  const cliConfig = parseCliOverrides(options.argv ?? process.argv);

  return mergeRuntimeConfig(withEnv, cliConfig);
}

export function resolveLlmApiKey(
  llmConfig: RuntimeConfig['llm'],
  explicitApiKey?: string,
): string | undefined {
  return firstDefined(
    explicitApiKey?.trim() ? explicitApiKey : undefined,
    llmConfig.deepseekApiKey?.trim() ? llmConfig.deepseekApiKey : undefined,
    llmConfig.openaiApiKey?.trim() ? llmConfig.openaiApiKey : undefined,
    llmConfig.apiKey?.trim() ? llmConfig.apiKey : undefined,
  );
}

export const runtimeConfig = createRuntimeConfig();

export type { RuntimeConfig };
