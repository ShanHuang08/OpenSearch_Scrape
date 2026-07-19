from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from environments import EnvironmentSpec
from models import ParsedField, ScrapeResult
from query import query_slug


def code_block(field: ParsedField, language: str | None = None) -> str:
    content = field.rendered
    longest_run = max((len(match.group(0)) for match in re.finditer(r"`+", content)), default=0)
    fence = "`" * max(3, longest_run + 1)
    selected_language = language
    if selected_language is None:
        selected_language = "json" if field.kind in {"json", "null"} else "text"
    return f"{fence}{selected_language}\n{content}\n{fence}"


def inline_code(value: object | None) -> str:
    text = "N/A" if value is None else str(value)
    longest_run = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(1, longest_run + 1)
    padding = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{padding}{text}{padding}{fence}"


def display_error(field: ParsedField) -> str:
    """Use an empty display value for the dashboard's no-error marker."""
    if field.rendered in {"-", "N/A", "(empty)", "null"}:
        return ""
    return field.rendered


def table_text(value: object | None) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def html_text(value: object | None) -> str:
    return html.escape("" if value is None else str(value), quote=False)


def html_attr(value: object | None) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _template_environment() -> Environment:
    environment = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(default=False),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["code_block"] = code_block
    environment.filters["inline_code"] = inline_code
    environment.filters["display_error"] = display_error
    environment.filters["table_text"] = table_text
    environment.filters["html_text"] = html_text
    environment.filters["html_attr"] = html_attr
    return environment


def render_markdown(
    result: ScrapeResult,
    *,
    environment: EnvironmentSpec,
    keywords: list[str],
    kql: str,
    time_from: str,
    time_to: str,
    executed_at: datetime,
    discover_url: str | None = None,
) -> str:
    template = _template_environment().get_template("report.md.j2")
    warning_count = len(result.warnings) + sum(
        len(record.parse_warnings) for record in result.records
    )
    return template.render(
        result=result,
        environment=environment,
        keywords=keywords,
        kql=kql,
        time_from=time_from,
        time_to=time_to,
        executed_at=executed_at,
        discover_url=discover_url,
        warning_count=warning_count,
    ).rstrip() + "\n"


def write_markdown(
    content: str,
    *,
    output_dir: Path,
    environment: EnvironmentSpec,
    keywords: list[str],
    executed_at: datetime,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = executed_at.strftime("%Y%m%dT%H%M%S%z")
    filename = f"{environment.name.lower()}_{query_slug(keywords)}_{timestamp}.md"
    path = output_dir / filename
    path.write_text(content, encoding="utf-8", newline="\n")
    return path
