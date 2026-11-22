import click

from . import db


@click.command()
def create_indexes():
    """Create the MongoDB indexes the app relies on."""
    names = db.create_indexes()
    click.echo("Created indexes: " + ", ".join(names))
