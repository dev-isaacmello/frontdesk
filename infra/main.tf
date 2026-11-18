# The demo environment: three container apps and a setup job, PostgreSQL, a session queue,
# a vault, a registry and a log workspace. No virtual network (ADR 0010).

locals {
  tags = { project = var.name, purpose = "demo" }

  database       = "frontdesk"
  database_host  = azurerm_postgresql_flexible_server.main.fqdn
  queue_endpoint = "${azurerm_servicebus_namespace.main.name}.servicebus.windows.net"
  registry       = azurerm_container_registry.main.login_server
  backend_image  = "${local.registry}/frontdesk-backend:${var.image_tag}"
  web_image      = "${local.registry}/frontdesk-web:${var.image_tag}"

  whatsapp_secrets = var.whatsapp == null ? {} : {
    "whatsapp-app-secret"   = var.whatsapp_app_secret
    "whatsapp-verify-token" = var.whatsapp_verify_token
    "whatsapp-access-token" = var.whatsapp_access_token
  }

  secrets = merge(
    {
      "postgres-admin-password" = random_password.database["admin"].result
      "postgres-owner-password" = random_password.database["owner"].result
      "postgres-app-password"   = random_password.database["app"].result
      "demo-owner-password"     = random_password.demo_owner.result
      "webchat-secret"          = random_password.webchat.result
      "database-url"            = "postgresql+psycopg://frontdesk_app:${random_password.database["app"].result}@${local.database_host}:5432/${local.database}?sslmode=require"
      "migrations-database-url" = "postgresql+psycopg://frontdesk_owner:${random_password.database["owner"].result}@${local.database_host}:5432/${local.database}?sslmode=require"
      "superuser-dsn"           = "postgresql://frontdesk_admin:${random_password.database["admin"].result}@${local.database_host}:5432/postgres?sslmode=require"
    },
    local.whatsapp_secrets,
  )

  # What each workload may read from the vault, and nothing else.
  workload_secrets = {
    api = concat(
      ["database-url", "webchat-secret"],
      var.whatsapp == null ? [] : ["whatsapp-app-secret", "whatsapp-verify-token"],
    )
    worker = concat(["database-url"], var.whatsapp == null ? [] : ["whatsapp-access-token"])
    web    = ["webchat-secret"]
    setup = [
      "database-url", "migrations-database-url", "superuser-dsn", "postgres-owner-password",
      "postgres-app-password", "demo-owner-password",
    ]
  }

  model_env = {
    FRONTDESK_MODEL_PROVIDER        = "azure_openai"
    FRONTDESK_MODEL                 = var.model
    FRONTDESK_EMBEDDING_MODEL       = var.embedding_model
    FRONTDESK_AZURE_OPENAI_ENDPOINT = var.model_account.endpoint
    FRONTDESK_DAILY_CAP_USD         = var.daily_cap_usd
  }

  queue_env = {
    FRONTDESK_SERVICEBUS_NAMESPACE = local.queue_endpoint
    FRONTDESK_QUEUE_NAME           = azurerm_servicebus_queue.triggers.name
  }
}

data "azurerm_client_config" "current" {}

resource "azurerm_resource_group" "main" {
  name     = "rg-${var.name}-demo"
  location = var.location
  tags     = local.tags
}

# ---------------------------------------------------------------------------- secrets

resource "random_password" "database" {
  for_each = toset(["admin", "owner", "app"])
  length   = 40
  # The passwords travel inside connection URLs.
  special = false
}

resource "random_password" "demo_owner" {
  length  = 24
  special = false
}

resource "random_password" "webchat" {
  length  = 48
  special = false
}

resource "azurerm_key_vault" "main" {
  name                       = "kv-${var.name}-${var.suffix}"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  soft_delete_retention_days = 7
  tags                       = local.tags
}

# Whoever applies writes the secrets. The workloads only read the ones they are given.
resource "azurerm_role_assignment" "operator_writes_secrets" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_key_vault_secret" "main" {
  for_each     = nonsensitive(toset(keys(local.secrets)))
  name         = each.key
  value        = local.secrets[each.key]
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.operator_writes_secrets]
}

# ------------------------------------------------------------------------- identities

