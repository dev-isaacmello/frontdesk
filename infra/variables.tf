variable "subscription_id" {
  description = "The subscription the environment is created in."
  type        = string
}

variable "location" {
  description = "One region for everything. The student subscription allows five, and this is the one the model resource is in."
  type        = string
  default     = "northcentralus"
}

variable "name" {
  description = "Prefix of every resource name."
  type        = string
  default     = "frontdesk"
}

variable "suffix" {
  description = "A few lowercase characters that make the globally unique names unique: registry, vault, database and queue namespace."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{3,8}$", var.suffix))
    error_message = "Three to eight lowercase letters or digits."
  }
}

variable "image_tag" {
  description = "Tag of the backend and web images in the registry. The deploy workflow pushes a tag and applies with it."
  type        = string
  default     = "bootstrap"
}

variable "model_account" {
  description = "The Azure OpenAI resource the agent calls, which this configuration does not create."
  type = object({
    name           = string
    resource_group = string
    endpoint       = string
  })
}

variable "model" {
  description = "Deployment that answers every node unless a route says otherwise."
  type        = string
  default     = "gpt-oss-120b"
}

variable "embedding_model" {
  description = "Deployment the knowledge base is embedded with."
  type        = string
  default     = "text-embedding-3-small"
}

variable "daily_cap_usd" {
  description = "What every tenant together may spend on models in a day."
  type        = string
  default     = "2"
}

variable "database_allowed_ips" {
  description = "Outbound addresses of the Container Apps environment, which are known only after it exists. Empty on the first apply; the second apply passes the output environment_outbound_ips."
  type        = list(string)
  default     = []
}

variable "github_subject" {
  description = "Subject of the GitHub Actions token that may deploy, as the token of this repository states it."
  type        = string
}

variable "whatsapp" {
  description = "The Meta app and the test number. Null leaves the WhatsApp channel out."
  type = object({
    phone_number_id = string
    tenant          = string
  })
  default = null
}

variable "whatsapp_app_secret" {
  type      = string
  default   = null
  sensitive = true
}

variable "whatsapp_verify_token" {
  type      = string
  default   = null
  sensitive = true
}

variable "whatsapp_access_token" {
  type      = string
  default   = null
  sensitive = true
}
