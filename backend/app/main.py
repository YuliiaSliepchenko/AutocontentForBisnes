from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .mcp_server import create_mcp
from .models import CreateContentProject, CreateCarousel, EditScript, EditSlide, NextSlide, ProjectCommand, SaveBrand, SelectCover
from .assets import save_logo
from .storage import Store
from .workflow import CarouselService, WorkflowError


def create_app(settings: Settings | None = None, service: CarouselService | None = None):
    settings = settings or Settings()
    service = service or CarouselService(Store(settings.autocontent_data_dir))
    mcp = create_mcp(service)
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title='AutoContent', version='0.1.0', lifespan=lifespan)
    app.state.service = service
    app.state.mcp = mcp

    @app.exception_handler(WorkflowError)
    async def workflow_error(request: Request, error: WorkflowError):
        return JSONResponse(status_code=error.status, content={'detail': str(error)})

    @app.get('/health')
    def health():
        with service.store.connect() as db:
            db.execute('SELECT 1')
        return {'status': 'ok', 'service': 'autocontent', 'provider': settings.autocontent_provider}

    @app.post('/api/projects')
    def create_content_project(command: CreateContentProject):
        return service.create_content_project(command)

    @app.post('/api/projects/{project_id}/setup')
    def save_brand(project_id: str, command: SaveBrand):
        return service.save_brand(project_id, command)

    @app.post('/api/projects/{project_id}/carousel')
    def create_carousel(project_id: str, command: CreateCarousel):
        return service.create_carousel(project_id, command)

    @app.post('/api/logos')
    async def upload_logo(file: UploadFile = File(...)):
        content = await file.read(5 * 1024 * 1024 + 1)
        await file.close()
        try:
            return save_logo(service.store, content)
        except ValueError as exc:
            raise WorkflowError(str(exc), 422) from exc

    @app.get('/api/logos/{asset_id}')
    def logo(asset_id: str):
        with service.store.connect() as db:
            row = db.execute('SELECT filename,mime FROM logos WHERE id=?', (asset_id,)).fetchone()
        if not row:
            raise WorkflowError('Logo not found', 404)
        return FileResponse(service.store.directory / 'logos' / row['filename'], media_type=row['mime'])

    @app.get('/api/projects/{project_id}')
    def get_project(project_id: str):
        return service.get_project(project_id)

    @app.get('/api/projects/{project_id}/status')
    def get_status(project_id: str):
        return service.get_project_status(project_id)

    @app.get('/api/projects/{project_id}/script')
    def get_script(project_id: str, version: int | None = None):
        return service.get_script(project_id, version)

    @app.post('/api/projects/{project_id}/script/approve')
    def approve(project_id: str, command: ProjectCommand):
        return service.approve_script(project_id, command)

    @app.post('/api/projects/{project_id}/script/edit')
    def edit_script(project_id: str, command: EditScript):
        return service.edit_script(project_id, command)

    @app.post('/api/projects/{project_id}/script/edit/start')
    def begin_script_edit(project_id: str, command: ProjectCommand):
        return service.begin_script_edit(project_id, command)

    @app.post('/api/projects/{project_id}/generation/resume')
    def resume_generation(project_id: str, command: ProjectCommand):
        return service.resume_generation(project_id, command)

    @app.post('/api/projects/{project_id}/covers/generate')
    def covers(project_id: str, command: ProjectCommand):
        return service.generate_cover_options(project_id, command)

    @app.post('/api/projects/{project_id}/covers/select')
    def select(project_id: str, command: SelectCover):
        return service.select_cover(project_id, command)

    @app.post('/api/projects/{project_id}/slides/next')
    def next_slide(project_id: str, command: NextSlide):
        return service.generate_next_slide(project_id, command)

    @app.post('/api/projects/{project_id}/slides/edit')
    def edit_slide(project_id: str, command: EditSlide):
        return service.edit_slide(project_id, command)

    @app.post('/api/projects/{project_id}/slides/edit/start')
    def begin_slide_edit(project_id: str, command: ProjectCommand):
        return service.begin_slide_edit(project_id, command)

    @app.get('/api/projects/{project_id}/slides/{slide_number}')
    def get_slide(project_id: str, slide_number: int):
        return service.get_slide(project_id, slide_number)

    @app.get('/api/jobs/{job_id}')
    def job(job_id: str):
        return service.get_job(job_id)

    @app.get('/api/assets/{asset_id}')
    def asset(asset_id: str):
        return FileResponse(service.asset_path(asset_id), media_type='image/png', filename=f'{asset_id}.png')

    frontend = Path(__file__).resolve().parents[2] / 'frontend'

    @app.get('/', include_in_schema=False)
    def index():
        return FileResponse(frontend / 'index.html')

    app.mount('/static', StaticFiles(directory=frontend), name='static')
    # MCP has /mcp internally; last mount preserves FastAPI routes and OpenAPI.
    app.mount('/', mcp_app)
    return app


app = create_app()
