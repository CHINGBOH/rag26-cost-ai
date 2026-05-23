# Recovery Procedures - RAG Dashboard Production

## Quick Recovery Reference

| Scenario | RTO | RPO | Procedure |
|----------|-----|-----|-----------|
| Single table corruption | 15 min | 1 hour | Point-in-time restore |
| Database loss | 30 min | 4 hours | Full restore from backup |
| Vector DB loss | 20 min | 1 day | Qdrant snapshot restore |
| Complete infrastructure | 2 hours | 4 hours | Full environment rebuild |

## Database Recovery

### PostgreSQL Point-in-Time Recovery

**Objective**: Recover to a specific timestamp before data corruption

**Steps**:

1. **Identify the recovery target**
   ```bash
   # Find the time of corruption
   RECOVERY_TIME="2026-05-05 14:30:00"
   ```

2. **Stop the application**
   ```bash
   docker-compose stop web api worker
   ```

3. **Restore from backup**
   ```bash
   # Connect to PostgreSQL
   psql -U postgres -h localhost
   
   # Verify current transaction log
   SELECT * FROM pg_wal_replay_pause();
   
   # Restore to point in time
   pg_restore -U rag_user -d rag_db --exit-on-error \
     /backup/rag_db_20260505.dump
   ```

4. **Verify data integrity**
   ```bash
   # Check for logical inconsistencies
   psql -U rag_user -d rag_db -c "SELECT COUNT(*) FROM document_registry;"
   psql -U rag_user -d rag_db -c "SELECT COUNT(*) FROM chunks;"
   
   # Verify all tables exist
   psql -U rag_user -d rag_db -c "\dt"
   ```

5. **Re-index if needed**
   ```bash
   psql -U rag_user -d rag_db -c "REINDEX DATABASE rag_db;"
   ```

6. **Restart application**
   ```bash
   docker-compose up -d
   ```

### Full Database Recovery

**Objective**: Restore entire database from backup

**Prerequisites**:
- Access to backup files
- Backup encryption key (if encrypted)
- Docker and PostgreSQL CLI tools

**Steps**:

1. **Prepare recovery environment**
   ```bash
   # Stop services
   docker-compose down
   
   # Create new database cluster
   docker-compose up -d postgres
   
   # Wait for PostgreSQL to initialize
   sleep 10
   ```

2. **Restore database**
   ```bash
   # Download backup from S3
   aws s3 cp s3://rag-dashboard-backups/rag_db_latest.dump /tmp/rag_db.dump
   
   # Verify backup file
   file /tmp/rag_db.dump
   
   # Restore
   pg_restore -U rag_user -h localhost \
     --format=custom \
     --exit-on-error \
     /tmp/rag_db.dump
   ```

3. **Validate recovery**
   ```bash
   psql -U rag_user -d rag_db -c "SELECT * FROM document_registry LIMIT 1;"
   psql -U rag_user -d rag_db -c "SELECT * FROM chunks LIMIT 1;"
   psql -U rag_user -d rag_db -c "SELECT * FROM document_chunks LIMIT 1;"
   ```

4. **Restart all services**
   ```bash
   docker-compose up -d
   ```

5. **Verify application health**
   ```bash
   curl http://localhost:8000/health
   curl http://localhost:8002/health
   curl http://localhost:3000/api/health
   ```

## Vector Database Recovery

### Qdrant Snapshot Restore

**Steps**:

1. **Stop Qdrant service**
   ```bash
   docker-compose stop qdrant
   ```

2. **Restore snapshot**
   ```bash
   # Download snapshot from S3
   aws s3 cp s3://rag-dashboard-backups/qdrant_snapshot_latest.tar /tmp/snapshot.tar
   
   # Extract to Qdrant storage
   tar -xf /tmp/snapshot.tar -C qdrant_storage/
   ```

3. **Verify collections**
   ```bash
   curl -X GET http://qdrant:6333/collections
   ```

