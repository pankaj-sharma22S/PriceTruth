# PriceTruth AI — Kubernetes Architecture & Deployment Guide

This directory contains the production-grade Kubernetes manifests and Kustomize overlays for deploying **PriceTruth AI** across local environments (Docker Desktop Kubernetes / Minikube) and cloud infrastructure (Oracle Cloud Free Tier K3s / OKE).

---

## Architecture Overview

```
                         Internet / Clients
                                 │
                                 ▼
                     [OCI Flexible LoadBalancer /
                    Docker Desktop LoadBalancer:80,443]
                                 │
                                 ▼
                    [NGINX Ingress Controller]
                     (pricetruth.example.com)
                     ┌───────────┴───────────┐
                     │                       │
           Path: /api, /metrics           Path: /
                     │                       │
                     ▼                       ▼
            [Backend Service]       [Frontend Service]
             (ClusterIP:8000)         (ClusterIP:80)
                     │                       │
             ┌───────┴───────┐               ▼
             ▼               ▼        [Frontend Pods]
     [Redis Cache]    [PostgreSQL]     (Nginx Replicas)
     (ClusterIP:6379) (ClusterIP:5432)
     In-Memory Only   StatefulSet +
     allkeys-lru      PVC (10Gi / 50Gi)
```

### Key Architectural Invariants
1. **Strictly In-Memory Redis**:
   - Deployed as a standard `Deployment` (never a StatefulSet).
   - Zero disk persistence (`--save ""` and `--appendonly no`).
   - Strictly bounded memory (`--maxmemory 128mb` and `--maxmemory-policy allkeys-lru`).
   - **No PersistentVolumeClaims (PVCs)**. Cache data is temporary and expendable.
2. **Persistent PostgreSQL**:
   - Deployed as a `StatefulSet` with automated `volumeClaimTemplates` (10Gi local, 50Gi production with `oci-bv` or `local-path`).
   - Health probes verified via `pg_isready`.
3. **Zero Celery / Zero Queue Workers**:
   - Background tasks, scheduled alert evaluations, and discovery jobs run in-process using FastAPI and APScheduler.
   - Status tracking is durably persisted in PostgreSQL (`BackgroundJob` model).
4. **Single External Ingress**:
   - Exactly one external `LoadBalancer` Service exposing NGINX Ingress Controller.
   - All internal services (`backend`, `frontend`, `postgres`, `redis`, `prometheus`, `grafana`) are strictly `ClusterIP`.
   - Kubernetes `NetworkPolicy` isolates database and Redis access exclusively to backend pods.

---

## Directory Structure

```
k8s/
├── base/                                # Reusable foundation
│   ├── namespace.yaml                  # Namespace: pricetruth
│   ├── serviceaccount.yaml             # ServiceAccount: pricetruth-app
│   ├── configmap.yaml                  # Application settings, cache TTLs, rate limits
│   ├── secrets.example.yaml            # Secret template
│   ├── backend/                        # Backend Deployment, ClusterIP Service, HPA
│   ├── frontend/                       # Frontend Deployment, ClusterIP Service
│   ├── redis/                          # Redis in-memory Deployment, ClusterIP Service
│   ├── postgres/                       # Postgres StatefulSet, ClusterIP Service, PVC
│   └── kustomization.yaml
├── networking/                         # Network policies & Ingress
│   ├── ingress.yaml                    # NGINX Ingress rules
│   ├── network-policy.yaml             # Pod isolation network policies
│   ├── nginx-ingress-controller.yaml   # Official NGINX Ingress controller + LoadBalancer
│   └── kustomization.yaml
├── monitoring/                         # Observability stack
│   ├── prometheus/                     # Prometheus scraping backend /metrics
│   ├── grafana/                        # Grafana with pre-provisioned PriceTruth AI dashboard
│   └── kustomization.yaml
├── local/                              # Docker Desktop / Minikube overlay
│   ├── configmap-patch.yaml            # Local development settings (LOG_LEVEL=DEBUG)
│   ├── ingress-patch.yaml              # pricetruth.local routing
│   └── kustomization.yaml
├── production/                         # Oracle Cloud K3s overlay
│   ├── configmap-patch.yaml            # Production settings & higher concurrency
│   ├── ingress-patch.yaml              # Production domain + TLS + SSL redirect
│   ├── postgres-storage-patch.yaml     # 50Gi OCI Block Volume storage patch
│   ├── hpa-patch.yaml                  # Auto-scaling 2 to 10 replicas at 70% CPU
│   ├── secrets.production.example.yaml # Production secrets template
│   └── kustomization.yaml
├── scripts/
│   └── backup_restore.sh               # pg_dump / pg_restore disaster recovery script
└── validate_k8s.py                     # Static verification suite
```

