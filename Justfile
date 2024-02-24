install-deps:
	@pip install -r requirements.txt

install-dev:
	@pip install -e '.[dev]'

version:
    @pip install pip setuptools setuptools_scm -U
    @./scripts/build.sh gen_version

requirements:
    @pip-compile -o requirements.txt

build: install-deps
    @pip install pyinstaller pyinstaller-hooks-contrib -U
    @./scripts/build.sh

clean:
	@rm -rf dist build *.spec version.txt

lint:
	@ruff check ./
	@ruff format --check ./

format:
	@ruff format ./

build-img tag platform="linux/amd64": clean version
    @docker build --platform {{platform}} -t container-vm-base -f files/Dockerfile.base .
    @docker build --platform {{platform}} -t container-vm-dev -f files/Dockerfile.dev .
    @docker build --platform {{platform}} -t container-vm:{{tag}} -f files/Dockerfile .
