# SigNoz Cloud tenant — fleet baseline alerts.
#
# The alert contract (what these rules are, why they're fleet-wide) is
# documented in django-harry/docs/observability-signoz.md (§4, §7). This file
# is its enforcement: five rules, each grouped by service.name and filtered to
# deployment.environment = prod, covering every service in the fleet
# automatically — including services that don't exist yet. There is no
# per-project alert provisioning anywhere.
#
# Auth: the token comes from the environment (SIGNOZ_ACCESS_TOKEN, see
# env.example). The API endpoint is set explicitly below because the
# SIGNOZ_ENDPOINT env var in this repo already means the OTLP *ingest*
# endpoint (used by the collectors), which is a different URL.
#
# Bootstrap: the notification channel ("Slack") is created by hand in the UI —
# the provider has no channel resource as of v0.0.14, and rules reference the
# channel by exact name. The rules themselves are created directly by
# `terraform apply`; no UI authoring or imports needed. After creation the UI
# is read-only for these rules: edit here, plan, apply — a UI edit to a
# managed rule is reverted on the next apply.
#
# Provider quirks (v0.0.14), learned the hard way:
#  - On create, apply errors with "invalid result object … preferred_channels"
#    AFTER the rule is created and saved to state, leaving it tainted. Recover
#    with `terraform untaint signoz_alert.<name>` — don't let Terraform
#    destroy/recreate. Expect this whenever a rule is added (e.g. a p95
#    override).
#  - Conditions must be written exactly as the server normalizes them or plan
#    never converges: builder_query specs carry `source = ""`, clickhouse
#    specs carry `disabled = false`, an empty groupBy is omitted entirely, and
#    notification_settings pins `renotify` with a NON-empty alert_states
#    (the server turns [] into null, so [] never settles; the value is inert
#    while enabled = false). After adding a rule, reconcile it against
#    `terraform state show`.
#  - The API accepting a condition doesn't prove the rule evaluates. Rules #4
#    and #5 fire on a single prod ERROR log, which is the cheap end-to-end
#    test of collector → rule → Slack.

# (provider requirement is declared in main.tf's required_providers)
provider "signoz" {
  endpoint = "https://leading-louse.us.signoz.cloud" # UI/API base URL of the tenant, NOT the ingest endpoint
}

locals {
  # The one notification channel every rule fires into (doc §3).
  channel = "Slack" # name of the channel exactly as created in the UI

  # ---- Per-service tuning ---------------------------------------------
  # A service listed here is carved out of the baseline p95 rule and gets
  # its own rule with the tuned threshold. Tuning a service = one entry.
  p95_default_ms = 1000
  p95_overrides_ms = {
    # "slow-reports" = 2500
  }

  prod = "deployment.environment = 'prod'"

  # Baseline p95 filter: prod, minus every overridden service. Derived from
  # the same map as the override rules, so carve-out and override can't drift.
  p95_baseline_filter = join(" AND ", concat(
    [local.prod],
    [for s in sort(keys(local.p95_overrides_ms)) : "service.name != '${s}'"],
  ))
}

# ---------------------------------------------------------------------------
# 1. Error rate > 5% over 5 min, per service (trace-based)
# ---------------------------------------------------------------------------
resource "signoz_alert" "error_rate" {
  alert       = "Error rate > 5% (fleet)"
  alert_type  = "TRACES_BASED_ALERT"
  severity    = "critical"
  description = "{{$service.name}} error span rate is {{$value}}% (threshold {{$threshold}}%)"
  summary     = "High error rate on {{$service.name}}"

  version        = "v5"
  schema_version = "v2alpha1"
  rule_type      = "threshold_rule"
  eval_window    = "5m0s"
  frequency      = "1m0s"

  evaluation = jsonencode({
    kind = "rolling"
    spec = {
      evalWindow = "5m0s"
      frequency  = "1m0s"
    }
  })

  disabled = false

  condition = jsonencode({
    compositeQuery = {
      queryType = "builder"
      panelType = "graph"
      queries = [
        {
          type = "builder_query"
          spec = {
            name         = "A"
            signal       = "traces"
            source       = ""
            stepInterval = 60
            aggregations = [{ expression = "count()" }]
            filter       = { expression = "has_error = true AND ${local.prod}" }
            groupBy      = [{ name = "service.name" }]
            having       = { expression = "" }
          }
        },
        {
          type = "builder_query"
          spec = {
            name         = "B"
            signal       = "traces"
            source       = ""
            stepInterval = 60
            aggregations = [{ expression = "count()" }]
            filter       = { expression = local.prod }
            groupBy      = [{ name = "service.name" }]
            having       = { expression = "" }
          }
        },
        {
          type = "builder_formula"
          spec = {
            name       = "F1"
            expression = "(A / B) * 100"
          }
        },
      ]
    }
    selectedQueryName = "F1"
    thresholds = {
      kind = "basic"
      spec = [{
        name           = "critical"
        target         = 5
        targetUnit     = "%"
        recoveryTarget = null
        matchType      = "3" # on average over the window
        op             = "1" # above
        channels       = [local.channel]
      }]
    }
  })

  notification_settings = {
    group_by = ["service.name"]
    renotify = {
      enabled      = false
      interval     = ""
      alert_states = ["firing"]
    }
  }
}

