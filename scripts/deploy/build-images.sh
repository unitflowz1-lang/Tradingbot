#!/bin/bash
# Build Docker images for RL system

set -e

# Configuration
REGISTRY=${DOCKER_REGISTRY:-"rl-trading"}
TAG=${BUILD_TAG:-"latest"}
PLATFORM=${BUILD_PLATFORM:-"linux/amd64"}

echo "Building RL Trading System Docker images..."
echo "Registry: $REGISTRY"
echo "Tag: $TAG"
echo "Platform: $PLATFORM"

# Build training image
echo "Building training image..."
docker build \
    --platform $PLATFORM \
    -f docker/rl-training/Dockerfile \
    -t $REGISTRY/training:$TAG \
    .

# Build inference image
echo "Building inference image..."
docker build \
    --platform $PLATFORM \
    -f docker/rl-inference/Dockerfile \
    -t $REGISTRY/inference:$TAG \
    .

# Tag images
if [ "$TAG" != "latest" ]; then
    docker tag $REGISTRY/training:$TAG $REGISTRY/training:latest
    docker tag $REGISTRY/inference:$TAG $REGISTRY/inference:latest
fi

echo "Images built successfully!"
echo "Training image: $REGISTRY/training:$TAG"
echo "Inference image: $REGISTRY/inference:$TAG"

# Push images if registry is specified
if [ -n "$PUSH_IMAGES" ] && [ "$PUSH_IMAGES" = "true" ]; then
    echo "Pushing images to registry..."
    docker push $REGISTRY/training:$TAG
    docker push $REGISTRY/inference:$TAG
    
    if [ "$TAG" != "latest" ]; then
        docker push $REGISTRY/training:latest
        docker push $REGISTRY/inference:latest
    fi
    
    echo "Images pushed successfully!"
fi