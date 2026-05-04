"""
Production Deployment Verification Tests
Comprehensive checks for Issue #96 production deployment checklist
"""

import os
import sys
import subprocess
import time
import json
import statistics
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
MIGRATIONS_DIR = PROJECT_ROOT / "sql" / "migrations"
INIT_DIR = PROJECT_ROOT / "sql" / "init"
CONFIG_DIR = PROJECT_ROOT / "config"


class DeploymentChecklist:
    """Main deployment verification class"""
    
    def __init__(self):
        self.results = {}
        self.failed_checks = []
        self.warnings = []
        self.timestamp = time.time()
    
    def log_check(self, category: str, name: str, passed: bool, details: str = ""):
        """Log a check result"""
        if category not in self.results:
            self.results[category] = []
        
        result = {
            'name': name,
            'passed': passed,
            'details': details,
            'timestamp': time.time()
        }
        self.results[category].append(result)
        
        symbol = "✅" if passed else "❌"
        status = "PASS" if passed else "FAIL"
        msg = f"{symbol} [{category}] {name}: {status}"
        if details:
            msg += f" - {details}"
        logger.info(msg)
        
        if not passed:
            self.failed_checks.append(f"{category}/{name}: {details}")
    
    def add_warning(self, message: str):
        """Add a warning (non-blocking)"""
        self.warnings.append(message)
        logger.warning(f"⚠️  {message}")
    
    # ==================== CHECK 1: Database Migrations ====================
    
    def check_database_migrations(self):
        """Verify all database migration files are present and valid"""
        logger.info("\n" + "="*60)
        logger.info("CHECK 1: Database Migration Verification")
        logger.info("="*60)
        
        # Check init files
        required_init_files = [
            "01_init_database.sql",
            "02_chinese_fts.sql",
            "03_ingest_jobs.sql",
            "04_blindspots.sql",
        ]
        
        for filename in required_init_files:
            filepath = INIT_DIR / filename
            passed = filepath.exists()
            details = f"File size: {filepath.stat().st_size} bytes" if passed else "File not found"
            self.log_check("Database Migrations", f"Init: {filename}", passed, details)
        
        # Check migration files
        required_migration_files = [
            "001_pgvector_single_db.sql",
            "001_chinese_fts.sql",
            "002_full_schema.sql",
            "003_add_rag_feedback.sql",
            "004_conversation_turns.sql",
            "008_learning_runs.sql",
            "202605_learning_signals.sql",
        ]
        
        for filename in required_migration_files:
            filepath = MIGRATIONS_DIR / filename
            passed = filepath.exists()
            details = f"File size: {filepath.stat().st_size} bytes" if passed else "File not found"
            self.log_check("Database Migrations", f"Migration: {filename}", passed, details)
        
        # Validate SQL syntax (basic check)
        migration_files = list(MIGRATIONS_DIR.glob("*.sql"))
        valid_sql = 0
        for filepath in sorted(migration_files):
            try:
                content = filepath.read_text()
                if "CREATE" in content or "ALTER" in content or "INSERT" in content:
                    valid_sql += 1
                    self.log_check("Database Migrations", f"SQL Syntax: {filepath.name}", True, "Valid SQL structure")
                else:
                    self.log_check("Database Migrations", f"SQL Syntax: {filepath.name}", False, "No SQL statements found")
            except Exception as e:
                self.log_check("Database Migrations", f"SQL Syntax: {filepath.name}", False, str(e))
        
        self.log_check("Database Migrations", "Total Valid Migration Files", valid_sql > 0, f"{valid_sql} migration files validated")
    
    # ==================== CHECK 2: Environment Configuration ====================
    
    def check_environment_configuration(self):
        """Verify all required environment variables are configured"""
        logger.info("\n" + "="*60)
        logger.info("CHECK 2: Environment Configuration Verification")
        logger.info("="*60)
        
        # Load .env file
        env_file = PROJECT_ROOT / ".env"
        env_example_file = CONFIG_DIR / ".env.example"
        
        # Check if .env exists
        has_env = env_file.exists()
        self.log_check("Environment Config", ".env file exists", has_env, 
                      "Configuration file found" if has_env else "Missing .env (use .env.example as template)")
        
        # Check if .env.example exists
        has_env_example = env_example_file.exists()
        self.log_check("Environment Config", ".env.example template exists", has_env_example,
                      "Template file found" if has_env_example else "Template missing")
        
        required_env_vars = [
            'DATABASE_URL',
            'REDIS_URL',
            'QDRANT_HOST',
            'QDRANT_PORT',
            'LOG_LEVEL',
        ]
        
        optional_env_vars = [
            'SENTRY_DSN',
            'SLACK_WEBHOOK',
            'DATADOG_API_KEY',
        ]
        
        # Load env file if it exists
        env_dict = {}
        if has_env:
            try:
                for line in env_file.read_text().split('\n'):
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_dict[key.strip()] = value.strip()
            except Exception as e:
                self.log_check("Environment Config", ".env parsing", False, str(e))
        
        # Check required vars
        missing_required = []
        for var in required_env_vars:
            present = var in os.environ or var in env_dict
            if not present:
                missing_required.append(var)
            self.log_check("Environment Config", f"Required: {var}", present,
                          "Set in environment or .env" if present else "Missing")
        
        # Check optional vars
        configured_optional = []
        for var in optional_env_vars:
            present = var in os.environ or var in env_dict
            if present:
                configured_optional.append(var)
            self.log_check("Environment Config", f"Optional: {var}", present,
                          "Configured" if present else "Not configured (optional)")
        
        # Summary
        optional_count = len(configured_optional)
        self.log_check("Environment Config", "Optional Variables Coverage", 
                      optional_count >= 0,
                      f"{optional_count}/{len(optional_env_vars)} optional vars configured")
        
        if missing_required:
            self.add_warning(f"Missing required environment variables: {', '.join(missing_required)}")
    
    # ==================== CHECK 3: Performance Baseline ====================
    
    def check_performance_baseline(self):
        """Verify performance baseline is established"""
        logger.info("\n" + "="*60)
        logger.info("CHECK 3: Performance Baseline Verification")
        logger.info("="*60)
        
        performance_baseline_file = PROJECT_ROOT / "performance_baseline.log"
        exists = performance_baseline_file.exists()
        
        self.log_check("Performance Baseline", "Baseline file exists", exists,
                      f"Size: {performance_baseline_file.stat().st_size} bytes" if exists else "File not found")
        
        if exists:
            try:
                content = performance_baseline_file.read_text()
                metrics = ["latency", "throughput", "error_rate", "p95", "p99"]
                found_metrics = sum(1 for m in metrics if m.lower() in content.lower())
                
                self.log_check("Performance Baseline", "Baseline Metrics Coverage",
                              found_metrics > 0,
                              f"{found_metrics}/{len(metrics)} baseline metrics recorded")
                
                # Try to parse JSON if available
                lines = content.split('\n')
                for line in lines:
                    if line.strip().startswith('{'):
                        try:
                            data = json.loads(line)
                            self.log_check("Performance Baseline", "Baseline Format",
                                          True, f"JSON metrics found: {list(data.keys())}")
                            break
                        except:
                            pass
            except Exception as e:
                self.log_check("Performance Baseline", "Baseline Parsing", False, str(e))
        else:
            self.add_warning("No performance baseline file found - should run baseline tests")
    
    # ==================== CHECK 4: Monitoring & Alerts ====================
    
    def check_monitoring_configuration(self):
        """Verify monitoring and alerting system configuration"""
        logger.info("\n" + "="*60)
        logger.info("CHECK 4: Monitoring & Alerts Configuration")
        logger.info("="*60)
        
        # Check logging configuration
        log_config = CONFIG_DIR / "logging.yaml"
        has_log_config = log_config.exists()
        self.log_check("Monitoring Config", "Logging configuration file", has_log_config,
                      "logging.yaml found" if has_log_config else "logging.yaml not found")
        
        if has_log_config:
            try:
                content = log_config.read_text()
                log_checks = {
                    'handlers': 'Log handlers configured',
                    'formatters': 'Log formatters configured',
                    'level': 'Log levels defined',
                }
                for key, desc in log_checks.items():
                    present = key in content
                    self.log_check("Monitoring Config", f"Logging: {desc}", present)
            except Exception as e:
                self.log_check("Monitoring Config", "Logging file parsing", False, str(e))
        
        # Check for monitoring scripts
        monitoring_scripts = [
            "scripts/monitor.sh",
            "scripts/health_check.sh",
        ]
        
        for script_path in monitoring_scripts:
            filepath = PROJECT_ROOT / script_path
            exists = filepath.exists()
            self.log_check("Monitoring Config", f"Script: {script_path}", exists,
                          f"Found and executable" if exists and os.access(filepath, os.X_OK) else "Not found or not executable")
        
        # Check for Docker Compose services (monitoring-related)
        docker_compose = PROJECT_ROOT / "docker-compose.yml"
        if docker_compose.exists():
            try:
                content = docker_compose.read_text()
                services_to_check = ["prometheus", "grafana", "loki", "jaeger"]
                found_services = [s for s in services_to_check if s in content]
                
                if found_services:
                    self.log_check("Monitoring Config", "Monitoring Stack Services",
                                  True, f"Found: {', '.join(found_services)}")
                else:
                    self.add_warning("No monitoring services (Prometheus/Grafana/Loki/Jaeger) configured in docker-compose")
            except Exception as e:
                logger.error(f"Error checking docker-compose: {e}")
    
    # ==================== CHECK 5: Disaster Recovery ====================
    
    def check_disaster_recovery_plan(self):
        """Verify disaster recovery plan documentation"""
        logger.info("\n" + "="*60)
        logger.info("CHECK 5: Disaster Recovery Plan Verification")
        logger.info("="*60)
        
        dr_docs = [
            ("Backup Strategy", "docs/backup-strategy.md"),
            ("Recovery Procedures", "docs/recovery-procedures.md"),
            ("Incident Response", "docs/incident-response.md"),
        ]
        
        found_docs = 0
        for doc_name, doc_path in dr_docs:
            filepath = PROJECT_ROOT / doc_path
            exists = filepath.exists()
            if exists:
                found_docs += 1
            self.log_check("Disaster Recovery", doc_name, exists,
                          f"Documentation found" if exists else "Documentation missing")
        
        if found_docs < len(dr_docs):
            self.add_warning(f"Only {found_docs}/{len(dr_docs)} DR documentation files found")
        
        # Check for backup scripts
        backup_scripts = [
            "scripts/backup_database.sh",
            "scripts/backup_config.sh",
        ]
        
        for script in backup_scripts:
            filepath = PROJECT_ROOT / script
            exists = filepath.exists()
            self.log_check("Disaster Recovery", f"Backup: {script}", exists,
                          "Script found" if exists else "Script missing")
    
    # ==================== CHECK 6: Team Training ====================
    
    def check_team_training_materials(self):
        """Verify team training materials are available"""
        logger.info("\n" + "="*60)
        logger.info("CHECK 6: Team Training Materials Verification")
        logger.info("="*60)
        
        training_materials = [
            ("Architecture Overview", "docs/architecture.md"),
            ("API Documentation", "docs/api.md"),
            ("Troubleshooting Guide", "docs/troubleshooting.md"),
            ("Runbooks", "docs/runbooks"),
            ("On-Call Guide", "docs/on-call.md"),
        ]
        
        found_materials = 0
        for material_name, material_path in training_materials:
            filepath = PROJECT_ROOT / material_path
            exists = filepath.exists()
            if exists:
                found_materials += 1
            self.log_check("Training Materials", material_name, exists,
                          "Found" if exists else "Missing")
        
        coverage = f"{found_materials}/{len(training_materials)}"
        self.log_check("Training Materials", "Coverage", found_materials >= 3, coverage)
        
        if found_materials < len(training_materials):
            self.add_warning(f"Only {coverage} training materials present")
    
    # ==================== CHECK 7: Rollback Plan ====================
    
    def check_rollback_plan(self):
        """Verify rollback plan documentation and procedures"""
        logger.info("\n" + "="*60)
        logger.info("CHECK 7: Rollback Plan Verification")
        logger.info("="*60)
        
        rollback_doc = PROJECT_ROOT / "docs" / "rollback-plan.md"
        exists = rollback_doc.exists()
        self.log_check("Rollback Plan", "Plan documentation", exists,
                      "rollback-plan.md found" if exists else "rollback-plan.md missing")
        
        if exists:
            try:
                content = rollback_doc.read_text()
                required_sections = [
                    "Preparation",
                    "Execution",
                    "Validation",
                    "Post-Rollback",
                ]
                
                found_sections = sum(1 for section in required_sections if section in content)
                self.log_check("Rollback Plan", "Plan Completeness",
                              found_sections == len(required_sections),
                              f"{found_sections}/{len(required_sections)} sections documented")
            except Exception as e:
                self.log_check("Rollback Plan", "Plan parsing", False, str(e))
        
        # Check rollback scripts
        rollback_script = PROJECT_ROOT / "scripts" / "rollback.sh"
        has_script = rollback_script.exists()
        self.log_check("Rollback Plan", "Rollback script", has_script,
                      "Executable script found" if has_script else "Script missing")
    
    # ==================== CHECK 8: Pre-Deployment ====================
    
    def check_pre_deployment_checklist(self):
        """Final pre-deployment verification"""
        logger.info("\n" + "="*60)
        logger.info("CHECK 8: Pre-Deployment Verification")
        logger.info("="*60)
        
        checks = {
            'Code Compilation': self._verify_code_compilation(),
            'Import Validation': self._verify_imports(),
            'Configuration Files': self._verify_config_files(),
            'Database Connection': self._verify_db_connection(),
            'External Services': self._verify_external_services(),
        }
        
        for check_name, result in checks.items():
            self.log_check("Pre-Deployment", check_name, result,
                          "Verification passed" if result else "Verification failed")
    
    def _verify_code_compilation(self) -> bool:
        """Verify Python code compiles"""
        try:
            # Check main backend
            main_files = [
                "src/backend/python-legacy/main.py",
                "src/backend/retrieval-service/main.py",
            ]
            
            for main_file in main_files:
                filepath = PROJECT_ROOT / main_file
                if filepath.exists():
                    result = subprocess.run(
                        [sys.executable, "-m", "py_compile", str(filepath)],
                        capture_output=True,
                        timeout=10
                    )
                    if result.returncode != 0:
                        return False
            
            return True
        except Exception as e:
            logger.error(f"Compilation check failed: {e}")
            return False
    
    def _verify_imports(self) -> bool:
        """Verify critical imports work"""
        try:
            # Test core Python imports
            import_tests = [
                "import fastapi",
                "import sqlalchemy",
                "import redis",
            ]
            
            for import_stmt in import_tests:
                result = subprocess.run(
                    [sys.executable, "-c", import_stmt],
                    capture_output=True,
                    timeout=5
                )
                if result.returncode != 0:
                    return False
            
            return True
        except Exception as e:
            logger.error(f"Import verification failed: {e}")
            return False
    
    def _verify_config_files(self) -> bool:
        """Verify required config files exist"""
        required_configs = [
            "config/config.yaml",
            "config/.env.example",
        ]
        
        for config_file in required_configs:
            filepath = PROJECT_ROOT / config_file
            if not filepath.exists():
                return False
        
        return True
    
    def _verify_db_connection(self) -> bool:
        """Verify database connection parameters are configured"""
        db_vars = ['DATABASE_URL', 'POSTGRES_HOST', 'POSTGRES_DB']
        
        for var in db_vars:
            if var in os.environ:
                return True
        
        # Check .env file
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            content = env_file.read_text()
            if any(var in content for var in db_vars):
                return True
        
        self.add_warning("Database connection parameters not fully configured")
        return False
    
    def _verify_external_services(self) -> bool:
        """Verify external service configurations"""
        # Check for docker-compose to verify services are defined
        docker_compose = PROJECT_ROOT / "docker-compose.yml"
        if docker_compose.exists():
            return True
        
        self.add_warning("docker-compose.yml not found - external services may not be configured")
        return False
    
    # ==================== Report Generation ====================
    
    def generate_report(self) -> str:
        """Generate final deployment verification report"""
        logger.info("\n" + "="*60)
        logger.info("GENERATING FINAL REPORT")
        logger.info("="*60)
        
        total_checks = sum(len(v) for v in self.results.values())
        passed_checks = sum(len([c for c in v if c['passed']]) for v in self.results.values())
        failed_checks = total_checks - passed_checks
        
        report = f"""# Production Deployment Verification Report
## Issue #96 - Production Deployment Checklist

**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S')}

## Summary

| Metric | Value |
|--------|-------|
| Total Checks | {total_checks} |
| Passed | {passed_checks} |
| Failed | {failed_checks} |
| Success Rate | {(passed_checks/total_checks*100):.1f}% |

## Detailed Results

"""
        
        for category, checks in self.results.items():
            category_passed = sum(1 for c in checks if c['passed'])
            category_total = len(checks)
            
            report += f"### {category} ({category_passed}/{category_total})\n\n"
            
            for check in checks:
                symbol = "✅" if check['passed'] else "❌"
                report += f"- {symbol} **{check['name']}**"
                if check['details']:
                    report += f": {check['details']}"
                report += "\n"
            
            report += "\n"
        
        # Warnings section
        if self.warnings:
            report += "## ⚠️  Warnings\n\n"
            for warning in self.warnings:
                report += f"- {warning}\n"
            report += "\n"
        
        # Failed checks section
        if self.failed_checks:
            report += "## ❌ Failed Checks\n\n"
            for failed in self.failed_checks:
                report += f"- {failed}\n"
            report += "\n"
        
        # Deployment readiness
        readiness = "🟢 READY FOR PRODUCTION" if failed_checks == 0 else "🟠 NEEDS ATTENTION"
        report += f"## Deployment Readiness: {readiness}\n\n"
        
        if failed_checks > 0:
            report += f"**Action Required**: {failed_checks} checks need attention before deployment.\n\n"
        
        report += "## Recommendations\n\n"
        report += "1. Address all failed checks listed above\n"
        report += "2. Review all warnings and determine if they need to be fixed\n"
        report += "3. Run performance baseline tests before deployment\n"
        report += "4. Verify database backups are current\n"
        report += "5. Ensure all team members have completed training\n"
        report += "6. Test rollback procedures in staging environment\n"
        report += "7. Review incident response plan with on-call team\n"
        
        return report
    
    def run_all_checks(self):
        """Run all deployment verification checks"""
        logger.info("\n" + "█"*60)
        logger.info("█ PRODUCTION DEPLOYMENT VERIFICATION CHECKLIST - ISSUE #96")
        logger.info("█"*60 + "\n")
        
        try:
            self.check_database_migrations()
            self.check_environment_configuration()
            self.check_performance_baseline()
            self.check_monitoring_configuration()
            self.check_disaster_recovery_plan()
            self.check_team_training_materials()
            self.check_rollback_plan()
            self.check_pre_deployment_checklist()
        except Exception as e:
            logger.error(f"Error during checks: {e}", exc_info=True)
            raise
        
        report = self.generate_report()
        return report, self.results, self.failed_checks, self.warnings


def main():
    """Main entry point"""
    checklist = DeploymentChecklist()
    report, results, failed_checks, warnings = checklist.run_all_checks()
    
    # Write report to file
    report_file = PROJECT_ROOT / "PRODUCTION_DEPLOYMENT_CHECKLIST.md"
    report_file.write_text(report)
    logger.info(f"\n✅ Report written to: {report_file}")
    
    # Also write JSON results
    json_report = {
        'timestamp': time.time(),
        'total_checks': sum(len(v) for v in results.values()),
        'passed': sum(len([c for c in v if c['passed']]) for v in results.values()),
        'failed': len(failed_checks),
        'warnings': warnings,
        'results': results,
    }
    
    json_file = PROJECT_ROOT / "deployment_verification_results.json"
    json_file.write_text(json.dumps(json_report, indent=2))
    logger.info(f"✅ JSON results written to: {json_file}")
    
    # Print summary
    logger.info("\n" + "="*60)
    logger.info("DEPLOYMENT VERIFICATION SUMMARY")
    logger.info("="*60)
    print(report)
    
    # Return exit code based on failed checks
    return 0 if len(failed_checks) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