# ---------------------------------------------------------------------------
# 2. New exception, per service (exceptions-based, ClickHouse)
# ---------------------------------------------------------------------------
# The SQL is the roughest of the five — the API accepted it, but until it has
# fired on a real novel exception, treat it as unproven.
resource "signoz_alert" "new_exception" {
  alert       = "New exception (fleet)"
  alert_type  = "EXCEPTIONS_BASED_ALERT"
  severity    = "critical"
  description = "An exception type not seen in the last 7 days appeared on {{$serviceName}}"
  summary     = "New exception on {{$serviceName}}"

  version        = "v5"
  schema_version = "v2alpha1"
  rule_type      = "threshold_rule"
  eval_window    = "5m0s"
  frequency      = "1m0s"

  evaluation = jsonencode({
    kind = "rolling"
    spec = {
      evalWindow = "5m0s"
      frequency  = "1m0s"
    }
  })

  disabled = false

  condition = jsonencode({
    compositeQuery = {
      queryType = "clickhouse_sql"
      panelType = "graph"
      queries = [{
        type = "clickhouse_sql"
        spec = {
          name     = "A"
          disabled = false
          query    = <<-SQL
            SELECT
              serviceName,
              count() AS value,
              toStartOfInterval(timestamp, toIntervalMinute(1)) AS interval
            FROM signoz_traces.distributed_signoz_error_index_v2
            WHERE timestamp BETWEEN {{.start_datetime}} AND {{.end_datetime}}
              AND (serviceName, exceptionType) NOT IN (
                SELECT DISTINCT serviceName, exceptionType
                FROM signoz_traces.distributed_signoz_error_index_v2
                WHERE timestamp BETWEEN now() - INTERVAL 7 DAY AND {{.start_datetime}}
              )
            GROUP BY serviceName, interval
          SQL
        }
      }]
    }
    selectedQueryName = "A"
    thresholds = {
      kind = "basic"
      spec = [{
        name           = "critical"
        target         = 0
        targetUnit     = ""
        recoveryTarget = null
        matchType      = "1" # at least once
        op             = "1" # above
        channels       = [local.channel]
      }]
    }
  })

  notification_settings = {
    group_by = ["serviceName"]
    renotify = {
      enabled      = false
      interval     = ""
      alert_states = ["firing"]
    }
  }
}

# ---------------------------------------------------------------------------
# 3. p95 latency, per service (trace-based) — baseline + per-service overrides
# ---------------------------------------------------------------------------
resource "signoz_alert" "p95_latency" {
  alert       = "p95 latency > ${local.p95_default_ms}ms (fleet)"
  alert_type  = "TRACES_BASED_ALERT"
  severity    = "warning"
  description = "{{$service.name}} p95 latency is {{$value}} (threshold {{$threshold}}ms)"
  summary     = "Slow p95 on {{$service.name}}"

  version        = "v5"
  schema_version = "v2alpha1"
  rule_type      = "threshold_rule"
  eval_window    = "10m0s"
  frequency      = "1m0s"

  evaluation = jsonencode({
    kind = "rolling"
    spec = {
      evalWindow = "10m0s"
      frequency  = "1m0s"
    }
  })

  disabled = false

  condition = jsonencode({
    compositeQuery = {
      queryType = "builder"
      panelType = "graph"
      queries = [{
        type = "builder_query"
        spec = {
          name         = "A"
          signal       = "traces"
          source       = ""
          stepInterval = 60
          aggregations = [{ expression = "p95(duration_nano)" }]
          filter       = { expression = local.p95_baseline_filter }
          groupBy      = [{ name = "service.name" }]
          having       = { expression = "" }
        }
      }]
    }
    selectedQueryName = "A"
    thresholds = {
      kind = "basic"
      spec = [{
        name           = "warning"
        target         = local.p95_default_ms
        targetUnit     = "ms"
        recoveryTarget = null
        matchType      = "2" # all the times, i.e. sustained for the window
        op             = "1" # above
        channels       = [local.channel]
      }]
    }
  })

  notification_settings = {
    group_by = ["service.name"]
    renotify = {
      enabled      = false
      interval     = ""
      alert_states = ["firing"]
    }
  }
}

