from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.core.session import get_csrf_token


templates = Jinja2Templates(directory=str(settings.templates_dir))


def _template_csrf_token(request) -> str:
    session = getattr(request.state, "session", {})
    return get_csrf_token(session)


def _template_csp_nonce(request) -> str:
    return str(getattr(request.state, "csp_nonce", ""))


templates.env.globals.update(
    csrf_token=_template_csrf_token,
    csp_nonce=_template_csp_nonce,
)
