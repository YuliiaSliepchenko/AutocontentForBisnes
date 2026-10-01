from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .models import CreateContentProject, CreateCarousel, EditScript, EditSlide, NextSlide, ProjectCommand, SaveBrand, SelectCover
from .dialogue import INTRO, NICHES, FORMATS, menu
from .workflow import CarouselService


def create_mcp(service: CarouselService):
    server = FastMCP(
        'AutoContent', stateless_http=True, json_response=True,
        instructions=(
            'AutoContent mock carousel MVP. Start with create_content_project and copy every known field '
            'from the first user message into command.context; never ask the same question again. '
            'Show response.message exactly and follow allowed_actions. Never invent completed formats. '
            'At first contact greeting and niche menu MUST be one message. '
            f'{INTRO}\n\nПочнемо з головного. Обери свою нішу 👇\n\n{menu(NICHES)}\n\nНапиши номер своєї ніші. '
            'Use save_brand(project_id,command) to answer ONLY the current setup step. '
            'Show the complete script and ask 1 approve / 2 edit. Never approve for the user. '
            'approve_script generates the two covers; do not generate them a second time. '
            'Only after both exist ask 1 with person / 2 without person. '
            'select_cover creates ONLY slide 2. After each slide ask 1 next / 2 edit; '
            'call begin_slide_edit on choice 2, ask changes, then edit_slide. '
            'For script editing call begin_script_edit, ask changes, then edit_script. Never call next automatically. '
            'Use a new request_id for each user action; reuse the same id and arguments on retries. '
            'Use the current project revision. Never claim files exist unless returned by the backend.'
        ),
    )
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    @server.tool(annotations=read)
    def get_project(project_id: str) -> dict[str, Any]:
        """Read persisted project, full current script, all slide versions and allowed actions."""
        return service.get_project(project_id)

    @server.tool(annotations=write)
    def create_content_project(command: CreateContentProject) -> dict[str, Any]:
        """Start persisted onboarding. Supply known initial context to avoid repeated questions.
        context.content_type=3 is carousel; other formats are explicitly unavailable.
        An uploaded logo is referenced by context.logo_asset_id; absence by no_logo=true.
        """
        return service.create_content_project(command)

    @server.tool(annotations=write)
    def save_brand(project_id: str, command: SaveBrand) -> dict[str, Any]:
        """Answer the current setup question: numeric choice, niche/custom-style text, HEX colors,
        logo_asset_id or text='немає'. Cannot skip missing setup states or alter a locked brand.
        """
        return service.save_brand(project_id, command)

    @server.tool(annotations=write)
    def create_carousel(project_id: str, command: CreateCarousel) -> dict[str, Any]:
        """Only in FORMAT_SETUP after carousel selection: create a complete 5–8 slide script.
        Reuse known brief fields; ask only missing fields. Show the full script and wait.
        """
        return service.create_carousel(project_id, command)

    @server.tool(annotations=read)
    def get_script(project_id: str, version: int | None = None) -> dict[str, Any]:
        """Read the complete current or historical script."""
        return service.get_script(project_id, version)

    @server.tool(annotations=write)
    def approve_script(project_id: str, command: ProjectCommand) -> dict[str, Any]:
        """Only after explicit user choice 1: approve script and generate exactly two separate covers."""
        return service.approve_script(project_id, command)

    @server.tool(annotations=write)
    def edit_script(project_id: str, command: EditScript) -> dict[str, Any]:
        """Apply user's requested changes after begin_script_edit. Show the FULL updated script and wait."""
        return service.edit_script(project_id, command)

    @server.tool(annotations=write)
    def generate_cover_options(project_id: str, command: ProjectCommand) -> dict[str, Any]:
        """Resume the existing COVER_GENERATION job after an interruption. Never create additional covers."""
        return service.generate_cover_options(project_id, command)

    @server.tool(annotations=write)
    def select_cover(project_id: str, command: SelectCover) -> dict[str, Any]:
        """Record user's choice 1 with person / 2 without. Lock style and create only slide 2."""
        return service.select_cover(project_id, command)

    @server.tool(annotations=write)
    def generate_next_slide(project_id: str, command: NextSlide) -> dict[str, Any]:
        """Only after explicit user confirmation: accept current slide and create exactly the next one.
        Accepting the last slide completes the carousel without creating another image.
        """
        return service.generate_next_slide(project_id, command)

    @server.tool(annotations=write)
    def edit_slide(project_id: str, command: EditSlide) -> dict[str, Any]:
        """Ask what to change first. Generate a new version of ONLY the current slide, then wait."""
        return service.edit_slide(project_id, command)

    @server.tool(annotations=read)
    def get_slide(project_id: str, slide_number: int) -> dict[str, Any]:
        """Read available versions of one slide; cannot create missing slides."""
        return service.get_slide(project_id, slide_number)

    @server.tool(annotations=read)
    def get_project_status(project_id: str) -> dict[str, Any]:
        """Recover workflow state and job status after reconnecting; independent of MCP session."""
        return service.get_project_status(project_id)

    @server.tool(annotations=write)
    def begin_script_edit(project_id: str, command: ProjectCommand) -> dict[str, Any]:
        """Record choice 2 for script review; ask what to change and wait."""
        return service.begin_script_edit(project_id, command)

    @server.tool(annotations=write)
    def begin_slide_edit(project_id: str, command: ProjectCommand) -> dict[str, Any]:
        """Record choice 2, persist SLIDE_EDIT, ask what to change and wait."""
        return service.begin_slide_edit(project_id, command)

    @server.tool(annotations=write)
    def resume_generation(project_id: str, command: ProjectCommand) -> dict[str, Any]:
        """Resume ONLY the already authorized, persisted job. Does not create the next slide."""
        return service.resume_generation(project_id, command)

    return server
