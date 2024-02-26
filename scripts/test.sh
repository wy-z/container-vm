#!/usr/bin/env bash

set -e

THIS_DIR=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
PROJ_DIR=$(dirname "${THIS_DIR}")
if [[ $PWD != "$PROJ_DIR" ]]; then
	echo "Please run this script from '$PROJ_DIR'"
	exit 1
fi

PYTEST_NODEIDS=".pytest-nodeids"
TEST_IMG="container-vm-test"

docker build -t "$TEST_IMG" --platform linux/amd64 -f files/Dockerfile.test .

pytest --collect-only "$@"
codes=(1)
set +e
for nodeid in $(jq -rc '.[]' "${PYTEST_NODEIDS}"); do
	echo "Running $nodeid ..."
	docker run --rm -t -v "$PWD":"$PWD" -w "$PWD" --device-cgroup-rule='c *:* rwm' \
		--cap-add=NET_ADMIN "$TEST_IMG" coverage run --source=src -m pytest "$nodeid"
	codes+=($?)
done
set -e

for code in "${codes[@]}"; do
	if [ "$code" -ne 0 ]; then
		exit 1
	fi
done