resource "signoz_alert" "p95_latency_override" {
  for_each = local.p95_overrides_ms

  alert       = "p95 latency > ${each.value}ms (${each.key})"
  alert_type  = "TRACES_BASED_ALERT"
  severity    = "warning"
  description = "${each.key} p95 latency is {{$value}} (tuned threshold {{$threshold}}ms)"
  summary     = "Slow p95 on ${each.key}"

  version        = "v5"
  schema_version = "v2alpha1"
  rule_type      = "threshold_rule"
  eval_window    = "10m0s"
  frequency      = "1m0s"

  evaluation = jsonencode({
    kind = "rolling"
    spec = {
      evalWindow = "10m0s"
      frequency  = "1m0s"
    }
  })

  disabled = false

  condition = jsonencode({
    compositeQuery = {
      queryType = "builder"
      panelType = "graph"
      queries = [{
        type = "builder_query"
        spec = {
          name         = "A"
          signal       = "traces"
          source       = ""
          stepInterval = 60
          aggregations = [{ expression = "p95(duration_nano)" }]
          filter       = { expression = "${local.prod} AND service.name = '${each.key}'" }
          groupBy      = [{ name = "service.name" }]
          having       = { expression = "" }
        }
      }]
    }
    selectedQueryName = "A"
    thresholds = {
      kind = "basic"
      spec = [{
        name           = "warning"
        target         = each.value
        targetUnit     = "ms"
        recoveryTarget = null
        matchType      = "2"
        op             = "1"
        channels       = [local.channel]
      }]
    }
  })

  notification_settings = {
    group_by = ["service.name"]
    renotify = {
      enabled      = false
      interval     = ""
      alert_states = ["firing"]
    }
  }
}

# ---------------------------------------------------------------------------
# 4. ERROR-log heartbeat, per service (log-based)
# ---------------------------------------------------------------------------
# Catches failures outside request spans (management commands, startup, cron)
# that the trace rules never see. Relies on the collectors stamping
# deployment.environment onto the logs pipeline — see the canonical collector
# config in django-harry/docs/observability-signoz.md §1.
resource "signoz_alert" "error_log_heartbeat" {
  alert       = "ERROR logs (fleet)"
  alert_type  = "LOGS_BASED_ALERT"
  severity    = "critical"
  description = "{{$service.name}} emitted {{$value}} ERROR log(s) in the last 5 minutes"
  summary     = "ERROR logs from {{$service.name}}"

  version        = "v5"
  schema_version = "v2alpha1"
  rule_type      = "threshold_rule"
  eval_window    = "5m0s"
  frequency      = "1m0s"

  evaluation = jsonencode({
    kind = "rolling"
    spec = {
      evalWindow = "5m0s"
      frequency  = "1m0s"
    }
  })

  disabled = false

  condition = jsonencode({
    compositeQuery = {
      queryType = "builder"
      panelType = "graph"
      queries = [{
        type = "builder_query"
        spec = {
          name         = "A"
          signal       = "logs"
          source       = ""
          stepInterval = 60
          aggregations = [{ expression = "count()" }]
          filter       = { expression = "severity_text = 'ERROR' AND ${local.prod}" }
          groupBy      = [{ name = "service.name" }]
          having       = { expression = "" }
        }
      }]
    }
    selectedQueryName = "A"
    thresholds = {
      kind = "basic"
      spec = [{
        name           = "critical"
        target         = 0
        targetUnit     = ""
        recoveryTarget = null
        matchType      = "1" # at least once
        op             = "1" # above
        channels       = [local.channel]
      }]
    }
  })

  notification_settings = {
    group_by = ["service.name"]
    renotify = {
      enabled      = false
      interval     = ""
      alert_states = ["firing"]
    }
  }
}

# ---------------------------------------------------------------------------
# 5. Hygiene rule: ERROR logs with NO service identity (log-based)
# ---------------------------------------------------------------------------
# The canary for telemetry that has lost its identity. Every execution
# context of a project (app unit, Caddy, cron/timers) must set
# OTEL_SERVICE_NAME; a forgotten env var makes that context's errors
# invisible to rule #4, which groups by service.name. This rule fires on
# exactly those orphaned errors so the misconfiguration surfaces instead of
# rotting silently.
resource "signoz_alert" "error_log_hygiene" {
  alert       = "ERROR logs without service.name (hygiene)"
  alert_type  = "LOGS_BASED_ALERT"
  severity    = "warning"
  description = "{{$value}} ERROR log(s) arrived with no service.name — some execution context is missing OTEL_SERVICE_NAME"
  summary     = "Unidentified ERROR logs in the fleet"

  version        = "v5"
  schema_version = "v2alpha1"
  rule_type      = "threshold_rule"
  eval_window    = "5m0s"
  frequency      = "1m0s"

  evaluation = jsonencode({
    kind = "rolling"
    spec = {
      evalWindow = "5m0s"
      frequency  = "1m0s"
    }
  })

  disabled = false

  condition = jsonencode({
    compositeQuery = {
      queryType = "builder"
      panelType = "graph"
      queries = [{
        type = "builder_query"
        spec = {
          name         = "A"
          signal       = "logs"
          source       = ""
          stepInterval = 60
          aggregations = [{ expression = "count()" }]
          filter       = { expression = "severity_text = 'ERROR' AND service.name NOT EXISTS AND ${local.prod}" }
          having       = { expression = "" }
        }
      }]
    }
    selectedQueryName = "A"
    thresholds = {
      kind = "basic"
      spec = [{
        name           = "warning"
        target         = 0
        targetUnit     = ""
        recoveryTarget = null
        matchType      = "1" # at least once
        op             = "1" # above
        channels       = [local.channel]
      }]
    }
  })

  notification_settings = {
    group_by = []
    renotify = {
      enabled      = false
      interval     = ""
      alert_states = ["firing"]
    }
  }
}
