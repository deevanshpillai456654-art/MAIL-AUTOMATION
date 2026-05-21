# Enterprise Operations Hardening Report

Generated: 2026-05-21T17:07:08.484266+00:00

## Enterprise Scalability

```json
{
  "event_driven_architecture": true,
  "queue_isolation": {
    "dead_letter_queues": true,
    "duplicate_prevention": true,
    "leases": true,
    "overflow_visibility": true,
    "retry_limits": true
  },
  "runtime_profile": "standard",
  "service_boundaries": "runtime policy separates core, agents, connectors, AI, operations, and observability"
}
```

## Deployment Architecture

```json
{
  "blockers": [],
  "environment": "local",
  "production_readiness": {
    "blockers": [
      "saas_queue_backend",
      "signed_update_validation",
      "external_observability",
      "backup_target"
    ],
    "gates": {
      "async_high_volume_sync": {
        "detail": "Async provider transport is available for Gmail/Outlook high-volume workers.",
        "ready": true
      },
      "backup_target": {
        "detail": "Configure BACKUP_PATH, BACKUP_BUCKET, or DATABASE_BACKUP_URL.",
        "ready": false
      },
      "external_observability": {
        "detail": "Configure OTEL_EXPORTER_OTLP_ENDPOINT, SENTRY_DSN, or PROMETHEUS_ENABLED.",
        "ready": false
      },
      "saas_queue_backend": {
        "detail": "Use local durable queue only for desktop/SMB deployments.",
        "ready": false
      },
      "signed_update_validation": {
        "detail": "AIO_UPDATE_SIGNING_KEY or UPDATE_SIGNING_KEY is required for production releases.",
        "ready": false
      }
    },
    "status": "action_required"
  },
  "queue_backend": {
    "backend": "local",
    "blockers": [],
    "capabilities": {
      "dead_letter_queues": true,
      "duplicate_prevention": true,
      "local_sqlite_durable": true,
      "overflow_protection": true,
      "postgres_skip_locked": false,
      "redis_streams": false,
      "stale_lease_recovery": true
    },
    "database_url_configured": false,
    "external_queue_ready": false,
    "local_queue_ready": true,
    "redis_url_configured": false,
    "saas_recommendation": "postgres SKIP LOCKED or Redis Streams",
    "warnings": [
      "local durable queue is suitable for desktop/SMB, not multi-instance SaaS fan-out"
    ]
  },
  "startup_validation": {
    "data_dir": "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\data",
    "log_dir": "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\logs",
    "project_root": "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated"
  },
  "status": "ready",
  "targets": {
    "offline": {
      "status": "ready"
    },
    "saas": {
      "status": "warning"
    },
    "self_hosted": {
      "status": "ready"
    },
    "shared_office": {
      "requires": [
        "local auth token",
        "loopback bind"
      ],
      "status": "ready"
    },
    "smb_office": {
      "mode": "local_first_shared_office",
      "status": "ready"
    },
    "windows_11": {
      "status": "ready"
    }
  },
  "warnings": []
}
```

## Service Management

```json
{
  "controls": {
    "dependency_validation": true,
    "resource_limits": true,
    "restart_controls": true,
    "restart_protection": true,
    "supports_auto_start": true,
    "supports_enable_disable": true
  },
  "overrides": {},
  "services": {
    "agents": {
      "auto_start": true,
      "category": "agents",
      "enabled": true,
      "failure_count": 0,
      "heavy": true,
      "id": "agents",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Agent Supervisor",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "ai_assistant": {
      "auto_start": false,
      "category": "ai",
      "enabled": true,
      "failure_count": 0,
      "heavy": true,
      "id": "ai_assistant",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "AI Assistant",
      "operator_auto_start": false,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "ai_enterprise": {
      "auto_start": false,
      "category": "ai",
      "enabled": true,
      "failure_count": 0,
      "heavy": true,
      "id": "ai_enterprise",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "AI Enterprise",
      "operator_auto_start": false,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "ai_gateway": {
      "auto_start": true,
      "category": "ai",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "ai_gateway",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "AI Gateway",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "alert_rules": {
      "auto_start": true,
      "category": "security",
      "enabled": true,
      "failure_count": 0,
      "heavy": true,
      "id": "alert_rules",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Alert Rules",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "asset_management": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "asset_management",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Asset Management",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "audit_log": {
      "auto_start": true,
      "category": "security",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "audit_log",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Audit Log",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "budget_tracking": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "budget_tracking",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Budget Tracking",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "capacity_planning": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "capacity_planning",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Capacity Planning",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "certificate_management": {
      "auto_start": true,
      "category": "security",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "certificate_management",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Certificate Management",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "change_management": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "change_management",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Change Management",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "config_management": {
      "auto_start": true,
      "category": "core",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "config_management",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Config Management",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "deployments": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "deployments",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Deployments",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "enterprise_operations": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "enterprise_operations",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Enterprise Operations",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "enterprise_system": {
      "auto_start": true,
      "category": "core",
      "enabled": true,
      "failure_count": 0,
      "heavy": true,
      "id": "enterprise_system",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Enterprise System",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "event_bus": {
      "auto_start": true,
      "category": "core",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "event_bus",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Event Bus",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "feature_flags": {
      "auto_start": true,
      "category": "core",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "feature_flags",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Feature Flags",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "human_approval": {
      "auto_start": true,
      "category": "workflow",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "human_approval",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Human Approval",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "incidents": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "incidents",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Incident Manager",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "job_runner": {
      "auto_start": true,
      "category": "core",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "job_runner",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Async Job Runner",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "knowledge_base": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "knowledge_base",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Knowledge Base",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "license_management": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "license_management",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "License Management",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "maintenance": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "maintenance",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "System Updates",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "metric_snapshots": {
      "auto_start": true,
      "category": "observability",
      "enabled": true,
      "failure_count": 0,
      "heavy": true,
      "id": "metric_snapshots",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Metric Snapshots",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "notifications": {
      "auto_start": true,
      "category": "notifications",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "notifications",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Notification Center",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "ocr": {
      "auto_start": false,
      "category": "ai",
      "enabled": true,
      "failure_count": 0,
      "heavy": true,
      "id": "ocr",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Document Intelligence",
      "operator_auto_start": false,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "oncall": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "oncall",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Team Availability",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "playbooks": {
      "auto_start": true,
      "category": "workflow",
      "enabled": true,
      "failure_count": 0,
      "heavy": true,
      "id": "playbooks",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "AI Actions",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "problem_management": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "problem_management",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Problem Management",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "reconciler": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": true,
      "id": "reconciler",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Operational Reconciler",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "risk_register": {
      "auto_start": true,
      "category": "security",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "risk_register",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Risk Register",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "runbooks": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "runbooks",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Runbooks",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "scheduled_reports": {
      "auto_start": true,
      "category": "reports",
      "enabled": true,
      "failure_count": 0,
      "heavy": true,
      "id": "scheduled_reports",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Scheduled Reports",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "service_catalog": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "service_catalog",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Service Catalog",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "sla": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "sla",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Service Goals",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "slo_management": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "slo_management",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "SLO Management",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "system_scheduler": {
      "auto_start": true,
      "category": "core",
      "enabled": true,
      "failure_count": 0,
      "heavy": true,
      "id": "system_scheduler",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "System Scheduler",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "telemetry": {
      "auto_start": false,
      "category": "observability",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "telemetry",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Platform Telemetry",
      "operator_auto_start": false,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "threat_intelligence": {
      "auto_start": false,
      "category": "security",
      "enabled": true,
      "failure_count": 0,
      "heavy": true,
      "id": "threat_intelligence",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Security Insights",
      "operator_auto_start": false,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "vendor_management": {
      "auto_start": true,
      "category": "operations",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "vendor_management",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Vendor Management",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "webhooks": {
      "auto_start": true,
      "category": "connectors",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "webhooks",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Webhook Dispatcher",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    },
    "workflow_scheduler": {
      "auto_start": true,
      "category": "workflow",
      "enabled": true,
      "failure_count": 0,
      "heavy": false,
      "id": "workflow_scheduler",
      "limits": {
        "poll_interval_seconds": 5,
        "queue_limit": 500,
        "worker_limit": 2
      },
      "name": "Workflow Scheduler",
      "operator_auto_start": true,
      "operator_enabled": true,
      "restart_allowed": true,
      "restart_block_reason": null
    }
  }
}
```

