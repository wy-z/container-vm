import logging

import typer

from src import run

logging.basicConfig(format="%(asctime)s %(levelname)s:%(message)s", level=logging.INFO)


app = typer.Typer()
app.add_typer(run.app, name="run")


if __name__ == "__main__":
    app()
