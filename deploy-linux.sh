#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# --- CONFIGURATION ---
IMAGE_NAME="discogs:latest"
TAR_FILE="discogs-linux-amd64.tar"
REMOTE_USER="koehntopp"
REMOTE_HOST="192.168.1.97"
REMOTE_DIR="/home/koehntopp/src/discogs"  # Temporary directory on Linux to hold the tar file
CONTAINER_NAME="discogs"
# ---------------------

echo "🚀 1. Building Docker image for Linux architecture..."
# Using buildx is crucial if your Mac is Apple Silicon (M1/M2/M3) but your server is Intel/AMD
docker buildx build --platform linux/amd64 -t $IMAGE_NAME --load .

echo "📦 2. Saving image to a tarball archive..."
docker save -o $TAR_FILE $IMAGE_NAME

echo "🚀 3. Transferring tarball to Linux server via SCP..."
scp $TAR_FILE ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/${TAR_FILE}

echo "🧹 4. Cleaning up local tarball on Mac..."
rm $TAR_FILE

echo "🔄 5. Updating and restarting services via Docker Compose on Linux box..."
ssh ${REMOTE_USER}@${REMOTE_HOST} << EOF
  set -e
  cd ${REMOTE_DIR}

  echo "📥 Loading image into remote Docker..."
  docker load -i ${TAR_FILE}

  echo "🧹 Removing remote tarball to save space..."
  rm ${TAR_FILE}

  echo "🔄 Recreating containers with Docker Compose..."
  docker compose up -d --remove-orphans
EOF

echo "✅ Deployment complete!"


