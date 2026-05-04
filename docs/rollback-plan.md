# Rollback Plan - RAG Dashboard Production

## Rollback Overview

This document defines the procedure to safely rollback the RAG Dashboard to a previous stable version when issues are detected in production.

## Rollback Triggers

| Condition | Decision | TTR Target |
|-----------|----------|-----------|
| > 10% error rate | Immediate | 5 minutes |
| > 50% performance degradation | Immediate | 5 minutes |
| Data corruption detected | Immediate | 15 minutes |
| Security issue exploited | Immediate | 15 minutes |
| Database migration fails | Immediate | 10 minutes |
| Service won't start | Immediate | 5 minutes |
| Unrecoverable state | Prepare to rollback | 30 minutes |

## Pre-Rollback Checklist

Before initiating rollback, verify:

- [ ] Have necessary access credentials
- [ ] Confirmed issue with multiple team members
- [ ] Backed up current state (logs, metrics)
- [ ] Identified stable previous version
- [ ] Notified stakeholders
- [ ] Prepared communication templates

## Rollback Strategies

### Strategy 1: Blue-Green Deployment Rollback (Recommended)

**Prerequisites**:
- Deployed on two identical environments (blue and green)
- Load balancer can switch between environments
- Database is shared or replicated

**Procedure**:

1. **Verify Active Environment**
   ```bash
   # Check which environment is active
   curl http://api:3000/version  # Should show current version
   docker-compose ps             # Check running containers
   ```

2. **Verify Standby Environment**
   ```bash
   # Check if standby is healthy
   curl http://api-standby:3000/version
   docker ps -a | grep standby
   ```

3. **Switch Traffic to Standby**
   ```bash
   # Update load balancer
   docker exec nginx curl -X POST http://localhost:8081/switch-environment \
     -d '{"target": "green"}'
   
   # Or manually update nginx config
   # Change upstream to point to standby servers
   ```

4. **Verify Rollback Success**
   ```bash
   # Check application responding on correct environment
   curl -H "X-Environment: green" http://api:3000/health
   
   # Monitor error rates
   watch -n 2 'curl http://monitoring:9090/metrics | grep http_requests_total'
   
   # Verify data integrity
   psql -U rag_user -d rag_db -c "SELECT COUNT(*) FROM document_registry;"
   ```

5. **Investigate Previous Environment**
   ```bash
   # Preserve logs for analysis
   docker-compose logs blue > /backup/blue_logs_$(date +%Y%m%d_%H%M%S).txt
   
   # Collect metrics
   curl http://blue-api:3000/metrics > /backup/blue_metrics_$(date +%Y%m%d_%H%M%S).txt
   ```

### Strategy 2: Container Image Rollback

**Prerequisites**:
- Docker registry with tagged images
- Ability to restart containers

**Procedure**:

1. **Stop Current Services**
   ```bash
   docker-compose down --remove-orphans
   ```

2. **Identify Previous Stable Version**
   ```bash
   # Check available versions
   docker images | grep rag
   
   # Or from registry
   aws ecr describe-images --repository-name rag-dashboard-api \
     --query 'sort_by(imageDetails,&imagePushedAt)[*].[imageTags[0],imagePushedAt]' \
     --output table
   ```

3. **Update docker-compose.yml**
   ```yaml
   # Change image tags to previous stable version
   services:
     api:
       image: 123456789.dkr.ecr.us-east-1.amazonaws.com/rag-dashboard-api:v1.2.0
       # was: v1.3.0-buggy
   ```

4. **Pull and Start Previous Version**
   ```bash
   docker-compose pull
   docker-compose up -d
   
   # Wait for services to start
   sleep 30
   
   # Verify
   docker-compose ps
   curl http://localhost:8000/health
   ```

5. **Verify Application State**
   ```bash
   # Check version
   curl http://localhost:8000/version
   
   # Run smoke tests
   ./tests/deployment/smoke_tests.sh
   ```

### Strategy 3: Database Rollback

**When to use**: Data schema or content was corrupted by new version

**Prerequisites**:
- Recent backup available
- Point-in-time recovery enabled
- Application can handle schema downgrade

**Procedure**:

1. **Stop Application**
   ```bash
   docker-compose stop web api worker
   ```

2. **Identify Recovery Point**
   ```bash
   # Find backup from just before deployment
   ls -lt /backup/rag_db_*.dump | head -5
   
   # Or from S3
   aws s3 ls s3://rag-dashboard-backups/ | sort -r | head -10
   ```

3. **Restore Database from Backup**
   ```bash
   # Create new database
   psql -U postgres -c "DROP DATABASE IF EXISTS rag_db_old;"
   psql -U postgres -c "CREATE DATABASE rag_db_old;"
   
   # Restore backup
   pg_restore -U rag_user -d rag_db_old --format=custom \
     /backup/rag_db_pre_deployment.dump
   
   # Verify restore
   psql -U rag_user -d rag_db_old -c "SELECT COUNT(*) FROM document_registry;"
   ```

4. **Switch to Restored Database**
   ```bash
   # Backup current database
   pg_dump -U rag_user -d rag_db --format=custom \
     -f /backup/rag_db_failed_$(date +%Y%m%d_%H%M%S).dump
   
   # Rename databases
   psql -U postgres -c "ALTER DATABASE rag_db RENAME TO rag_db_failed;"
   psql -U postgres -c "ALTER DATABASE rag_db_old RENAME TO rag_db;"
   ```

5. **Restart Application**
   ```bash
   docker-compose up -d
   sleep 30
   docker-compose ps
   ```

