# AgentProvision Kubernetes Deployment Guide

This guide covers deploying AgentProvision to Google Kubernetes Engine (GKE) using Helm charts and GitHub Actions.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         GKE Cluster                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                    gateway-system namespace                          ││
│  │  ┌─────────────────────────────────────────────────────────────┐    ││
│  │  │  GKE Gateway (L7 Global External Managed)                   │    ││
│  │  │  - HTTPS (443) with GCP Managed Certificate                 │    ││
│  │  │  - HTTP (80) → HTTPS redirect                               │    ││
│  │  └─────────────────────────────────────────────────────────────┘    ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                    │                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                       prod namespace                                 ││
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               ││
│  │  │     Web      │  │     API      │  │    Worker    │               ││
│  │  │   (Nginx)    │──│  (FastAPI)   │──│  (Temporal)  │               ││
│  │  └──────────────┘  └──────────────┘  └──────────────┘               ││
│  │         │                 │                 │                        ││
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               ││
│  │  │    Redis     │  │   Temporal   │  │  MCP Server  │               ││
│  │  │   (Cache)    │  │   (Workflows)│  │   (Shared)   │               ││
│  │  └──────────────┘  └──────────────┘  └──────────────┘               ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                    │                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                     database namespace                               ││
│  │  ┌──────────────────────────────────────────────────────┐           ││
│  │  │              PostgreSQL (or Cloud SQL)                │           ││
│  │  └──────────────────────────────────────────────────────┘           ││
│  └─────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

### 1. GKE Cluster

Ensure you have a GKE cluster with:
- Workload Identity enabled
- Gateway API enabled (for GKE Gateway)
- Kubernetes version 1.27+

```bash
# Create cluster (if needed)
gcloud container clusters create agentprovision-cluster \
  --zone us-central1-a \
  --num-nodes 3 \
  --machine-type e2-medium \
  --workload-pool=YOUR_PROJECT.svc.id.goog \
  --gateway-api=standard
```

### 2. GitHub Repository Variables

Set these in your GitHub repository settings (Settings > Secrets and variables > Actions):

**Variables:**
- `GCP_PROJECT`: Your GCP project ID
- `GCP_REGION`: GCP region (e.g., `us-central1`)
- `GKE_CLUSTER`: GKE cluster name
- `GKE_ZONE`: GKE cluster zone (e.g., `us-central1-a`)

**Secrets:**
- `GCP_SA_KEY`: JSON key for a GCP service account with permissions:
  - `roles/container.developer`
  - `roles/storage.admin` (for GCR)
  - `roles/secretmanager.secretAccessor`

### 3. GCP Secret Manager

Create secrets in GCP Secret Manager:

```bash
# Required secrets
gcloud secrets create agentprovision-secret-key --data-file=<(echo -n "your-jwt-secret")
gcloud secrets create agentprovision-database-url --data-file=<(echo -n "postgresql://...")
gcloud secrets create agentprovision-anthropic-api-key --data-file=<(echo -n "sk-ant-...")
gcloud secrets create agentprovision-mcp-api-key --data-file=<(echo -n "your-mcp-key")
gcloud secrets create agentprovision-api-internal-key --data-file=<(echo -n "your-internal-key")
gcloud secrets create agentprovision-postgres-password --data-file=<(echo -n "your-db-password")
```

### 4. DNS Configuration

After deploying infrastructure, configure DNS A records:
- `agentprovision.com` → Gateway IP
- `www.agentprovision.com` → Gateway IP
- `api.agentprovision.com` → Gateway IP

## Deployment

### Rapid Runbook (GitHub Actions + kubectl)

1. **Push latest code**
   ```bash
   git push origin main
   ```
2. **Kick off the full stack deploy pipeline** (skips infra rebuild unless needed):
   ```bash
   gh workflow run deploy-all.yaml -f deploy_infrastructure=false -f environment=prod
   ```
3. **Publish the ADK server image + Helm release** when agent logic changes:
   ```bash
   gh workflow run adk-deploy.yaml -f deploy=true -f environment=prod
   ```
