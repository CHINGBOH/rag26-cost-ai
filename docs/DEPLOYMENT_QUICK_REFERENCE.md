# Production Deployment Quick Reference - Issue #96

## 🚀 Quick Start (5 minutes)

### Verify Readiness
```bash
cd /home/l/rag-dashboard
python tests/deployment/test_production_deployment.py
```

### Check System Health
```bash
./scripts/health_check.sh
```

### Create Database Backup
```bash
./scripts/backup_database.sh
```

---

## ⚙️ Pre-Deployment Configuration

### 1. Environment Variables
```bash
# Copy template
cp config/.env.example .env

# Edit with production values
export DATABASE_URL="postgresql://user:pass@host:5432/rag_db"
export REDIS_URL="redis://host:6379/0"
export LOG_LEVEL="INFO"
```

### 2. Database Initialization
```bash
psql -U rag_user -d rag_db -h localhost < sql/init/01_init_database.sql
psql -U rag_user -d rag_db -h localhost < sql/migrations/002_full_schema.sql
psql -U rag_user -d rag_db -h localhost < sql/migrations/004_conversation_turns.sql
psql -U rag_user -d rag_db -h localhost < sql/migrations/202605_learning_signals.sql
```

---

## 🎯 Deployment Steps

### Step 1: Pre-Flight Check
```bash
# Verify all systems
python tests/deployment/test_production_deployment.py

# Expected: 70%+ success rate
# Review: PRODUCTION_DEPLOYMENT_CHECKLIST.md
```

### Step 2: Start Services
```bash
./start-all.sh production
sleep 30
docker-compose ps
```

### Step 3: Health Verification
```bash
# Check all endpoints
curl http://localhost:8000/health
curl http://localhost:8002/health
curl http://localhost:3000/health

# Run diagnostics
./scripts/health_check.sh
```

### Step 4: Enable Backups
```bash
# Run initial backup
./scripts/backup_database.sh

# Schedule daily (add to crontab)
0 2 * * * /home/l/rag-dashboard/scripts/backup_database.sh >> /var/log/rag_backup.log 2>&1
```

---

## 🔄 Rollback Procedure (Emergency)

### If Issues Detected
```bash
# STOP: Don't panic
# 1. Identify the issue
./scripts/health_check.sh

# 2. Check logs
docker-compose logs --tail=100

# 3. If critical: Rollback
./scripts/rollback.sh v1.2.0

# 4. Verify
./scripts/health_check.sh
```

---

## �� Files Reference

### Generated Reports
| File | Purpose |
|------|---------|
| `PRODUCTION_DEPLOYMENT_CHECKLIST.md` | Main verification report |
| `deployment_verification_results.json` | Machine-readable results |
| `ISSUE_96_DEPLOYMENT_SUMMARY.md` | Executive summary |

### Documentation
| File | Purpose |
|------|---------|
| `docs/backup-strategy.md` | Backup procedures |
| `docs/recovery-procedures.md` | Disaster recovery |
| `docs/incident-response.md` | Incident handling |
| `docs/rollback-plan.md` | Rollback procedures |

### Scripts
| Script | Purpose |
|--------|---------|
| `scripts/health_check.sh` | System health check |
| `scripts/backup_database.sh` | Database backup |
| `scripts/rollback.sh` | Safe rollback |
| `start-all.sh` | Start all services |
| `stop-all.sh` | Stop all services |

---

## ✅ Verification Checklist

### Pre-Deployment
- [ ] Run deployment verification script
- [ ] All migration files present
- [ ] Environment variables configured
- [ ] Database connectivity verified
- [ ] Code compiles successfully

### During Deployment
- [ ] Services starting correctly
- [ ] API endpoints responding
- [ ] Database accessible
- [ ] No error spike in logs
- [ ] Memory/CPU usage normal

### Post-Deployment
- [ ] All services stable
- [ ] Error rate < 1%
- [ ] Latency within baseline
- [ ] Data integrity verified
- [ ] Initial backup created

---

## 🚨 Troubleshooting

### Service Won't Start
```bash
# Check logs
docker-compose logs

# View error details
docker-compose logs --tail=50 | grep ERROR

# Restart service
docker-compose restart [service_name]
```

### Database Connection Error
```bash
# Test connection
psql -U rag_user -d rag_db -h localhost -c "SELECT 1;"

# Check environment variables
echo $DATABASE_URL

# Verify credentials
cat .env | grep DATABASE_URL
```

### API Returning 500 Errors
```bash
# Check application logs
docker-compose logs -f web

# Check database for issues
psql -U rag_user -d rag_db -h localhost -c "SELECT COUNT(*) FROM document_registry;"

# Check cache
redis-cli ping
```

### Performance Degradation
```bash
# Check resource usage
docker stats

# Check database connections
psql -U rag_user -d rag_db -h localhost -c "SELECT COUNT(*) FROM pg_stat_activity;"

# Check query performance
psql -U rag_user -d rag_db -h localhost -c "SELECT * FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10;"
```

---

## 📞 Emergency Contacts

| Role | Status |
|------|--------|
| On-Call | [See Schedule] |
| Engineering Manager | [Contact] |
| DevOps Lead | [Contact] |

---

## 📋 Key Metrics

### Target Performance
| Metric | Target | Current |
|--------|--------|---------|
| API Latency (p99) | < 500ms | [Test] |
| Error Rate | < 1% | [Monitor] |
| Uptime | > 99.9% | [Monitor] |
| CPU Usage | < 70% | [Monitor] |
| Memory Usage | < 80% | [Monitor] |
| Disk Usage | < 85% | [Monitor] |

### Backup Metrics
| Type | Frequency | Retention |
|------|-----------|-----------|
| Database | Daily | 30 days |
| Vector DB | Daily | 14 days |
| Config | Daily | 30 days |

---

## 🔐 Security Checklist

- [ ] .env file permissions: 600
- [ ] Database passwords secured in .env
- [ ] API keys not in logs
- [ ] SSL certificates valid
- [ ] Firewalls configured
- [ ] Network policies enforced

---

## 📈 Success Criteria

✅ **Deployment Success When**:
- All 54 checks showing >= 70% pass rate
- All critical services responding
- Error rate < 1% after 1 hour
- Database queries completing normally
- Backup script executing successfully

---

**Document Version**: 1.0  
**Last Updated**: 2026-05-05  
**Next Review**: Post-deployment  