## Queue Optimization

```json
{
  "backend": {
    "backend": "local",
    "blockers": [],
    "capabilities": {
      "dead_letter_queues": true,
      "duplicate_prevention": true,
      "local_sqlite_durable": true,
      "overflow_protection": true,
      "postgres_skip_locked": false,
      "redis_streams": false,
      "stale_lease_recovery": true
    },
    "database_url_configured": false,
    "external_queue_ready": false,
    "local_queue_ready": true,
    "redis_url_configured": false,
    "saas_recommendation": "postgres SKIP LOCKED or Redis Streams",
    "warnings": [
      "local durable queue is suitable for desktop/SMB, not multi-instance SaaS fan-out"
    ]
  },
  "protections": {
    "dead_letter_queues": true,
    "duplicate_prevention": true,
    "leases": true,
    "overflow_visibility": true,
    "queue_cleanup": true,
    "retry_limits": true,
    "retry_protection": true,
    "worker_starvation_visibility": true
  },
  "queues": {},
  "recommendations": [
    "Queue state is within operating limits."
  ],
  "risk": "healthy",
  "stale_leases": 0,
  "totals": {}
}
```

## Connector Hardening

```json
{
  "api_degradation_handling": true,
  "connectors": {
    "connectors": {
      "aftership": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "aftership",
        "isolated": true,
        "manifest_present": false,
        "name": "aftership",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.aftership",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\shipping\\aftership\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "approval_first_automation": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "approval_first_automation",
        "isolated": true,
        "manifest_present": true,
        "name": "Approval First Automation",
        "permissions": [
          "approvals.decide",
          "approvals.view"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.approval_first_automation",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\plugins\\approvals\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "delhivery": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "delhivery",
        "isolated": true,
        "manifest_present": false,
        "name": "delhivery",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.delhivery",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\shipping\\delhivery\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "dhl": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "dhl",
        "isolated": true,
        "manifest_present": false,
        "name": "dhl",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.dhl",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\shipping\\dhl\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "email_whatsapp_unified_communication": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "email_whatsapp_unified_communication",
        "isolated": true,
        "manifest_present": true,
        "name": "Email + WhatsApp Unified Communication",
        "permissions": [
          "communication.view"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.email_whatsapp_unified_communication",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\plugins\\communication\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "erp_crm_tracking_connector_sdk_adapters": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "erp_crm_tracking_connector_sdk_adapters",
        "isolated": true,
        "manifest_present": true,
        "name": "ERP/CRM/Tracking Connector SDK Adapters",
        "permissions": [
          "connectors.run",
          "connectors.view"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.erp_crm_tracking_connector_sdk_adapters",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\plugins\\connectors\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "erpnext": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "enterprise_required": true,
        "id": "erpnext",
        "isolated": true,
        "manifest_present": false,
        "name": "erpnext",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.erpnext",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\erpnext\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "fedex": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "fedex",
        "isolated": true,
        "manifest_present": false,
        "name": "fedex",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.fedex",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\shipping\\fedex\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "gmail": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "enterprise_required": true,
        "id": "gmail",
        "isolated": true,
        "manifest_present": false,
        "name": "gmail",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.gmail",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\gmail\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "gmail_connector": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "gmail_connector",
        "isolated": true,
        "manifest_present": true,
        "name": "gmail_connector",
        "permissions": [
          "contacts.read",
          "gmail.modify",
          "gmail.read",
          "gmail.send"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.gmail_connector",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\plugins\\gmail\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "hubspot": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "hubspot",
        "isolated": true,
        "manifest_present": false,
        "name": "hubspot",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.hubspot",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\hubspot\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "local_whatsapp_operations_engine": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "local_whatsapp_operations_engine",
        "isolated": true,
        "manifest_present": true,
        "name": "Local WhatsApp Operations Engine",
        "permissions": [
          "whatsapp.ops.send",
          "whatsapp.ops.view"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.local_whatsapp_operations_engine",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\plugins\\whatsapp_ops\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "ocr_document_intelligence": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "ocr_document_intelligence",
        "isolated": true,
        "manifest_present": true,
        "name": "OCR Document Intelligence",
        "permissions": [
          "ocr.review",
          "ocr.view"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.ocr_document_intelligence",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\plugins\\ocr\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "ocr_engine_connector": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "ocr_engine_connector",
        "isolated": true,
        "manifest_present": true,
        "name": "ocr_engine_connector",
        "permissions": [
          "documents.process",
          "documents.read",
          "invoices.read",
          "ocr.results.write"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.ocr_engine_connector",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\plugins\\ocr_engine\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "odoo": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "odoo",
        "isolated": true,
        "manifest_present": false,
        "name": "odoo",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.odoo",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\odoo\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "openai_connector": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "openai_connector",
        "isolated": true,
        "manifest_present": true,
        "name": "openai_connector",
        "permissions": [
          "ai.chat",
          "ai.classify",
          "ai.embed",
          "ai.extract"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.openai_connector",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\plugins\\openai\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "operational_search_and_indexing": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "operational_search_and_indexing",
        "isolated": true,
        "manifest_present": true,
        "name": "Operational Search and Indexing",
        "permissions": [
          "search.view"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.operational_search_and_indexing",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\plugins\\search\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "quickbooks": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "quickbooks",
        "isolated": true,
        "manifest_present": false,
        "name": "quickbooks",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.quickbooks",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\quickbooks\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "salesforce": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "salesforce",
        "isolated": true,
        "manifest_present": false,
        "name": "salesforce",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.salesforce",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\salesforce\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "sap": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "enterprise_required": true,
        "id": "sap",
        "isolated": true,
        "manifest_present": false,
        "name": "sap",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.sap",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\sap\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "shiprocket": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "shiprocket",
        "isolated": true,
        "manifest_present": false,
        "name": "shiprocket",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.shiprocket",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\shipping\\shiprocket\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "shopify": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "shopify",
        "isolated": true,
        "manifest_present": false,
        "name": "shopify",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.shopify",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\shopify\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "shopify_connector": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "shopify_connector",
        "isolated": true,
        "manifest_present": true,
        "name": "shopify_connector",
        "permissions": [
          "customers.read",
          "inventory.read",
          "orders.read",
          "orders.write",
          "products.read"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.shopify_connector",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\plugins\\shopify\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "slack_connector": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "slack_connector",
        "isolated": true,
        "manifest_present": true,
        "name": "slack_connector",
        "permissions": [
          "slack.channels.read",
          "slack.message.send",
          "slack.users.read"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.slack_connector",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\plugins\\slack\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "slack_enterprise": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "enterprise_required": true,
        "id": "slack_enterprise",
        "isolated": true,
        "manifest_present": false,
        "name": "slack_enterprise",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.slack_enterprise",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\slack_enterprise\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "tally_connector": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "tally_connector",
        "isolated": true,
        "manifest_present": true,
        "name": "tally_connector",
        "permissions": [
          "tally.analytics.read",
          "tally.audit.read",
          "tally.companies.read",
          "tally.connect",
          "tally.gst.read",
          "tally.inventory.read",
          "tally.ledgers.write",
          "tally.vouchers.write"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.tally_connector",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\plugins\\tally\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "teams": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "teams",
        "isolated": true,
        "manifest_present": false,
        "name": "teams",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.teams",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\teams\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "tracking_aggregation_and_event_normalization": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "tracking_aggregation_and_event_normalization",
        "isolated": true,
        "manifest_present": true,
        "name": "Tracking Aggregation and Event Normalization",
        "permissions": [
          "tracking.ingest",
          "tracking.view"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.tracking_aggregation_and_event_normalization",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\plugins\\tracking\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "unified_shipment_workspace": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "unified_shipment_workspace",
        "isolated": true,
        "manifest_present": true,
        "name": "Unified Shipment Workspace",
        "permissions": [
          "workspace.view"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.unified_shipment_workspace",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\plugins\\workspace\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "ups": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "ups",
        "isolated": true,
        "manifest_present": false,
        "name": "ups",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.ups",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\shipping\\ups\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "webhook_listener": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "webhook_listener",
        "isolated": true,
        "manifest_present": true,
        "name": "webhook_listener",
        "permissions": [
          "events.publish",
          "webhooks.receive"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.webhook_listener",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\plugins\\webhook_listener\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "whatsapp": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "enterprise_required": true,
        "id": "whatsapp",
        "isolated": true,
        "manifest_present": false,
        "name": "whatsapp",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.whatsapp",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\whatsapp\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "whatsapp_connector": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "whatsapp_connector",
        "isolated": true,
        "manifest_present": true,
        "name": "whatsapp_connector",
        "permissions": [
          "contacts.read",
          "messages.read",
          "messages.send"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.whatsapp_connector",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\plugins\\whatsapp\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "xero": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "xero",
        "isolated": true,
        "manifest_present": false,
        "name": "xero",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.xero",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\xero\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "zoho_crm": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "enterprise_required": true,
        "id": "zoho_crm",
        "isolated": true,
        "manifest_present": false,
        "name": "zoho_crm",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.zoho_crm",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\zoho_crm\\connector.py"
        ],
        "token_refresh_handling": true
      }
    },
    "count": 35,
    "isolation": {
      "credential_scope_per_connector": true,
      "failure_containment": true,
      "queue_per_connector": true,
      "sandboxed_execution": true
    },
    "protections": {
      "api_degradation_handling": true,
      "credential_verification": true,
      "rate_limiting": true,
      "retry_protection": true,
      "token_refresh_handling": true
    },
    "required_connectors": {
      "erp": {
        "api_degradation_handling": true,
        "credential_verification": true,
        "isolated": true,
        "matched_connectors": [
          "erpnext",
          "odoo",
          "sap"
        ],
        "present": true,
        "queue_isolated": true,
        "rate_limited": true,
        "retry_protected": true
      },
      "gmail": {
        "api_degradation_handling": true,
        "credential_verification": true,
        "isolated": true,
        "matched_connectors": [
          "gmail",
          "gmail_connector"
        ],
        "present": true,
        "queue_isolated": true,
        "rate_limited": true,
        "retry_protected": true
      },
      "outlook": {
        "api_degradation_handling": false,
        "credential_verification": false,
        "isolated": false,
        "matched_connectors": [],
        "present": false,
        "queue_isolated": false,
        "rate_limited": false,
        "retry_protected": false
      },
      "sap": {
        "api_degradation_handling": true,
        "credential_verification": true,
        "isolated": true,
        "matched_connectors": [
          "sap"
        ],
        "present": true,
        "queue_isolated": true,
        "rate_limited": true,
        "retry_protected": true
      },
      "slack": {
        "api_degradation_handling": true,
        "credential_verification": true,
        "isolated": true,
        "matched_connectors": [
          "slack_connector",
          "slack_enterprise"
        ],
        "present": true,
        "queue_isolated": true,
        "rate_limited": true,
        "retry_protected": true
      },
      "tally": {
        "api_degradation_handling": true,
        "credential_verification": true,
        "isolated": true,
        "matched_connectors": [
          "tally_connector"
        ],
        "present": true,
        "queue_isolated": true,
        "rate_limited": true,
        "retry_protected": true
      },
      "whatsapp": {
        "api_degradation_handling": true,
        "credential_verification": true,
        "isolated": true,
        "matched_connectors": [
          "whatsapp",
          "whatsapp_connector"
        ],
        "present": true,
        "queue_isolated": true,
        "rate_limited": true,
        "retry_protected": true
      },
      "zoho": {
        "api_degradation_handling": true,
        "credential_verification": true,
        "isolated": true,
        "matched_connectors": [
          "zoho_crm"
        ],
        "present": true,
        "queue_isolated": true,
        "rate_limited": true,
        "retry_protected": true
      }
    }
  },
  "sandboxing": true,
  "token_refresh_handling": true
}
```

