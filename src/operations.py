import typer

app = typer.Typer()


@app.command()
def windows(iso: str, **kwargs):
    """Windows specific commands"""
    pass
