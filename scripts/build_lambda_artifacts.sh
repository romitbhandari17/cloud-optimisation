#!/usr/bin/env bash
# Builds the Lambda deployment artifacts consumed by terraform/compute:
#   dist/cloudineer_function.zip  -> src/cloudineer package + handlers (your code)
#   dist/cloudineer_layer.zip     -> third-party dependencies (pydantic, PyYAML)
#
# boto3/botocore are already provided by the Lambda Python runtime and are
# intentionally excluded from the layer to keep it small.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "${BUILD_DIR}"' EXIT

echo "Building Lambda function package..."
mkdir -p "${DIST_DIR}" "${BUILD_DIR}/function"
cp -R "${ROOT_DIR}/src/cloudineer" "${BUILD_DIR}/function/"
# Bundled so api_handler.py can list/load customer configs without a DB lookup.
cp -R "${ROOT_DIR}/config" "${BUILD_DIR}/function/"
find "${BUILD_DIR}/function" -name "__pycache__" -type d -prune -exec rm -rf {} +
(cd "${BUILD_DIR}/function" && zip -rq "${DIST_DIR}/cloudineer_function.zip" .)

echo "Building Lambda dependency layer..."
mkdir -p "${BUILD_DIR}/layer/python"
PYTHON_BIN="${PYTHON_BIN:-python3}"
# Force manylinux wheels for the Lambda runtime (python3.12, x86_64) so
# compiled deps like pydantic_core work regardless of the host OS/arch
# (e.g. building on macOS/arm64 would otherwise ship incompatible binaries).
"${PYTHON_BIN}" -m pip install --quiet --target "${BUILD_DIR}/layer/python" \
  --platform manylinux2014_x86_64 --python-version 3.12 \
  --implementation cp --only-binary=:all: \
  "pydantic>=2.6" "PyYAML>=6.0"
(cd "${BUILD_DIR}/layer" && zip -rq "${DIST_DIR}/cloudineer_layer.zip" .)

echo "Done:"
ls -lh "${DIST_DIR}"/cloudineer_function.zip "${DIST_DIR}"/cloudineer_layer.zip
