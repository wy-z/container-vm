from setuptools import find_packages, setup

install_requires = ["typer[all]", "pydantic", "dynaconf", "ring", "tenacity"]

extras_require = {
    "dev": [
        "ruff",
        "isort",
        "pip-tools",
        "mypy",
        "pytest",
        "pytest-variables[yaml]",
        "pytest-xdist",
        "pytest-cov",
    ],
    "build": ["pyinstaller"],
}

setup(
    name="container-vm",
    url="https://github.com/wy-z/container-vm",
    license="MIT",
    author="weiyang",
    author_email="weiyang.ones@gmail.com",
    description="VM in container",
    packages=find_packages(),
    use_scm_version={
        "write_to": "version.txt",
    },
    setup_requires=["setuptools_scm"],
    install_requires=install_requires,
    extras_require=extras_require,
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
    ],
)
