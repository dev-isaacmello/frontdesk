output "web_url" {
  description = "Where the chat and the owner's panel are."
  value       = "https://${azurerm_container_app.web.ingress[0].fqdn}"
}

output "api_url" {
  description = "Where Meta's webhook points: <api_url>/channels/whatsapp/webhook."
  value       = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "environment_outbound_ips" {
  description = "Pass these as database_allowed_ips on the second apply."
  value       = distinct(concat(azurerm_container_app.api.outbound_ip_addresses, azurerm_container_app.worker.outbound_ip_addresses))
}

output "registry" {
  value = azurerm_container_registry.main.login_server
}

output "resource_group" {
  value = azurerm_resource_group.main.name
}

output "deploy_client_id" {
  description = "The client id GitHub Actions signs in with."
  value       = azurerm_user_assigned_identity.deploy.client_id
}

output "setup_job" {
  value = azurerm_container_app_job.setup.name
}

output "vault" {
  description = "Holds the demo owner's password, under the name demo-owner-password."
  value       = azurerm_key_vault.main.name
}
