import { describe, expect, it } from 'vitest';

import { createRuntimeConfig, resolveLlmApiKey } from '../config/runtime';

const baseConfig = {
  app: {
    environment: 'production',
  },
  logging: {
    level: 'info',
    outputFile: './logs/app.log',
    enableConsole: true,
    enableFile: false,
    prettyPrint: false,
    flushIntervalMs: 5000,
  },
  telemetry: {
    endpoint: '',
    serviceName: 'node-orchestrator',
  },
  databases: {
    qdrantUrl: 'http://localhost:6333',
    neo4jUrl: 'bolt://localhost:7687',
    neo4jUsername: 'neo4j',
    neo4jPassword: '',
    elasticsearchUrl: 'http://localhost:9200',
    elasticsearchUsername: '',
    elasticsearchPassword: '',
    postgresHost: 'localhost',
    postgresPort: 5432,
    postgresDatabase: 'rag_db',
    postgresUser: 'rag_user',
    postgresPassword: 'rag_password',
  },
  embeddings: {
    model: 'text-embedding-ada-002',
    dimensions: 1536,
    batchSize: 32,
  },
  retrieval: {
    sessionContextCollection: 'session_context',
    documentsCollection: 'document_chunks',
    documentsIndexName: 'documents',
    timeoutMs: 30000,
    defaultTopK: 10,
    enableRerank: true,
    enableFusion: true,
    vectorWeight: 0.6,
    textWeight: 0.4,
    rerankWeight: 0.5,
    graphWeight: 0,
  },
  cascadeRetrieval: {
    enableNeo4j: false,
    enableElasticsearch: false,
    enablePostgres: false,
    defaultTopK: 10,
    vectorWeight: 0.5,
    graphWeight: 0.3,
    keywordWeight: 0.2,
  },
  ocr: {
    language: 'ch',
    dpi: 300,
    timeoutMs: 300000,
    useGpu: false,
    chunkSize: 512,
    chunkOverlap: 50,
    minChunkSize: 100,
  },
  storage: {
    queueName: 'queue:default',
    storeKeyPrefix: 'store:',
    redisMaxRetriesPerRequest: 3,
    redisRetryMaxDelayMs: 3000,
  },
  persistence: {
    enabled: false,
    connectionString: '',
    ssl: false,
  },
  expertJudgment: {
    baseUrl: 'https://api.kimi.com/coding/v1',
    apiKey: '',
    model: 'kimi-for-coding',
    temperature: 0.3,
    maxTokens: 2000,
  },
  server: {
    host: '0.0.0.0',
    port: 3001,
    corsOrigins: ['http://localhost:3000'],
    wsPublicUrl: 'ws://localhost:8081/ws',
    requestTimeoutMs: 30000,
    connectionTimeoutMs: 30000,
  },
  rateLimit: {
    max: 100,
    timeWindow: '1 minute',
  },
  heartbeat: {
    broadcastIntervalMs: 3000,
    silenceThresholdMs: 30000,
    statusLogIntervalMs: 60000,
  },
  llm: {
    provider: 'deepseek',
    baseUrl: 'https://api.deepseek.com',
    model: 'deepseek-chat',
    apiKey: '',
    deepseekApiKey: '',
    openaiApiKey: '',
    temperature: 0.7,
    maxTokens: 2000,
  },
  services: {
    redisUrl: 'redis://localhost:6379',
    pythonApiUrl: 'http://localhost:8000',
    ocrApiUrl: 'http://localhost:8001',
    retrievalApiUrl: 'http://localhost:8002',
    wsBroadcastUrl: 'http://localhost:8081/broadcast',
  },
  cache: {
    defaultTtlSeconds: 3600,
    keyPrefix: 'rag:',
  },
  taskQueue: {
    concurrency: 3,
    evaluationConcurrency: 5,
    ocrConcurrency: 2,
  },
  pipeline: {
    uploadDir: '/tmp/rag-uploads',
    maxConcurrent: 5,
    processingLoopIntervalMs: 1000,
  },
  recursion: {
    cleanupIntervalMs: 10 * 60 * 1000,
    completedSessionMaxAgeMs: 24 * 60 * 60 * 1000,
    hardSessionMaxAgeMs: 7 * 24 * 60 * 60 * 1000,
    requestTimeoutMs: 120000,
  },
  auth: {
    serviceSecret: '',
    jwtSecret: '',
    tokenExpirySeconds: 24 * 60 * 60,
    jwtExpiresInSeconds: 3600,
    jwtRefreshExpiresInSeconds: 7 * 24 * 60 * 60,
    defaultAdminUsername: 'admin',
    defaultAdminPassword: '',
  },
};

