"""`vethuq licence`: install a licence on every add-on it lists, see what is installed, and ask for
one. A request opens a prefilled issue in VethuQ's **public** repository, so it carries only the
request code, the add-ons or wallet wanted and a short note: never file names, keys, tokens or
contact details."""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from vethuq.errors import InvalidLicenceError
from vethuq_cli.console import Theme, console
from vethuq_cli.output import dump, say, table
from vethuq_cli.state import State

licence_app = typer.Typer(help="Licences: install, show and request.", no_args_is_help=True)


def _client():
    return State.client()


@licence_app.command("install")
def install(
    token: str = typer.Argument(None, help="The licence key (or use --file)."),
    file: Annotated[Path | None, typer.Option("--file", "-f", help="A .vqlic file.")] = None,
    github_id: int = typer.Option(
        None, "--github-id", help="Your numeric GitHub id, for a licence bound to GitHub accounts."
    ),
) -> None:
    """Install one licence on every add-on it lists."""
    if (token is None) == (file is None):
        raise InvalidLicenceError(
            "Give the licence key, or --file.", "For example: --file acme.vqlic"
        )
    licences = _client().licences
    results = licences.install_file(file, github_id) if file else licences.install(token, github_id)
    table(results, ["addon_id", "status", "detail"], empty="Nothing was installed.")
    stored = sum(1 for r in results if r.status in ("stored", "replaced", "unchanged"))
    missing = [r.addon_id for r in results if r.status == "not_installed"]
    if not State.json:
        say(f"Installed on {stored} add-on(s).", style=Theme.OK)
        if missing:
            say(f"Not installed here, so skipped: {', '.join(missing)}.", style=Theme.DIM)


@licence_app.command("show")
def show() -> None:
    """The installed licences: what each unlocks, until when, and where it is installed."""
    table(
        _client().licences.show(),
        ["licence_id", "kind", "status", "valid_until", "bundles", "lists", "installed_on"],
        empty="No licence is installed.",
    )


@licence_app.command("bundles")
def bundles() -> None:
    """Each bundle and whether a licence covers it: free, licensed, expired or not licensed."""
    table(
        _client().licences.bundles(),
        ["bundle_id", "state", "licence_id", "valid_until", "licensed_addons"],
        empty="No bundles are known here.",
    )


@licence_app.command("code")
def code(
    github: bool = typer.Option(False, "--github", help="Include your numeric GitHub id."),
    github_id: int = typer.Option(None, "--github-id", help="Your numeric GitHub id."),
    runner_owner: str = typer.Option(None, "--runner-owner", help="The runner repository's owner."),
    runner_owner_id: int = typer.Option(None, "--runner-owner-id"),
) -> None:
    """The request code to send the admin (see `licence request`)."""
    value = _client().licences.request_code(
        github=github,
        github_owner_id=github_id,
        runner_owner=runner_owner,
        runner_owner_id=runner_owner_id,
    )
    say(value, data={"code": value})


@licence_app.command("request")
def request(
    kind: str = typer.Option("new", "--type", help="new, top-up or rebind."),
    addon: Annotated[
        list[str] | None, typer.Option("--addon", help="An add-on id; repeat for several.")
    ] = None,
    bundle: str = typer.Option(None, "--bundle", help="A bundle id, such as office."),
    wallet: str = typer.Option(None, "--wallet", help="For a top-up: the wallet (local)."),
    note: str = typer.Option(
        None, "--note", help="A short note; it is public, so no contact details."
    ),
    github: bool = typer.Option(False, "--github", help="Include your numeric GitHub id."),
    github_id: int = typer.Option(None, "--github-id", help="Your numeric GitHub id."),
    runner_owner: str = typer.Option(None, "--runner-owner", help="The runner repository's owner."),
    runner_owner_id: int = typer.Option(None, "--runner-owner-id"),
    open_: bool = typer.Option(False, "--open", help="Open the prefilled issue in the browser."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask before opening."),
) -> None:
    """Ask for a licence, a top-up or a re-bind through a public GitHub issue (no token needed)."""
    made = _client().licences.request(
        kind=kind,
        addons=addon or (),
        bundle=bundle,
        wallet=wallet,
        note=note,
        github=github,
        github_owner_id=github_id,
        runner_owner=runner_owner,
        runner_owner_id=runner_owner_id,
    )
    if State.json:
        dump(made.to_dict())
    else:
        console.print(made.privacy, style=Theme.WARN)
        grid = Table.grid(padding=(0, 2))
        for name, value in made.fields.items():
            grid.add_row(name.replace("_", " "), value)
        console.print("\nExactly what will be in the issue:")
        console.print(grid)
        console.print(f"\n{made.url}", style=Theme.DIM, soft_wrap=True)
    if not open_:
        return
    if not yes and not typer.confirm("Open this in your browser?", default=False):
        return
    if not webbrowser.open(made.url):
        say("The browser couldn't be opened: copy the address above.", style=Theme.WARN)
