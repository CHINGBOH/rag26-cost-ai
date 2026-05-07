import { describe, expect, it } from 'vitest';

import { runtimeConfig } from '../../../config/runtime';
import { resolveCascadeSearchOptions } from '../src/cascade-retrieval';

describe('resolveCascadeSearchOptions', () => {
  it('uses canonical runtime defaults without enabling optional backends', () => {
    const resolved = resolveCascadeSearchOptions();

    expect(resolved.qdrantUrl).toBe(runtimeConfig.databases.qdrantUrl);
    expect(resolved.neo4jUrl).toBe(runtimeConfig.databases.neo4jUrl);
    expect(resolved.elasticsearchUrl).toBe(runtimeConfig.databases.elasticsearchUrl);
    expect(resolved.collectionName).toBe(runtimeConfig.retrieval.documentsCollection);
    expect(resolved.indexName).toBe(runtimeConfig.retrieval.documentsIndexName);
    expect(resolved.enableNeo4j).toBe(runtimeConfig.cascadeRetrieval.enableNeo4j);
    expect(resolved.enableElasticsearch).toBe(runtimeConfig.cascadeRetrieval.enableElasticsearch);
    expect(resolved.enablePostgres).toBe(runtimeConfig.cascadeRetrieval.enablePostgres);
    expect(resolved.topK).toBe(runtimeConfig.cascadeRetrieval.defaultTopK);
    expect(resolved.vectorWeight).toBe(runtimeConfig.cascadeRetrieval.vectorWeight);
    expect(resolved.graphWeight).toBe(runtimeConfig.cascadeRetrieval.graphWeight);
    expect(resolved.keywordWeight).toBe(runtimeConfig.cascadeRetrieval.keywordWeight);
  });

  it('prefers explicit options and auto-enables backends when explicit URLs are supplied', () => {
    const resolved = resolveCascadeSearchOptions({
      qdrantUrl: 'http://qdrant.example:7333',
      neo4jUrl: 'bolt://neo4j.example:8687',
      neo4jUsername: 'neo4j-custom',
      neo4jPassword: 'neo4j-custom-pw',
      elasticsearchUrl: 'http://es.example:9920',
      elasticUsername: 'elastic-custom',
      elasticPassword: 'elastic-custom-pw',
      postgresUrl: 'postgres://custom:secret@pg.example:5432/rag',
      collectionName: 'custom-documents',
      indexName: 'custom-index',
      topK: 14,
      vectorWeight: 0.51,
      graphWeight: 0.29,
      keywordWeight: 0.2,
    });

    expect(resolved.qdrantUrl).toBe('http://qdrant.example:7333');
    expect(resolved.neo4jUrl).toBe('bolt://neo4j.example:8687');
    expect(resolved.neo4jUsername).toBe('neo4j-custom');
    expect(resolved.neo4jPassword).toBe('neo4j-custom-pw');
    expect(resolved.elasticsearchUrl).toBe('http://es.example:9920');
    expect(resolved.elasticUsername).toBe('elastic-custom');
    expect(resolved.elasticPassword).toBe('elastic-custom-pw');
    expect(resolved.postgresUrl).toBe('postgres://custom:secret@pg.example:5432/rag');
    expect(resolved.collectionName).toBe('custom-documents');
    expect(resolved.indexName).toBe('custom-index');
    expect(resolved.enableNeo4j).toBe(true);
    expect(resolved.enableElasticsearch).toBe(true);
    expect(resolved.enablePostgres).toBe(true);
    expect(resolved.topK).toBe(14);
    expect(resolved.vectorWeight).toBe(0.51);
    expect(resolved.graphWeight).toBe(0.29);
    expect(resolved.keywordWeight).toBe(0.2);
  });
});
