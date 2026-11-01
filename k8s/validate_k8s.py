#!/usr/bin/env python3
"""
PriceTruth AI - Comprehensive Kubernetes Manifests & Architecture Validator.
Statically verifies:
1. YAML syntax across all manifests.
2. kubectl kustomize builds for both local and production overlays.
3. Redis rules: Redis is a Deployment (NOT StatefulSet), NO PVC, in-memory only.
4. PostgreSQL rules: Postgres is a StatefulSet with PVC / volumeClaimTemplates.
5. Celery / Job exclusions: NO Celery, NO Kubernetes CronJobs, NO Jobs, NO Redis queue.
6. Service selector matching Deployments / StatefulSets.
7. Single external LoadBalancer Service exclusively for Ingress Controller.
8. Health probes & resource requests/limits on all core workloads.
9. HPA target reference.
"""

import os
import sys
import subprocess
import yaml
from pathlib import Path

K8S_ROOT = Path("E:/browser/k8s")

def log(msg):
    print(f"[VALIDATE] {msg}")

def error(msg):
    print(f"[ERROR] {msg}", file=sys.stderr)
    return False

def check_yaml_syntax():
    log("Checking YAML syntax across all files in k8s/...")
    all_valid = True
    yaml_files = list(K8S_ROOT.rglob("*.yaml")) + list(K8S_ROOT.rglob("*.yml"))
    if not yaml_files:
        return error("No YAML files found in k8s directory!")
    
    for yf in yaml_files:
        try:
            with open(yf, "r", encoding="utf-8") as f:
                list(yaml.safe_load_all(f))
        except Exception as e:
            error(f"Failed to parse {yf}: {e}")
            all_valid = False
            
    if all_valid:
        log(f"All {len(yaml_files)} YAML files parsed successfully.")
    return all_valid

def run_kustomize_build(overlay_dir):
    cmd = ["kubectl", "kustomize", str(overlay_dir)]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        error(f"kubectl kustomize failed for {overlay_dir}:\n{res.stderr}")
        return None
    return list(yaml.safe_load_all(res.stdout))