## Rollback Execution Phases

### Phase 1: Preparation (0-5 minutes)

**Tasks**:
- [ ] Confirm rollback necessity with engineering lead
- [ ] Identify target version
- [ ] Notify on-call team
- [ ] Start war room (Slack #incidents)
- [ ] Begin communication to users

**Preparation Commands**:
```bash
# Set rollback version
export ROLLBACK_VERSION="v1.2.0"
export ROLLBACK_TIME=$(date +%Y%m%d_%H%M%S)

# Backup current state
mkdir -p /backup/rollback_${ROLLBACK_TIME}
docker-compose logs > /backup/rollback_${ROLLBACK_TIME}/logs.txt
docker ps -a > /backup/rollback_${ROLLBACK_TIME}/containers.txt
git log --oneline -30 > /backup/rollback_${ROLLBACK_TIME}/git_log.txt
```

### Phase 2: Execution (5-15 minutes)

**Follow appropriate strategy** (Blue-Green, Image, or Database):

1. **Stop Current Services**
2. **Restore Previous Version**
3. **Verify Services Starting**
4. **Run Health Checks**

**Monitoring During Rollback**:
```bash
# Watch status in separate terminal
watch -n 2 'docker-compose ps'

# Monitor error rates
watch -n 5 'curl http://localhost:8000/metrics | grep error_rate'

# Check logs for issues
docker-compose logs --tail=50 -f
```

### Phase 3: Validation (15-30 minutes)

**Automated Validation**:
```bash
# Run smoke tests
./tests/deployment/smoke_tests.sh

# Run integration tests
pytest tests/deployment/test_production_deployment.py -v

# Check data integrity
psql -U rag_user -d rag_db -c "SELECT COUNT(*) FROM document_registry;"
```

**Manual Validation**:
- [ ] Access application UI
- [ ] Test core functionality
- [ ] Verify user data is accessible
- [ ] Check for any error messages
- [ ] Monitor application logs

**Health Check Commands**:
```bash
# API Health
curl http://localhost:8000/health
curl http://localhost:8002/health
curl http://localhost:3000/health

# Database
psql -U rag_user -d rag_db -c "SELECT 1;"

# Vector DB
curl http://localhost:6333/health

# Cache
redis-cli ping
```

### Phase 4: Communication (Ongoing)

**Immediate Notification** (first 5 min):
- Rollback initiated
- Estimated time to recovery

**Status Updates** (every 5 min):
- Current phase
- Any blockers
- Updated ETA

**Resolution Notification**:
- Rollback complete
- System status
- Post-incident review schedule

## Rollback Verification Checklist

### Service Health

- [ ] All containers running (`docker-compose ps`)
- [ ] No restarts in past 5 minutes
- [ ] CPU usage normal (< 70%)
- [ ] Memory usage normal (< 80%)
- [ ] Disk usage acceptable (< 85%)

### API Health

- [ ] `/health` endpoints return 200
- [ ] No error spike in logs
- [ ] Request latency < 500ms p99
- [ ] Error rate < 1%

### Data Health

- [ ] Database connected
- [ ] Can query document_registry
- [ ] Can query chunks table
- [ ] Replication lag < 1 second (if applicable)

### Functional Tests

- [ ] Can search documents
- [ ] Can ingest documents
- [ ] Can retrieve embeddings
- [ ] User authentication works
- [ ] API key validation works

## Rollback Abort Conditions

**Abort rollback if**:
- [ ] Rollback procedure not working as expected
- [ ] Database restore fails
- [ ] Services won't start after rollback
- [ ] Data corruption detected post-rollback
- [ ] Security issue still present

**If abort needed**:
1. Immediately stop rollback procedure
2. Restore original services
3. Escalate to CTO
4. Consider disaster recovery procedures

## Post-Rollback Actions

### Immediate (< 1 hour)

- [ ] Declare incident resolved
- [ ] Update incident ticket with timeline
- [ ] Preserve all logs and metrics for investigation
- [ ] Notify stakeholders of resolution

### Short-term (< 24 hours)

- [ ] Conduct root cause analysis
- [ ] Create bug report for issue that triggered rollback
- [ ] Schedule post-mortem meeting
- [ ] Update runbooks based on lessons learned

### Long-term (< 1 week)

- [ ] Implement fix for root cause
- [ ] Add automated test to catch regression
- [ ] Improve deployment process to catch issues earlier
- [ ] Update monitoring/alerting rules
- [ ] Document lessons learned

## Rollback Contacts

| Role | Name | On-Call | Contact |
|------|------|---------|---------|
| Incident Commander | [Rotates] | Yes | [Slack] |
| Engineering Lead | [Name] | Yes | [Phone] |
| Database Admin | [Name] | On-demand | [Email] |
| DevOps Lead | [Name] | Yes | [Phone] |

## Rollback Version Tracking

| Version | Release Date | Stability | Rollback Tested |
|---------|-------------|-----------|-----------------|
| v1.4.0 | 2026-05-01 | 🟢 Stable | ✅ |
| v1.3.0 | 2026-04-24 | 🟠 Caution | ✅ |
| v1.2.0 | 2026-04-17 | 🟢 Stable | ✅ |

## Related Documents

- [Deployment Procedures](../scripts/)
- [Incident Response Plan](incident-response.md)
- [Recovery Procedures](recovery-procedures.md)
- [Database Backup Strategy](backup-strategy.md)

---
**Last Updated**: 2026-05-05
**Next Review**: 2026-06-05
