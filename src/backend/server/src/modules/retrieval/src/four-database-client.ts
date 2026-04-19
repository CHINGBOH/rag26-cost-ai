import { QdrantClient } from '@qdrant/qdrant-js';
import { Client as ElasticsearchClient } from '@elastic/elasticsearch';
import { Neo4jGraph } from '@langchain/community/graphs/neo4j_graph';
import { Pool } from 'pg';

const QDRANT_HOST = process.env.QDRANT_HOST || 'localhost';
const QDRANT_PORT = parseInt(process.env.QDRANT_PORT || '6333');

const ES_HOST = process.env.ES_HOST || 'localhost';
const ES_PORT = parseInt(process.env.ES_PORT || '9200');

const NEO4J_URI = process.env.NEO4J_URI || 'bolt://localhost:7687';
const NEO4J_USER = process.env.NEO4J_USER || 'neo4j';
const NEO4J_PASSWORD = process.env.NEO4J_PASSWORD || 'password';

const PG_HOST = process.env.PG_HOST || 'localhost';
const PG_PORT = parseInt(process.env.PG_PORT || '5432');
const PG_DB = process.env.PG_DB || 'rag_db';
const PG_USER = process.env.PG_USER || 'rag_user';
const PG_PASSWORD = process.env.PG_PASSWORD || 'rag_password';

export interface FourDatabaseClients {
  qdrant: QdrantClient;
  elasticsearch?: ElasticsearchClient;
  neo4j?: Neo4jGraph;
  postgres?: Pool;
}

export async function initializeFourDatabases(): Promise<FourDatabaseClients> {
  const qdrant = new QdrantClient({
    url: `http://${QDRANT_HOST}:${QDRANT_PORT}`,
  });

  const clients: FourDatabaseClients = { qdrant };

  try {
    const es = new ElasticsearchClient({
      node: `http://${ES_HOST}:${ES_PORT}`,
    });
    await es.ping();
    clients.elasticsearch = es;
    console.log('[FourDB] Elasticsearch connected');
  } catch (e) {
    console.warn('[FourDB] Elasticsearch not available:', (e as Error).message);
  }

  try {
    const neo4j = await Neo4jGraph.initialize({
      url: NEO4J_URI,
      username: NEO4J_USER,
      password: NEO4J_PASSWORD,
    });
    clients.neo4j = neo4j;
    console.log('[FourDB] Neo4j connected');
  } catch (e) {
    console.warn('[FourDB] Neo4j not available:', (e as Error).message);
  }

  try {
    const pg = new Pool({
      host: PG_HOST,
      port: PG_PORT,
      database: PG_DB,
      user: PG_USER,
      password: PG_PASSWORD,
    });
    await pg.query('SELECT 1');
    clients.postgres = pg;
    console.log('[FourDB] PostgreSQL connected');
  } catch (e) {
    console.warn('[FourDB] PostgreSQL not available:', (e as Error).message);
  }

  return clients;
}

export async function closeFourDatabases(clients: FourDatabaseClients): Promise<void> {
  if (clients.elasticsearch) {
    await clients.elasticsearch.close();
  }
  if (clients.neo4j) {
    await clients.neo4j.close();
  }
  if (clients.postgres) {
    await clients.postgres.end();
  }
}