## Agent Runtime Optimization

```json
{
  "agents": {
    "ai_reply": {
      "auto_start": true,
      "enabled": true,
      "id": "ai_reply",
      "limits": {
        "api_daily_limit": 1000,
        "cpu_limit_percent": 20,
        "memory_limit_mb": 128,
        "queue_limit": 500,
        "retry_limit": 3
      },
      "name": "AI Reply Agent",
      "priority": 90,
      "service_id": "agents"
    },
    "attachment": {
      "auto_start": true,
      "enabled": true,
      "id": "attachment",
      "limits": {
        "api_daily_limit": 1000,
        "cpu_limit_percent": 20,
        "memory_limit_mb": 128,
        "queue_limit": 500,
        "retry_limit": 3
      },
      "name": "Attachment Agent",
      "priority": 100,
      "service_id": "agents"
    },
    "connector": {
      "auto_start": true,
      "enabled": true,
      "id": "connector",
      "limits": {
        "api_daily_limit": 1000,
        "cpu_limit_percent": 20,
        "memory_limit_mb": 128,
        "queue_limit": 500,
        "retry_limit": 3
      },
      "name": "Connector Agent",
      "priority": 20,
      "service_id": "agents"
    },
    "document_intelligence": {
      "auto_start": true,
      "enabled": true,
      "id": "document_intelligence",
      "limits": {
        "api_daily_limit": 1000,
        "cpu_limit_percent": 20,
        "memory_limit_mb": 128,
        "queue_limit": 500,
        "retry_limit": 3
      },
      "name": "Document Intelligence Agent",
      "priority": 70,
      "service_id": "agents"
    },
    "finance_monitor": {
      "auto_start": true,
      "enabled": true,
      "id": "finance_monitor",
      "limits": {
        "api_daily_limit": 1000,
        "cpu_limit_percent": 20,
        "memory_limit_mb": 128,
        "queue_limit": 500,
        "retry_limit": 3
      },
      "name": "Finance Monitor",
      "priority": 85,
      "service_id": "agents"
    },
    "human_approval": {
      "auto_start": true,
      "enabled": true,
      "id": "human_approval",
      "limits": {
        "api_daily_limit": 1000,
        "cpu_limit_percent": 20,
        "memory_limit_mb": 128,
        "queue_limit": 500,
        "retry_limit": 3
      },
      "name": "Human Approval Agent",
      "priority": 30,
      "service_id": "agents"
    },
    "inbox_monitor": {
      "auto_start": true,
      "enabled": true,
      "id": "inbox_monitor",
      "limits": {
        "api_daily_limit": 1000,
        "cpu_limit_percent": 20,
        "memory_limit_mb": 128,
        "queue_limit": 500,
        "retry_limit": 3
      },
      "name": "Inbox Monitor",
      "priority": 80,
      "service_id": "agents"
    },
    "inbox_triage": {
      "auto_start": true,
      "enabled": true,
      "id": "inbox_triage",
      "limits": {
        "api_daily_limit": 1000,
        "cpu_limit_percent": 20,
        "memory_limit_mb": 128,
        "queue_limit": 500,
        "retry_limit": 3
      },
      "name": "Inbox Triage Agent",
      "priority": 80,
      "service_id": "agents"
    },
    "notification": {
      "auto_start": true,
      "enabled": true,
      "id": "notification",
      "limits": {
        "api_daily_limit": 1000,
        "cpu_limit_percent": 20,
        "memory_limit_mb": 128,
        "queue_limit": 500,
        "retry_limit": 3
      },
      "name": "Notification Agent",
      "priority": 40,
      "service_id": "agents"
    },
    "performance_analyst": {
      "auto_start": true,
      "enabled": true,
      "id": "performance_analyst",
      "limits": {
        "api_daily_limit": 1000,
        "cpu_limit_percent": 20,
        "memory_limit_mb": 128,
        "queue_limit": 500,
        "retry_limit": 3
      },
      "name": "Performance Analyst",
      "priority": 120,
      "service_id": "agents"
    },
    "search_memory": {
      "auto_start": true,
      "enabled": true,
      "id": "search_memory",
      "limits": {
        "api_daily_limit": 1000,
        "cpu_limit_percent": 20,
        "memory_limit_mb": 128,
        "queue_limit": 500,
        "retry_limit": 3
      },
      "name": "Search & Memory Agent",
      "priority": 50,
      "service_id": "agents"
    },
    "security_posture": {
      "auto_start": true,
      "enabled": true,
      "id": "security_posture",
      "limits": {
        "api_daily_limit": 1000,
        "cpu_limit_percent": 20,
        "memory_limit_mb": 128,
        "queue_limit": 500,
        "retry_limit": 3
      },
      "name": "Security Posture Agent",
      "priority": 65,
      "service_id": "agents"
    },
    "security_threat": {
      "auto_start": true,
      "enabled": true,
      "id": "security_threat",
      "limits": {
        "api_daily_limit": 1000,
        "cpu_limit_percent": 20,
        "memory_limit_mb": 128,
        "queue_limit": 500,
        "retry_limit": 3
      },
      "name": "Security & Threat Agent",
      "priority": 60,
      "service_id": "agents"
    },
    "threat_watch": {
      "auto_start": true,
      "enabled": true,
      "id": "threat_watch",
      "limits": {
        "api_daily_limit": 1000,
        "cpu_limit_percent": 20,
        "memory_limit_mb": 128,
        "queue_limit": 500,
        "retry_limit": 3
      },
      "name": "Threat Watch",
      "priority": 60,
      "service_id": "agents"
    },
    "workflow_automation": {
      "auto_start": true,
      "enabled": true,
      "id": "workflow_automation",
      "limits": {
        "api_daily_limit": 1000,
        "cpu_limit_percent": 20,
        "memory_limit_mb": 128,
        "queue_limit": 500,
        "retry_limit": 3
      },
      "name": "Workflow Automation Agent",
      "priority": 110,
      "service_id": "agents"
    },
    "workflow_orchestrator": {
      "auto_start": true,
      "enabled": true,
      "id": "workflow_orchestrator",
      "limits": {
        "api_daily_limit": 1000,
        "cpu_limit_percent": 20,
        "memory_limit_mb": 128,
        "queue_limit": 500,
        "retry_limit": 3
      },
      "name": "Workflow Orchestrator Agent",
      "priority": 10,
      "service_id": "agents"
    }
  },
  "autostart_count": 16,
  "dependency_management": true,
  "disabled_agents_unloaded": true,
  "disabled_count": 0,
  "enabled_count": 16,
  "failure_recovery": true,
  "idle_resource_policy": "disabled_agents_do_not_autostart",
  "limits": {
    "api_daily_limits": true,
    "max_agent_cpu_percent": 20,
    "max_agent_memory_mb": 128,
    "queue_limits": true,
    "retry_limits": true
  },
  "low_resource": false,
  "profile": "standard",
  "resource_cleanup": true,
  "restart_safety": true,
  "runtime_isolation": true,
  "shutdown_cleanup": true,
  "shutdown_lifecycle": "disable_prevents_autostart_and_allows_full_unload",
  "startup_lifecycle": "policy_validated_before_autostart",
  "total_count": 16,
  "zombie_process_prevention": true
}
```

