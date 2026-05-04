# Incident Response Plan - RAG Dashboard Production

## Executive Summary

This document outlines the procedures for responding to production incidents in the RAG Dashboard system. The goal is to minimize downtime, prevent data loss, and maintain service quality.

## Incident Severity Levels

### Severity 1 - Critical
- Complete system outage
- Data loss in progress
- Security breach detected
- **Response Time**: Immediate (< 5 minutes)
- **Escalation**: VP Engineering, CTO

### Severity 2 - High
- Partial system outage (> 20% of users affected)
- Performance degradation (> 50% slower than baseline)
- Data corruption detected
- **Response Time**: < 15 minutes
- **Escalation**: Engineering Manager, DevOps Lead

### Severity 3 - Medium
- Service degradation (5-20% of users affected)
- Performance issues (10-50% slower than baseline)
- Non-critical feature broken
- **Response Time**: < 1 hour
- **Escalation**: On-Call Engineer

### Severity 4 - Low
- Minor issues, no user impact
- Informational warnings
- Documentation updates needed
- **Response Time**: < 24 hours
- **Escalation**: Development Team

## Incident Response Process

### Phase 1: Detection and Initial Response (0-5 min)

**Automated Monitoring**:
```yaml
Alerts Configured:
  - API response time > 1000ms
  - Error rate > 5%
  - Database connection pool exhausted
  - Vector DB unavailable
  - Memory usage > 80%
  - Disk usage > 85%
  - Network latency spike
```

**Manual Detection Triggers**:
- Customer reports via support
- Automated test failures
- Performance dashboard anomalies
- Log aggregation alerts

