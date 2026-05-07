#!/usr/bin/env python3
"""
Configuration Audit Tool - Issue #122

Detects configuration conflicts across multiple config sources:
- config/config.yaml
- .env files
- Environment variables (RAG__*)
- config/settings.py (deprecated)

Usage:
    python scripts/audit_config.py
    python scripts/audit_config.py --check-only  # Exit 1 if conflicts found
"""

import os
import sys
import yaml
import warnings
from pathlib import Path
from typing import Any, Dict, List, Tuple
from collections import defaultdict

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import dotenv_values


class ConfigAuditor:
    """Audit configuration sources for conflicts"""
    
    def __init__(self):
        self.conflicts: List[Dict[str, Any]] = []
        self.sources: Dict[str, Dict[str, Any]] = {}
    
    def load_yaml_config(self) -> Dict[str, Any]:
        """Load config.yaml"""
        yaml_path = PROJECT_ROOT / "config" / "config.yaml"
        if not yaml_path.exists():
            return {}
        
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        
        return self._flatten_dict(data, prefix="")
    
    def load_env_file(self) -> Dict[str, Any]:
        """Load .env file"""
        env_path = PROJECT_ROOT / ".env"
        if not env_path.exists():
            return {}
        
        env_vars = dotenv_values(env_path)
        # Filter RAG__ prefixed vars
        return {k: v for k, v in env_vars.items() if k.startswith("RAG__")}
    
    def load_env_vars(self) -> Dict[str, Any]:
        """Load environment variables"""
        return {k: v for k, v in os.environ.items() if k.startswith("RAG__")}
    
    def _flatten_dict(self, d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
        """Flatten nested dict to dot-notation keys"""
        result = {}
        for key, value in d.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                result.update(self._flatten_dict(value, full_key))
            else:
                result[full_key] = value
        return result
    
    def _convert_env_key_to_dot(self, env_key: str) -> str:
        """Convert RAG__SECTION__KEY to section.key"""
        if not env_key.startswith("RAG__"):
            return env_key
        
        # Remove RAG__ prefix
        key = env_key[5:]
        # Convert __ to .
        key = key.replace("__", ".").lower()
        return key
    
    def audit(self) -> bool:
        """
        Run configuration audit.
        
        Returns:
            True if no conflicts found, False otherwise
        """
        print("🔍 RAG Dashboard Configuration Audit")
        print("=" * 60)
        
        # Load all sources
        yaml_config = self.load_yaml_config()
        env_file = self.load_env_file()
        env_vars = self.load_env_vars()
        
        self.sources = {
            "config.yaml": yaml_config,
            ".env": env_file,
            "env_vars": env_vars,
        }
        
        # Print source summary
        print(f"\n📋 Configuration Sources:")
        print(f"  - config.yaml: {len(yaml_config)} keys")
        print(f"  - .env file: {len(env_file)} keys")
        print(f"  - Environment variables: {len(env_vars)} keys")
        
        # Find conflicts
        all_keys = set()
        for source_data in self.sources.values():
            if source_data == yaml_config:
                all_keys.update(source_data.keys())
            else:
                # Convert env keys to dot notation
                all_keys.update(self._convert_env_key_to_dot(k) for k in source_data.keys())
        
        conflicts_found = False
        
        print(f"\n⚖️  Checking {len(all_keys)} unique configuration keys...")
        
        for key in sorted(all_keys):
            values_by_source = {}
            
            # Check YAML
            if key in yaml_config:
                values_by_source["config.yaml"] = yaml_config[key]
            
            # Check .env
            env_key = f"RAG__{key.upper().replace('.', '__')}"
            if env_key in env_file:
                values_by_source[".env"] = env_file[env_key]
            
            # Check env vars
            if env_key in env_vars:
                values_by_source["env_vars"] = env_vars[env_key]
            
            # Conflict if multiple different values
            unique_values = set(str(v) for v in values_by_source.values())
            if len(unique_values) > 1:
                conflicts_found = True
                self.conflicts.append({
                    "key": key,
                    "values": values_by_source
                })
        
        # Report conflicts
        if conflicts_found:
            print(f"\n❌ Configuration Conflicts Detected: {len(self.conflicts)} keys")
            print("=" * 60)
            
            for conflict in self.conflicts:
                print(f"\n🔴 Key: {conflict['key']}")
                for source, value in conflict['values'].items():
                    print(f"   {source:15} → {value}")
                
                # Show precedence
                print(f"   ⚡ Applied value: {self._resolve_value(conflict)}")
        else:
            print(f"\n✅ No configuration conflicts found!")
        
        # Check for deprecated usage
        print(f"\n📚 Deprecated Config Usage:")
        deprecated_imports = self._check_deprecated_imports()
        if deprecated_imports:
            print(f"   ⚠️  Found {len(deprecated_imports)} files still using config.settings:")
            for file_path in deprecated_imports[:5]:  # Show first 5
                print(f"      - {file_path}")
            if len(deprecated_imports) > 5:
                print(f"      ... and {len(deprecated_imports) - 5} more")
            print(f"   💡 Migrate to: from config.loader import get_config, RAGConfig")
        else:
            print(f"   ✅ No deprecated config.settings imports found")
        
        print("\n" + "=" * 60)
        
        return not conflicts_found
    
    def _resolve_value(self, conflict: Dict[str, Any]) -> str:
        """
        Resolve value based on precedence:
        default < config.yaml < .env < env_vars < CLI < runtime
        """
        values = conflict['values']
        
        # Highest precedence first
        if "env_vars" in values:
            return f"{values['env_vars']} (from env_vars)"
        if ".env" in values:
            return f"{values['.env']} (from .env)"
        if "config.yaml" in values:
            return f"{values['config.yaml']} (from config.yaml)"
        
        return "unknown"
    
    def _check_deprecated_imports(self) -> List[str]:
        """Find files still using config.settings"""
        deprecated_files = []
        
        for py_file in PROJECT_ROOT.glob("src/backend/**/*.py"):
            try:
                with open(py_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    if "from config.settings import" in content or "from config import settings" in content:
                        deprecated_files.append(str(py_file.relative_to(PROJECT_ROOT)))
            except Exception:
                pass
        
        return deprecated_files


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Audit RAG Dashboard configuration")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Exit with code 1 if conflicts found (for CI)"
    )
    
    args = parser.parse_args()
    
    auditor = ConfigAuditor()
    no_conflicts = auditor.audit()
    
    if args.check_only and not no_conflicts:
        print("\n❌ Configuration audit failed: conflicts detected")
        sys.exit(1)
    
    sys.exit(0 if no_conflicts else 0)  # Always exit 0 unless --check-only


if __name__ == "__main__":
    main()
