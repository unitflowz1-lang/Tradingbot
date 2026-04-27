# RL Trading System Deployment Guide

This guide covers deploying the RL Trading System in production environments using Docker and Kubernetes.

## Overview

The RL Trading System consists of two main components:
- **Training Service**: Handles model training and hyperparameter optimization
- **Inference Service**: Serves trained models for real-time trading decisions

## Prerequisites

### Required Tools
- Docker (>= 20.10)
- Kubernetes (>= 1.24)
- kubectl
- Helm (>= 3.8)

### Cloud Platform Tools
- **AWS**: AWS CLI, eksctl
- **GCP**: gcloud CLI
- **Azure**: az CLI

## Quick Start

### 1. Build Docker Images

```bash
# Build images locally
./scripts/deploy/build-images.sh

# Build and push to registry
export DOCKER_REGISTRY="your-registry.com/rl-trading"
export PUSH_IMAGES="true"
./scripts/deploy/build-images.sh
```

### 2. Deploy to Kubernetes

```bash
# Deploy to existing cluster
./scripts/deploy/deploy-k8s.sh

# Deploy with custom namespace
export K8S_NAMESPACE="my-rl-system"
./scripts/deploy/deploy-k8s.sh
```

## Cloud Platform Deployment

### AWS EKS

```bash
# Set configuration
export EKS_CLUSTER_NAME="rl-trading-cluster"
export AWS_REGION="us-west-2"
export ECR_REGISTRY="123456789012.dkr.ecr.us-west-2.amazonaws.com"

# Deploy
./scripts/deploy/aws-deploy.sh
```

### Google Cloud GKE

```bash
# Set configuration
export GKE_CLUSTER_NAME="rl-trading-cluster"
export GCP_ZONE="us-central1-a"
export GCP_PROJECT_ID="my-project-id"

# Deploy
./scripts/deploy/gcp-deploy.sh
```

## Configuration

### Environment Variables

#### Training Service
- `REDIS_HOST`: Redis server hostname
- `REDIS_PORT`: Redis server port (default: 6379)
- `WORKER_ID`: Unique worker identifier
- `DISTRIBUTED_TRAINING`: Enable distributed training (true/false)

#### Inference Service
- `MODEL_PATH`: Path to model files (default: /app/models)
- `INFERENCE_WORKERS`: Number of worker processes (default: 4)
- `PORT`: Server port (default: 8080)

### Resource Requirements

#### Training Service
- **CPU**: 2-4 cores per replica
- **Memory**: 4-8 GB per replica
- **Storage**: 100 GB for models, 50 GB for logs

#### Inference Service
- **CPU**: 1-2 cores per replica
- **Memory**: 2-4 GB per replica
- **Storage**: 100 GB for models (read-only)

## Monitoring and Health Checks

### Health Endpoints

#### Training Service
- `GET /health`: Overall health status
- `GET /ready`: Readiness check
- `GET /metrics`: Prometheus metrics

#### Inference Service
- `GET /health`: Overall health status
- `GET /ready`: Readiness check
- `GET /metrics`: Prometheus metrics
- `GET /models`: List loaded models

### Prometheus Metrics

Key metrics exposed:
- `rl_system_health_status`: Component health (0/1)
- `rl_system_memory_usage_bytes`: Memory usage
- `rl_system_cpu_usage_percent`: CPU usage
- `rl_inference_requests_total`: Total inference requests
- `rl_model_load_time_seconds`: Model loading time

### Monitoring Setup

Deploy Prometheus monitoring:

```bash
kubectl apply -f k8s/monitoring.yaml
```

Access Prometheus UI:

```bash
kubectl port-forward service/prometheus-service 9090:9090 -n rl-trading
```

## Scaling

### Horizontal Pod Autoscaling

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: rl-inference-hpa
  namespace: rl-trading
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: rl-inference
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### Vertical Pod Autoscaling

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: rl-training-vpa
  namespace: rl-trading
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: rl-training
  updatePolicy:
    updateMode: "Auto"
```

## Security

### Network Policies

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: rl-network-policy
  namespace: rl-trading
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: rl-trading
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          name: rl-trading
  - to: []
    ports:
    - protocol: TCP
      port: 53
    - protocol: UDP
      port: 53
```

### RBAC

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: rl-service-account
  namespace: rl-trading
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: rl-role
  namespace: rl-trading
rules:
- apiGroups: [""]
  resources: ["pods", "services", "configmaps"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: rl-role-binding
  namespace: rl-trading
subjects:
- kind: ServiceAccount
  name: rl-service-account
  namespace: rl-trading
roleRef:
  kind: Role
  name: rl-role
  apiGroup: rbac.authorization.k8s.io
```

## Troubleshooting

### Common Issues

#### Pod Startup Issues
```bash
# Check pod status
kubectl get pods -n rl-trading

# Check pod logs
kubectl logs -f deployment/rl-training -n rl-trading

# Describe pod for events
kubectl describe pod <pod-name> -n rl-trading
```

#### Model Loading Issues
```bash
# Check model availability
kubectl exec -it deployment/rl-inference -n rl-trading -- ls -la /app/models

# Check inference service logs
kubectl logs -f deployment/rl-inference -n rl-trading
```

#### Resource Issues
```bash
# Check resource usage
kubectl top pods -n rl-trading
kubectl top nodes

# Check resource limits
kubectl describe deployment rl-training -n rl-trading
```

### Performance Tuning

#### Training Performance
- Increase `batch_size` for better GPU utilization
- Use multiple workers for data loading
- Enable gradient compression for distributed training

#### Inference Performance
- Increase `INFERENCE_WORKERS` for higher throughput
- Use model quantization for faster inference
- Enable batch inference for multiple requests

## Backup and Recovery

### Model Backup
```bash
# Backup models to cloud storage
kubectl create job model-backup --from=cronjob/model-backup-cron -n rl-trading
```

### Configuration Backup
```bash
# Export configurations
kubectl get configmap rl-config -n rl-trading -o yaml > rl-config-backup.yaml
```

## Updates and Rollbacks

### Rolling Updates
```bash
# Update image
kubectl set image deployment/rl-inference rl-inference=rl-trading/inference:v2.0 -n rl-trading

# Check rollout status
kubectl rollout status deployment/rl-inference -n rl-trading
```

### Rollbacks
```bash
# Rollback to previous version
kubectl rollout undo deployment/rl-inference -n rl-trading

# Rollback to specific revision
kubectl rollout undo deployment/rl-inference --to-revision=2 -n rl-trading
```