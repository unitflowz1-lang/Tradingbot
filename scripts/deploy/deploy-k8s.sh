#!/bin/bash
# Deploy RL system to Kubernetes

set -e

# Configuration
NAMESPACE=${K8S_NAMESPACE:-"rl-trading"}
CONTEXT=${K8S_CONTEXT:-""}
DRY_RUN=${DRY_RUN:-"false"}

echo "Deploying RL Trading System to Kubernetes..."
echo "Namespace: $NAMESPACE"

# Set kubectl context if specified
if [ -n "$CONTEXT" ]; then
    echo "Using context: $CONTEXT"
    kubectl config use-context $CONTEXT
fi

# Dry run flag
DRY_RUN_FLAG=""
if [ "$DRY_RUN" = "true" ]; then
    DRY_RUN_FLAG="--dry-run=client"
    echo "Running in dry-run mode"
fi

# Create namespace
echo "Creating namespace..."
kubectl apply $DRY_RUN_FLAG -f k8s/namespace.yaml

# Apply storage configurations
echo "Applying storage configurations..."
kubectl apply $DRY_RUN_FLAG -f k8s/storage.yaml

# Apply config maps
echo "Applying config maps..."
kubectl apply $DRY_RUN_FLAG -f k8s/configmap.yaml

# Deploy Redis
echo "Deploying Redis..."
kubectl apply $DRY_RUN_FLAG -f k8s/redis-deployment.yaml

# Wait for Redis to be ready (if not dry run)
if [ "$DRY_RUN" != "true" ]; then
    echo "Waiting for Redis to be ready..."
    kubectl wait --for=condition=available --timeout=300s deployment/redis -n $NAMESPACE
fi

# Deploy training components
echo "Deploying training components..."
kubectl apply $DRY_RUN_FLAG -f k8s/training-deployment.yaml

# Deploy inference components
echo "Deploying inference components..."
kubectl apply $DRY_RUN_FLAG -f k8s/inference-deployment.yaml

if [ "$DRY_RUN" != "true" ]; then
    # Wait for deployments to be ready
    echo "Waiting for deployments to be ready..."
    kubectl wait --for=condition=available --timeout=600s deployment/rl-training -n $NAMESPACE
    kubectl wait --for=condition=available --timeout=600s deployment/rl-inference -n $NAMESPACE
    
    # Show deployment status
    echo "Deployment status:"
    kubectl get pods -n $NAMESPACE
    kubectl get services -n $NAMESPACE
    
    # Get service endpoints
    echo "Service endpoints:"
    kubectl get service rl-inference-service -n $NAMESPACE -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
fi

echo "Deployment completed successfully!"