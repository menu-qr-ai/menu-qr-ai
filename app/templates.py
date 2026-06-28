from fastapi.templating import Jinja2Templates

from app.core.config import settings


templates = Jinja2Templates(directory=str(settings.templates_dir))
