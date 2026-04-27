#!/bin/bash
# Deploy RL system to AWS EKS

set -e

# Configuration
CLUSTER_NAME=${EKS_CLUSTER_NAME:-"rl-trading-cluster"}
REGION=${AWS_REGION:-"us-west-2"}
ECR_REGISTRY=${ECR_REGISTRY:-""}
NAMESPACE=${K8S_NAMESPACE:-"rl-trading"}

echo "Deploying RL Trading System to AWS EKS..."
echo "Cluster: $CLUSTER_NAME"
echo "Region: $REGION"

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo "AWS CLI not found. Please install AWS CLI."
    exit 1
fi

# Check kubectl
if ! command -v kubectl &> /dev/null; then
    echo "kubectl not found. Please install kubectl."
    exit 1
fi

# Update kubeconfig
echo "Updating kubeconfig for EKS cluster..."
aws eks update-kubeconfig --region $REGION --name $CLUSTER_NAME

# Create ECR repositories if they don't exist
if [ -n "$ECR_REGISTRY" ]; then
    echo "Creating ECR repositories..."
    
    aws ecr describe-repositories --repository-names rl-trading/training --region $REGION 2>/dev/null || \
        aws ecr create-repository --repository-name rl-trading/training --region $REGION
    
    aws ecr describe-repositories --repository-names rl-trading/inference --region $REGION 2>/dev/null || \
        aws ecr create-repository --repository-name rl-trading/inference --region $REGION
    
    # Get ECR login token
    echo "Logging into ECR..."
    aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ECR_REGISTRY
    
    # Build and push images
    echo "Building and pushing images to ECR..."
    export DOCKER_REGISTRY="$ECR_REGISTRY/rl-trading"
    export PUSH_IMAGES="true"
    ./scripts/deploy/build-images.sh
fi

# Install AWS Load Balancer Controller (if not already installed)
echo "Checking for AWS Load Balancer Controller..."
if ! kubectl get deployment -n kube-system aws-load-balancer-controller &> /dev/null; then
    echo "Installing AWS Load Balancer Controller..."
    
    # Create IAM role for service account
    eksctl create iamserviceaccount \
        --cluster=$CLUSTER_NAME \
        --namespace=kube-system \
        --name=aws-load-balancer-controller \
        --role-name "AmazonEKSLoadBalancerControllerRole" \
        --attach-policy-arn=arn:aws:iam::aws:policy/ElasticLoadBalancingFullAccess \
        --approve \
        --override-existing-serviceaccounts
    
    # Install controller
    kubectl apply -k "github.com/aws/eks-charts/stable/aws-load-balancer-controller//crds?ref=master"
    helm repo add eks https://aws.github.io/eks-charts
    helm repo update
    helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
        -n kube-system \
        --set clusterName=$CLUSTER_NAME \
        --set serviceAccount.create=false \
        --set serviceAccount.name=aws-load-balancer-controller
fi

# Create EFS storage class for shared storage
echo "Creating EFS storage class..."
cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: efs-sc
provisioner: efs.csi.aws.com
parameters:
  provisioningMode: efs-ap
  fileSystemId: ${EFS_FILE_SYSTEM_ID}
  directoryPerms: "0755"
EOF

# Update storage class in k8s configs
sed -i.bak 's/storageClassName: fast-ssd/storageClassName: gp3/g' k8s/storage.yaml
sed -i.bak 's/storageClassName: standard/storageClassName: gp3/g' k8s/storage.yaml

# Deploy to Kubernetes
echo "Deploying to Kubernetes..."
export K8S_NAMESPACE=$NAMESPACE
./scripts/deploy/deploy-k8s.sh

# Create ingress for external access
echo "Creating ingress..."
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: rl-inference-ingress
  namespace: $NAMESPACE
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/healthcheck-path: /health
spec:
  rules:
  - http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: rl-inference-service
            port:
              number: 80
EOF

echo "AWS EKS deployment completed successfully!"
echo "Check ingress status with: kubectl get ingress -n $NAMESPACE"