resource "azurerm_user_assigned_identity" "workload" {
  for_each            = toset(["api", "worker", "web", "setup"])
  name                = "id-${var.name}-${each.key}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}

resource "azurerm_role_assignment" "reads_secret" {
  for_each = merge([
    for workload, names in local.workload_secrets : {
      for name in names : "${workload}/${name}" => { workload = workload, secret = name }
    }
  ]...)

  scope                = azurerm_key_vault_secret.main[each.value.secret].resource_versionless_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.workload[each.value.workload].principal_id
}

resource "azurerm_role_assignment" "pulls_images" {
  for_each             = azurerm_user_assigned_identity.workload
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = each.value.principal_id
}

# The API only puts triggers on the queue and the worker only takes them off.
resource "azurerm_role_assignment" "api_sends" {
  scope                = azurerm_servicebus_queue.triggers.id
  role_definition_name = "Azure Service Bus Data Sender"
  principal_id         = azurerm_user_assigned_identity.workload["api"].principal_id
}

resource "azurerm_role_assignment" "worker_receives" {
  scope                = azurerm_servicebus_queue.triggers.id
  role_definition_name = "Azure Service Bus Data Receiver"
  principal_id         = azurerm_user_assigned_identity.workload["worker"].principal_id
}

# The worker sends too: a turn that fails is put back with a delay.
resource "azurerm_role_assignment" "worker_sends" {
  scope                = azurerm_servicebus_queue.triggers.id
  role_definition_name = "Azure Service Bus Data Sender"
  principal_id         = azurerm_user_assigned_identity.workload["worker"].principal_id
}

data "azurerm_cognitive_account" "model" {
  name                = var.model_account.name
  resource_group_name = var.model_account.resource_group
}

# The worker answers customers, the API reviews the owner's rules, and the setup job
# embeds the knowledge base. None of them holds a key.
resource "azurerm_role_assignment" "calls_the_model" {
  for_each             = toset(["api", "worker", "setup"])
  scope                = data.azurerm_cognitive_account.model.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.workload[each.key].principal_id
}

# ------------------------------------------------------------------- registry and logs

resource "azurerm_container_registry" "main" {
  name                = "cr${var.name}${var.suffix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.tags
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${var.name}-demo"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  # The demo cannot ingest past what is free in a month.
  daily_quota_gb = 0.15
  tags           = local.tags
}

# ------------------------------------------------------------------------------ queue

resource "azurerm_servicebus_namespace" "main" {
  name                = "sb-${var.name}-${var.suffix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  # Sessions and duplicate detection do not exist on Basic.
  sku = "Standard"
  # Entra ID only: there is no connection string to leak.
  local_auth_enabled = false
  tags               = local.tags
}

# The same settings the local emulator is given in ops/local/servicebus-emulator.json.
resource "azurerm_servicebus_queue" "triggers" {
  name                                    = "triggers"
  namespace_id                            = azurerm_servicebus_namespace.main.id
  requires_session                        = true
  requires_duplicate_detection            = true
  duplicate_detection_history_time_window = "PT5M"
  lock_duration                           = "PT1M"
  max_delivery_count                      = 5
  default_message_ttl                     = "PT1H"
  dead_lettering_on_message_expiration    = false
}

# The one alarm of the demo. A trigger in the dead-letter queue is a conversation that was
# handed to a person after five failed attempts (docs/runbooks/queue-growing.md). The count
# is Service Bus's own metric, so it is true while the worker is down. There is no action
# group: it shows in the portal as a fired alert and notifies nobody.
resource "azurerm_monitor_metric_alert" "dead_letters" {
  name                = "dead-letters-${var.name}"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_servicebus_namespace.main.id]
  description         = "A trigger failed five deliveries and is in the dead-letter queue."
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT5M"
  tags                = local.tags

  criteria {
    metric_namespace = "Microsoft.ServiceBus/namespaces"
    metric_name      = "DeadletteredMessages"
    aggregation      = "Maximum"
    operator         = "GreaterThan"
    threshold        = 0

    dimension {
      name     = "EntityName"
      operator = "Include"
      values   = [azurerm_servicebus_queue.triggers.name]
    }
  }
}

# --------------------------------------------------------------------------- database

resource "azurerm_postgresql_flexible_server" "main" {
  name                          = "psql-${var.name}-${var.suffix}"
  location                      = azurerm_resource_group.main.location
  resource_group_name           = azurerm_resource_group.main.name
  version                       = "18"
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  backup_retention_days         = 7
  administrator_login           = "frontdesk_admin"
  administrator_password        = random_password.database["admin"].result
  public_network_access_enabled = true
  # A demo of fictional data on the smallest server: no standby. The zone is left to Azure:
  # the student subscription refuses a named one in this region, and whichever it picks is
  # not a change to undo.
  tags = local.tags

  lifecycle {
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "BTREE_GIST,VECTOR"
}

# The rule Azure reads as "any Azure service", and not the environment's own addresses as
# ADR 0010 planned: without a virtual network the environment leaves through 181 addresses
# of a pool it shares with other customers, so naming them was 181 rules that kept nobody
# in particular out. What stands in front of the database is TLS and a password, and the
# internet outside Azure is refused. The ADR has what this gives up.
resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  name             = "azure-services"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# ----------------------------------------------------------------------- container apps

resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${var.name}-demo"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = local.tags
}

