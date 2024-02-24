import logging
import os

import typer

from src import run

logging.basicConfig(format="%(asctime)s %(levelname)s:%(message)s", level=logging.INFO)

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
app = typer.Typer()
app.add_typer(run.app, name="run")


@app.command()
def version():
    """
    Cli version
    """
    with open(os.path.join(THIS_DIR, "version.txt")) as version_file:
        version = version_file.read().strip()
    typer.echo(version)


if __name__ == "__main__":
    app()
