#!/usr/bin/env bash

set -e

THIS_DIR=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")

CLI_NAME=container-vm
PROJ_DIR=$(dirname "${THIS_DIR}")
DIST_DIR=${PROJ_DIR}/dist
VERSION_DIST_FILE=${DIST_DIR}/version

mkdir -p "${DIST_DIR}"

build() {
	VERSION=${VERSION:=$(cat "${PROJ_DIR}"/version.txt)}
	# bin
	pyinstaller "${PROJ_DIR}"/main.py --clean \
		--distpath "${DIST_DIR}" --name "${CLI_NAME}" \
		--add-data version.txt:.
	# version
	echo "${VERSION}" >"${VERSION_DIST_FILE}"
}

gen_version() {
	python3 "${PROJ_DIR}/setup.py" --version
}

if [[ $# -eq 0 ]]; then
	build
else
	func=${1}
	shift
	${func} "$@"
fi
