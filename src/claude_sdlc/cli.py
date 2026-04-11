"""CLI entry point for csdlc."""

import click

from claude_sdlc import __version__


@click.group()
@click.version_option(version=__version__, prog_name="csdlc")
def main():
    """Automate your Claude Code SDLC — from story creation through code review and traceability."""


@main.command()
@click.argument("story_key")
def run(story_key):
    """Execute the full pipeline for a story."""
    click.echo(f"Pipeline run for {story_key} — not yet implemented (see Story 3)")


@main.command()
def init():
    """Generate .csdlc/config.yaml for this project."""
    click.echo("Init — not yet implemented (see Story 3)")


@main.command()
def validate():
    """Check config and environment."""
    click.echo("Validate — not yet implemented (see Story 3)")
