# Backup Strategy - RAG Dashboard Production

## Overview
This document outlines the backup and recovery strategy for the RAG Dashboard production environment to ensure data protection and business continuity.

## Database Backup

### PostgreSQL Backup Strategy

**Frequency**: Daily at 02:00 UTC
**Retention**: 30 days rolling window
**Location**: Cloud storage (S3-compatible)

#### Backup Methods

1. **Full Database Backups**
   - Using `pg_dump` for logical backups
   - Command: `pg_dump -U rag_user -d rag_db -h localhost --format=custom -f /backup/rag_db_$(date +%Y%m%d).dump`
   - Size: ~500MB (estimated)
   - Time: ~5 minutes

2. **Incremental Backups**
   - Using WAL archiving for point-in-time recovery
   - Configuration: `wal_level = replica`
   - Archive command configured in PostgreSQL

3. **Backup Verification**
   - Daily test restore to verify backup integrity
   - Checksum validation before archival
   - Restore time target: < 10 minutes for RTO

### Backup Locations

| Type | Primary | Secondary | Access |
|------|---------|-----------|--------|
| Database Dumps | S3 Bucket | Local Archive | Encrypted, IAM-controlled |
| WAL Archives | S3 Bucket | Local Archive | Encrypted, IAM-controlled |
| Config Files | Git Repository | S3 Bucket | Version controlled |

## Vector Database Backups

### Qdrant Snapshots

**Frequency**: Daily
**Retention**: 14 days
**Size**: ~2GB (estimated)

```bash
# Create Qdrant snapshot
curl -X POST http://qdrant:6333/snapshots
```

### Elasticsearch Snapshots

**Frequency**: Daily
**Retention**: 7 days

```bash
# Register snapshot repository
curl -X PUT "elasticsearch:9200/_snapshot/backup_repo" -H "Content-Type: application/json" -d '{
  "type": "s3",
  "settings": {
    "bucket": "rag-dashboard-backups"
  }
}'
```

## Configuration Backups

### What to Back Up

1. **Application Configuration**
   - `config/config.yaml`
   - `config/.env` (encrypted)
   - All docker-compose files

2. **Infrastructure as Code**
   - Terraform files
   - Kubernetes manifests
   - Docker images (registry)

3. **Database Schema**
   - DDL scripts in `sql/migrations`
   - Stored procedures and functions

### Backup Methods

```bash
# Git-based configuration backup
git clone https://github.com/CHINGBOH/RAG26.git rag26-backup-$(date +%Y%m%d)

# Encrypted .env backup
gpg --symmetric --cipher-algo AES256 .env -o .env.gpg
```

## Backup Verification Process

### Daily Checks
- [ ] Backup file created successfully
- [ ] File size within expected range (±10%)
- [ ] Checksum verified
- [ ] Encryption verified
- [ ] Archive logging completed

### Weekly Verification
- [ ] Test restore of PostgreSQL dump
- [ ] Verify Qdrant snapshot integrity
- [ ] Verify Elasticsearch snapshot integrity
- [ ] Document restore time

### Monthly Validation
- [ ] Full restore test in staging environment
- [ ] Document step-by-step restore procedures
- [ ] Verify all data integrity post-restore
- [ ] Update recovery procedures

## Monitoring and Alerting

### Backup Monitoring Metrics

```yaml
Alerts:
  - backup_failed: When daily backup fails to complete
    Threshold: Any failure
    Action: Notify ops team immediately
  
  - backup_delayed: When backup takes longer than expected
    Threshold: > 10 minutes
    Action: Notify ops team
  
  - storage_low: When backup storage < 20% available
    Threshold: < 20% capacity
    Action: Notify ops team to cleanup old backups
```

### Monitoring Dashboard

- Backup completion status
- Backup size trends
- Storage utilization
- Restore test results

## Recovery Procedures

See [Recovery Procedures](recovery-procedures.md) for detailed restore steps.

## Backup Schedule

```
Monday - Friday:  Daily full backup at 02:00 UTC
Saturday:         Full backup + verification
Sunday:           Full backup + weekly test restore
```

## Storage Requirements

| Component | Daily Size | 30-Day Total | Retention |
|-----------|-----------|-------------|-----------|
| PostgreSQL | 500MB | 15GB | 30 days |
| Qdrant | 200MB | 2.8GB | 14 days |
| Elasticsearch | 300MB | 2.1GB | 7 days |
| Config/Code | 50MB | 50MB | 30 days |
| **Total** | **1050MB** | **~20GB** | **Varies** |

## Disaster Recovery Contact

**On-Call DBA**: [Contact Info]
**Ops Manager**: [Contact Info]
**System Administrator**: [Contact Info]

## Review and Updates

- **Last Updated**: 2026-05-05
- **Next Review**: 2026-06-05
- **Reviewed By**: [Name]
- **Approved By**: [Name]
