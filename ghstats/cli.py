from __future__ import annotations

import webbrowser
from pathlib import Path

import typer

from ghstats.config import ConfigError, build_runtime_config
from ghstats.github.client import GitHubApiError
from ghstats.render.templates import template_choices
from ghstats.service import GhStatsService, write_json, write_text
from ghstats.utils.timeparse import build_time_window


def main(
    since: str = typer.Option("30d", help="Time window such as 7d, 30d, 12w, 6m, or 1y."),
    output: Path = typer.Option(Path("ghstats-report.html"), help="HTML output path."),
    include_private: bool = typer.Option(False, "--include-private", help="Include private activity when the token allows it."),
    token: str | None = typer.Option(None, help="GitHub token override. Defaults to GITHUB_TOKEN/GH_TOKEN."),
    api_base_url: str = typer.Option("https://api.github.com", help="GitHub API base URL."),
    open_browser: bool = typer.Option(False, "--open", help="Open the generated report in a browser."),
    json_output: Path | None = typer.Option(None, help="Optional JSON export path."),
    sample_data: bool = typer.Option(False, "--sample-data", help="Generate a demo report without live GitHub API calls."),
    template: str = typer.Option("default", help=f"Report template. Options: {', '.join(template_choices())}."),
) -> None:
    """Generate a GitHub activity infographic for the authenticated user."""

    try:
        window = build_time_window(since)
        config = build_runtime_config(
            token=token,
            include_private=include_private,
            api_base_url=api_base_url,
        )
        service = GhStatsService(config)
        artifacts = service.build_artifacts(window=window, sample_data=sample_data, template_key=template)
        report_path = write_text(output.expanduser().resolve(), artifacts.html)
        typer.echo(f"HTML report written to {report_path}")

        if json_output is not None:
            json_path = write_json(
                json_output.expanduser().resolve(),
                {
                    "dataset": artifacts.dataset.to_dict(),
                    "report": artifacts.context,
                },
            )
            typer.echo(f"JSON export written to {json_path}")

        if open_browser:
            webbrowser.open(report_path.as_uri())
            typer.echo("Opened report in your default browser.")
    except (ConfigError, GitHubApiError, ValueError) as error:
        typer.secho(f"Error: {error}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from error


def run() -> None:
    typer.run(main)