## Memory Optimization

```json
{
  "cache_size_bytes": 2791,
  "cleanup_jobs": true,
  "low_resource_mode": false,
  "smart_unloading": true
}
```

## Cpu Optimization

```json
{
  "adaptive_polling": true,
  "async_provider_transport": {
    "async_transport_available": true,
    "high_volume_providers": {
      "gmail": {
        "async_client_ready": true,
        "idle_resource_overhead": "near_zero_until_used",
        "module_present": true,
        "pooled_http": true,
        "retry_protection": true,
        "timeout_protection": true
      },
      "imap": {
        "async_client_ready": true,
        "idle_resource_overhead": "near_zero_until_used",
        "module_present": true,
        "pooled_http": true,
        "retry_protection": true,
        "timeout_protection": true
      },
      "outlook": {
        "async_client_ready": true,
        "idle_resource_overhead": "near_zero_until_used",
        "module_present": true,
        "pooled_http": true,
        "retry_protection": true,
        "timeout_protection": true
      }
    },
    "recommendation": "Use async provider transport for SaaS/high-volume sync workers; desktop low-resource mode can keep synchronous single-worker sync.",
    "shared_http_pool": true,
    "sync_compatibility_preserved": true
  },
  "background_throttling": false,
  "deferred_processing": true
}
```

## Observability Implementation

