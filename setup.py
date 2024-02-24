from setuptools import find_packages, setup

install_requires = ["typer[all]", "pydantic", "dynaconf", "diskcache"]

extras_require = {
    "dev": [
        "pip-tools",
        "ruff",
        "isort",
        "mypy",
        "pytest",
        "pytest-variables[yaml]",
        "pytest-xdist",
        "pytest-cov",
    ],
    "build": ["pyinstaller", "pyinstaller-hooks-contrib"],
}

setup(
    name="container-vm",
    url="https://github.com/wy-z/container-vm",
    license="MIT",
    author="weiyang",
    author_email="weiyang.ones@gmail.com",
    description="Run VM in container",
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
