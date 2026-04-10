# External Secrets Configuration for AgentProvision

This directory contains the External Secrets Operator configuration for syncing secrets from GCP Secret Manager.

## Prerequisites

1. **Install External Secrets Operator**
   ```bash
   helm repo add external-secrets https://charts.external-secrets.io
   helm install external-secrets external-secrets/external-secrets \
     --namespace external-secrets \
     --create-namespace \
     --set installCRDs=true
   ```

2. **Create GCP Service Account**
   ```bash
   # Create service account for External Secrets
   gcloud iam service-accounts create external-secrets \
     --display-name="External Secrets Operator" \
     --project=YOUR_GCP_PROJECT

   # Grant Secret Manager access
   gcloud projects add-iam-policy-binding YOUR_GCP_PROJECT \
     --member="serviceAccount:external-secrets@YOUR_GCP_PROJECT.iam.gserviceaccount.com" \
     --role="roles/secretmanager.secretAccessor"

   # Create Workload Identity binding
   gcloud iam service-accounts add-iam-policy-binding external-secrets@YOUR_GCP_PROJECT.iam.gserviceaccount.com \
     --role="roles/iam.workloadIdentityUser" \
     --member="serviceAccount:YOUR_GCP_PROJECT.svc.id.goog[prod/external-secrets-sa]"

   gcloud iam service-accounts add-iam-policy-binding external-secrets@YOUR_GCP_PROJECT.iam.gserviceaccount.com \
     --role="roles/iam.workloadIdentityUser" \
     --member="serviceAccount:YOUR_GCP_PROJECT.svc.id.goog[database/external-secrets-sa]"
   ```

3. **Create Secrets in GCP Secret Manager**
   ```bash
   # API secrets
   echo -n "your-jwt-secret-key" | gcloud secrets create agentprovision-secret-key --data-file=-
   echo -n "postgresql://user:pass@host:5432/agentprovision" | gcloud secrets create agentprovision-database-url --data-file=-
   echo -n "sk-ant-api03-xxx" | gcloud secrets create agentprovision-anthropic-api-key --data-file=-
   echo -n "your-mcp-api-key" | gcloud secrets create agentprovision-mcp-api-key --data-file=-
   echo -n "your-internal-key" | gcloud secrets create agentprovision-api-internal-key --data-file=-

   # Database secrets
   echo -n "your-postgres-password" | gcloud secrets create agentprovision-postgres-password --data-file=-

   # Temporal secrets
   echo -n "temporal-postgres-password" | gcloud secrets create temporal-postgres-password --data-file=-
   echo -n "postgresql-host" | gcloud secrets create temporal-postgres-host --data-file=-
   ```

## Required Secrets

| Secret Name | Description | Used By |
|------------|-------------|---------|
| `agentprovision-secret-key` | JWT signing key | API |
| `agentprovision-database-url` | PostgreSQL connection string | API, Worker |
| `agentprovision-anthropic-api-key` | Claude AI API key | API |
| `agentprovision-mcp-api-key` | MCP server authentication | API, Worker |
| `agentprovision-api-internal-key` | Service-to-service auth | API, Worker, MCP |
| `agentprovision-postgres-password` | PostgreSQL password | PostgreSQL |
| `temporal-postgres-password` | Temporal DB password | Temporal |
| `temporal-postgres-host` | Temporal DB host | Temporal |

## Verification

```bash
# Check SecretStore status
kubectl get secretstore -n prod

# Check ExternalSecret sync status
kubectl get externalsecret -n prod

# View synced secrets
kubectl get secrets -n prod
```