```json
{
  "agent_monitoring": {
    "agents": {
      "ai_reply": {
        "auto_start": true,
        "enabled": true,
        "id": "ai_reply",
        "limits": {
          "api_daily_limit": 1000,
          "cpu_limit_percent": 20,
          "memory_limit_mb": 128,
          "queue_limit": 500,
          "retry_limit": 3
        },
        "name": "AI Reply Agent",
        "priority": 90,
        "service_id": "agents"
      },
      "attachment": {
        "auto_start": true,
        "enabled": true,
        "id": "attachment",
        "limits": {
          "api_daily_limit": 1000,
          "cpu_limit_percent": 20,
          "memory_limit_mb": 128,
          "queue_limit": 500,
          "retry_limit": 3
        },
        "name": "Attachment Agent",
        "priority": 100,
        "service_id": "agents"
      },
      "connector": {
        "auto_start": true,
        "enabled": true,
        "id": "connector",
        "limits": {
          "api_daily_limit": 1000,
          "cpu_limit_percent": 20,
          "memory_limit_mb": 128,
          "queue_limit": 500,
          "retry_limit": 3
        },
        "name": "Connector Agent",
        "priority": 20,
        "service_id": "agents"
      },
      "document_intelligence": {
        "auto_start": true,
        "enabled": true,
        "id": "document_intelligence",
        "limits": {
          "api_daily_limit": 1000,
          "cpu_limit_percent": 20,
          "memory_limit_mb": 128,
          "queue_limit": 500,
          "retry_limit": 3
        },
        "name": "Document Intelligence Agent",
        "priority": 70,
        "service_id": "agents"
      },
      "finance_monitor": {
        "auto_start": true,
        "enabled": true,
        "id": "finance_monitor",
        "limits": {
          "api_daily_limit": 1000,
          "cpu_limit_percent": 20,
          "memory_limit_mb": 128,
          "queue_limit": 500,
          "retry_limit": 3
        },
        "name": "Finance Monitor",
        "priority": 85,
        "service_id": "agents"
      },
      "human_approval": {
        "auto_start": true,
        "enabled": true,
        "id": "human_approval",
        "limits": {
          "api_daily_limit": 1000,
          "cpu_limit_percent": 20,
          "memory_limit_mb": 128,
          "queue_limit": 500,
          "retry_limit": 3
        },
        "name": "Human Approval Agent",
        "priority": 30,
        "service_id": "agents"
      },
      "inbox_monitor": {
        "auto_start": true,
        "enabled": true,
        "id": "inbox_monitor",
        "limits": {
          "api_daily_limit": 1000,
          "cpu_limit_percent": 20,
          "memory_limit_mb": 128,
          "queue_limit": 500,
          "retry_limit": 3
        },
        "name": "Inbox Monitor",
        "priority": 80,
        "service_id": "agents"
      },
      "inbox_triage": {
        "auto_start": true,
        "enabled": true,
        "id": "inbox_triage",
        "limits": {
          "api_daily_limit": 1000,
          "cpu_limit_percent": 20,
          "memory_limit_mb": 128,
          "queue_limit": 500,
          "retry_limit": 3
        },
        "name": "Inbox Triage Agent",
        "priority": 80,
        "service_id": "agents"
      },
      "notification": {
        "auto_start": true,
        "enabled": true,
        "id": "notification",
        "limits": {
          "api_daily_limit": 1000,
          "cpu_limit_percent": 20,
          "memory_limit_mb": 128,
          "queue_limit": 500,
          "retry_limit": 3
        },
        "name": "Notification Agent",
        "priority": 40,
        "service_id": "agents"
      },
      "performance_analyst": {
        "auto_start": true,
        "enabled": true,
        "id": "performance_analyst",
        "limits": {
          "api_daily_limit": 1000,
          "cpu_limit_percent": 20,
          "memory_limit_mb": 128,
          "queue_limit": 500,
          "retry_limit": 3
        },
        "name": "Performance Analyst",
        "priority": 120,
        "service_id": "agents"
      },
      "search_memory": {
        "auto_start": true,
        "enabled": true,
        "id": "search_memory",
        "limits": {
          "api_daily_limit": 1000,
          "cpu_limit_percent": 20,
          "memory_limit_mb": 128,
          "queue_limit": 500,
          "retry_limit": 3
        },
        "name": "Search & Memory Agent",
        "priority": 50,
        "service_id": "agents"
      },
      "security_posture": {
        "auto_start": true,
        "enabled": true,
        "id": "security_posture",
        "limits": {
          "api_daily_limit": 1000,
          "cpu_limit_percent": 20,
          "memory_limit_mb": 128,
          "queue_limit": 500,
          "retry_limit": 3
        },
        "name": "Security Posture Agent",
        "priority": 65,
        "service_id": "agents"
      },
      "security_threat": {
        "auto_start": true,
        "enabled": true,
        "id": "security_threat",
        "limits": {
          "api_daily_limit": 1000,
          "cpu_limit_percent": 20,
          "memory_limit_mb": 128,
          "queue_limit": 500,
          "retry_limit": 3
        },
        "name": "Security & Threat Agent",
        "priority": 60,
        "service_id": "agents"
      },
      "threat_watch": {
        "auto_start": true,
        "enabled": true,
        "id": "threat_watch",
        "limits": {
          "api_daily_limit": 1000,
          "cpu_limit_percent": 20,
          "memory_limit_mb": 128,
          "queue_limit": 500,
          "retry_limit": 3
        },
        "name": "Threat Watch",
        "priority": 60,
        "service_id": "agents"
      },
      "workflow_automation": {
        "auto_start": true,
        "enabled": true,
        "id": "workflow_automation",
        "limits": {
          "api_daily_limit": 1000,
          "cpu_limit_percent": 20,
          "memory_limit_mb": 128,
          "queue_limit": 500,
          "retry_limit": 3
        },
        "name": "Workflow Automation Agent",
        "priority": 110,
        "service_id": "agents"
      },
      "workflow_orchestrator": {
        "auto_start": true,
        "enabled": true,
        "id": "workflow_orchestrator",
        "limits": {
          "api_daily_limit": 1000,
          "cpu_limit_percent": 20,
          "memory_limit_mb": 128,
          "queue_limit": 500,
          "retry_limit": 3
        },
        "name": "Workflow Orchestrator Agent",
        "priority": 10,
        "service_id": "agents"
      }
    },
    "autostart_count": 16,
    "dependency_management": true,
    "disabled_agents_unloaded": true,
    "disabled_count": 0,
    "enabled_count": 16,
    "failure_recovery": true,
    "idle_resource_policy": "disabled_agents_do_not_autostart",
    "limits": {
      "api_daily_limits": true,
      "max_agent_cpu_percent": 20,
      "max_agent_memory_mb": 128,
      "queue_limits": true,
      "retry_limits": true
    },
    "low_resource": false,
    "profile": "standard",
    "resource_cleanup": true,
    "restart_safety": true,
    "runtime_isolation": true,
    "shutdown_lifecycle": "disable_prevents_autostart_and_allows_full_unload",
    "startup_lifecycle": "policy_validated_before_autostart",
    "total_count": 16,
    "zombie_process_prevention": true
  },
  "audit_logs": {
    "enabled": true,
    "sensitive_data_redaction": true
  },
  "connector_monitoring": {
    "connectors": {
      "aftership": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "aftership",
        "isolated": true,
        "manifest_present": false,
        "name": "aftership",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.aftership",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\shipping\\aftership\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "approval_first_automation": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "approval_first_automation",
        "isolated": true,
        "manifest_present": true,
        "name": "Approval First Automation",
        "permissions": [
          "approvals.decide",
          "approvals.view"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.approval_first_automation",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\plugins\\approvals\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "delhivery": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "delhivery",
        "isolated": true,
        "manifest_present": false,
        "name": "delhivery",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.delhivery",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\shipping\\delhivery\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "dhl": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "dhl",
        "isolated": true,
        "manifest_present": false,
        "name": "dhl",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.dhl",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\shipping\\dhl\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "email_whatsapp_unified_communication": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "email_whatsapp_unified_communication",
        "isolated": true,
        "manifest_present": true,
        "name": "Email + WhatsApp Unified Communication",
        "permissions": [
          "communication.view"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.email_whatsapp_unified_communication",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\plugins\\communication\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "erp_crm_tracking_connector_sdk_adapters": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "erp_crm_tracking_connector_sdk_adapters",
        "isolated": true,
        "manifest_present": true,
        "name": "ERP/CRM/Tracking Connector SDK Adapters",
        "permissions": [
          "connectors.run",
          "connectors.view"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.erp_crm_tracking_connector_sdk_adapters",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\plugins\\connectors\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "erpnext": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "enterprise_required": true,
        "id": "erpnext",
        "isolated": true,
        "manifest_present": false,
        "name": "erpnext",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.erpnext",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\erpnext\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "fedex": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "fedex",
        "isolated": true,
        "manifest_present": false,
        "name": "fedex",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.fedex",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\shipping\\fedex\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "gmail": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "enterprise_required": true,
        "id": "gmail",
        "isolated": true,
        "manifest_present": false,
        "name": "gmail",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.gmail",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\gmail\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "gmail_connector": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "gmail_connector",
        "isolated": true,
        "manifest_present": true,
        "name": "gmail_connector",
        "permissions": [
          "contacts.read",
          "gmail.modify",
          "gmail.read",
          "gmail.send"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.gmail_connector",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\plugins\\gmail\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "hubspot": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "hubspot",
        "isolated": true,
        "manifest_present": false,
        "name": "hubspot",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.hubspot",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\hubspot\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "local_whatsapp_operations_engine": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "local_whatsapp_operations_engine",
        "isolated": true,
        "manifest_present": true,
        "name": "Local WhatsApp Operations Engine",
        "permissions": [
          "whatsapp.ops.send",
          "whatsapp.ops.view"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.local_whatsapp_operations_engine",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\plugins\\whatsapp_ops\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "ocr_document_intelligence": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "ocr_document_intelligence",
        "isolated": true,
        "manifest_present": true,
        "name": "OCR Document Intelligence",
        "permissions": [
          "ocr.review",
          "ocr.view"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.ocr_document_intelligence",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\plugins\\ocr\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "ocr_engine_connector": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "ocr_engine_connector",
        "isolated": true,
        "manifest_present": true,
        "name": "ocr_engine_connector",
        "permissions": [
          "documents.process",
          "documents.read",
          "invoices.read",
          "ocr.results.write"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.ocr_engine_connector",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\plugins\\ocr_engine\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "odoo": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "odoo",
        "isolated": true,
        "manifest_present": false,
        "name": "odoo",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.odoo",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\odoo\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "openai_connector": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "openai_connector",
        "isolated": true,
        "manifest_present": true,
        "name": "openai_connector",
        "permissions": [
          "ai.chat",
          "ai.classify",
          "ai.embed",
          "ai.extract"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.openai_connector",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\plugins\\openai\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "operational_search_and_indexing": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "operational_search_and_indexing",
        "isolated": true,
        "manifest_present": true,
        "name": "Operational Search and Indexing",
        "permissions": [
          "search.view"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.operational_search_and_indexing",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\plugins\\search\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "quickbooks": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "quickbooks",
        "isolated": true,
        "manifest_present": false,
        "name": "quickbooks",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.quickbooks",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\quickbooks\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "salesforce": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "salesforce",
        "isolated": true,
        "manifest_present": false,
        "name": "salesforce",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.salesforce",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\salesforce\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "sap": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "enterprise_required": true,
        "id": "sap",
        "isolated": true,
        "manifest_present": false,
        "name": "sap",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.sap",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\sap\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "shiprocket": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "shiprocket",
        "isolated": true,
        "manifest_present": false,
        "name": "shiprocket",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.shiprocket",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\shipping\\shiprocket\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "shopify": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "shopify",
        "isolated": true,
        "manifest_present": false,
        "name": "shopify",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.shopify",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\shopify\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "shopify_connector": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "shopify_connector",
        "isolated": true,
        "manifest_present": true,
        "name": "shopify_connector",
        "permissions": [
          "customers.read",
          "inventory.read",
          "orders.read",
          "orders.write",
          "products.read"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.shopify_connector",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\plugins\\shopify\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "slack_connector": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "slack_connector",
        "isolated": true,
        "manifest_present": true,
        "name": "slack_connector",
        "permissions": [
          "slack.channels.read",
          "slack.message.send",
          "slack.users.read"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.slack_connector",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\plugins\\slack\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "slack_enterprise": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "enterprise_required": true,
        "id": "slack_enterprise",
        "isolated": true,
        "manifest_present": false,
        "name": "slack_enterprise",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.slack_enterprise",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\slack_enterprise\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "tally_connector": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "tally_connector",
        "isolated": true,
        "manifest_present": true,
        "name": "tally_connector",
        "permissions": [
          "tally.analytics.read",
          "tally.audit.read",
          "tally.companies.read",
          "tally.connect",
          "tally.gst.read",
          "tally.inventory.read",
          "tally.ledgers.write",
          "tally.vouchers.write"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.tally_connector",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\plugins\\tally\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "teams": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "teams",
        "isolated": true,
        "manifest_present": false,
        "name": "teams",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.teams",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\teams\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "tracking_aggregation_and_event_normalization": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "tracking_aggregation_and_event_normalization",
        "isolated": true,
        "manifest_present": true,
        "name": "Tracking Aggregation and Event Normalization",
        "permissions": [
          "tracking.ingest",
          "tracking.view"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.tracking_aggregation_and_event_normalization",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\plugins\\tracking\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "unified_shipment_workspace": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "unified_shipment_workspace",
        "isolated": true,
        "manifest_present": true,
        "name": "Unified Shipment Workspace",
        "permissions": [
          "workspace.view"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.unified_shipment_workspace",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\plugins\\workspace\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "ups": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "ups",
        "isolated": true,
        "manifest_present": false,
        "name": "ups",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.ups",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\shipping\\ups\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "webhook_listener": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "webhook_listener",
        "isolated": true,
        "manifest_present": true,
        "name": "webhook_listener",
        "permissions": [
          "events.publish",
          "webhooks.receive"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.webhook_listener",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\plugins\\webhook_listener\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "whatsapp": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "enterprise_required": true,
        "id": "whatsapp",
        "isolated": true,
        "manifest_present": false,
        "name": "whatsapp",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.whatsapp",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\whatsapp\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "whatsapp_connector": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "whatsapp_connector",
        "isolated": true,
        "manifest_present": true,
        "name": "whatsapp_connector",
        "permissions": [
          "contacts.read",
          "messages.read",
          "messages.send"
        ],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.whatsapp_connector",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\plugins\\whatsapp\\plugin.json"
        ],
        "token_refresh_handling": true
      },
      "xero": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "id": "xero",
        "isolated": true,
        "manifest_present": false,
        "name": "xero",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.xero",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\xero\\connector.py"
        ],
        "token_refresh_handling": true
      },
      "zoho_crm": {
        "credential_values_exposed": false,
        "credential_verification": true,
        "degradation_handling": true,
        "enterprise_required": true,
        "id": "zoho_crm",
        "isolated": true,
        "manifest_present": false,
        "name": "zoho_crm",
        "permissions": [],
        "present": true,
        "queue_isolated": true,
        "queue_name": "connector.zoho_crm",
        "rate_limited": true,
        "retry_protected": true,
        "sandboxed": true,
        "source_paths": [
          "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\platform\\connectors-panel\\connectors\\zoho_crm\\connector.py"
        ],
        "token_refresh_handling": true
      }
    },
    "count": 35,
    "isolation": {
      "credential_scope_per_connector": true,
      "failure_containment": true,
      "queue_per_connector": true,
      "sandboxed_execution": true
    },
    "protections": {
      "api_degradation_handling": true,
      "credential_verification": true,
      "rate_limiting": true,
      "retry_protection": true,
      "token_refresh_handling": true
    },
    "required_connectors": {
      "erp": {
        "api_degradation_handling": true,
        "credential_verification": true,
        "isolated": true,
        "matched_connectors": [
          "erpnext",
          "odoo",
          "sap"
        ],
        "present": true,
        "queue_isolated": true,
        "rate_limited": true,
        "retry_protected": true
      },
      "gmail": {
        "api_degradation_handling": true,
        "credential_verification": true,
        "isolated": true,
        "matched_connectors": [
          "gmail",
          "gmail_connector"
        ],
        "present": true,
        "queue_isolated": true,
        "rate_limited": true,
        "retry_protected": true
      },
      "outlook": {
        "api_degradation_handling": false,
        "credential_verification": false,
        "isolated": false,
        "matched_connectors": [],
        "present": false,
        "queue_isolated": false,
        "rate_limited": false,
        "retry_protected": false
      },
      "sap": {
        "api_degradation_handling": true,
        "credential_verification": true,
        "isolated": true,
        "matched_connectors": [
          "sap"
        ],
        "present": true,
        "queue_isolated": true,
        "rate_limited": true,
        "retry_protected": true
      },
      "slack": {
        "api_degradation_handling": true,
        "credential_verification": true,
        "isolated": true,
        "matched_connectors": [
          "slack_connector",
          "slack_enterprise"
        ],
        "present": true,
        "queue_isolated": true,
        "rate_limited": true,
        "retry_protected": true
      },
      "tally": {
        "api_degradation_handling": true,
        "credential_verification": true,
        "isolated": true,
        "matched_connectors": [
          "tally_connector"
        ],
        "present": true,
        "queue_isolated": true,
        "rate_limited": true,
        "retry_protected": true
      },
      "whatsapp": {
        "api_degradation_handling": true,
        "credential_verification": true,
        "isolated": true,
        "matched_connectors": [
          "whatsapp",
          "whatsapp_connector"
        ],
        "present": true,
        "queue_isolated": true,
        "rate_limited": true,
        "retry_protected": true
      },
      "zoho": {
        "api_degradation_handling": true,
        "credential_verification": true,
        "isolated": true,
        "matched_connectors": [
          "zoho_crm"
        ],
        "present": true,
        "queue_isolated": true,
        "rate_limited": true,
        "retry_protected": true
      }
    }
  },
  "error_tracking": true,
  "health_monitoring": true,
  "metrics_dashboard": true,
  "metrics_export": {
    "endpoint": "/api/v1/enterprise-operations/metrics",
    "external_apm_configured": false,
    "prometheus_text": true,
    "sensitive_labels_redacted": true
  },
  "queue_monitoring": {
    "protections": {
      "dead_letter_queues": true,
      "duplicate_prevention": true,
      "leases": true,
      "overflow_visibility": true,
      "retry_limits": true
    },
    "queues": {},
    "recommendations": [
      "Queue state is within operating limits."
    ],
    "risk": "healthy",
    "stale_leases": 0,
    "totals": {}
  },
  "resource_monitoring": {
    "cpu_percent": 0.0,
    "low_resource_recommendations": [
      "Use low_resource runtime profile on 4GB RAM machines.",
      "Disable heavy AI, OCR, report scheduling, and autonomous agents unless explicitly needed.",
      "Prefer event-driven sync and longer polling intervals on shared office systems."
    ],
    "memory_available_mb": 1684.8,
    "memory_percent": 79.2,
    "memory_total_mb": 8103.3,
    "pressure": {
      "actions": [
        "No resource throttling action required."
      ],
      "cpu_percent": 0.0,
      "level": "normal",
      "memory_available_mb": 1684.77734375,
      "queue_pending": 0,
      "reasons": []
    }
  },
  "runtime_diagnostics": {
    "ai_enabled": true,
    "ai_mode": "cloud",
    "enterprise_mode": false,
    "frontend": {
      "ai_enabled": true,
      "deferred_rendering": false,
      "low_resource": false,
      "minimal_animations": false,
      "offline_mode": false,
      "profile": "standard",
      "virtualize_lists": true
    },
    "limits": {
      "job_concurrency": 4,
      "max_workers": 4,
      "poll_interval_seconds": 3,
      "queue_limit": 2500,
      "sync_interval_seconds": 120
    },
    "low_resource": false,
    "offline_mode": false,
    "profile": "standard"
  },
  "workflow_analytics": true
}
```

