# The demo environment on Azure

Terraform for the environment described in [ADR 0008](../docs/adr/0008-one-cloud-azure.md), [0009](../docs/adr/0009-container-apps-over-foundry-agent-service.md) and [0010](../docs/adr/0010-public-endpoints-behind-identity-and-a-firewall.md): three container apps and a setup job, PostgreSQL flexible server, a Service Bus queue with sessions, a vault, a registry and a log workspace, in one resource group. It is meant to be applied for a measured window and destroyed, and nothing here runs by itself: every apply is a person's decision.

The configuration passes `terraform validate` against the provider version in the lock file. Until the first window is recorded in [docs/medicoes.md](../docs/medicoes.md) it has not been applied, and the steps below are the plan and not a report.

## What it costs

About USD 3.48 for 72 hours with everything on, by the estimate in [docs/design/cost-estimate.md](../docs/design/cost-estimate.md). Destroying the resource group ends every charge.

## State

The state contains the generated passwords, so it is kept in a storage account with no public access and reached with the operator's own sign-in. That account is the one thing created by hand, once, outside this configuration:

```
az group create --name rg-frontdesk-state --location northcentralus
az storage account create --name stfrontdeskstate<suffix> --resource-group rg-frontdesk-state \
  --sku Standard_LRS --allow-blob-public-access false --allow-shared-key-access false
az storage container create --name tfstate --account-name stfrontdeskstate<suffix> --auth-mode login
```

The operator needs Storage Blob Data Contributor on it. Then:

```
terraform init \
  -backend-config=resource_group_name=rg-frontdesk-state \
  -backend-config=storage_account_name=stfrontdeskstate<suffix> \
  -backend-config=container_name=tfstate -backend-config=key=demo.tfstate
```

## Applying takes three passes, and why

An app cannot be created before its image is in the registry, and the database firewall cannot name the environment's outbound addresses before the environment exists. So:

1. The registry and the identity that deploys to it.

   ```
   terraform apply -var-file=demo.tfvars \
     -target=azurerm_role_assignment.deploy_pushes_images \
     -target=azurerm_federated_identity_credential.github
   ```

   Put the output `deploy_client_id`, the tenant and the subscription in the repository's secrets, the registry and the resource group in its variables, and run the `deploy` workflow with "push only". It builds both images and pushes them tagged with the commit.

2. Everything else, with that tag.

   ```
   terraform apply -var-file=demo.tfvars -var image_tag=<commit>
   ```

   The apps start and cannot reach the database yet.

3. The firewall, with the addresses the second pass printed.

   ```
   terraform apply -var-file=demo.tfvars -var image_tag=<commit> \
     -var 'database_allowed_ips=["<address>", "<address>"]'
   ```

   Then start the job that creates the roles, the schema and the two demo tenants:

   ```
   az containerapp job start --name caj-frontdesk-setup --resource-group rg-frontdesk-demo
   ```

After that the `deploy` workflow rolls a new commit by itself: it pushes the images, starts the setup job, which migrates, and points the three apps at the new tag.

## Ending the window

```
terraform destroy -var-file=demo.tfvars
```

The vault is purged on destroy, so its name is free for the next window. The storage account of the state is the only thing left, and an empty one costs a fraction of a cent a month.

## What an identity may do

Each app and the job run as their own identity. The API may send to the queue, the worker may receive from it and send to it, the three that call a model hold the inference role on the model resource, each reads from the vault only the secrets it is given by name, and all of them may pull images. The identity GitHub signs in as may push images and change the apps, and may not read a secret or grant a role. Service Bus accepts no connection string.

What is weaker than it should be: the database is reached with a password over a public endpoint behind a firewall rule, and Terraform's own state knows every secret it generated.