# Azure created this environment as "express" on the student subscription: a shared tier
# with no jobs and no Key Vault references, which is what the first apply failed on. Its
# documentation says a template gets a standard environment unless it asks for express,
# and azurerm 4 has no argument for the mode, so the mode is set through the resource API.
# On an environment that came up express the change took Azure about twenty-five minutes.
# A PATCH of the one property: a full update is refused, because reading the environment
# does not give back the workspace key that writing it requires.
resource "azapi_resource_action" "standard_environment" {
  type        = "Microsoft.App/managedEnvironments@2026-07-01"
  resource_id = azurerm_container_app_environment.main.id
  method      = "PATCH"

  body = {
    properties = {
      environmentMode = "WorkloadProfiles"
    }
  }
}

resource "azurerm_container_app" "api" {
  name                         = "ca-${var.name}-api"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.workload["api"].id]
  }

  registry {
    server   = local.registry
    identity = azurerm_user_assigned_identity.workload["api"].id
  }

  dynamic "secret" {
    for_each = toset(local.workload_secrets.api)
    content {
      name                = secret.value
      key_vault_secret_id = azurerm_key_vault_secret.main[secret.value].versionless_id
      identity            = azurerm_user_assigned_identity.workload["api"].id
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "api"
      image  = local.backend_image
      cpu    = 0.25
      memory = "0.5Gi"

      dynamic "env" {
        for_each = merge(local.model_env, local.queue_env, {
          # Which of the identities of the app the Azure SDKs sign in as.
          AZURE_CLIENT_ID = azurerm_user_assigned_identity.workload["api"].client_id
        })
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name        = "FRONTDESK_DATABASE_URL"
        secret_name = "database-url"
      }
      env {
        name        = "FRONTDESK_WEBCHAT_SECRET"
        secret_name = "webchat-secret"
      }
      dynamic "env" {
        for_each = var.whatsapp == null ? {} : {
          FRONTDESK_WHATSAPP_APP_SECRET   = "whatsapp-app-secret"
          FRONTDESK_WHATSAPP_VERIFY_TOKEN = "whatsapp-verify-token"
        }
        content {
          name        = env.key
          secret_name = env.value
        }
      }

      liveness_probe {
        transport = "HTTP"
        path      = "/healthz"
        port      = 8000
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.reads_secret,
    azurerm_role_assignment.pulls_images,
    azapi_resource_action.standard_environment,
  ]

  # The image is set here once, at creation. After that the deploy workflow rolls it.
  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
}

resource "azurerm_container_app" "worker" {
  name                         = "ca-${var.name}-worker"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.workload["worker"].id]
  }

  registry {
    server   = local.registry
    identity = azurerm_user_assigned_identity.workload["worker"].id
  }

  dynamic "secret" {
    for_each = toset(local.workload_secrets.worker)
    content {
      name                = secret.value
      key_vault_secret_id = azurerm_key_vault_secret.main[secret.value].versionless_id
      identity            = azurerm_user_assigned_identity.workload["worker"].id
    }
  }

  template {
    # One worker, always on: a conversation is a session on the queue, and nothing wakes
    # an app that has scaled to zero when a session gets a message.
    min_replicas = 1
    max_replicas = 1

    container {
      name    = "worker"
      image   = local.backend_image
      command = ["python", "-m", "frontdesk.worker"]
      cpu     = 0.5
      memory  = "1Gi"

      dynamic "env" {
        for_each = merge(local.model_env, local.queue_env, {
          AZURE_CLIENT_ID = azurerm_user_assigned_identity.workload["worker"].client_id
        })
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name        = "FRONTDESK_DATABASE_URL"
        secret_name = "database-url"
      }
      # The worker reads the whole configuration and sends nothing with this one.
      env {
        name  = "FRONTDESK_WEBCHAT_SECRET"
        value = "unused-by-the-worker"
      }
      dynamic "env" {
        for_each = var.whatsapp == null ? {} : {
          FRONTDESK_WHATSAPP_ACCESS_TOKEN = "whatsapp-access-token"
        }
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.reads_secret,
    azurerm_role_assignment.pulls_images,
    azapi_resource_action.standard_environment,
  ]

  # The image is set here once, at creation. After that the deploy workflow rolls it.
  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
}

resource "azurerm_container_app" "web" {
  name                         = "ca-${var.name}-web"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.workload["web"].id]
  }

  registry {
    server   = local.registry
    identity = azurerm_user_assigned_identity.workload["web"].id
  }

  secret {
    name                = "webchat-secret"
    key_vault_secret_id = azurerm_key_vault_secret.main["webchat-secret"].versionless_id
    identity            = azurerm_user_assigned_identity.workload["web"].id
  }

  ingress {
    external_enabled = true
    target_port      = 3000
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "web"
      image  = local.web_image
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name = "FRONTDESK_API_URL"
        # Inside the environment, by the app's name, without leaving it.
        value = "http://${azurerm_container_app.api.name}"
      }
      env {
        name        = "FRONTDESK_WEBCHAT_SECRET"
        secret_name = "webchat-secret"
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.reads_secret,
    azurerm_role_assignment.pulls_images,
    azapi_resource_action.standard_environment,
  ]

  # The image is set here once, at creation. After that the deploy workflow rolls it.
  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
}