**Immediate Actions**:
1. [ ] Acknowledge alert in monitoring system
2. [ ] Create incident ticket
3. [ ] Notify on-call team
4. [ ] Begin war room communication (Slack channel: #incidents)
5. [ ] Assign incident commander

### Phase 2: Triage and Diagnosis (5-30 min)

**Diagnostic Checklist**:
```bash
# 1. Check service status
docker-compose ps
docker-compose logs --tail=100 -f

# 2. Check system resources
free -h                 # Memory
df -h                   # Disk space
top -b -n1              # CPU usage
docker stats            # Container stats

# 3. Check database connectivity
psql -U rag_user -d rag_db -c "SELECT 1;"
redis-cli ping
curl http://qdrant:6333/health
curl http://elasticsearch:9200/

# 4. Check recent deployments
git log --oneline -20
docker images | head -10

# 5. Check logs for errors
journalctl -u docker --since "30 minutes ago" | grep -i error
docker-compose logs --tail=500 | grep -i error
```

**Incident Classification**:
- [ ] Identify affected component(s)
- [ ] Determine root cause (if obvious)
- [ ] Estimate time to recovery (TTR)
- [ ] Determine if rollback needed

### Phase 3: Communication (Ongoing)

**Initial Communication** (Immediately):
- [ ] Update #incidents channel with status
- [ ] Notify engineering manager
- [ ] Estimate TTR to stakeholders
- [ ] Update status page

**Every 15 Minutes** (During incident):
- [ ] Post status update in #incidents
- [ ] Share diagnostic findings
- [ ] Update TTR estimate

**Resolution Communication**:
- [ ] Announce resolution
- [ ] Post-incident review scheduled
- [ ] Thank you to responders

### Phase 4: Mitigation and Resolution (During incident)

**Mitigation Steps** (in order of preference):

1. **Scaling**
   ```bash
   # Increase container resources
   docker-compose up -d --scale service=3
   ```

2. **Cache Invalidation**
   ```bash
   redis-cli FLUSHALL
   ```

3. **Rate Limiting**
   - Temporarily reduce rate limits for non-critical APIs
   - Redirect traffic to healthy instances

4. **Graceful Degradation**
   - Disable expensive features
   - Use fallback behaviors
   - Serve cached responses

5. **Restart Services** (if necessary)
   ```bash
   docker-compose restart web
   docker-compose restart api
   ```

6. **Database Failover** (if applicable)
   - Switch to read replica
   - Manual failover procedure

7. **Rollback** (last resort)
   - See [Rollback Plan](../ISSUE_96_FIX_REPORT.md)

### Phase 5: Investigation (Post-Incident)

**What to Preserve**:
- [ ] Container logs (save before cleanup)
- [ ] System metrics (CPU, memory, disk, network)
- [ ] Application logs and traces
- [ ] Database query logs
- [ ] Network packet captures (if applicable)

```bash
# Save logs for investigation
docker-compose logs > incident_logs_$(date +%Y%m%d_%H%M%S).txt
docker ps -a > containers_$(date +%Y%m%d_%H%M%S).txt
```

**Root Cause Analysis**:
- Why did the incident occur?
- Why wasn't it caught earlier?
- What are the contributing factors?
- What can be improved?

### Phase 6: Resolution Verification

**Health Checks**:
```bash
# Basic connectivity
curl http://localhost:8000/health
curl http://localhost:8002/health
curl http://localhost:3000/api/health

# Database
psql -U rag_user -d rag_db -c "SELECT COUNT(*) FROM document_registry;"

# API functionality
curl -X POST http://localhost:8002/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "test"}'
```

**Performance Verification**:
- [ ] Response times normal (< 500ms p99)
- [ ] Error rates < 1%
- [ ] Resource usage normal
- [ ] No alert triggers

**Data Integrity Verification**:
- [ ] No missing records
- [ ] No data corruption
- [ ] All services in sync
- [ ] Replication lag < 1 second

## Runbooks

### Database High Connection Usage

**Symptoms**: `psql: too many connections`

**Resolution**:
1. Identify idle connections:
   ```sql
   SELECT pid, usename, state, query FROM pg_stat_activity
   WHERE state = 'idle' AND query_start < now() - interval '10 minutes';
   ```

2. Terminate idle connections:
   ```sql
   SELECT pg_terminate_backend(pid) FROM pg_stat_activity
   WHERE state = 'idle' AND query_start < now() - interval '10 minutes';
   ```

3. Increase connection pool if needed:
   - Update `postgres.conf`: `max_connections = 300`
   - Restart PostgreSQL

### Vector DB Out of Memory

**Symptoms**: Qdrant returns 500 errors, memory limit exceeded

**Resolution**:
1. Check Qdrant metrics:
   ```bash
   curl http://qdrant:6333/metrics
   ```

2. Scale Qdrant:
   ```bash
   docker-compose up -d --scale qdrant=2
   ```

3. If persistent, clear old snapshots:
   ```bash
   curl -X DELETE http://qdrant:6333/collections/old_collection
   ```

### High Error Rate in API

**Symptoms**: > 5% error rate, user reports failures

**Resolution**:
1. Check recent logs:
   ```bash
   docker-compose logs --tail=1000 web | grep ERROR
   ```

2. Identify error pattern:
   - Is it specific endpoint?
   - Is it specific user?
   - Is it intermittent or constant?

3. Scale API service:
   ```bash
   docker-compose up -d --scale api=3
   ```

4. If error persists, consider rollback

### Database Replication Lag

**Symptoms**: Read-replica lag > 30 seconds

**Resolution**:
1. Check replication status:
   ```sql
   SELECT slot_name, restart_lsn, confirmed_flush_lsn FROM pg_replication_slots;
   ```

2. Monitor until caught up:
   ```bash
   watch -n 5 'psql -U replica_user -d rag_db -c "SELECT now() - pg_last_xact_replay_timestamp();"'
   ```

3. If not catching up, restart replica:
   ```bash
   docker-compose restart postgres-replica
   ```

## Escalation Path

```
┌─────────────────────────────┐
│ Automated Monitoring Alert  │
└──────────────┬──────────────┘
               │
        ┌──────▼──────┐
        │ On-Call Eng │
        │  (5 min)    │
        └──────┬──────┘
               │
        ┌──────▼──────────────────┐
        │ Diagnose & Mitigate     │
        │ (15 min)                │
        └──────┬──────────────────┘
               │
      ┌────────▼─────────┐
      │ Issue Resolved?  │
      └───┬──────────┬───┘
          │          │
         YES        NO
          │          │
         [END]  ┌────▼────────────────────┐
                │ Escalate to Manager    │
                │ + Engineering Lead     │
                │ (30 min)               │
                └────┬────────────────────┘
                     │
           ┌─────────▼─────────┐
           │ Issue Resolved?   │
           └───┬──────────┬────┘
               │          │
              YES        NO
               │          │
              [END]  ┌────▼──────────────┐
                     │ Escalate to CTO  │
                     │ (60 min)         │
                     └────┬─────────────┘
                          │
                          ▼
                      [Rollback]
```

## Post-Incident Review

**Timeline** (within 24 hours):
1. [ ] Collect all logs and metrics
2. [ ] Document incident timeline
3. [ ] Identify root cause
4. [ ] Schedule blameless postmortem

**Post-Mortem Meeting**:
1. [ ] Present incident timeline
2. [ ] Discuss root cause analysis
3. [ ] Identify action items
4. [ ] Assign owners for fixes
5. [ ] Schedule follow-up

**Action Items Template**:
- [ ] Issue: [Description]
- [ ] Owner: [Name]
- [ ] Due: [Date]
- [ ] Link: [Ticket]

## On-Call Procedures

**On-Call Rotation**: Weekly, Monday 9:00 AM UTC

**On-Call Responsibilities**:
- [ ] Monitor #incidents channel
- [ ] Respond to pages within 5 minutes
- [ ] Participate in incident response
- [ ] Document incident timeline

**Tools and Access**:
- [ ] VPN access to production
- [ ] AWS console access
- [ ] PagerDuty configuration
- [ ] Slack integration
- [ ] Status page admin access

## Contact Information

| Role | Name | Email | Phone |
|------|------|-------|-------|
| On-Call | [Rotates] | [See Schedule] | [See Schedule] |
| Engineering Manager | [Name] | [Email] | [Phone] |
| CTO | [Name] | [Email] | [Phone] |
| Vendor Support | [Vendor] | [Email] | [Phone] |

## Related Documents

- [Backup Strategy](backup-strategy.md)
- [Recovery Procedures](recovery-procedures.md)
- [Rollback Plan](../ISSUE_96_FIX_REPORT.md)
- [Monitoring Guide](../LAYER3_COMPLETION_CHECKLIST.md)

---
**Last Updated**: 2026-05-05
**Next Review**: 2026-06-05
