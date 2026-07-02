from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader
from pathlib import Path

_TEMPLATE_DIR = str(Path(__file__).parent.parent / "templates")
_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR))


def render(name: str, context: dict = None) -> HTMLResponse:
    t = _env.get_template(name)
    html = t.render(**(context or {}))
    return HTMLResponse(html)