## Logging System

```json
{
  "cleanup_recommended": false,
  "log_size_bytes": 301298,
  "redaction_enabled": true,
  "rotation_enabled": true,
  "structured_logging": true
}
```

## Error Recovery

```json
{
  "fallback_modes": [
    "low_resource",
    "offline",
    "lite"
  ],
  "graceful_degradation": true,
  "queue_recovery": true,
  "workflow_recovery": true
}
```

## Low Resource Optimization

```json
{
  "frontend": {
    "ai_enabled": true,
    "deferred_rendering": false,
    "low_resource": false,
    "minimal_animations": false,
    "offline_mode": false,
    "profile": "standard",
    "virtualize_lists": true
  },
  "limits": {
    "job_concurrency": 4,
    "max_workers": 4,
    "poll_interval_seconds": 3,
    "queue_limit": 2500,
    "sync_interval_seconds": 120
  },
  "profile": "standard",
  "recommendations": [
    "Use low_resource runtime profile on 4GB RAM machines.",
    "Disable heavy AI, OCR, report scheduling, and autonomous agents unless explicitly needed.",
    "Prefer event-driven sync and longer polling intervals on shared office systems."
  ]
}
```

## Electron Enterprise Hardening

```json
{
  "context_isolation": true,
  "devtools_restricted": true,
  "main_js_present": true,
  "navigation_allowlist": true,
  "node_integration_disabled": true,
  "sandbox": true,
  "web_security_enabled": true,
  "window_lifecycle": "single main window, external navigation allowlist"
}
```

