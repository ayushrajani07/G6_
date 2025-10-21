#!/usr/bin/env python3
"""
Health monitoring system for G6 Platform.
"""

import datetime
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from src.utils.color import FG_GREEN, FG_RED, colorize

logger = logging.getLogger(__name__)
from src.error_handling import ErrorCategory, ErrorSeverity, get_error_handler


class HealthMonitor:
    """System health monitoring for G6 Platform."""

    def __init__(self, check_interval=60):
        """
        Initialize health monitor.
        
        Args:
            check_interval: Seconds between health checks
        """
        self.check_interval = check_interval
        self.components = {}
        self.last_status = {}
        self.running = False
        self.monitor_thread = None
        self.health_checks = []
        self.logger = logging.getLogger(__name__)

        # Create health dir if it doesn't exist
        os.makedirs("data/health", exist_ok=True)

    def register_component(self, name, component, check_method=None):
        """
        Register a component for health monitoring.
        
        Args:
            name: Component name
            component: Component instance
            check_method: Optional health check method name
        """
        self.components[name] = {
            'instance': component,
            'check_method': check_method,
            'last_check': None,
            'status': 'unknown'
        }
        # Log registration at DEBUG to avoid noisy startup
        self.logger.debug(
            colorize(f"Registered component for health monitoring: {name}", FG_GREEN, bold=False)
        )

    def register_health_check(self, name: str, check_fn: Callable[[], dict[str, Any]]):
        """
        Register a custom health check function.
        
        Args:
            name: Health check name
            check_fn: Function that returns health status dict
        """
        self.health_checks.append({
            'name': name,
            'function': check_fn,
            'last_check': None,
            'status': 'unknown'
        })
        # Log registration at DEBUG to avoid noisy startup
        self.logger.debug(colorize(f"Registered health check: {name}", FG_GREEN, bold=False))

    def start(self):
        """Start health monitoring thread."""
        if self.running:
            return

        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        # Start message at DEBUG to reduce chatter; banner will summarize health
        self.logger.debug(
            colorize(
                f"Health monitoring started with {len(self.components)} components",
                FG_GREEN,
                bold=False,
            )
        )

    def stop(self):
        """Stop health monitoring thread."""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5.0)
        self.logger.info("Health monitoring stopped")

    def _monitor_loop(self):
        """Main monitoring loop."""
        while self.running:
            try:
                self._check_all_components()
                self._run_health_checks()
                self._save_health_status()
            except Exception as e:
                # Route monitoring loop errors centrally (INITIALIZATION/RESOURCE)
                try:
                    get_error_handler().handle_error(
                        e,
                        category=ErrorCategory.RESOURCE,
                        severity=ErrorSeverity.MEDIUM,
                        component="health.monitor",
                        function_name="_monitor_loop",
                        message="Error in health monitoring loop",
                    )
                except Exception:
                    pass
                self.logger.error(f"Error in health monitoring: {e}")

            # Sleep until next check
            time.sleep(self.check_interval)

    def _check_all_components(self):
        """Check health of all registered components."""
        for name, data in self.components.items():
            try:
                status = 'healthy'
                message = 'OK'

                if data['check_method'] and hasattr(data['instance'], data['check_method']):
                    # Call component's health check method
                    check_result = getattr(data['instance'], data['check_method'])()
                    if isinstance(check_result, dict):
                        status = check_result.get('status', 'healthy')
                        message = check_result.get('message', 'OK')
                    else:
                        status = 'healthy' if check_result else 'unhealthy'
                        message = 'Check failed' if not check_result else 'OK'

                # Update component status
                self.components[name]['last_check'] = datetime.datetime.now()  # local-ok
                self.components[name]['status'] = status
                self.components[name]['message'] = message

                if status != 'healthy':
                    # Unhealthy -> red WARNING
                    self.logger.warning(colorize(f"Component {name} health check: {status} - {message}", FG_RED, bold=True))
                else:
                    # Healthy -> DEBUG (reduce normal noise); warnings stay INFO/ERROR paths
                    self.logger.debug(colorize(f"Component {name} health check: {status}", FG_GREEN, bold=False))

            except Exception as e:
                try:
                    get_error_handler().handle_error(
                        e,
                        category=ErrorCategory.RESOURCE,
                        severity=ErrorSeverity.MEDIUM,
                        component="health.monitor",
                        function_name="_check_all_components",
                        message=f"Error checking component {name}",
                        context={"component": name},
                    )
                except Exception:
                    pass
                self.logger.error(f"Error checking component {name}: {e}")
                self.components[name]['last_check'] = datetime.datetime.now()  # local-ok
                self.components[name]['status'] = 'error'
                self.components[name]['message'] = str(e)

    def _run_health_checks(self):
        """Run all registered custom health checks."""
        for check in self.health_checks:
            try:
                result = check['function']()
                check['last_check'] = datetime.datetime.now()  # local-ok

                if isinstance(result, dict):
                    check['status'] = result.get('status', 'unknown')
                    check['message'] = result.get('message', '')
                    check['data'] = result.get('data', {})
                else:
                    check['status'] = 'error'
                    check['message'] = 'Invalid check result format'

                if check['status'] != 'healthy':
                    self.logger.warning(colorize(f"Health check {check['name']}: {check['status']} - {check['message']}", FG_RED, bold=True))
                else:
                    # Downgrade healthy pass logs to DEBUG
                    self.logger.debug(colorize(f"Health check {check['name']}: healthy", FG_GREEN, bold=False))

            except Exception as e:
                try:
                    get_error_handler().handle_error(
                        e,
                        category=ErrorCategory.RESOURCE,
                        severity=ErrorSeverity.MEDIUM,
                        component="health.monitor",
                        function_name="_run_health_checks",
                        message=f"Error in health check {check['name']}",
                        context={"check": check['name']},
                    )
                except Exception:
                    pass
                self.logger.error(f"Error in health check {check['name']}: {e}")
                check['last_check'] = datetime.datetime.now()  # local-ok
                check['status'] = 'error'
                check['message'] = str(e)

    def _save_health_status(self):
        """Save current health status to file."""
        try:
            from src.utils.timeutils import isoformat_z, utc_now  # type: ignore
            ts = isoformat_z(utc_now())
        except Exception:
            # Fallback: still produce an aware UTC ISO8601 with Z while avoiding forbidden utcnow
            ts = datetime.datetime.now(datetime.UTC).isoformat().replace('+00:00', 'Z')  # fallback aware
        status = {
            'timestamp': ts,
            'components': {},
            'health_checks': {}
        }

        # Add component statuses
        for name, data in self.components.items():
            status['components'][name] = {
                'status': data['status'],
                'message': data.get('message', ''),
                'last_check': data['last_check'].isoformat() if data['last_check'] else None
            }

        # Add health check results
        for check in self.health_checks:
            status['health_checks'][check['name']] = {
                'status': check['status'],
                'message': check.get('message', ''),
                'last_check': check['last_check'].isoformat() if check['last_check'] else None,
                'data': check.get('data', {})
            }

        # Save to file
        health_file = f"data/health/status_{datetime.datetime.now().strftime('%Y-%m-%d')}.json"  # local-ok
        try:
            with open(health_file, 'w') as f:
                json.dump(status, f, indent=2)
        except Exception as e:
            try:
                get_error_handler().handle_error(
                    e,
                    category=ErrorCategory.FILE_IO,
                    severity=ErrorSeverity.MEDIUM,
                    component="health.monitor",
                    function_name="_save_health_status",
                    message="Error saving health status",
                    context={"path": health_file},
                )
            except Exception:
                pass
            self.logger.error(f"Error saving health status: {e}")

        # Update last status
        self.last_status = status

    def get_health_status(self):
        """
        Get current health status.
        
        Returns:
            Dict with health status information
        """
        return self.last_status

    def is_healthy(self):
        """
        Check if system is healthy overall.
        
        Returns:
            bool: True if all components and checks are healthy
        """
        # Check components
        for name, data in self.components.items():
            if data['status'] != 'healthy':
                return False

        # Check custom health checks
        for check in self.health_checks:
            if check['status'] != 'healthy':
                return False

        return True
