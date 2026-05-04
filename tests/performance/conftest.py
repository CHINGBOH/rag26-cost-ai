"""Pytest configuration for performance tests."""
import pytest
import json
import os


def pytest_configure(config):
    """Register performance marker."""
    config.addinivalue_line(
        "markers", "performance: mark test as a performance test"
    )


@pytest.fixture
def performance_results():
    """Fixture to collect performance results."""
    return {}


def pytest_sessionfinish(session, exitstatus):
    """Save performance results after session."""
    # Collect results from test node data
    results = {
        'baseline': {},
        'concurrent': {},
        'db_connections': {},
        'memory': {},
        'query_perf': {},
        'scalability': {},
        'cache': {}
    }
    
    # Store results for report generation
    results_file = os.path.join(
        os.path.dirname(__file__),
        "performance_results.json"
    )
    
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
