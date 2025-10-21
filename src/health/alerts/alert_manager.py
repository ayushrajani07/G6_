#!/usr/bin/env python3
"""
Optional Alert Manager for G6 health subsystem.

Default OFF. When enabled via config/env, routes health updates to channels
(email/webhook) based on simple policies with cooldown and dedup.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import threading
import time
import uuid
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertStatus(Enum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Alert:
    def __init__(self, component: str, message: str, severity: AlertSeverity, details: dict[str, Any] | None = None):
        self.id = str(uuid.uuid4())
        self.component = component
        self.message = message
        self.severity = severity
        self.details = details or {}
        self.status = AlertStatus.ACTIVE
        self.created_at = datetime.datetime.now(datetime.UTC)
        self.updated_at = self.created_at
        self.group_key = f"{component}:{severity.value}:{hash(message) % 1000000}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "component": self.component,
            "message": self.message,
            "severity": self.severity.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "details": self.details,
            "group_key": self.group_key,
        }


class AlertChannel:
    def __init__(self, name: str):
        self.name = name
        self.enabled = True

    def send(self, alert: Alert) -> bool:  # pragma: no cover - abstract
        raise NotImplementedError


class EmailChannel(AlertChannel):
    def __init__(self, name: str, smtp_server: str, smtp_port: int, sender: str, recipients: list[str], username: str | None = None, password: str | None = None, use_tls: bool = True):
        super().__init__(name)
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender = sender
        self.recipients = recipients
        self.username = username
        self.password = password
        self.use_tls = use_tls

    def send(self, alert: Alert) -> bool:
        try:
            import smtplib
            from email.mime.text import MIMEText
            subject = f"[{alert.severity.value.upper()}] {alert.component}"
            body = json.dumps(alert.to_dict(), indent=2)
            msg = MIMEText(body, "plain", "utf-8")
            msg["From"] = self.sender
            msg["To"] = ", ".join(self.recipients)
            msg["Subject"] = subject
            s = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=5)
            if self.use_tls:
                try:
                    s.starttls()
                except Exception as _e:
                    try:
                        from src.error_handling import handle_ui_error
                        handle_ui_error(_e, component="alerts.email.starttls")
                    except Exception:
                        pass
            if self.username and self.password:
                try:
                    s.login(self.username, self.password)
                except Exception as _e:
                    try:
                        from src.error_handling import handle_ui_error
                        handle_ui_error(_e, component="alerts.email.login")
                    except Exception:
                        pass
            s.sendmail(self.sender, self.recipients, msg.as_string())
            s.quit()
            return True
        except Exception as e:  # pragma: no cover
            logger.warning("EmailChannel send failed: %s", e)
            try:
                from src.error_handling import handle_ui_error
                handle_ui_error(e, component="alerts.email.send")
            except Exception:
                pass
            return False


class WebhookChannel(AlertChannel):
    def __init__(self, name: str, url: str, headers: dict[str, str] | None = None, timeout: float = 5.0):
        super().__init__(name)
        self.url = url
        self.headers = headers or {"Content-Type": "application/json"}
        self.timeout = timeout

    def send(self, alert: Alert) -> bool:
        try:
            try:
                import requests
            except Exception as _e:
                logger.warning("WebhookChannel requires requests; skipping send")
                try:
                    from src.error_handling import handle_ui_error
                    handle_ui_error(_e, component="alerts.webhook.import_requests")
                except Exception:
                    pass
                return False
            resp = requests.post(self.url, json=alert.to_dict(), headers=self.headers, timeout=self.timeout)
            return resp.status_code < 400
        except Exception as e:  # pragma: no cover
            logger.warning("WebhookChannel send failed: %s", e)
            try:
                from src.error_handling import handle_ui_error
                handle_ui_error(e, component="alerts.webhook.send", context={"url": self.url})
            except Exception:
                pass
            return False


class AlertPolicy:
    def __init__(self, name: str, component_pattern: str = "*", min_level: int = 2, cooldown_seconds: int = 300, channels: list[str] | None = None):
        self.name = name
        self.component_pattern = component_pattern
        self.min_level = int(min_level)  # 0 healthy .. higher worse
        self.cooldown_seconds = int(cooldown_seconds)
        self.channels = channels
        self._last_trigger: dict[str, datetime.datetime] = {}

    def matches(self, component: str) -> bool:
        if self.component_pattern == "*":
            return True
        if self.component_pattern.endswith("*"):
            return component.startswith(self.component_pattern[:-1])
        return component == self.component_pattern

    def allow(self, component: str) -> bool:
        now = datetime.datetime.now(datetime.UTC)
        last = self._last_trigger.get(component)
        if last and (now - last).total_seconds() < self.cooldown_seconds:
            return False
        self._last_trigger[component] = now
        return True


class AlertManager:
    _inst: AlertManager | None = None
    _lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> AlertManager:
        with cls._lock:
            if cls._inst is None:
                cls._inst = AlertManager()
            return cls._inst

    def __init__(self) -> None:
        self.enabled = False
        self.channels: dict[str, AlertChannel] = {}
        self.policies: list[AlertPolicy] = []
        self.active: dict[str, Alert] = {}
        self.history: list[Alert] = []
        self.state_dir: str | None = None
        self._queue: list[Alert] = []
        self._q_lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def initialize(self, cfg: dict[str, Any]) -> None:
        """Initialize channels and policies, start background processing."""
        self.enabled = bool(cfg.get("enabled", False))
        if not self.enabled:
            return
        sd = cfg.get("state_directory") or os.path.join("data", "health", "alerts")
        self.state_dir = str(sd)
        try:
            os.makedirs(self.state_dir, exist_ok=True)
        except Exception as _e:
            try:
                from src.error_handling import handle_ui_error
                handle_ui_error(_e, component="alerts.init.mkdir", context={"dir": self.state_dir})
            except Exception:
                pass
        # Channels
        for ch in cfg.get("channels", []):
            try:
                ctype = str(ch.get("type", "")).lower()
                name = ch.get("name") or ctype
                if ctype == "email":
                    channel: AlertChannel = EmailChannel(
                        name=name,
                        smtp_server=ch.get("smtp_server", "localhost"),
                        smtp_port=int(ch.get("smtp_port", 25)),
                        sender=ch.get("sender", "g6@localhost"),
                        recipients=list(ch.get("recipients", [])),
                        username=ch.get("username"),
                        password=ch.get("password"),
                        use_tls=bool(ch.get("use_tls", True)),
                    )
                elif ctype == "webhook" or ctype == "slack":
                    channel = WebhookChannel(
                        name=name,
                        url=ch.get("url") or ch.get("webhook_url", ""),
                        headers=ch.get("headers") or {"Content-Type": "application/json"},
                    )
                else:
                    continue
                self.channels[name] = channel
            except Exception as e:  # pragma: no cover
                logger.warning("Failed creating channel %s: %s", ch, e)
                try:
                    from src.error_handling import handle_ui_error
                    handle_ui_error(e, component="alerts.init.create_channel", context={"channel": ch})
                except Exception:
                    pass
        # Policies
        pols = cfg.get("policies") or [{"name": "default", "component": "*", "min_level": 2, "cooldown_seconds": 300}]
        for p in pols:
            try:
                pol = AlertPolicy(
                    name=p.get("name", "default"),
                    component_pattern=p.get("component", "*"),
                    min_level=int(p.get("min_level", 2)),
                    cooldown_seconds=int(p.get("cooldown_seconds", 300)),
                    channels=list(p.get("channels", [])) if p.get("channels") else None,
                )
                self.policies.append(pol)
            except Exception as _e:
                try:
                    from src.error_handling import handle_ui_error
                    handle_ui_error(_e, component="alerts.init.policy")
                except Exception:
                    pass
        # Start worker
        self._start_worker()

    def _start_worker(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="AlertManager", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        try:
            self._stop.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=5)
        except Exception as _e:
            try:
                from src.error_handling import handle_ui_error
                handle_ui_error(_e, component="alerts.stop")
            except Exception:
                pass

    # -------- Public API --------
    def process_health_update(self, component: str, level: int, state: Any, details: dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        # Decide if any policy wants an alert
        for pol in self.policies:
            if not pol.matches(component):
                continue
            if int(level) < pol.min_level:
                # Auto-resolve previous alerts if any
                self._resolve_component(component)
                continue
            if not pol.allow(component):
                continue
            # Map level to severity (simple mapping)
            sev = AlertSeverity.WARNING
            if int(level) >= 3:
                sev = AlertSeverity.CRITICAL
            elif int(level) == 2:
                sev = AlertSeverity.WARNING
            elif int(level) == 1:
                sev = AlertSeverity.WARNING
            else:
                sev = AlertSeverity.INFO
            msg = f"{component} state={getattr(state, 'value', str(state))} level={int(level)}"
            alert = Alert(component=component, message=msg, severity=sev, details=details)
            self._enqueue(alert, target_channels=pol.channels)

    def get_active_alerts(self) -> list[dict[str, Any]]:
        return [a.to_dict() for a in self.active.values() if a.status in (AlertStatus.ACTIVE, AlertStatus.ACKNOWLEDGED)]

    def get_alert_history(self, limit: int = 100) -> list[dict[str, Any]]:
        return [a.to_dict() for a in self.history[-limit:]]

    def acknowledge(self, alert_id: str) -> bool:
        a = self.active.get(alert_id)
        if not a:
            return False
        a.status = AlertStatus.ACKNOWLEDGED
        a.updated_at = datetime.datetime.now(datetime.UTC)
        self._persist()
        return True

    def resolve(self, alert_id: str) -> bool:
        a = self.active.pop(alert_id, None)
        if not a:
            return False
        a.status = AlertStatus.RESOLVED
        a.updated_at = datetime.datetime.now(datetime.UTC)
        self.history.append(a)
        self._persist()
        return True

    # -------- Internal --------
    def _resolve_component(self, component: str) -> None:
        for aid, a in list(self.active.items()):
            if a.component == component and a.status == AlertStatus.ACTIVE:
                self.resolve(aid)

    def _enqueue(self, alert: Alert, target_channels: list[str] | None) -> None:
        with self._q_lock:
            # Dedup by group key if an active one exists
            for a in self.active.values():
                if a.group_key == alert.group_key and a.status in (AlertStatus.ACTIVE, AlertStatus.ACKNOWLEDGED):
                    return
            self.active[alert.id] = alert
            if target_channels:
                alert.details.setdefault("target_channels", target_channels)
            self._queue.append(alert)
            self._persist()

    def _loop(self) -> None:  # pragma: no cover - background thread
        while not self._stop.is_set():
            try:
                self._drain_once()
            except Exception as e:
                logger.debug("Alert loop error: %s", e)
                try:
                    from src.error_handling import handle_ui_error
                    handle_ui_error(e, component="alerts.loop", context={"op": "drain_once"})
                except Exception:
                    pass
            time.sleep(1)

    def _drain_once(self) -> None:
        batch: list[Alert] = []
        with self._q_lock:
            if not self._queue:
                return
            batch = self._queue[:10]
            self._queue = self._queue[10:]
        for a in batch:
            self._deliver(a)

    def _deliver(self, alert: Alert) -> None:
        targets: list[AlertChannel]
        tgt_names = alert.details.get("target_channels")
        if tgt_names:
            targets = [self.channels[n] for n in tgt_names if n in self.channels]
        else:
            targets = list(self.channels.values())
        ok_any = False
        for ch in targets:
            try:
                if not ch.enabled:
                    continue
                ok = ch.send(alert)
                ok_any = ok_any or ok
            except Exception as _e:
                try:
                    from src.error_handling import handle_ui_error
                    handle_ui_error(_e, component="alerts.deliver", context={"channel": getattr(ch, 'name', None)})
                except Exception:
                    pass
        # Always record to history after attempt
        self.history.append(alert)
        if len(self.history) > 1000:
            self.history = self.history[-1000:]
        # Persist occasionally
        self._persist()

    def _persist(self) -> None:
        if not self.state_dir:
            return
        try:
            with open(os.path.join(self.state_dir, "active_alerts.json"), "w", encoding="utf-8") as f:
                json.dump({k: v.to_dict() for k, v in self.active.items()}, f, indent=2)
            with open(os.path.join(self.state_dir, "history.json"), "w", encoding="utf-8") as f:
                json.dump([a.to_dict() for a in self.history[-200:]], f, indent=2)
        except Exception as _e:
            try:
                from src.error_handling import handle_ui_error
                handle_ui_error(_e, component="alerts.persist", context={"dir": self.state_dir})
            except Exception:
                pass


__all__ = [
    "AlertManager",
    "AlertPolicy",
    "Alert",
    "AlertChannel",
    "EmailChannel",
    "WebhookChannel",
    "AlertSeverity",
    "AlertStatus",
]