4. **Watch rollout status** directly from the cluster:
   ```bash
   kubectl get pods -n prod -w
   kubectl rollout status deployment/agentprovision-api -n prod
   kubectl rollout status deployment/agentprovision-adk -n prod
   ```
5. **Validate Helm releases** for all microservices:
   ```bash
   helm list -n prod | grep agentprovision
   helm status agentprovision-adk -n prod
   ```

These commands ensure the same artifacts built in CI/CD are promoted to the cluster via the Helm chart definitions checked into `helm/`.

### Initial Infrastructure Deployment

1. **Manual trigger via GitHub Actions:**
   - Go to Actions tab
   - Select "Deploy Kubernetes Infrastructure"
   - Click "Run workflow"
   - Choose environment: `prod`

2. **Or via CLI:**
   ```bash
   gh workflow run kubernetes-infrastructure.yaml -f environment=prod
   ```

This will:
- Create global IP address
- Deploy namespaces with Pod Security Standards
- Deploy Gateway API resources
- Install External Secrets Operator
- Configure SecretStores

### Deploy All Services

1. **First deployment (includes infrastructure):**
   ```bash
   gh workflow run deploy-all.yaml \
     -f deploy_infrastructure=true \
     -f environment=prod
   ```

2. **Subsequent deployments:**
   ```bash
   gh workflow run deploy-all.yaml \
     -f deploy_infrastructure=false \
     -f environment=prod
   ```

### Deploy Individual Services

Services are automatically deployed on push to `main`:

- **API**: Triggers on changes to `apps/api/**`
- **Web**: Triggers on changes to `apps/web/**`
- **Worker**: Follows API deployment

Manual deployment:
```bash
# Deploy API
gh workflow run agentprovision-api.yaml -f deploy=true

# Deploy Web
gh workflow run agentprovision-web.yaml -f deploy=true

# Deploy Worker
gh workflow run agentprovision-worker.yaml -f deploy=true
```

## Helm Chart Structure

```
helm/
├── charts/
│   └── microservice/           # Reusable base chart
│       ├── Chart.yaml
│       ├── values.yaml         # Default values
│       └── templates/
│           ├── _helpers.tpl
│           ├── deployment.yaml
│           ├── service.yaml
│           ├── configmap.yaml
│           ├── externalsecret.yaml
│           ├── serviceaccount.yaml
│           ├── hpa.yaml
│           ├── pdb.yaml
│           ├── pvc.yaml
│           ├── httproute.yaml
│           ├── migration-job.yaml
│           ├── nginx-config.yaml
│           ├── managed-cert.yaml
│           └── health-check-policy.yaml
└── values/
    ├── agentprovision-api.yaml
    ├── agentprovision-web.yaml
    ├── agentprovision-worker.yaml
    ├── temporal.yaml
    ├── temporal-web.yaml
    ├── postgresql.yaml
    └── redis.yaml
```

## Local Development with Helm

### Install dependencies

```bash
# Get cluster credentials
gcloud container clusters get-credentials $GKE_CLUSTER --zone $GKE_ZONE

# Verify connection
kubectl cluster-info
```

### Deploy manually

```bash
# Replace placeholder values
export GCP_PROJECT=your-project-id
sed -i "s/YOUR_GCP_PROJECT/$GCP_PROJECT/g" helm/values/*.yaml

# Deploy a service
helm upgrade --install agentprovision-api \
  ./helm/charts/microservice \
  --namespace prod \
  --values ./helm/values/agentprovision-api.yaml \
  --set image.tag=latest \
  --dry-run  # Remove for actual deployment
```

### Debug

```bash
# Check deployment status
kubectl get deployments -n prod

# Check pods
kubectl get pods -n prod

# View logs
kubectl logs -n prod -l app.kubernetes.io/name=agentprovision-api -f

# Describe pod
kubectl describe pod -n prod -l app.kubernetes.io/name=agentprovision-api

# Check External Secrets
kubectl get externalsecrets -n prod
kubectl describe externalsecret agentprovision-api -n prod
```

## Monitoring

### Health Checks

