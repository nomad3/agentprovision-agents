# AgentProvision Helm Charts

This directory contains Helm charts for deploying AgentProvision to Kubernetes.

## Structure

```
helm/
├── charts/
│   └── microservice/           # Reusable base chart for all services
│       ├── Chart.yaml
│       ├── values.yaml
│       └── templates/
└── values/
    ├── agentprovision-api.yaml    # API service values
    ├── agentprovision-web.yaml    # Web frontend values
    ├── agentprovision-worker.yaml # PostgreSQL worker values
    ├── temporal.yaml              # Temporal server values
    ├── temporal-web.yaml          # Temporal Web UI values
    ├── postgresql.yaml            # PostgreSQL values
    └── redis.yaml                 # Redis values
```

## Quick Start

### Prerequisites

- Kubernetes cluster (GKE recommended)
- Helm 3.x installed
- kubectl configured

### Deploy a service

```bash
# Set your GCP project
export GCP_PROJECT=your-project-id

# Update placeholder values
sed -i "s/YOUR_GCP_PROJECT/$GCP_PROJECT/g" values/*.yaml

# Deploy API service
helm upgrade --install agentprovision-api \
  ./charts/microservice \
  --namespace prod \
  --create-namespace \
  --values ./values/agentprovision-api.yaml

# Deploy Web frontend
helm upgrade --install agentprovision-web \
  ./charts/microservice \
  --namespace prod \
  --values ./values/agentprovision-web.yaml
```

## DRY Principle

This setup follows the DRY (Don't Repeat Yourself) principle:

1. **Single Base Chart**: All services use the same `microservice` chart
2. **Values Files**: Service-specific configuration in separate values files
3. **Shared Templates**: Common templates (deployment, service, etc.) are reused

### Customizing per Service

Each values file only needs to specify what's different from defaults:

```yaml
# Example: agentprovision-api.yaml
nameOverride: "agentprovision-api"
image:
  repository: gcr.io/project/agentprovision-api
container:
  port: 8000
resources:
  requests:
    cpu: 200m
    memory: 512Mi
```

## Key Features

### External Secrets

Integrates with GCP Secret Manager:

```yaml
externalSecret:
  enabled: true
  data:
    - secretKey: DATABASE_URL
      remoteRef:
        key: agentprovision-database-url
```

### Health Checks

Configurable liveness and readiness probes:

```yaml
livenessProbe:
  enabled: true
  httpGet:
    path: /health
    port: http
  initialDelaySeconds: 30
```

### Autoscaling

Horizontal Pod Autoscaler support:

```yaml
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
```

### Gateway API

Modern ingress with GKE Gateway:

```yaml
httpRoute:
  enabled: true
  parentRefs:
    - name: agentprovision-gateway
      namespace: gateway-system
  hostnames:
    - "agentprovision.com"
```

## Template Reference

| Template | Purpose |
|----------|---------|
| `deployment.yaml` | Main pod deployment |
| `service.yaml` | Kubernetes Service |
| `configmap.yaml` | Non-sensitive configuration |
| `externalsecret.yaml` | GCP Secret Manager sync |
| `serviceaccount.yaml` | Service account with Workload Identity |
| `hpa.yaml` | Horizontal Pod Autoscaler |
| `pdb.yaml` | Pod Disruption Budget |
| `pvc.yaml` | Persistent Volume Claim |
| `httproute.yaml` | Gateway API HTTPRoute |
| `migration-job.yaml` | Pre-deploy migrations |
| `nginx-config.yaml` | Nginx configuration |
| `managed-cert.yaml` | GCP Managed Certificate |
| `health-check-policy.yaml` | GKE Health Check Policy |

## Values Reference

See `charts/microservice/values.yaml` for all available options with comments.

### Common Values

```yaml
# Image configuration
image:
  repository: gcr.io/project/service
  tag: latest
  pullPolicy: IfNotPresent

# Replica count
replicaCount: 2

# Container port
container:
  port: 8000

# Resources
resources:
  requests:
    cpu: 100m
    memory: 256Mi
  limits:
    cpu: 500m
    memory: 512Mi

# Enable ConfigMap
configMap:
  enabled: true
  data:
    KEY: "value"

# Enable External Secrets
externalSecret:
  enabled: true
  data:
    - secretKey: SECRET_NAME
      remoteRef:
        key: gcp-secret-name
```

## Debugging

```bash
# Render templates without deploying
helm template agentprovision-api ./charts/microservice \
  --values ./values/agentprovision-api.yaml

# Debug installation
helm upgrade --install agentprovision-api ./charts/microservice \
  --values ./values/agentprovision-api.yaml \
  --debug --dry-run

# Check release status
helm status agentprovision-api -n prod

# View release history
helm history agentprovision-api -n prod
```
