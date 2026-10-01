# Spend alarms. The account runs on AWS credits; `credits-exhausted-alarm`
# (credits *included*, so net spend) is the one that means real money.
# `runs-on-app-daily-budget` belongs to the runs-on CloudFormation stack and
# is not managed here.

locals {
  # include_credit/include_refund = false → gross usage, before credits.
  gross_cost = {
    include_credit = false
    include_refund = false
  }

  budgets = {
    migration = {
      name        = "migration-monthly-spend"
      limit       = "1400.0"
      start       = "2026-08-01_00:00"
      gross       = true
      service     = null
      actual      = [500, 800, 1400]
      forecasted  = [1400]
      percentages = false
    }
    bedrock = {
      name        = "bedrock-monthly-spend"
      limit       = "200.0"
      start       = "2026-09-01_00:00"
      gross       = true
      service     = "Amazon Bedrock"
      actual      = [150, 200]
      forecasted  = [200]
      percentages = false
    }
    kiro = {
      name        = "kiro-monthly-spend"
      limit       = "500.0"
      start       = "2026-09-01_00:00"
      gross       = true
      service     = "Kiro"
      actual      = [375, 500]
      forecasted  = [500]
      percentages = false
    }
    credits_exhausted = {
      name        = "credits-exhausted-alarm"
      limit       = "5.0"
      start       = "2026-08-01_00:00"
      gross       = false
      service     = null
      actual      = [1]
      forecasted  = []
      percentages = false
    }
    account_total = {
      name        = "tuna-os-account-total"
      limit       = "120.0"
      start       = "2026-07-01_00:00"
      gross       = false
      service     = null
      actual      = [50, 80, 90]
      forecasted  = []
      percentages = true
    }
  }
}

resource "aws_budgets_budget" "this" {
  for_each = local.budgets

  account_id        = data.aws_caller_identity.current.account_id
  name              = each.value.name
  budget_type       = "COST"
  limit_amount      = each.value.limit
  limit_unit        = "USD"
  time_unit         = "MONTHLY"
  time_period_start = each.value.start

  dynamic "cost_filter" {
    for_each = each.value.service == null ? [] : [each.value.service]
    content {
      name   = "Service"
      values = [cost_filter.value]
    }
  }

  dynamic "cost_types" {
    for_each = each.value.gross ? [local.gross_cost] : []
    content {
      include_credit = cost_types.value.include_credit
      include_refund = cost_types.value.include_refund
    }
  }

  dynamic "notification" {
    for_each = concat(
      [for t in each.value.actual : { type = "ACTUAL", threshold = t }],
      [for t in each.value.forecasted : { type = "FORECASTED", threshold = t }],
    )
    content {
      comparison_operator        = "GREATER_THAN"
      notification_type          = notification.value.type
      threshold                  = notification.value.threshold
      threshold_type             = each.value.percentages ? "PERCENTAGE" : "ABSOLUTE_VALUE"
      subscriber_email_addresses = [var.alert_email]
    }
  }
}