# Roles, schema and seed. Started by hand or by the deploy, once per release.
resource "azurerm_container_app_job" "setup" {
  name                         = "caj-${var.name}-setup"
  location                     = azurerm_resource_group.main.location
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  replica_timeout_in_seconds   = 600
  replica_retry_limit          = 0
  tags                         = local.tags

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.workload["setup"].id]
  }

  registry {
    server   = local.registry
    identity = azurerm_user_assigned_identity.workload["setup"].id
  }

  dynamic "secret" {
    for_each = toset(local.workload_secrets.setup)
    content {
      name                = secret.value
      key_vault_secret_id = azurerm_key_vault_secret.main[secret.value].versionless_id
      identity            = azurerm_user_assigned_identity.workload["setup"].id
    }
  }

  template {
    container {
      name    = "setup"
      image   = local.backend_image
      command = ["python", "-m", "frontdesk.setup"]
      cpu     = 0.25
      memory  = "0.5Gi"

      dynamic "env" {
        for_each = merge(
          {
            FRONTDESK_DATABASE_NAME         = local.database
            FRONTDESK_EMBEDDING_MODEL       = var.embedding_model
            FRONTDESK_AZURE_OPENAI_ENDPOINT = var.model_account.endpoint
            AZURE_CLIENT_ID                 = azurerm_user_assigned_identity.workload["setup"].client_id
          },
          var.whatsapp == null ? {} : {
            FRONTDESK_WHATSAPP_PHONE_NUMBER_ID = var.whatsapp.phone_number_id
            FRONTDESK_WHATSAPP_TENANT          = var.whatsapp.tenant
          },
        )
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = {
          FRONTDESK_DATABASE_URL            = "database-url"
          FRONTDESK_MIGRATIONS_DATABASE_URL = "migrations-database-url"
          FRONTDESK_SUPERUSER_DSN           = "superuser-dsn"
          FRONTDESK_OWNER_PASSWORD          = "postgres-owner-password"
          FRONTDESK_APP_PASSWORD            = "postgres-app-password"
          FRONTDESK_DEMO_OWNER_PASSWORD     = "demo-owner-password"
        }
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.reads_secret,
    azurerm_role_assignment.pulls_images,
    azapi_resource_action.standard_environment,
  ]

  # The image is set here once, at creation. After that the deploy workflow rolls it.
  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
}

# ----------------------------------------------------------------------------- deploy

# GitHub Actions signs in as this identity with a token of its own, and no stored secret.
resource "azurerm_user_assigned_identity" "deploy" {
  name                = "id-${var.name}-deploy"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}

resource "azurerm_federated_identity_credential" "github" {
  name                = "github-main"
  resource_group_name = azurerm_resource_group.main.name
  parent_id           = azurerm_user_assigned_identity.deploy.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = var.github_subject
}

# It pushes images and rolls the apps to them. It cannot read a secret or grant a role.
resource "azurerm_role_assignment" "deploy_pushes_images" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
}

resource "azurerm_role_assignment" "deploy_rolls_apps" {
  scope                = azurerm_resource_group.main.id
  role_definition_name = "Container Apps Contributor"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
}

# Rolling an app that runs as an identity needs leave to assign that identity to it.
resource "azurerm_role_assignment" "deploy_uses_identities" {
  for_each             = azurerm_user_assigned_identity.workload
  scope                = each.value.id
  role_definition_name = "Managed Identity Operator"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
}