describe('createRuntimeConfig', () => {
  it('keeps config-file defaults when there are no overrides', () => {
    const resolved = createRuntimeConfig({
      baseConfig,
      env: {},
      argv: ['node', 'server'],
    });

    expect(resolved.app.environment).toBe('production');
    expect(resolved.logging.level).toBe('info');
    expect(resolved.telemetry.serviceName).toBe('node-orchestrator');
    expect(resolved.databases.qdrantUrl).toBe('http://localhost:6333');
    expect(resolved.databases.neo4jUrl).toBe('bolt://localhost:7687');
    expect(resolved.databases.elasticsearchUrl).toBe('http://localhost:9200');
    expect(resolved.embeddings.model).toBe('text-embedding-ada-002');
    expect(resolved.retrieval.sessionContextCollection).toBe('session_context');
    expect(resolved.retrieval.documentsCollection).toBe('document_chunks');
    expect(resolved.cascadeRetrieval.enableNeo4j).toBe(false);
    expect(resolved.cascadeRetrieval.keywordWeight).toBe(0.2);
    expect(resolved.ocr.language).toBe('ch');
    expect(resolved.storage.queueName).toBe('queue:default');
    expect(resolved.persistence.enabled).toBe(false);
    expect(resolved.expertJudgment.model).toBe('kimi-for-coding');
    expect(resolved.server.port).toBe(3001);
    expect(resolved.server.corsOrigins).toEqual(['http://localhost:3000']);
    expect(resolved.server.wsPublicUrl).toBe('ws://localhost:8081/ws');
    expect(resolved.llm.provider).toBe('deepseek');
    expect(resolved.llm.baseUrl).toBe('https://api.deepseek.com');
    expect(resolved.llm.maxTokens).toBe(2000);
    expect(resolved.services.redisUrl).toBe('redis://localhost:6379');
    expect(resolved.pipeline.uploadDir).toBe('/tmp/rag-uploads');
    expect(resolved.auth.defaultAdminUsername).toBe('admin');
  });

  it('applies environment variables over config-file defaults', () => {
    const resolved = createRuntimeConfig({
      baseConfig,
      env: {
        NODE_ENV: 'development',
        LOG_LEVEL: 'debug',
        ENABLE_FILE_LOG: 'true',
        LOG_PRETTY_PRINT: 'false',
        LOG_FLUSH_INTERVAL_MS: '2500',
        OTEL_EXPORTER_OTLP_ENDPOINT: 'http://tempo.example:4318',
        OTEL_SERVICE_NAME: 'rag-node-test',
        QDRANT_HOST: 'qdrant.internal',
        QDRANT_PORT: '7000',
        NEO4J_URI: 'bolt://neo4j.internal:7687',
        NEO4J_USERNAME: 'neo4j-runtime',
        NEO4J_PASSWORD: 'neo4j-runtime-pw',
        ES_HOST: 'http://es.internal:9200',
        ES_USERNAME: 'elastic-runtime',
        ES_PASSWORD: 'elastic-runtime-pw',
        EMBEDDING_MODEL: 'text-embedding-3-small',
        EMBEDDING_DIMENSIONS: '1024',
        EMBEDDING_BATCH_SIZE: '16',
        RETRIEVAL_SESSION_CONTEXT_COLLECTION: 'runtime-session-context',
        RETRIEVAL_DOCUMENTS_COLLECTION: 'runtime-documents',
        RETRIEVAL_DOCUMENTS_INDEX_NAME: 'runtime-index',
        RETRIEVAL_TIMEOUT_MS: '45000',
        RETRIEVAL_DEFAULT_TOP_K: '12',
        RETRIEVAL_ENABLE_RERANK: 'false',
        RETRIEVAL_ENABLE_FUSION: 'false',
        RETRIEVAL_VECTOR_WEIGHT: '0.7',
        RETRIEVAL_TEXT_WEIGHT: '0.3',
        FUSION_WEIGHT_RERANK: '0.2',
        FUSION_WEIGHT_GRAPH: '0.1',
        CASCADE_RETRIEVAL_ENABLE_NEO4J: 'true',
        CASCADE_RETRIEVAL_ENABLE_ELASTICSEARCH: 'true',
        CASCADE_RETRIEVAL_ENABLE_POSTGRES: 'true',
        CASCADE_RETRIEVAL_DEFAULT_TOP_K: '18',
        CASCADE_RETRIEVAL_VECTOR_WEIGHT: '0.52',
        CASCADE_RETRIEVAL_GRAPH_WEIGHT: '0.28',
        CASCADE_RETRIEVAL_KEYWORD_WEIGHT: '0.20',
        OCR_LANGUAGE: 'en',
        OCR_DPI: '200',
        OCR_TIMEOUT_MS: '120000',
        OCR_USE_GPU: 'true',
        OCR_CHUNK_SIZE: '256',
        OCR_CHUNK_OVERLAP: '32',
        OCR_MIN_CHUNK_SIZE: '80',
        STORAGE_REDIS_QUEUE_NAME: 'queue:runtime',
        STORAGE_REDIS_STORE_KEY_PREFIX: 'store:runtime:',
        STORAGE_REDIS_MAX_RETRIES_PER_REQUEST: '5',
        STORAGE_REDIS_RETRY_MAX_DELAY_MS: '6000',
        PERSISTENCE_ENABLED: 'true',
        PERSISTENCE_CONNECTION_STRING: 'postgres://persist.example:5432/rag',
        PERSISTENCE_SSL: 'true',
        EXPERT_JUDGMENT_BASE_URL: 'https://judge.example/v1',
        EXPERT_JUDGMENT_API_KEY: 'judge-key',
        EXPERT_JUDGMENT_MODEL: 'judge-model',
        EXPERT_JUDGMENT_TEMPERATURE: '0.15',
        EXPERT_JUDGMENT_MAX_TOKENS: '900',
        POSTGRES_HOST: 'pg.internal',
        POSTGRES_PORT: '5544',
        POSTGRES_DB: 'rag_test',
        POSTGRES_USER: 'rag_tester',
        POSTGRES_PASSWORD: 'rag_pw',
        PORT: '4100',
        CORS_ORIGIN: 'http://localhost:5173,http://localhost:4173',
        WS_PUBLIC_URL: 'ws://localhost:9090/ws',
        LLM_PROVIDER: 'openai',
        LLM_BASE_URL: 'https://example.com/v1',
        OPENAI_API_KEY: 'openai-env-key',
        HEARTBEAT_SILENCE_THRESHOLD_MS: '45000',
        REDIS_URL: 'redis://cache.example:6380/2',
        PYTHON_URL: 'http://python.example:9000',
        OCR_API_URL: 'http://ocr.example:9001',
        RETRIEVAL_URL: 'http://retrieval.example:9002',
        WS_GATEWAY_URL: 'http://ws.example:9003/broadcast',
        PIPELINE_UPLOAD_DIR: '/var/tmp/rag-uploads',
        PIPELINE_MAX_CONCURRENT: '7',
        TASK_QUEUE_CONCURRENCY: '6',
        DEFAULT_ADMIN_PASSWORD: 'from-env-secret',
      },
      argv: ['node', 'server'],
    });

    expect(resolved.app.environment).toBe('development');
    expect(resolved.logging.level).toBe('debug');
    expect(resolved.logging.enableFile).toBe(true);
    expect(resolved.logging.prettyPrint).toBe(false);
    expect(resolved.logging.flushIntervalMs).toBe(2500);
    expect(resolved.telemetry.endpoint).toBe('http://tempo.example:4318');
    expect(resolved.telemetry.serviceName).toBe('rag-node-test');
    expect(resolved.databases.qdrantUrl).toBe('http://qdrant.internal:7000');
    expect(resolved.databases.neo4jUrl).toBe('bolt://neo4j.internal:7687');
    expect(resolved.databases.neo4jUsername).toBe('neo4j-runtime');
    expect(resolved.databases.neo4jPassword).toBe('neo4j-runtime-pw');
    expect(resolved.databases.elasticsearchUrl).toBe('http://es.internal:9200');
    expect(resolved.databases.elasticsearchUsername).toBe('elastic-runtime');
    expect(resolved.databases.elasticsearchPassword).toBe('elastic-runtime-pw');
    expect(resolved.embeddings.model).toBe('text-embedding-3-small');
    expect(resolved.embeddings.dimensions).toBe(1024);
    expect(resolved.embeddings.batchSize).toBe(16);
    expect(resolved.retrieval.sessionContextCollection).toBe('runtime-session-context');
    expect(resolved.retrieval.documentsCollection).toBe('runtime-documents');
    expect(resolved.retrieval.documentsIndexName).toBe('runtime-index');
    expect(resolved.retrieval.timeoutMs).toBe(45000);
    expect(resolved.retrieval.defaultTopK).toBe(12);
    expect(resolved.retrieval.enableRerank).toBe(false);
    expect(resolved.retrieval.enableFusion).toBe(false);
    expect(resolved.retrieval.vectorWeight).toBe(0.7);
    expect(resolved.retrieval.textWeight).toBe(0.3);
    expect(resolved.retrieval.rerankWeight).toBe(0.2);
    expect(resolved.retrieval.graphWeight).toBe(0.1);
    expect(resolved.cascadeRetrieval.enableNeo4j).toBe(true);
    expect(resolved.cascadeRetrieval.enableElasticsearch).toBe(true);
    expect(resolved.cascadeRetrieval.enablePostgres).toBe(true);
    expect(resolved.cascadeRetrieval.defaultTopK).toBe(18);
    expect(resolved.cascadeRetrieval.vectorWeight).toBe(0.52);
    expect(resolved.cascadeRetrieval.graphWeight).toBe(0.28);
    expect(resolved.cascadeRetrieval.keywordWeight).toBe(0.2);
    expect(resolved.ocr.language).toBe('en');
    expect(resolved.ocr.dpi).toBe(200);
    expect(resolved.ocr.timeoutMs).toBe(120000);
    expect(resolved.ocr.useGpu).toBe(true);
    expect(resolved.ocr.chunkSize).toBe(256);
    expect(resolved.ocr.chunkOverlap).toBe(32);
    expect(resolved.ocr.minChunkSize).toBe(80);
    expect(resolved.storage.queueName).toBe('queue:runtime');
    expect(resolved.storage.storeKeyPrefix).toBe('store:runtime:');
    expect(resolved.storage.redisMaxRetriesPerRequest).toBe(5);
    expect(resolved.storage.redisRetryMaxDelayMs).toBe(6000);
    expect(resolved.persistence.enabled).toBe(true);
    expect(resolved.persistence.connectionString).toBe('postgres://persist.example:5432/rag');
    expect(resolved.persistence.ssl).toBe(true);
    expect(resolved.expertJudgment.baseUrl).toBe('https://judge.example/v1');
    expect(resolved.expertJudgment.apiKey).toBe('judge-key');
    expect(resolved.expertJudgment.model).toBe('judge-model');
    expect(resolved.expertJudgment.temperature).toBe(0.15);
    expect(resolved.expertJudgment.maxTokens).toBe(900);
    expect(resolved.databases.postgresHost).toBe('pg.internal');
    expect(resolved.databases.postgresPort).toBe(5544);
    expect(resolved.databases.postgresDatabase).toBe('rag_test');
    expect(resolved.databases.postgresUser).toBe('rag_tester');
    expect(resolved.databases.postgresPassword).toBe('rag_pw');
    expect(resolved.server.port).toBe(4100);
    expect(resolved.server.corsOrigins).toEqual([
      'http://localhost:5173',
      'http://localhost:4173',
    ]);
    expect(resolved.server.wsPublicUrl).toBe('ws://localhost:9090/ws');
    expect(resolved.llm.provider).toBe('openai');
    expect(resolved.llm.baseUrl).toBe('https://example.com/v1');
    expect(resolved.llm.openaiApiKey).toBe('openai-env-key');
    expect(resolved.heartbeat.silenceThresholdMs).toBe(45000);
    expect(resolved.services.redisUrl).toBe('redis://cache.example:6380/2');
    expect(resolved.services.pythonApiUrl).toBe('http://python.example:9000');
    expect(resolved.services.ocrApiUrl).toBe('http://ocr.example:9001');
    expect(resolved.services.retrievalApiUrl).toBe('http://retrieval.example:9002');
    expect(resolved.services.wsBroadcastUrl).toBe('http://ws.example:9003/broadcast');
    expect(resolved.pipeline.uploadDir).toBe('/var/tmp/rag-uploads');
    expect(resolved.pipeline.maxConcurrent).toBe(7);
    expect(resolved.taskQueue.concurrency).toBe(6);
    expect(resolved.auth.defaultAdminPassword).toBe('from-env-secret');
  });

  it('applies CLI arguments over environment variables', () => {
    const resolved = createRuntimeConfig({
      baseConfig,
      env: {
        PORT: '4100',
        RATE_LIMIT_MAX: '120',
      },
      argv: [
        'node',
        'server',
        '--node-env',
        'test',
        '--log-level',
        'warn',
        '--log-enable-file',
        'false',
        '--otel-service-name',
        'rag-node-cli',
        '--qdrant-url',
        'http://127.0.0.1:7333',
        '--neo4j-url',
        'bolt://127.0.0.1:8687',
        '--neo4j-username',
        'neo4j-cli',
        '--neo4j-password',
        'neo4j-cli-pw',
        '--elasticsearch-url',
        'http://127.0.0.1:9920',
        '--elasticsearch-username',
        'elastic-cli',
        '--elasticsearch-password',
        'elastic-cli-pw',
        '--embedding-model',
        'text-embedding-cli',
        '--embedding-dimensions',
        '768',
        '--embedding-batch-size',
        '24',
        '--retrieval-session-context-collection',
        'cli-session-context',
        '--retrieval-documents-collection',
        'cli-documents',
        '--retrieval-documents-index-name',
        'cli-index',
        '--retrieval-timeout-ms',
        '60000',
        '--retrieval-default-top-k',
        '14',
        '--retrieval-enable-rerank',
        'true',
        '--retrieval-enable-fusion',
        'false',
        '--retrieval-vector-weight',
        '0.55',
        '--retrieval-text-weight',
        '0.45',
        '--retrieval-rerank-weight',
        '0.25',
        '--retrieval-graph-weight',
        '0.05',
        '--cascade-enable-neo4j',
        'true',
        '--cascade-enable-elasticsearch',
        'true',
        '--cascade-enable-postgres',
        'true',
        '--cascade-default-top-k',
        '16',
        '--cascade-vector-weight',
        '0.51',
        '--cascade-graph-weight',
        '0.29',
        '--cascade-keyword-weight',
        '0.20',
        '--ocr-language',
        'ja',
        '--ocr-dpi',
        '240',
        '--ocr-timeout-ms',
        '180000',
        '--ocr-use-gpu',
        'true',
        '--ocr-chunk-size',
        '384',
        '--ocr-chunk-overlap',
        '24',
        '--ocr-min-chunk-size',
        '96',
        '--storage-queue-name',
        'queue:cli',
        '--storage-store-key-prefix',
        'store:cli:',
        '--storage-redis-max-retries',
        '7',
        '--storage-redis-retry-max-delay-ms',
        '9000',
        '--persistence-enabled',
        'true',
        '--persistence-connection-string',
        'postgres://cli.example:5432/rag_cli',
        '--persistence-ssl',
        'true',
        '--expert-judgment-base-url',
        'https://judge.cli/v1',
        '--expert-judgment-api-key',
        'judge-cli-key',
        '--expert-judgment-model',
        'judge-cli-model',
        '--expert-judgment-temperature',
        '0.2',
        '--expert-judgment-max-tokens',
        '1200',
        '--pg-host',
        '127.0.0.1',
        '--pg-port',
        '6432',
        '--pg-database',
        'rag_cli',
        '--pg-user',
        'cli_user',
        '--pg-password',
        'cli_pw',
        '--port',
        '4300',
        '--host',
        '127.0.0.1',
        '--ws-public-url',
        'ws://127.0.0.1:4301/ws',
        '--rate-limit-max',
        '250',
        '--llm-provider',
        'kimi',
        '--llm-model',
        'kimi-for-coding',
        '--llm-temperature',
        '0.3',
        '--llm-max-tokens',
        '4096',
        '--redis-url',
        'redis://127.0.0.1:6390/4',
        '--python-api-url',
        'http://127.0.0.1:8010',
        '--upload-dir',
        '/srv/rag-uploads',
        '--pipeline-max-concurrent',
        '9',
        '--auth-token-expiry-seconds',
        '7200',
        '--default-admin-username',
        'super-admin',
      ],
    });

    expect(resolved.app.environment).toBe('test');
    expect(resolved.logging.level).toBe('warn');
    expect(resolved.logging.enableFile).toBe(false);
    expect(resolved.telemetry.serviceName).toBe('rag-node-cli');
    expect(resolved.databases.qdrantUrl).toBe('http://127.0.0.1:7333');
    expect(resolved.databases.neo4jUrl).toBe('bolt://127.0.0.1:8687');
    expect(resolved.databases.neo4jUsername).toBe('neo4j-cli');
    expect(resolved.databases.neo4jPassword).toBe('neo4j-cli-pw');
    expect(resolved.databases.elasticsearchUrl).toBe('http://127.0.0.1:9920');
    expect(resolved.databases.elasticsearchUsername).toBe('elastic-cli');
    expect(resolved.databases.elasticsearchPassword).toBe('elastic-cli-pw');
    expect(resolved.embeddings.model).toBe('text-embedding-cli');
    expect(resolved.embeddings.dimensions).toBe(768);
    expect(resolved.embeddings.batchSize).toBe(24);
    expect(resolved.retrieval.sessionContextCollection).toBe('cli-session-context');
    expect(resolved.retrieval.documentsCollection).toBe('cli-documents');
    expect(resolved.retrieval.documentsIndexName).toBe('cli-index');
    expect(resolved.retrieval.timeoutMs).toBe(60000);
    expect(resolved.retrieval.defaultTopK).toBe(14);
    expect(resolved.retrieval.enableRerank).toBe(true);
    expect(resolved.retrieval.enableFusion).toBe(false);
    expect(resolved.retrieval.vectorWeight).toBe(0.55);
    expect(resolved.retrieval.textWeight).toBe(0.45);
    expect(resolved.retrieval.rerankWeight).toBe(0.25);
    expect(resolved.retrieval.graphWeight).toBe(0.05);
    expect(resolved.cascadeRetrieval.enableNeo4j).toBe(true);
    expect(resolved.cascadeRetrieval.enableElasticsearch).toBe(true);
    expect(resolved.cascadeRetrieval.enablePostgres).toBe(true);
    expect(resolved.cascadeRetrieval.defaultTopK).toBe(16);
    expect(resolved.cascadeRetrieval.vectorWeight).toBe(0.51);
    expect(resolved.cascadeRetrieval.graphWeight).toBe(0.29);
    expect(resolved.cascadeRetrieval.keywordWeight).toBe(0.2);
    expect(resolved.ocr.language).toBe('ja');
    expect(resolved.ocr.dpi).toBe(240);
    expect(resolved.ocr.timeoutMs).toBe(180000);
    expect(resolved.ocr.useGpu).toBe(true);
    expect(resolved.ocr.chunkSize).toBe(384);
    expect(resolved.ocr.chunkOverlap).toBe(24);
    expect(resolved.ocr.minChunkSize).toBe(96);
    expect(resolved.storage.queueName).toBe('queue:cli');
    expect(resolved.storage.storeKeyPrefix).toBe('store:cli:');
    expect(resolved.storage.redisMaxRetriesPerRequest).toBe(7);
    expect(resolved.storage.redisRetryMaxDelayMs).toBe(9000);
    expect(resolved.persistence.enabled).toBe(true);
    expect(resolved.persistence.connectionString).toBe('postgres://cli.example:5432/rag_cli');
    expect(resolved.persistence.ssl).toBe(true);
    expect(resolved.expertJudgment.baseUrl).toBe('https://judge.cli/v1');
    expect(resolved.expertJudgment.apiKey).toBe('judge-cli-key');
    expect(resolved.expertJudgment.model).toBe('judge-cli-model');
    expect(resolved.expertJudgment.temperature).toBe(0.2);
    expect(resolved.expertJudgment.maxTokens).toBe(1200);
    expect(resolved.databases.postgresHost).toBe('127.0.0.1');
    expect(resolved.databases.postgresPort).toBe(6432);
    expect(resolved.databases.postgresDatabase).toBe('rag_cli');
    expect(resolved.databases.postgresUser).toBe('cli_user');
    expect(resolved.databases.postgresPassword).toBe('cli_pw');
    expect(resolved.server.port).toBe(4300);
    expect(resolved.server.host).toBe('127.0.0.1');
    expect(resolved.server.wsPublicUrl).toBe('ws://127.0.0.1:4301/ws');
    expect(resolved.rateLimit.max).toBe(250);
    expect(resolved.llm.provider).toBe('kimi');
    expect(resolved.llm.model).toBe('kimi-for-coding');
    expect(resolved.llm.temperature).toBe(0.3);
    expect(resolved.llm.maxTokens).toBe(4096);
    expect(resolved.services.redisUrl).toBe('redis://127.0.0.1:6390/4');
    expect(resolved.services.pythonApiUrl).toBe('http://127.0.0.1:8010');
    expect(resolved.pipeline.uploadDir).toBe('/srv/rag-uploads');
    expect(resolved.pipeline.maxConcurrent).toBe(9);
    expect(resolved.auth.tokenExpirySeconds).toBe(7200);
    expect(resolved.auth.defaultAdminUsername).toBe('super-admin');
  });

  it('resolves LLM API keys in the expected precedence order', () => {
    const resolved = createRuntimeConfig({
      baseConfig,
      env: {
        DEEPSEEK_API_KEY: 'deepseek-key',
        OPENAI_API_KEY: 'openai-key',
        LLM_API_KEY: 'generic-key',
      },
      argv: ['node', 'server'],
    });

    expect(resolveLlmApiKey(resolved.llm)).toBe('deepseek-key');
    expect(resolveLlmApiKey(resolved.llm, 'runtime-override')).toBe('runtime-override');
  });
});
