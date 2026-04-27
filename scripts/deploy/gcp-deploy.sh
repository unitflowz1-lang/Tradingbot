#!/bin/bash
# Deploy RL system to Google Cloud GKE

set -e

# Configuration
CLUSTER_NAME=${GKE_CLUSTER_NAME:-"rl-trading-cluster"}
ZONE=${GCP_ZONE:-"us-central1-a"}
PROJECT_ID=${GCP_PROJECT_ID:-""}
NAMESPACE=${K8S_NAMESPACE:-"rl-trading"}

echo "Deploying RL Trading System to Google Cloud GKE..."
echo "Cluster: $CLUSTER_NAME"
echo "Zone: $ZONE"
echo "Project: $PROJECT_ID"

# Check required tools
if ! command -v gcloud &> /dev/null; then
    echo "gcloud CLI not found. Please install Google Cloud SDK."
    exit 1
fi

if ! command -v kubectl &> /dev/null; then
    echo "kubectl not found. Please install kubectl."
    exit 1
fi

# Set project
if [ -n "$PROJECT_ID" ]; then
    gcloud config set project $PROJECT_ID
fi

# Get cluster credentials
echo "Getting cluster credentials..."
gcloud container clusters get-credentials $CLUSTER_NAME --zone $ZONE

# Enable required APIs
echo "Enabling required APIs..."
gcloud services enable container.googleapis.com
gcloud services enable containerregistry.googleapis.com

# Build and push images to GCR
echo "Building and pushing images to Google Container Registry..."
export DOCKER_REGISTRY="gcr.io/$PROJECT_ID/rl-trading"
export PUSH_IMAGES="true"

# Configure Docker for GCR
gcloud auth configure-docker

# Build images
./scripts/deploy/build-images.sh

# Create GKE-specific storage class
echo "Creating GKE storage class..."
cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
provisioner: kubernetes.io/gce-pd
parameters:
  type: pd-ssd
  replication-type: none
allowVolumeExpansion: true
---
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: standard
provisioner: kubernetes.io/gce-pd
parameters:
  type: pd-standard
  replication-type: none
allowVolumeExpansion: true
EOF

# Deploy to Kubernetes
echo "Deploying to Kubernetes..."
export K8S_NAMESPACE=$NAMESPACE
./scripts/deploy/deploy-k8s.sh

# Create load balancer service
echo "Creating load balancer..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: rl-inference-lb
  namespace: $NAMESPACE
  annotations:
    cloud.google.com/load-balancer-type: "External"
spec:
  type: LoadBalancer
  selector:
    app: rl-inference
    component: inference
  ports:
  - name: http
    port: 80
    targetPort: 8080
    protocol: TCP
EOF

# Wait for load balancer IP
echo "Waiting for load balancer IP..."
kubectl wait --for=jsonpath='{.status.loadBalancer.ingress[0].ip}' service/rl-inference-lb -n $NAMESPACE --timeout=300s

# Get external IP
EXTERNAL_IP=$(kubectl get service rl-inference-lb -n $NAMESPACE -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

echo "GKE deployment completed successfully!"
echo "External IP: $EXTERNAL_IP"
echo "Health check: http://$EXTERNAL_IP/health"