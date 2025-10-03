# G6 Platform Cleanup Guide

This document outlines problematic areas in the G6 Platform codebase and provides detailed remediation steps to clean up the code without disrupting functionality.

## Table of Contents

1. [Architecture Issues](#architecture-issues)
2. [Code Quality Problems](#code-quality-problems)
3. [Redundant Components](#redundant-components)
4. [Performance Bottlenecks](#performance-bottlenecks)
5. [Maintainability Concerns](#maintainability-concerns)
6. [Testing Infrastructure](#testing-infrastructure)
7. [Documentation Gaps](#documentation-gaps)
8. [Configuration Management](#configuration-management)
9. [Cleanup Execution Plan](#cleanup-execution-plan)

## Architecture Issues

### 1. Monolithic Metrics Registry

**Problem**: The metrics system (`src/metrics/metrics.py`) is over 1400 lines, handling registration, grouping, and specialized metrics logic in a single file.

**Affected Areas**:
- `src/metrics/metrics.py`
- All code importing from `metrics.py`

**Remediation Steps**:

1. Create separate modules for logical components:
   ```python
   # filepath: src/metrics/groups.py
   """Metric group management and filtering."""
   
   def reload_group_filters():
       """Reload metric group filters from environment."""
       # Move implementation from metrics.py
   
   # Additional group-related functions
   ```

2. Create a metrics directory structure:
   ```
   src/metrics/
   ├── __init__.py
   ├── registry.py       # Core registry functionality
   ├── groups.py         # Group management 
   ├── derived.py        # Derived metric calculations
   ├── cardinality.py    # Cardinality management
   └── specialized/      # Specialized metric types
       ├── __init__.py
       ├── option_metrics.py
       ├── index_metrics.py
       └── system_metrics.py
   ```

3. Update imports without changing the public API:
   ```python
   # filepath: src/metrics/__init__.py
   """Metrics system for G6 Platform."""
   
   from .registry import MetricsRegistry, get_registry
   # Re-export all public functions to maintain backward compatibility
   ```

4. Incremental refactoring approach:
   - Move one group of functionality at a time
   - Add tests for each new module
   - Update imports without changing external behavior
   - Verify metrics still register and update correctly

### 2. Unified Main Module Replacement

**Problem**: The `unified_main.py` module is being replaced by the orchestrator components, but there may be residual dependencies.

**Affected Areas**:
- `src/unified_main.py`
- Code importing from `unified_main.py`
- `src/orchestrator/` directory

**Remediation Steps**:

1. Identify and catalog all imports of `unified_main`:
   ```bash
   find . -name "*.py" -exec grep -l "unified_main" {} \;
   ```

2. Create compatibility layer:
   ```python
   # filepath: src/unified_main.py
   """Compatibility layer for unified_main (DEPRECATED)."""
   import warnings
   from src.orchestrator.bootstrap import bootstrap_runtime
   from src.orchestrator.loop import run_loop
   
   warnings.warn(
       "unified_main is deprecated and will be removed. Use orchestrator.bootstrap and orchestrator.loop instead.",
       DeprecationWarning,
       stacklevel=2
   )
   
   def run_unified(...):
       """Legacy entry point - forwards to new implementation."""
       ctx = bootstrap_runtime(...)
       return run_loop(ctx, ...)
   ```

3. Update each importing module one by one:
   ```python
   # Before
   from src.unified_main import run_unified
   
   # After
   from src.orchestrator.bootstrap import bootstrap_runtime
   from src.orchestrator.loop import run_loop
   
   # And replace run_unified(...) with:
   ctx = bootstrap_runtime(...)
   result = run_loop(ctx, ...)
   ```

4. Add deprecation tests to ensure removal happens in future:
   ```python
   # filepath: tests/test_deprecation_unified_main.py
   def test_unified_main_not_imported_directly():
       """Ensure unified_main.py is not directly imported by any module."""
       # Implement import scanner to verify
   ```

## Code Quality Problems

### 1. Excessive Try/Except Blocks

**Problem**: Widespread use of try/except blocks that catch too broadly and may hide actual errors.

**Affected Areas**: Various files across the codebase

**Remediation Steps**:

1. Replace broad exception handling with specific exceptions:
   ```python
   # Before
   try:
       do_something()
   except:  # Too broad
       pass
   
   # After
   try:
       do_something()
   except (ValueError, KeyError) as e:  # Specific exceptions
       logger.warning("Expected error in do_something: %s", e)
   ```

2. Add logging to all except blocks:
   ```python
   try:
       result = optional_feature()
   except ImportError as e:
       logger.info("Optional feature unavailable: %s", e)
       result = None
   ```

3. Implement a utility for optional features:
   ```python
   # filepath: src/utils/optional.py
   def try_import(module_name, default=None):
       """Safely attempt to import a module, returning default on failure."""
       try:
           return importlib.import_module(module_name)
       except ImportError as e:
           logger.debug("Optional module %s not available: %s", module_name, e)
           return default
   ```

4. Search and update all instances:
   ```bash
   find . -name "*.py" -exec grep -l "except:" {} \;
   ```

### 2. Any Type Usage

**Problem**: Excessive use of `Any` type annotations that weaken type safety.

**Affected Areas**:
- `src/orchestrator/context.py` (RuntimeContext)
- Provider interfaces

**Remediation Steps**:

1. Define proper Protocol types for interfaces:
   ```python
   # filepath: src/providers/interfaces.py
   from typing import Protocol, Dict, Any, Optional
   
   class Provider(Protocol):
       """Interface defining the contract for data providers."""
       
       def get_data(self, index: str) -> Dict[str, Any]:
           """Get data for the specified index."""
           ...
       
       def health_check(self) -> bool:
           """Check if provider is healthy."""
           ...
   ```

2. Update context class to use proper typing:
   ```python
   # filepath: src/orchestrator/context.py
   from src.providers.interfaces import Provider
   
   class RuntimeContext:
       def __init__(self, providers: Dict[str, Provider]):
           self.providers = providers
   ```

3. Gradually improve type annotations throughout the codebase:
   - Start with core interfaces and runtime components
   - Add docstrings with type information
   - Use mypy to validate type consistency

## Redundant Components

### 1. Multiple Summary Renderers

**Problem**: Multiple scripts handle summary rendering with duplicated logic.

**Affected Areas**:
- `scripts/summary_view.py`
- `scripts/status_to_panels.py`
- Panel helper modules

**Remediation Steps**:

1. Create a unified rendering module:
   ```python
   # filepath: src/summary/renderer.py
   """Unified rendering module for terminal and panel output."""
   
   class SummaryRenderer:
       """Renders summary data in different formats."""
       
       def __init__(self, status_data, config=None):
           self.status_data = status_data
           self.config = config or {}
       
       def render_terminal(self):
           """Render for terminal output."""
           # Implementation
       
       def render_panels(self):
           """Render for panel output."""
           # Implementation
   ```

2. Create adapter scripts that use the unified renderer:
   ```python
   # filepath: scripts/summary_view.py
   from src.summary.renderer import SummaryRenderer
   from src.utils.status import get_latest_status
   
   def main():
       status = get_latest_status()
       renderer = SummaryRenderer(status)
       print(renderer.render_terminal())
   ```

3. Mark old implementations as deprecated:
   ```python
   # In old implementations
   warnings.warn("This module is deprecated. Use src.summary.renderer instead.", DeprecationWarning)
   ```

4. Gradually migrate usages to the new API

### 2. Archived and Backup Directories

**Problem**: `archived/` and `config_backup/` contain dead code that's no longer needed.

**Affected Areas**:
- `archived/` directory
- `config_backup/` directory

**Remediation Steps**:

1. Verify no imports from these directories:
   ```bash
   find . -name "*.py" -not -path "./archived/*" -exec grep -l "archived" {} \;
   find . -name "*.py" -not -path "./config_backup/*" -exec grep -l "config_backup" {} \;
   ```

2. Create archive of these directories outside of code:
   ```bash
   # Create a ZIP backup before removal
   zip -r archived_backup.zip archived/ config_backup/
   ```

3. Update .gitignore to exclude them:
   ```
   # Archived code - preserved for reference only
   /archived/
   /config_backup/
   ```

4. Remove references from build scripts and CI configs

5. Document the removal in CHANGELOG.md

## Performance Bottlenecks

### 1. Metric Cardinality Issues

**Problem**: Per-index/per-option instrumentation creates excessive metric cardinality.

**Affected Areas**:
- `src/metrics/metrics.py`
- `src/orchestrator/cardinality_guard.py`

**Remediation Steps**:

1. Implement smarter metric aggregation:
   ```python
   # filepath: src/metrics/aggregation.py
   """Metric aggregation strategies to reduce cardinality."""
   
   def bucket_by_strike_distance(options_data):
       """Group options by distance from ATM rather than individual strikes."""
       # Implementation
   
   def aggregate_by_expiry_groups(data, max_groups=5):
       """Aggregate metrics by expiry groups rather than individual expiries."""
       # Implementation
   ```

2. Update metric registration to use aggregation:
   ```python
   # In metrics registry
   def register_option_metrics(self, use_aggregation=True):
       if use_aggregation:
           # Use aggregation strategy
       else:
           # Original high-cardinality approach
   ```

3. Add configuration toggle with sensible default:
   ```python
   # filepath: src/config/defaults.py
   METRIC_AGGREGATION_ENABLED = True
   METRIC_MAX_EXPIRY_GROUPS = 5
   METRIC_MAX_STRIKE_GROUPS = 7
   ```

4. Update cardinality guard to use new aggregation:
   ```python
   # filepath: src/orchestrator/cardinality_guard.py
   from src.metrics.aggregation import bucket_by_strike_distance
   
   def guard_metrics_cardinality(data, max_series=1000):
       """Apply cardinality guards using aggregation strategies."""
       # Implementation using new aggregation functions
   ```

### 2. Inefficient Data Processing

**Problem**: Multiple passes over the same data when collecting metrics and generating summaries.

**Affected Areas**:
- Data collection routines
- Metrics calculation
- Summary generation

**Remediation Steps**:

1. Implement a cached data processor:
   ```python
   # filepath: src/processing/cached_processor.py
   """Cached data processor to avoid redundant calculations."""
   
   class CachedProcessor:
       """Processes data once and caches derived values."""
       
       def __init__(self, raw_data):
           self.raw_data = raw_data
           self._cache = {}
       
       def get_metric_inputs(self):
           """Get derived data for metrics calculation."""
           if "metric_inputs" not in self._cache:
               self._cache["metric_inputs"] = self._calculate_metric_inputs()
           return self._cache["metric_inputs"]
       
       def get_summary_data(self):
           """Get derived data for summary generation."""
           if "summary_data" not in self._cache:
               # Reuse metric calculations where possible
               metric_inputs = self.get_metric_inputs()
               self._cache["summary_data"] = self._enrich_for_summary(metric_inputs)
           return self._cache["summary_data"]
   ```

2. Integrate the cached processor into the collection cycle:
   ```python
   # filepath: src/orchestrator/cycle.py
   from src.processing.cached_processor import CachedProcessor
   
   def execute_cycle(context):
       raw_data = collect_raw_data(context)
       processor = CachedProcessor(raw_data)
       
       # Update metrics
       metric_data = processor.get_metric_inputs()
       update_metrics(metric_data)
       
       # Generate summary
       summary_data = processor.get_summary_data()
       update_summary(summary_data)
   ```

## Maintainability Concerns

### 1. Environment Variable Proliferation

**Problem**: Numerous `G6_*` environment variables without central documentation or schema.

**Affected Areas**: Throughout the codebase

**Remediation Steps**:

1. Create an environment variable registry:
   ```python
   # filepath: src/config/env_registry.py
   """Registry for environment variables used in G6 Platform."""
   
   from dataclasses import dataclass
   from typing import Any, Optional, List
   
   @dataclass
   class EnvVarSpec:
       """Specification for an environment variable."""
       name: str
       default: Any
       description: str
       deprecated: bool = False
       replacement: Optional[str] = None
       allowed_values: Optional[List[Any]] = None
   
   # Register all environment variables
   ENV_VARS = [
       EnvVarSpec(
           name="G6_LOOP_MAX_CYCLES",
           default=None,
           description="Maximum number of collection cycles to run (None for infinite)",
       ),
       EnvVarSpec(
           name="G6_PARALLEL_INDICES",
           default=False,
           description="Process indices in parallel",
       ),
       # Add all other env vars
   ]
   
   def get_env_var_value(name):
       """Get the value of an environment variable with proper typing."""
       # Implementation
   
   def validate_env_vars():
       """Validate that environment variables have valid values."""
       # Implementation
   ```

2. Create an environment variable documentation generator:
   ```python
   # filepath: scripts/gen_env_docs.py
   """Generate documentation for environment variables."""
   
   from src.config.env_registry import ENV_VARS
   
   def main():
       """Generate Markdown documentation for environment variables."""
       with open('docs/ENV_VARS.md', 'w') as f:
           f.write("# Environment Variables\n\n")
           f.write("This document lists all environment variables used in G6 Platform.\n\n")
           
           for var in ENV_VARS:
               f.write(f"## {var.name}\n\n")
               f.write(f"{var.description}\n\n")
               f.write(f"- Default: `{var.default}`\n")
               if var.deprecated:
                   f.write(f"- **DEPRECATED**: Use `{var.replacement}` instead\n")
               if var.allowed_values:
                   f.write(f"- Allowed values: {', '.join(str(v) for v in var.allowed_values)}\n")
               f.write("\n")
   ```

3. Update code to use the registry:
   ```python
   # Before
   max_cycles = os.environ.get("G6_LOOP_MAX_CYCLES")
   
   # After
   from src.config.env_registry import get_env_var_value
   max_cycles = get_env_var_value("G6_LOOP_MAX_CYCLES")
   ```

4. Run validation at startup:
   ```python
   # filepath: src/orchestrator/bootstrap.py
   from src.config.env_registry import validate_env_vars
   
   def bootstrap_runtime(...):
       validate_env_vars()  # Validate environment variables
       # Rest of bootstrap logic
   ```

### 2. Inconsistent Error Handling

**Problem**: Different parts of the codebase handle errors in inconsistent ways.

**Affected Areas**: Throughout the codebase

**Remediation Steps**:

1. Create a centralized error handling module:
   ```python
   # filepath: src/utils/error_handling.py
   """Standardized error handling for G6 Platform."""
   
   import logging
   from enum import Enum
   from functools import wraps
   
   logger = logging.getLogger(__name__)
   
   class ErrorSeverity(Enum):
       """Severity levels for errors."""
       DEBUG = 1
       INFO = 2
       WARNING = 3
       ERROR = 4
       CRITICAL = 5
   
   def handle_error(e, severity=ErrorSeverity.ERROR, reraise=True, context=None):
       """Standard error handling function."""
       ctx_str = f" in {context}" if context else ""
       
       if severity == ErrorSeverity.DEBUG:
           logger.debug("Error%s: %s", ctx_str, e)
       elif severity == ErrorSeverity.INFO:
           logger.info("Error%s: %s", ctx_str, e)
       elif severity == ErrorSeverity.WARNING:
           logger.warning("Error%s: %s", ctx_str, e)
       elif severity == ErrorSeverity.ERROR:
           logger.error("Error%s: %s", ctx_str, e)
       elif severity == ErrorSeverity.CRITICAL:
           logger.critical("Error%s: %s", ctx_str, e)
       
       if reraise:
           raise
   
   def safe_operation(severity=ErrorSeverity.WARNING, reraise=False):
       """Decorator for functions that should handle errors gracefully."""
       def decorator(func):
           @wraps(func)
           def wrapper(*args, **kwargs):
               try:
                   return func(*args, **kwargs)
               except Exception as e:
                   handle_error(e, severity, reraise, context=func.__name__)
                   return None
           return wrapper
       return decorator
   ```

2. Apply the standard error handling throughout the codebase:
   ```python
   # filepath: any_module.py
   from src.utils.error_handling import safe_operation, ErrorSeverity
   
   @safe_operation(severity=ErrorSeverity.WARNING)
   def try_optional_feature():
       """Try to use an optional feature."""
       # Implementation
   ```

3. Create guidelines for error handling:
   ```markdown
   # filepath: docs/ERROR_HANDLING.md
   # Error Handling Guidelines
   
   This document outlines the standard approach to error handling in G6 Platform.
   
   ## General Principles
   
   1. Use specific exception types rather than catching all exceptions
   2. Always log exceptions with appropriate context
   3. Use the standard error handling utilities from `src.utils.error_handling`
   
   ## Severity Levels
   
   - DEBUG: Used for optional features or expected failures in development
   - INFO: Used for expected failures that don't impact functionality
   - WARNING: Used for recoverable errors that might indicate problems
   - ERROR: Used for failures that impact functionality but don't crash
   - CRITICAL: Used for severe errors that require immediate attention
   
   ## Examples
   
   ```python
   # Safe operation that shouldn't crash on failure
   @safe_operation(severity=ErrorSeverity.WARNING)
   def optional_feature():
       # Implementation
   
   # Operation that should log errors but still raise them
   @safe_operation(severity=ErrorSeverity.ERROR, reraise=True)
   def important_operation():
       # Implementation
   ```
   ```

## Testing Infrastructure

### 1. Test Suite Organization and Speed

**Problem**: Large test suite with mixed fast and slow tests makes local development difficult.

**Affected Areas**:
- Test directory structure
- CI configuration

**Remediation Steps**:

1. Organize tests by speed and type:
   ```
   tests/
   ├── unit/           # Fast unit tests
   ├── integration/    # Integration tests
   ├── slow/           # Slow tests
   └── performance/    # Performance benchmarks
   ```

2. Update pytest markers:
   ```python
   # filepath: tests/conftest.py
   def pytest_configure(config):
       """Configure pytest with custom markers."""
       config.addinivalue_line("markers", "unit: fast unit tests")
       config.addinivalue_line("markers", "integration: integration tests")
       config.addinivalue_line("markers", "slow: slow tests")
       config.addinivalue_line("markers", "performance: performance tests")
   ```

3. Create test running scripts:
   ```python
   # filepath: scripts/run_fast_tests.py
   """Run only fast tests for local development."""
   
   import subprocess
   import sys
   
   def main():
       """Run fast tests."""
       result = subprocess.run(
           ["pytest", "tests/unit", "-v"],
           check=False,
       )
       sys.exit(result.returncode)
   
   if __name__ == "__main__":
       main()
   ```

4. Update CI configuration to run tests in stages:
   ```yaml
   # CI configuration
   stages:
     - fast_tests
     - integration_tests
     - slow_tests
     - performance_tests
   
   fast_tests:
     stage: fast_tests
     script: pytest tests/unit -v
   
   integration_tests:
     stage: integration_tests
     script: pytest tests/integration -v
   
   slow_tests:
     stage: slow_tests
     script: pytest tests/slow -v
   
   performance_tests:
     stage: performance_tests
     script: pytest tests/performance -v
   ```

5. Move tests to appropriate directories and update markers

### 2. Test Data Management

**Problem**: Test data is scattered and sometimes duplicated across test files.

**Affected Areas**: Test files

**Remediation Steps**:

1. Create a centralized test data module:
   ```python
   # filepath: tests/test_data/__init__.py
   """Test data for G6 Platform tests."""
   
   import json
   import os
   from typing import Dict, Any
   
   def load_test_data(filename: str) -> Dict[str, Any]:
       """Load test data from a JSON file."""
       data_dir = os.path.join(os.path.dirname(__file__), "data")
       file_path = os.path.join(data_dir, filename)
       with open(file_path, "r") as f:
           return json.load(f)
   
   # Common test data sets
   SAMPLE_INDEX_DATA = load_test_data("sample_index_data.json")
   SAMPLE_OPTIONS_DATA = load_test_data("sample_options_data.json")
   ```

2. Organize test data files:
   ```
   tests/test_data/
   ├── __init__.py
   ├── data/
   │   ├── sample_index_data.json
   │   ├── sample_options_data.json
   │   └── ...
   ├── factories.py          # Factory methods for test data
   └── fixtures.py           # Pytest fixtures for test data
   ```

3. Create factory methods for dynamic test data:
   ```python
   # filepath: tests/test_data/factories.py
   """Factory methods for generating test data."""
   
   import datetime
   from typing import Dict, Any, List
   
   def create_option_data(
       strike: float,
       expiry: datetime.date,
       underlying: float = 100.0,
       iv: float = 0.2,
   ) -> Dict[str, Any]:
       """Create synthetic option data for testing."""
       # Implementation
   
   def create_index_data(
       index_name: str,
       current_value: float,
       options: List[Dict[str, Any]],
   ) -> Dict[str, Any]:
       """Create synthetic index data for testing."""
       # Implementation
   ```

4. Create pytest fixtures:
   ```python
   # filepath: tests/test_data/fixtures.py
   """Pytest fixtures for test data."""
   
   import pytest
   from datetime import date, timedelta
   
   from .factories import create_option_data, create_index_data
   
   @pytest.fixture
   def sample_expiry_dates():
       """Sample expiry dates for testing."""
       today = date.today()
       return [
           today + timedelta(days=7),
           today + timedelta(days=30),
           today + timedelta(days=90),
       ]
   
   @pytest.fixture
   def sample_option_chain(sample_expiry_dates):
       """Sample option chain for testing."""
       # Implementation using factories
   ```

5. Use centralized test data in tests:
   ```python
   # filepath: tests/unit/test_metrics.py
   from tests.test_data import SAMPLE_INDEX_DATA
   from tests.test_data.fixtures import sample_option_chain
   
   def test_metric_calculation(sample_option_chain):
       # Test using the fixture
   ```

## Documentation Gaps

### 1. Missing API Documentation

**Problem**: Lack of comprehensive API documentation makes the codebase difficult to navigate.

**Affected Areas**: All modules

**Remediation Steps**:

1. Add docstrings to all public functions, classes, and methods:
   ```python
   def function_name(param1, param2):
       """Short description of function purpose.
       
       Longer description with more details about behavior,
       edge cases, and examples.
       
       Args:
           param1: Description of param1
           param2: Description of param2
           
       Returns:
           Description of return value
           
       Raises:
           ExceptionType: When and why this exception is raised
       """
       # Implementation
   ```

2. Create a documentation build system using Sphinx:
   ```
   docs/
   ├── conf.py           # Sphinx configuration
   ├── index.rst         # Main documentation page
   ├── api/              # API documentation
   ├── guides/           # User guides
   └── Makefile          # Build scripts
   ```

3. Add documentation building to CI pipeline:
   ```bash
   # Documentation build script
   sphinx-build -b html docs/ docs/_build/html
   ```

4. Create a script to check documentation coverage:
   ```python
   # filepath: scripts/check_doc_coverage.py
   """Check documentation coverage for Python modules."""
   
   import importlib
   import inspect
   import pkgutil
   import sys
   from typing import Dict, List, Tuple
   
   def get_module_doc_coverage(module_name: str) -> Tuple[int, int, List[str]]:
       """Get documentation coverage for a module."""
       try:
           module = importlib.import_module(module_name)
       except ImportError:
           return 0, 0, [f"Could not import {module_name}"]
       
       total_items = 0
       documented_items = 0
       undocumented = []
       
       for name, obj in inspect.getmembers(module):
           if name.startswith('_'):
               continue
               
           if inspect.isfunction(obj) or inspect.isclass(obj):
               total_items += 1
               if obj.__doc__:
                   documented_items += 1
               else:
                   undocumented.append(f"{module_name}.{name}")
       
       return documented_items, total_items, undocumented
   
   def main():
       """Check documentation coverage for all modules."""
       # Implementation to scan all modules
   
   if __name__ == "__main__":
       main()
   ```

### 2. Architecture Documentation

**Problem**: Lack of high-level architecture documentation makes it difficult for new developers.

**Affected Areas**: Project-wide

**Remediation Steps**:

1. Create architecture documentation:
   ```markdown
   # filepath: docs/ARCHITECTURE.md
   # G6 Platform Architecture
   
   This document provides an overview of the G6 Platform architecture.
   
   ## System Components
   
   ### Orchestrator
   
   The orchestrator is responsible for managing the data collection cycle.
   
   - **Bootstrap**: Initializes the runtime context
   - **Loop**: Manages the collection loop
   - **Cycle**: Executes a single collection cycle
   
   ### Metrics System
   
   The metrics system collects and exposes metrics about the platform.
   
   - **Registry**: Manages metric registration and updates
   - **Groups**: Organizes metrics into logical groups
   - **Cardinality**: Controls metric cardinality
   
   ### Data Collection
   
   The data collection system gathers options data from various sources.
   
   - **Providers**: External data source interfaces
   - **Collectors**: Specialized data collectors
   - **Validators**: Data validation logic
   
   ### Summary System
   
   The summary system generates human-readable summaries of the platform state.
   
   - **Renderer**: Renders summaries in different formats
   - **Formatters**: Formats specific data types
   
   ## Data Flow
   
   1. Orchestrator bootstrap initializes the system
   2. Loop manager runs collection cycles
   3. Each cycle collects data from providers
   4. Data is processed and metrics are updated
   5. Summary is generated and displayed
   
   ## Configuration
   
   Configuration is managed through:
   
   - Configuration files
   - Environment variables
   - Command-line arguments
   
   ## Deployment
   
   Deployment options include:
   
   - Local development
   - Production deployment
   - CI/CD integration
   ```

2. Create component diagrams using Mermaid:
   ```markdown
   # filepath: docs/COMPONENT_DIAGRAMS.md
   # Component Diagrams
   
   ## Main Data Flow
   
   ```mermaid
   graph TD
       A[Orchestrator] --> B[Providers]
       B --> C[Data Processing]
       C --> D[Metrics Update]
       C --> E[Summary Generation]
       D --> F[Prometheus]
       E --> G[Terminal/UI]
   ```
   
   ## Orchestrator Components
   
   ```mermaid
   graph TD
       A[Bootstrap] --> B[Runtime Context]
       B --> C[Loop Manager]
       C --> D[Cycle Executor]
       D --> E[Status Writer]
   ```
   ```

3. Add architectural decision records:
   ```markdown
   # filepath: docs/adr/0001-metrics-system-design.md
   # ADR 0001: Metrics System Design
   
   ## Status
   
   Accepted
   
   ## Context
   
   We need a metrics system that can handle a large number of metrics with dynamic cardinality.
   
   ## Decision
   
   We will use a metrics registry with group filtering and cardinality management.
   
   ## Consequences
   
   - Pros: Flexible metrics system that can handle dynamic cardinality
   - Cons: Complexity in maintaining the registry
   ```

## Configuration Management

### 1. Scattered Configuration

**Problem**: Configuration is spread across multiple files and environment variables.

**Affected Areas**:
- `config/` directory
- Environment variables
- Command-line arguments

**Remediation Steps**:

1. Create a unified configuration system:
   ```python
   # filepath: src/config/config.py
   """Unified configuration system for G6 Platform."""
   
   import os
   import json
   from typing import Any, Dict, Optional
   
   class Config:
       """Unified configuration class."""
       
       def __init__(
           self,
           config_file: Optional[str] = None,
           env_prefix: str = "G6_",
           cli_args: Optional[Dict[str, Any]] = None,
       ):
           self.values = {}
           self._load_defaults()
           
           if config_file:
               self._load_from_file(config_file)
               
           self._load_from_env(env_prefix)
           
           if cli_args:
               self._load_from_cli(cli_args)
       
       def _load_defaults(self):
           """Load default configuration values."""
           self.values = {
               "loop": {
                   "max_cycles": None,
                   "parallel_indices": False,
               },
               "metrics": {
                   "enabled_groups": ["core", "system"],
                   "disabled_groups": [],
               },
               # More default values
           }
       
       def _load_from_file(self, config_file: str):
           """Load configuration from a file."""
           try:
               with open(config_file, "r") as f:
                   file_config = json.load(f)
                   self._merge_config(file_config)
           except (FileNotFoundError, json.JSONDecodeError) as e:
               print(f"Error loading config file: {e}")
       
       def _load_from_env(self, prefix: str):
           """Load configuration from environment variables."""
           # Implementation
       
       def _load_from_cli(self, cli_args: Dict[str, Any]):
           """Load configuration from command-line arguments."""
           # Implementation
       
       def _merge_config(self, new_config: Dict[str, Any]):
           """Merge new configuration into existing configuration."""
           # Implementation
       
       def get(self, key: str, default: Any = None) -> Any:
           """Get a configuration value."""
           # Implementation
   ```

2. Create a configuration schema:
   ```python
   # filepath: src/config/schema.py
   """Configuration schema for G6 Platform."""
   
   from typing import Dict, Any, List, Optional, Union
   from pydantic import BaseModel, Field
   
   class LoopConfig(BaseModel):
       """Configuration for the collection loop."""
       max_cycles: Optional[int] = Field(None, description="Maximum number of collection cycles")
       parallel_indices: bool = Field(False, description="Process indices in parallel")
   
   class MetricsConfig(BaseModel):
       """Configuration for the metrics system."""
       enabled_groups: List[str] = Field(["core", "system"], description="Enabled metric groups")
       disabled_groups: List[str] = Field([], description="Disabled metric groups")
   
   class Config(BaseModel):
       """Root configuration schema."""
       loop: LoopConfig = Field(default_factory=LoopConfig)
       metrics: MetricsConfig = Field(default_factory=MetricsConfig)
       # More configuration sections
   ```

3. Create a configuration validator:
   ```python
   # filepath: src/config/validator.py
   """Configuration validator for G6 Platform."""
   
   from .schema import Config as ConfigSchema
   
   def validate_config(config_dict):
       """Validate configuration against schema."""
       try:
           config_schema = ConfigSchema(**config_dict)
           return config_schema.dict()
       except Exception as e:
           raise ValueError(f"Invalid configuration: {e}")
   ```

4. Update bootstrap to use the new configuration system:
   ```python
   # filepath: src/orchestrator/bootstrap.py
   from src.config.config import Config
   from src.config.validator import validate_config
   
   def bootstrap_runtime(config_file=None, cli_args=None):
       """Bootstrap the runtime with configuration."""
       config = Config(config_file, cli_args=cli_args)
       validated_config = validate_config(config.values)
       
       # Use validated configuration
   ```

### 2. Configuration Documentation

**Problem**: Configuration options are not well-documented.

**Affected Areas**: Configuration files and environment variables

**Remediation Steps**:

1. Generate configuration documentation from schema:
   ```python
   # filepath: scripts/gen_config_docs.py
   """Generate configuration documentation from schema."""
   
   import json
   from src.config.schema import Config
   
   def main():
       """Generate Markdown documentation for configuration options."""
       schema = Config.schema()
       
       with open("docs/CONFIGURATION.md", "w") as f:
           f.write("# Configuration Options\n\n")
           f.write("This document describes all configuration options for G6 Platform.\n\n")
           
           f.write("## Root Configuration\n\n")
           for prop_name, prop in schema["properties"].items():
               f.write(f"### {prop_name}\n\n")
               f.write(f"{prop.get('description', 'No description')}\n\n")
               
               if "$ref" in prop:
                   ref_name = prop["$ref"].split("/")[-1]
                   ref_schema = schema["definitions"][ref_name]
                   
                   for sub_prop_name, sub_prop in ref_schema["properties"].items():
                       f.write(f"#### {prop_name}.{sub_prop_name}\n\n")
                       f.write(f"{sub_prop.get('description', 'No description')}\n\n")
                       f.write(f"- Type: `{sub_prop['type']}`\n")
                       f.write(f"- Default: `{sub_prop.get('default', 'None')}`\n\n")
   
   if __name__ == "__main__":
       main()
   ```

2. Create configuration examples:
   ```json
   // filepath: config/examples/default.json
   {
     "loop": {
       "max_cycles": null,
       "parallel_indices": false
     },
     "metrics": {
       "enabled_groups": ["core", "system"],
       "disabled_groups": []
     }
   }
   ```

3. Add configuration section to README:
   ```markdown
   # filepath: README.md (section)
   ## Configuration
   
   G6 Platform can be configured through:
   
   1. Configuration files
   2. Environment variables
   3. Command-line arguments
   
   See [Configuration Documentation](docs/CONFIGURATION.md) for details.
   
   ### Quick Start
   
   ```bash
   # Using environment variables
   export G6_LOOP_MAX_CYCLES=100
   export G6_PARALLEL_INDICES=true
   
   # Using configuration file
   python -m g6 run --config config/examples/default.json
   ```
   ```

## Cleanup Execution Plan

To execute this cleanup without disrupting functionality, follow this phased approach:

### Phase 1: Documentation and Analysis

1. Generate environment variable inventory
2. Create architecture documentation
3. Document configuration options
4. Identify and catalog redundant components

### Phase 2: Non-Disruptive Improvements

1. Add proper docstrings to core modules
2. Organize test suite by speed and type
3. Create centralized test data module
4. Remove archived and backup directories
5. Implement the error handling module

### Phase 3: Incremental Refactoring

1. Create the configuration system
2. Refactor metrics registry into smaller modules
3. Create proper interfaces for providers
4. Implement cached data processor
5. Create unified rendering module

### Phase 4: Migration and Cleanup

1. Migrate from unified_main to orchestrator components
2. Replace broad exception handling with specific exceptions
3. Update environment variable usage to use the registry
4. Implement metric aggregation strategies
5. Remove redundant summary renderers

### Validation Strategy

For each change:

1. Run the test suite to verify functionality
2. Check for regressions in performance
3. Verify metrics are still correctly registered and updated
4. Ensure summary output remains consistent
5. Document changes in CHANGELOG.md

This phased approach ensures that the cleanup can be executed without disrupting ongoing development or production usage of the platform.