---

## 1. Local Deployment (Docker Desktop Kubernetes / Minikube)

### Prerequisites
- Docker Desktop with Kubernetes enabled.
- NGINX Ingress Controller installed:
  ```bash
  kubectl apply -f k8s/networking/nginx-ingress-controller.yaml
  ```
- Map `pricetruth.local` to `127.0.0.1` in your hosts file (`C:\Windows\System32\drivers\etc\hosts` or `/etc/hosts`):
  ```
  127.0.0.1 pricetruth.local
  ```

### Build Local Container Images
```bash
# Build Backend
docker build -t pricetruth-backend:latest -f backend/Dockerfile backend/

# Build Frontend
docker build -t pricetruth-frontend:latest -f frontend/Dockerfile frontend/
```

### Deploy Local Overlay
```bash
# Review rendered manifests
kubectl kustomize k8s/local

# Apply namespace and secrets first
kubectl apply -f k8s/base/namespace.yaml
kubectl apply -f k8s/base/secrets.example.yaml

# Deploy entire stack
kubectl apply -k k8s/local
```

### Accessing Local Services
- **Web UI & API**: Open [http://pricetruth.local](http://pricetruth.local)
- **API Health**: [http://pricetruth.local/api/health](http://pricetruth.local/api/health)
- **Prometheus Metrics**: [http://pricetruth.local/metrics](http://pricetruth.local/metrics)
- **Grafana Dashboards**: Port-forward `kubectl port-forward -n pricetruth svc/grafana 3000:3000` and open [http://localhost:3000](http://localhost:3000) (admin / admin).

---

## 2. Oracle Cloud Free Tier K3s Deployment

### Why Disable Default K3s Traefik?
K3s includes Traefik by default, binding to ports 80 and 443. To run NGINX Ingress Controller without port conflicts, start K3s with:
```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik" sh -
```
Or if K3s is already running:
```bash
sudo rm -f /var/lib/rancher/k3s/server/manifests/traefik.yaml
```

### Multi-Architecture Builds (Oracle Ampere A1 ARM64 vs AMD64)
Oracle Cloud Free Tier offers up to 4 OCPU and 24GB RAM on Ampere A1 (ARM64). Build and push multi-arch images using Docker Buildx:
```bash
docker buildx create --use
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t <region>.ocir.io/<tenancy>/pricetruth-backend:v1.0.0 \
  -f backend/Dockerfile backend/ --push

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t <region>.ocir.io/<tenancy>/pricetruth-frontend:v1.0.0 \
  -f frontend/Dockerfile frontend/ --push
```

### Apply Production Overlay
```bash
# 1. Create namespace
kubectl apply -f k8s/base/namespace.yaml

# 2. Deploy NGINX Ingress Controller with OCI LoadBalancer integration
kubectl apply -f k8s/networking/nginx-ingress-controller.yaml

# 3. Create production secrets
kubectl apply -f k8s/production/secrets.production.example.yaml

# 4. Deploy production Kustomize overlay
kubectl apply -k k8s/production
```

---

## 3. Database Backup & Disaster Recovery

Run the automated script `k8s/scripts/backup_restore.sh`:

```bash
# Execute compressed binary backup from running pod
bash k8s/scripts/backup_restore.sh backup

# Restore a backup file
bash k8s/scripts/backup_restore.sh restore /path/to/pricetruth_db_20261101_015500.dump
```

To enable direct off-cluster archival to Oracle Cloud Infrastructure (OCI) Object Storage, set:
```bash
export OCI_BACKUP_BUCKET="my-backup-bucket"
export OCI_STORAGE_NAMESPACE="my-tenancy-namespace"
```

---

## 4. Manifest Validation

Run the automated validation suite at any time:
```bash
python k8s/validate_k8s.py
```
This statically verifies YAML syntax, Kustomize builds, Redis in-memory rules, PostgreSQL persistence, and absence of prohibited queue workers or CronJobs.
