import uvicorn

from .config import Settings

settings = Settings()
uvicorn.run('backend.app.main:app', host=settings.host, port=settings.port, workers=1)