## Database Hardening

```json
{
  "backend": "sqlite",
  "backup_safety": true,
  "connection_leak_protection": true,
  "exists": true,
  "index_count": 59,
  "integrity_check": "ok",
  "migration_safety": true,
  "path": "C:\\Users\\admin\\AppData\\Local\\AIEmailOrganizer\\data\\emails.db",
  "size_bytes": 2232320,
  "sqlite_wal": "wal",
  "wal_size_bytes": 0
}
```

## Security Hardening

```json
{
  "api_host": "127.0.0.1",
  "attachment_sandboxing": true,
  "credential_redaction": true,
  "local_token_file_present": false,
  "loopback_bound": true,
  "request_auth_required": true,
  "secret_key_count": 7,
  "secret_values_exposed": false,
  "websocket_security": true
}
```

## Production Operations

```json
{
  "deployment_profiles": {
    "offline": {
      "env": {
        "AIO_AI_MODE": "disabled",
        "AIO_OFFLINE_MODE": "1",
        "AIO_RUNTIME_PROFILE": "low_resource",
        "QUEUE_BACKEND": "local"
      },
      "validation": [
        "offline packages present",
        "no cloud dependency required",
        "update package pre-validated"
      ]
    },
    "saas": {
      "env": {
        "AIO_ENTERPRISE_MODE": "1",
        "AIO_RUNTIME_PROFILE": "enterprise",
        "DB_BACKEND": "postgres",
        "PROMETHEUS_ENABLED": "1",
        "QUEUE_BACKEND": "redis"
      },
      "validation": [
        "external DB",
        "external queue",
        "metrics exporter",
        "tenant isolation policy"
      ]
    },
    "self_hosted": {
      "env": {
        "AIO_AI_MODE": "hybrid",
        "AIO_RUNTIME_PROFILE": "enterprise",
        "DB_BACKEND": "postgres",
        "QUEUE_BACKEND": "postgres"
      },
      "validation": [
        "DATABASE_URL configured",
        "backup path configured",
        "TLS termination configured"
      ]
    },
    "shared_office": {
      "env": {
        "AIO_OFFLINE_MODE": "0",
        "AIO_RUNTIME_PROFILE": "lite",
        "ALLOW_EXTERNAL_BIND": "0",
        "MAX_WORKERS": "2"
      },
      "validation": [
        "no wildcard bind",
        "per-install local token",
        "operator service toggles reviewed"
      ]
    },
    "smb_office": {
      "env": {
        "AIO_AI_MODE": "lite",
        "AIO_RUNTIME_PROFILE": "lite",
        "DB_BACKEND": "sqlite",
        "MAX_WORKERS": "2",
        "QUEUE_BACKEND": "local"
      },
      "validation": [
        "local token auth",
        "service discovery file",
        "queue dead-letter monitoring"
      ]
    },
    "windows_11_low_resource": {
      "env": {
        "AIO_AI_MODE": "disabled",
        "AIO_RUNTIME_PROFILE": "low_resource",
        "DB_BACKEND": "sqlite",
        "MAX_WORKERS": "1",
        "QUEUE_BACKEND": "local"
      },
      "validation": [
        "loopback API binding",
        "rotating logs",
        "low-resource services disabled"
      ]
    }
  },
  "deployment_provisioning_pack": {
    "env": {
      "AIO_ENTERPRISE_MODE": "1",
      "AIO_RUNTIME_PROFILE": "enterprise",
      "AIO_UPDATE_SIGNING_KEY": "<set-in-secret-manager>",
      "BACKUP_PATH": "<backup-path>",
      "DATABASE_URL": "<set-in-secret-manager>",
      "DB_BACKEND": "postgres",
      "GMAIL_CLIENT_ID": "<set-in-secret-manager>",
      "GMAIL_CLIENT_SECRET": "<set-in-secret-manager>",
      "OTEL_EXPORTER_OTLP_ENDPOINT": "<otel-exporter-otlp-endpoint>",
      "OUTLOOK_CLIENT_ID": "<set-in-secret-manager>",
      "OUTLOOK_CLIENT_SECRET": "<set-in-secret-manager>",
      "PROMETHEUS_ENABLED": "1",
      "QUEUE_BACKEND": "postgres",
      "TOKEN_ENCRYPTION_KEY": "<set-in-secret-manager>"
    },
    "environment_provisioning_covered": true,
    "profile": "saas",
    "readiness_gates": [
      "async_high_volume_sync",
      "saas_queue_backend",
      "signed_update_validation",
      "external_observability",
      "backup_target"
    ],
    "required_endpoints": {
      "BACKUP_PATH": "Backup target path or bucket URL.",
      "DATABASE_URL": "PostgreSQL connection URL.",
      "OTEL_EXPORTER_OTLP_ENDPOINT": "OpenTelemetry collector endpoint."
    },
    "required_secrets": {
      "AIO_UPDATE_SIGNING_KEY": "Release signing key for signed update validation.",
      "DATABASE_URL": "PostgreSQL connection URL stored in a secret manager.",
      "GMAIL_CLIENT_ID": "Gmail OAuth client id.",
      "GMAIL_CLIENT_SECRET": "Gmail OAuth client secret.",
      "OUTLOOK_CLIENT_ID": "Outlook OAuth client id.",
      "OUTLOOK_CLIENT_SECRET": "Outlook OAuth client secret.",
      "TOKEN_ENCRYPTION_KEY": "256-bit token encryption key from a secret manager."
    },
    "secret_values_included": false,
    "status": "ready",
    "validation": [
      "external DB",
      "external queue",
      "metrics exporter",
      "tenant isolation policy"
    ]
  },
  "deployment_template_generation": true,
  "deployment_validation": {
    "blockers": [],
    "environment": "local",
    "production_readiness": {
      "blockers": [
        "saas_queue_backend",
        "signed_update_validation",
        "external_observability",
        "backup_target"
      ],
      "gates": {
        "async_high_volume_sync": {
          "detail": "Async provider transport is available for Gmail/Outlook high-volume workers.",
          "ready": true
        },
        "backup_target": {
          "detail": "Configure BACKUP_PATH, BACKUP_BUCKET, or DATABASE_BACKUP_URL.",
          "ready": false
        },
        "external_observability": {
          "detail": "Configure OTEL_EXPORTER_OTLP_ENDPOINT, SENTRY_DSN, or PROMETHEUS_ENABLED.",
          "ready": false
        },
        "saas_queue_backend": {
          "detail": "Use local durable queue only for desktop/SMB deployments.",
          "ready": false
        },
        "signed_update_validation": {
          "detail": "AIO_UPDATE_SIGNING_KEY or UPDATE_SIGNING_KEY is required for production releases.",
          "ready": false
        }
      },
      "status": "action_required"
    },
    "queue_backend": {
      "backend": "local",
      "blockers": [],
      "capabilities": {
        "dead_letter_queues": true,
        "duplicate_prevention": true,
        "local_sqlite_durable": true,
        "overflow_protection": true,
        "postgres_skip_locked": false,
        "redis_streams": false,
        "stale_lease_recovery": true
      },
      "database_url_configured": false,
      "external_queue_ready": false,
      "local_queue_ready": true,
      "redis_url_configured": false,
      "saas_recommendation": "postgres SKIP LOCKED or Redis Streams",
      "warnings": [
        "local durable queue is suitable for desktop/SMB, not multi-instance SaaS fan-out"
      ]
    },
    "startup_validation": {
      "data_dir": "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\data",
      "log_dir": "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated\\logs",
      "project_root": "C:\\Email\\AI36_CURATED_REBUILD\\AI36_curated"
    },
    "status": "ready",
    "targets": {
      "offline": {
        "status": "ready"
      },
      "saas": {
        "status": "warning"
      },
      "self_hosted": {
        "status": "ready"
      },
      "shared_office": {
        "requires": [
          "local auth token",
          "loopback bind"
        ],
        "status": "ready"
      },
      "smb_office": {
        "mode": "local_first_shared_office",
        "status": "ready"
      },
      "windows_11": {
        "status": "ready"
      }
    },
    "warnings": []
  },
  "diagnostics": {
    "health_diagnostics": true,
    "runtime_inspection": true,
    "support_bundle_ready": true,
    "troubleshooting_helpers": true
  },
  "production_readiness_gates": {
    "blockers": [
      "saas_queue_backend",
      "signed_update_validation",
      "external_observability",
      "backup_target"
    ],
    "gates": {
      "async_high_volume_sync": {
        "detail": "Async provider transport is available for Gmail/Outlook high-volume workers.",
        "ready": true
      },
      "backup_target": {
        "detail": "Configure BACKUP_PATH, BACKUP_BUCKET, or DATABASE_BACKUP_URL.",
        "ready": false
      },
      "external_observability": {
        "detail": "Configure OTEL_EXPORTER_OTLP_ENDPOINT, SENTRY_DSN, or PROMETHEUS_ENABLED.",
        "ready": false
      },
      "saas_queue_backend": {
        "detail": "Use local durable queue only for desktop/SMB deployments.",
        "ready": false
      },
      "signed_update_validation": {
        "detail": "AIO_UPDATE_SIGNING_KEY or UPDATE_SIGNING_KEY is required for production releases.",
        "ready": false
      }
    },
    "metrics_export": {
      "endpoint": "/api/v1/enterprise-operations/metrics",
      "external_apm_configured": false,
      "prometheus_text": true,
      "sensitive_labels_redacted": true
    },
    "queue_backend": {
      "backend": "local",
      "blockers": [],
      "capabilities": {
        "dead_letter_queues": true,
        "duplicate_prevention": true,
        "local_sqlite_durable": true,
        "overflow_protection": true,
        "postgres_skip_locked": false,
        "redis_streams": false,
        "stale_lease_recovery": true
      },
      "database_url_configured": false,
      "external_queue_ready": false,
      "local_queue_ready": true,
      "redis_url_configured": false,
      "saas_recommendation": "postgres SKIP LOCKED or Redis Streams",
      "warnings": [
        "local durable queue is suitable for desktop/SMB, not multi-instance SaaS fan-out"
      ]
    },
    "status": "action_required",
    "sync_transport": {
      "async_transport_available": true,
      "high_volume_providers": {
        "gmail": {
          "async_client_ready": true,
          "idle_resource_overhead": "near_zero_until_used",
          "module_present": true,
          "pooled_http": true,
          "retry_protection": true,
          "timeout_protection": true
        },
        "imap": {
          "async_client_ready": true,
          "idle_resource_overhead": "near_zero_until_used",
          "module_present": true,
          "pooled_http": true,
          "retry_protection": true,
          "timeout_protection": true
        },
        "outlook": {
          "async_client_ready": true,
          "idle_resource_overhead": "near_zero_until_used",
          "module_present": true,
          "pooled_http": true,
          "retry_protection": true,
          "timeout_protection": true
        }
      },
      "recommendation": "Use async provider transport for SaaS/high-volume sync workers; desktop low-resource mode can keep synchronous single-worker sync.",
      "shared_http_pool": true,
      "sync_compatibility_preserved": true
    }
  },
  "update_diagnostics": {
    "diagnostics": [
      "validate archive before install",
      "validate manifest signature and file checksums before install",
      "create backup before apply",
      "verify startup after update",
      "rollback on failed verification"
    ],
    "file_checksum_validation": true,
    "migration_safety": true,
    "partial_update_protection": true,
    "rollback_available": true,
    "safe_update_flow": true,
    "signed_manifest_validation": true,
    "signing_key_configured": false,
    "version_validation": true
  }
}
```

## Long Term Maintainability

```json
{
  "configuration_driven_runtime": true,
  "reports_are_machine_readable": true,
  "single_operations_facade": true,
  "test_coverage_added": true
}
```

## Remaining Technical Debt

```json
{
  "environment_inputs_required": [
    "saas_queue_backend",
    "signed_update_validation",
    "external_observability",
    "backup_target"
  ],
  "environment_provisioning_pack_ready": true,
  "platform_items": [],
  "status": "platform_complete"
}
```
