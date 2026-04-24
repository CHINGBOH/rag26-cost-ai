import { QdrantClient } from '@qdrant/qdrant-js';
import { Pool } from 'pg';

const QDRANT_HOST = process.env.QDRANT_HOST || 'localhost';
const QDRANT_PORT = parseInt(process.env.QDRANT_PORT || '6333');

const PG_HOST = process.env.PG_HOST || process.env.POSTGRES_HOST || 'localhost';
const PG_PORT = parseInt(process.env.PG_PORT || process.env.POSTGRES_PORT || '5432');
const PG_DB = process.env.PG_DB || process.env.POSTGRES_DB || 'rag_db';
const PG_USER = process.env.PG_USER || process.env.POSTGRES_USER || 'rag_user';
const PG_PASSWORD = process.env.PG_PASSWORD || process.env.POSTGRES_PASSWORD || 'rag_password';

export interface DatabaseClients {
  qdrant: QdrantClient;
  postgres?: Pool;
}

export async function initializeDatabases(): Promise<DatabaseClients> {
  const qdrant = new QdrantClient({
    url: `http://${QDRANT_HOST}:${QDRANT_PORT}`,
  });

  const clients: DatabaseClients = { qdrant };

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
    console.log('[DB] PostgreSQL connected');
  } catch (e) {
    console.warn('[DB] PostgreSQL not available:', (e as Error).message);
  }

  return clients;
}

export async function closeDatabases(clients: DatabaseClients): Promise<void> {
  if (clients.postgres) {
    await clients.postgres.end();
  }
}