4. **Start Qdrant**
   ```bash
   docker-compose up -d qdrant
   ```

### Elasticsearch Snapshot Restore

**Steps**:

1. **List available snapshots**
   ```bash
   curl -X GET "elasticsearch:9200/_cat/snapshots/backup_repo"
   ```

2. **Restore snapshot**
   ```bash
   curl -X POST "elasticsearch:9200/_snapshot/backup_repo/snapshot_20260505/_restore" \
     -H "Content-Type: application/json" -d '{
       "indices": "documents",
       "index_settings": {
         "index.number_of_replicas": 0
       }
     }'
   ```

3. **Monitor restore progress**
   ```bash
   curl -X GET "elasticsearch:9200/_cat/recovery"
   ```

## Configuration Recovery

### Restore from Git

**Steps**:

1. **Clone recovery repository**
   ```bash
   git clone --depth=1 -b backup/2026-05-05 \
     https://github.com/CHINGBOH/RAG26.git /tmp/rag26-recovery
   ```

2. **Restore configuration files**
   ```bash
   cp /tmp/rag26-recovery/config/* /app/config/
   cp /tmp/rag26-recovery/.env.encrypted /app/.env
   gpg --decrypt /app/.env.encrypted > /app/.env
   chmod 600 /app/.env
   ```

3. **Verify configuration**
   ```bash
   cat /app/config/config.yaml | grep -E "(version|timestamp)"
   ```

## Infrastructure Recovery

### Rebuild from Docker Images

**Steps**:

1. **List available images**
   ```bash
   docker images | grep rag
   ```

2. **Pull latest images from registry**
   ```bash
   docker-compose pull
   ```

3. **Rebuild volumes if needed**
   ```bash
   docker-compose down -v
   docker-compose up -d
   ```

4. **Restore data**
   - See Database Recovery section above

### Restore from IaC (Terraform)

**Steps**:

1. **Review Terraform state**
   ```bash
   cd infrastructure/
   terraform show
   ```

2. **Verify current resources**
   ```bash
   terraform plan
   ```

3. **Rebuild if necessary**
   ```bash
   terraform apply -auto-approve
   ```

## Health Checks After Recovery

### Critical Endpoints

```bash
# API Health
curl -v http://localhost:8000/health
curl -v http://localhost:8002/health
curl -v http://localhost:3000/api/health

# Database Connectivity
psql -U rag_user -d rag_db -c "SELECT 1"

# Vector DB
curl http://localhost:6333/health

# Cache
redis-cli ping

# Search
curl -v http://localhost:9200/
```

### Data Integrity Checks

```bash
# Count documents
psql -U rag_user -d rag_db -c "SELECT COUNT(*) FROM document_registry;"

# Check for orphaned chunks
psql -U rag_user -d rag_db -c "
  SELECT chunk_id FROM chunks
  WHERE document_id NOT IN (SELECT id FROM document_registry)
  LIMIT 10;"

# Verify vector count
curl http://localhost:6333/collections/documents/count
```

## Rollback After Recovery

If recovery fails or introduces new issues:

1. **Revert to previous state**
   ```bash
   docker-compose down
   # Restore from earlier backup
   ```

2. **Notify stakeholders**
   - Send incident notification
   - Update status page

3. **Post-Incident Review**
   - Document what went wrong
   - Update recovery procedures
   - Schedule team meeting

## Recovery Contacts

| Role | Name | Contact |
|------|------|---------|
| DBA | [Name] | [Email/Phone] |
| DevOps Lead | [Name] | [Email/Phone] |
| Engineering Manager | [Name] | [Email/Phone] |

## Related Documents

- [Backup Strategy](backup-strategy.md)
- [Incident Response Plan](incident-response.md)
- [Rollback Plan](../ISSUE_96_FIX_REPORT.md)

## Revision History

| Date | Author | Changes |
|------|--------|---------|
| 2026-05-05 | System | Initial version |

---
**Last Updated**: 2026-05-05
**Next Review**: 2026-06-05
