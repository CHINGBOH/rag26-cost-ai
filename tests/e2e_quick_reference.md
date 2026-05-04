# E2E Integration Tests Quick Start Guide

## Overview

Issue #96 E2E integration tests verify the complete workflow:

```
Signal Collection → Problem Identification → Strategy Generation → 
Execution Verification → Monitoring Dashboard
```

## File Structure

```
tests/
├── e2e/                          # E2E test suite directory
│   ├── conftest.py              # Test configuration & fixtures
│   ├── test_01_signal_flow.py   # Signal collection tests
│   ├── test_02_problem_detection.py  # Problem identification
│   ├── test_03_root_cause.py    # Root cause analysis
│   ├── test_04_strategy.py      # Strategy generation
│   ├── test_05_executor.py      # Execution & verification
│   ├── test_06_api_endpoints.py # API endpoint coverage
│   └── test_07_db_consistency.py # Database integrity
├── E2E_TEST_REPORT.md           # Comprehensive report (this file)
└── e2e_quick_reference.md       # Quick start guide (you are here)
```

## Prerequisites

```bash
# Install dependencies
pip install pytest pytest-asyncio httpx psycopg2-binary requests

# Ensure services are running
# - PostgreSQL on port 5432
# - Qdrant on port 6333
# - Redis on port 6379
# - Retrieval Service on port 8002

# Start retrieval service
cd src/backend/retrieval-service
python -m uvicorn main:app --host 0.0.0.0 --port 8002
```

## Running Tests

### Run All Tests
```bash
cd /home/l/rag-dashboard
pytest tests/e2e/ -v
```

### Run Specific Test Suite
```bash
# Signal collection tests
pytest tests/e2e/test_01_signal_flow.py -v

# Problem detection tests
pytest tests/e2e/test_02_problem_detection.py -v

# Database tests (usually most reliable)
pytest tests/e2e/test_07_db_consistency.py -v
```

### Run Specific Test
```bash
pytest tests/e2e/test_07_db_consistency.py::test_db_schema_integrity -v
```

### Run with Output Capture
```bash
pytest tests/e2e/ -v -s  # Show print statements
```

### Run with Coverage Report
```bash
pytest tests/e2e/ --cov=src/backend/retrieval-service/app/agent --cov-report=html
```

## Test Suites Summary

| Suite | File | Tests | Focus |
|-------|------|-------|-------|
| 1 | test_01_signal_flow.py | 4 | Signal collection & stats |
| 2 | test_02_problem_detection.py | 4 | Problem detection & DB |
| 3 | test_03_root_cause.py | 4 | Root cause analysis |
| 4 | test_04_strategy.py | 4 | Strategy generation |
| 5 | test_05_executor.py | 5 | Execution & verification |
| 6 | test_06_api_endpoints.py | 4 | All 13 API endpoints |
| 7 | test_07_db_consistency.py | 5 | Database integrity ✅ |

## Expected Results

### Reliable Tests (Database Tests)
✅ `test_db_schema_integrity` - Verifies schema exists
✅ `test_feedback_signals_integrity` - Checks feedback signals table
✅ `test_problem_via_db` - Direct database queries
✅ `test_execution_db_records` - Event tracking

### Tests Requiring Running Service
⚠️ Signal flow tests - Need active HTTP requests
⚠️ Problem detection API - Need retrieval service running
⚠️ Endpoint tests - Network connectivity required

## Troubleshooting

### Service Connection Errors
```
❌ HTTPConnectionPool: Max retries exceeded
```
**Solution:** Ensure retrieval service is running on port 8002
```bash
curl http://localhost:8002/health
```

### Database Connection Errors
```
❌ psycopg2: Connection refused
```
**Solution:** Ensure PostgreSQL is running
```bash
psql -U rag_user -d rag_db -h localhost -c "SELECT 1"
```

### Proxy-Related Errors
```
❌ Unknown scheme for proxy URL 'socks://'
```
**Solution:** Tests use `trust_env=False` to bypass proxies
- This is automatically configured in conftest.py

### Import Errors
```
❌ ModuleNotFoundError: No module named 'infrastructure'
```
**Solution:** conftest.py adds retrieval-service to sys.path automatically

## Test Data

Each test uses auto-generated test data:
```python
{
    "broken_query": "broken_query_abc123def",
    "test_problem_id": "test_problem_xyz789",
    "test_route": "R1_navigator_dict"
}
```

No persistent data is created - tests are isolated.

## Database Verification

To manually verify database state:

```bash
# Check improvement_events
psql -U rag_user -d rag_db -h localhost << 'SQL'
SELECT id, affected_route, actor, ts FROM improvement_events LIMIT 5;
SQL

# Check feedback signals
psql -U rag_user -d rag_db -h localhost << 'SQL'
SELECT signal_type, COUNT(*) FROM signal_* GROUP BY signal_type;
SQL

# Check schema
psql -U rag_user -d rag_db -h localhost << 'SQL'
SELECT table_name FROM information_schema.tables WHERE table_schema='public';
SQL
```

## Continuous Integration

### Add to GitHub Actions
```yaml
- name: Run E2E Tests
  run: |
    cd /home/l/rag-dashboard
    pytest tests/e2e/ -v --junit-xml=results.xml
    
- name: Publish Results
  if: always()
  uses: actions/upload-artifact@v2
  with:
    name: test-results
    path: results.xml
```

## Next Steps

1. ✅ Review test coverage in `/tests/e2e/`
2. ✅ Run database tests: `pytest tests/e2e/test_07_db_consistency.py`
3. ✅ Start retrieval service and run full suite
4. ✅ Integrate into CI/CD pipeline
5. ✅ Monitor test results over time

## Support

For issues or questions:
1. Check test logs: `pytest tests/e2e/ -v --tb=long`
2. Review test code in `tests/e2e/*.py`
3. Check full report: `tests/E2E_TEST_REPORT.md`

---

**Happy Testing! 🚀**

For detailed information, see: `/tests/E2E_TEST_REPORT.md`
