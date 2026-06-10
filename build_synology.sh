#!/usr/bin/env bash
# Build a Docker image for Synology NAS and save it as a tar file for manual upload.
#
# Usage:
#   ./build_synology.sh [amd64|arm64]
#
# Most Synology NAS (DS/RS series Intel/AMD): amd64  (default)
# Newer ARM-based Synology (DS-series Cortex):  arm64
#
# After upload in Synology Container Manager:
#   Images → Add → Import from file → select discogs-synology.tar

set -euo pipefail

PLATFORM="${1:-amd64}"
IMAGE_NAME="discogs"
IMAGE_TAG="latest"
OUTPUT_FILE="discogs-synology-${PLATFORM}.tar"

echo "Building for linux/${PLATFORM}..."
docker buildx build \
    --platform "linux/${PLATFORM}" \
    --tag "${IMAGE_NAME}:${IMAGE_TAG}" \
    --load \
    .

echo "Saving image to ${OUTPUT_FILE}..."
docker save "${IMAGE_NAME}:${IMAGE_TAG}" -o "${OUTPUT_FILE}"

SIZE=$(du -sh "${OUTPUT_FILE}" | cut -f1)
echo ""
echo "Done. ${OUTPUT_FILE} (${SIZE})"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Synology Container Manager setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "1. Upload image"
echo "   Container Manager → Image → Add → Import from file"
echo "   Select: ${OUTPUT_FILE}"
echo ""
echo "2. Create container from the image"
echo "   Container Manager → Container → Create"
echo ""
echo "3. Volume mounts"
echo "   ┌─────────────────────────────────┬──────────┐"
echo "   │ Host path (Synology)            │ Container│"
echo "   ├─────────────────────────────────┼──────────┤"
echo "   │ /volume1/docker/discogs/config  │ /config  │"
echo "   │ /volume1/FLAC                   │ /flac    │"
echo "   └─────────────────────────────────┴──────────┘"
echo "   Adjust host paths to match your Synology volume layout."
echo ""
echo "4. Environment variables"
echo "   ┌───────────────────┬──────────────────────────────────────┐"
echo "   │ Variable          │ Value                                │"
echo "   ├───────────────────┼──────────────────────────────────────┤"
echo "   │ CONFIG_DIR        │ /config                              │"
echo "   │ PORT              │ 8000                                 │"
echo "   │ RCLONE_CONFIG     │ /config/rclone.conf                  │"
echo "   └───────────────────┴──────────────────────────────────────┘"
echo ""
echo "5. Port"
echo "   Local: 8000  →  Container: 8000  (TCP)"
echo ""
echo "6. First-run: copy config.py into /volume1/docker/discogs/config/"
echo "   (Use config_demo.py as template, update paths to /flac and /config)"
echo ""
echo "   Key settings in config.py for Synology:"
echo "     config_dir  = '/config'"
echo "     flacroot    = '/flac/'"
echo "     flacroot_local = '/volume1/FLAC/'   # path as seen from your Mac"
echo ""
