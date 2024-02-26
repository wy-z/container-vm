import copy
import functools
import json
import logging
import os

import pytest
import typer.testing

import main
from src import meta

logging.basicConfig(format="%(asctime)s %(levelname)s:%(message)s", level=logging.INFO)


def pytest_collection_modifyitems(config, items):
    """
    Write test ids to '.pytest-nodeids'
    """
    nodeids = [item.nodeid for item in items]
    with open(".pytest-nodeids", "w") as f:
        json.dump(nodeids, f)


@pytest.fixture(scope="session", autouse=True)
def check_env():
    if os.getenv("CONTAINER_VM_TEST_IN_CONTAINER") != "1":
        raise EnvironmentError("Tests must be run inside 'container-vm-test'")


origin_config = copy.deepcopy(meta.config)


@pytest.fixture
def c():
    yield meta.config
    meta.config = origin_config


@pytest.fixture(scope="session")
def cli():
    runner = typer.testing.CliRunner()
    return functools.partial(runner.invoke, main.app)