Each service exposes health endpoints:
- **API**: `GET /api/v1/`
- **Web**: `GET /health`
- **Temporal Web**: `GET /`

### Logs

```bash
# API logs
kubectl logs -n prod -l app.kubernetes.io/name=agentprovision-api -f

# Web logs
kubectl logs -n prod -l app.kubernetes.io/name=agentprovision-web -f

# Worker logs
kubectl logs -n prod -l app.kubernetes.io/name=agentprovision-worker -f
```

### Metrics

The HPA monitors:
- CPU utilization (target: 70%)
- Memory utilization (target: 80%)

```bash
# Check HPA status
kubectl get hpa -n prod

# Check resource usage
kubectl top pods -n prod
```

## Scaling

### Automatic Scaling

HPA is configured for API and Web services:

| Service | Min Replicas | Max Replicas | CPU Target | Memory Target |
|---------|--------------|--------------|------------|---------------|
| API     | 2            | 10           | 70%        | 80%           |
| Web     | 2            | 8            | 80%        | 85%           |

### Manual Scaling

```bash
# Scale API
kubectl scale deployment agentprovision-api -n prod --replicas=5

# Or update HPA
kubectl patch hpa agentprovision-api -n prod -p '{"spec":{"minReplicas":3}}'
```

## Troubleshooting

### Gateway Issues

```bash
# Check Gateway status
kubectl get gateway -n gateway-system
kubectl describe gateway agentprovision-gateway -n gateway-system

# Check HTTPRoutes
kubectl get httproutes -A
kubectl describe httproute agentprovision-web -n prod
```

### Secret Issues

```bash
# Check SecretStore status
kubectl get secretstore -n prod
kubectl describe secretstore gcp-secret-store -n prod

# Check ExternalSecret sync
kubectl get externalsecrets -n prod
kubectl describe externalsecret agentprovision-api -n prod

# View synced secret
kubectl get secret agentprovision-api-secret -n prod -o yaml
```

### Pod Crashes

```bash
# Check pod events
kubectl describe pod -n prod -l app.kubernetes.io/name=agentprovision-api

# Check previous logs
kubectl logs -n prod -l app.kubernetes.io/name=agentprovision-api --previous

# Exec into pod
kubectl exec -it -n prod deployment/agentprovision-api -- /bin/bash
```

## Security

### Pod Security Standards

All namespaces enforce Pod Security Standards:
- `prod`: `restricted` (strictest)
- `database`: `baseline` (allows DB-specific permissions)
- `monitoring`: `baseline`

### Network Policies

Network policies restrict traffic:
- Default deny all ingress
- Explicit allow for:
  - Gateway → Web/API
  - Web → API
  - API → MCP Server
  - API/Worker → Temporal
  - All prod → PostgreSQL

### Workload Identity

Services use Workload Identity for GCP authentication:
- No service account keys in pods
- Fine-grained IAM permissions
- Automatic credential rotation

## Rollback

```bash
# List release history
helm history agentprovision-api -n prod

# Rollback to previous release
helm rollback agentprovision-api -n prod

# Rollback to specific revision
helm rollback agentprovision-api 2 -n prod
```

## Cost Optimization

### Recommendations

1. **Use GKE Autopilot** for automatic node management
2. **Right-size resources** based on actual usage
3. **Enable cluster autoscaler** for node-level scaling
4. **Use preemptible VMs** for non-critical workloads

### Resource Estimates

| Service    | CPU Request | Memory Request | Monthly Cost (est.) |
|------------|-------------|----------------|---------------------|
| API (2)    | 400m        | 1Gi            | ~$30                |
| Web (2)    | 100m        | 256Mi          | ~$10                |
| Worker (1) | 100m        | 256Mi          | ~$5                 |
| Temporal   | 500m        | 1Gi            | ~$15                |
| Redis      | 50m         | 128Mi          | ~$5                 |
| PostgreSQL | 250m        | 512Mi          | ~$15                |
| **Total**  |             |                | **~$80/month**      |

*Note: Using Cloud SQL instead of in-cluster PostgreSQL will increase costs but improve reliability.*