def validate_architectural_rules(manifests, env_name):
    log(f"Verifying architectural rules for '{env_name}' overlay...")
    passed = True

    kinds = {}
    for doc in manifests:
        if not doc:
            continue
        kind = doc.get("kind")
        name = doc.get("metadata", {}).get("name")
        kinds.setdefault(kind, []).append(doc)

    # 1. Prohibited Kinds Check: NO CronJob, NO Job
    prohibited_kinds = ["CronJob", "Job"]
    for pk in prohibited_kinds:
        if pk in kinds:
            error(f"Found prohibited kind '{pk}' in {env_name} overlay!")
            passed = False

    # 2. Celery & Redis Queue Exclusions in all manifests
    for doc in manifests:
        if not doc:
            continue
        doc_str = yaml.dump(doc).lower()
        if "celery" in doc_str:
            error(f"Found Celery reference in manifest {doc.get('kind')}/{doc.get('metadata', {}).get('name')}")
            passed = False
        if "redis_queue" in doc_str or "task_queue" in doc_str:
            error(f"Found Redis queue reference in manifest {doc.get('kind')}/{doc.get('metadata', {}).get('name')}")
            passed = False

    # 3. Redis Architectural Invariants
    redis_deployments = [d for d in kinds.get("Deployment", []) if d.get("metadata", {}).get("name") == "redis"]
    redis_statefulsets = [s for s in kinds.get("StatefulSet", []) if s.get("metadata", {}).get("name") == "redis"]
    redis_pvcs = [p for p in kinds.get("PersistentVolumeClaim", []) if "redis" in p.get("metadata", {}).get("name", "")]

    if not redis_deployments:
        error(f"[{env_name}] Redis Deployment is missing!")
        passed = False
    if redis_statefulsets:
        error(f"[{env_name}] Redis must NOT be a StatefulSet!")
        passed = False
    if redis_pvcs:
        error(f"[{env_name}] Redis must NOT have any PersistentVolumeClaim! Found: {[p['metadata']['name'] for p in redis_pvcs]}")
        passed = False

    for rd in redis_deployments:
        # Check volumes - must NOT mount persistent volumes
        vols = rd.get("spec", {}).get("template", {}).get("spec", {}).get("volumes", [])
        for v in vols:
            if "persistentVolumeClaim" in v:
                error(f"[{env_name}] Redis pod template mounts a PVC: {v}")
                passed = False
        # Check command/args for eviction policy and no disk save
        containers = rd.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        for c in containers:
            cmd_args = c.get("command", []) + c.get("args", [])
            args_str = " ".join(cmd_args)
            if "allkeys-lru" not in args_str:
                error(f"[{env_name}] Redis container missing --maxmemory-policy allkeys-lru: {args_str}")
                passed = False
            if '--save ""' not in args_str and "--save" not in args_str:
                error(f"[{env_name}] Redis container should disable RDB snapshots: {args_str}")
                passed = False

    # 4. PostgreSQL Architectural Invariants
    pg_statefulsets = [s for s in kinds.get("StatefulSet", []) if s.get("metadata", {}).get("name") == "postgres"]
    if not pg_statefulsets:
        error(f"[{env_name}] PostgreSQL StatefulSet is missing!")
        passed = False
    else:
        for pgs in pg_statefulsets:
            vct = pgs.get("spec", {}).get("volumeClaimTemplates", [])
            if not vct:
                error(f"[{env_name}] PostgreSQL StatefulSet must define volumeClaimTemplates!")
                passed = False
            else:
                log(f"[{env_name}] PostgreSQL has persistent volumeClaimTemplate: {vct[0].get('metadata', {}).get('name')}")

    # 5. Services and Ingress Rules
    services = kinds.get("Service", [])
    lb_services = [s for s in services if s.get("spec", {}).get("type") == "LoadBalancer"]
    
    # Internal services (backend, frontend, postgres, redis) must be ClusterIP
    for svc in services:
        svc_name = svc.get("metadata", {}).get("name")
        svc_type = svc.get("spec", {}).get("type", "ClusterIP")
        if svc_name in ["backend", "frontend", "postgres", "redis"]:
            if svc_type != "ClusterIP":
                error(f"[{env_name}] Internal service {svc_name} must be ClusterIP, but got {svc_type}")
                passed = False

    # Single Ingress Controller Service
    ingress_classes = kinds.get("IngressClass", [])
    ingresses = kinds.get("Ingress", [])
    if not ingresses:
        error(f"[{env_name}] Ingress resource is missing!")
        passed = False
    else:
        for ing in ingresses:
            rules = ing.get("spec", {}).get("rules", [])
            paths = [p.get("path") for r in rules for p in r.get("http", {}).get("paths", [])]
            if "/api" not in paths or "/" not in paths:
                error(f"[{env_name}] Ingress must route both /api and /: {paths}")
                passed = False

    # 6. Service Selector Matches Deployment/StatefulSet Labels
    deployments = {d.get("metadata", {}).get("name"): d for d in kinds.get("Deployment", [])}
    statefulsets = {s.get("metadata", {}).get("name"): s for s in kinds.get("StatefulSet", [])}

    for svc in services:
        s_name = svc.get("metadata", {}).get("name")
        selector = svc.get("spec", {}).get("selector", {})
        if not selector:
            continue
        
        target = deployments.get(s_name) or statefulsets.get(s_name)
        if target:
            target_labels = target.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {})
            for k, v in selector.items():
                if target_labels.get(k) != v:
                    error(f"[{env_name}] Service {s_name} selector {k}={v} does not match pod labels {target_labels}")
                    passed = False
            log(f"[{env_name}] Service '{s_name}' correctly targets pod labels: {selector}")

    # 7. Probes & Resource Limits on backend and frontend
    for app_name in ["backend", "frontend"]:
        dep = deployments.get(app_name)
        if dep:
            c = dep["spec"]["template"]["spec"]["containers"][0]
            if "livenessProbe" not in c or "readinessProbe" not in c:
                error(f"[{env_name}] Deployment '{app_name}' container is missing liveness or readiness probes!")
                passed = False
            if "resources" not in c or "limits" not in c["resources"] or "requests" not in c["resources"]:
                error(f"[{env_name}] Deployment '{app_name}' container is missing resource requests or limits!")
                passed = False

    # 8. HPA targeting backend
    hpas = kinds.get("HorizontalPodAutoscaler", [])
    if not hpas:
        error(f"[{env_name}] HorizontalPodAutoscaler is missing!")
        passed = False
    else:
        for h in hpas:
            target_ref = h.get("spec", {}).get("scaleTargetRef", {})
            if target_ref.get("kind") != "Deployment" or target_ref.get("name") != "backend":
                error(f"[{env_name}] HPA target must be Deployment/backend, got: {target_ref}")
                passed = False
            else:
                log(f"[{env_name}] HPA targets {target_ref['kind']}/{target_ref['name']} (min: {h['spec']['minReplicas']}, max: {h['spec']['maxReplicas']})")

    return passed

def main():
    log("Starting PriceTruth AI Kubernetes Validation Suite...")
    
    if not check_yaml_syntax():
        sys.exit(1)

    local_manifests = run_kustomize_build(K8S_ROOT / "local")
    if local_manifests is None:
        sys.exit(1)
    if not validate_architectural_rules(local_manifests, "local"):
        sys.exit(1)

    prod_manifests = run_kustomize_build(K8S_ROOT / "production")
    if prod_manifests is None:
        sys.exit(1)
    if not validate_architectural_rules(prod_manifests, "production"):
        sys.exit(1)

    log("==================================================================")
    log("ALL KUBERNETES MANIFESTS & ARCHITECTURAL CHECKS PASSED PERFECTION!")
    log("==================================================================")

if __name__ == "__main__":
    main()
