from enum import StrEnum
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
Identifier = Annotated[str, StringConstraints(pattern=r'^[a-zA-Z0-9_-]{1,100}$')]


def new_id() -> str:
    return uuid4().hex


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Style(StrEnum):
    REALISM = 'Реалізм'
    PIXAR = 'Pixar'
    MINECRAFT = 'Minecraft'
    CARTOON = '3D cartoon'
    ANIME = 'Anime'
    CINEMATIC = 'Cinematic'
    MINIMALISM = 'Мінімалізм'
    CUSTOM = 'Власний стиль'


class BrandInput(Model):
    niche: Text
    logo: str | None = None  # Reference only; the mock never fetches arbitrary URLs.
    colors: list[Annotated[str, StringConstraints(pattern=r'^#[0-9a-fA-F]{6}$')]] = Field(min_length=1, max_length=8)
    style: Style
    person_mode: Literal['with_person', 'without_person'] = 'without_person'
    typography: Text = 'Sans serif'
    visual_rules: list[Text] = Field(default_factory=list, max_length=30)
    custom_style: Text | None = None

    @model_validator(mode='after')
    def require_custom_style(self):
        if self.style == Style.CUSTOM and not self.custom_style:
            raise ValueError('custom_style is required for Власний стиль')
        return self


class Brand(BrandInput):
    id: str = Field(default_factory=new_id)


class Brief(Model):
    topic: Text
    goal: Text
    audience: Text
    product: Text
    slide_count: int = Field(ge=5, le=8)


class ScriptItem(Model):
    number: int = Field(ge=1, le=8)
    title: Text
    body: Text
    visual: Text
    main_idea: str = ''
    role: Literal['cover', 'body', 'cta'] = 'body'


class Script(Model):
    project_id: str
    version: int = Field(ge=1)
    approved: bool = False
    slides: list[ScriptItem] = Field(min_length=5, max_length=8)


class State(StrEnum):
    IDLE = 'IDLE'
    NICHE_SETUP = 'NICHE_SETUP'
    LOGO_SETUP = 'LOGO_SETUP'
    COLOR_SETUP = 'COLOR_SETUP'
    STYLE_SETUP = 'STYLE_SETUP'
    CONTENT_TYPE = 'CONTENT_TYPE'
    FORMAT_SETUP = 'FORMAT_SETUP'
    SCRIPT_CREATION = 'SCRIPT_CREATION'
    SCRIPT_REVIEW = 'SCRIPT_REVIEW'
    COVER_GENERATION = 'COVER_GENERATION'
    COVER_SELECTION = 'COVER_SELECTION'
    SLIDE_GENERATION = 'SLIDE_GENERATION'
    SLIDE_REVIEW = 'SLIDE_REVIEW'
    SLIDE_EDIT = 'SLIDE_EDIT'
    COMPLETED = 'COMPLETED'


class SetupContext(Model):
    niche: Text | None = None
    logo_asset_id: Identifier | None = None
    no_logo: bool = False
    colors: list[Annotated[str, StringConstraints(pattern=r'^#[0-9a-fA-F]{6}$')]] | None = Field(default=None, min_length=1, max_length=8)
    style: Style | None = None
    custom_style: Text | None = None
    typography: Text = 'Sans serif'
    visual_rules: list[Text] = Field(default_factory=list)
    audience: Text | None = None
    positioning: Text | None = None
    topic: Text | None = None
    goal: Text | None = None
    product: Text | None = None
    slide_count: int = Field(default=7, ge=5, le=8)
    content_type: int | None = Field(default=None, ge=1, le=10)

    @model_validator(mode='after')
    def logo_choice(self):
        if self.no_logo and self.logo_asset_id:
            raise ValueError('Choose a logo or no_logo, not both')
        return self


class Project(Model):
    id: str = Field(default_factory=new_id)
    brand: Brand | None = None
    brief: Brief | None = None
    setup: SetupContext = Field(default_factory=SetupContext)
    state: State = State.IDLE
    revision: int = 1
    script_version: int = 0
    current_slide: int = 0
    selected_cover: str | None = None
    locked_style: dict | None = None
    active_job_id: str | None = None
    pending_question: str | None = None
    palette_options: list[dict] = Field(default_factory=list)
    first_message: str | None = None
    legacy_imported: bool = False


class Slide(Model):
    id: str
    project_id: str
    number: int
    version: int
    script_version: int
    variant: Literal['cover_with_person', 'cover_without_person', 'slide']
    asset_id: str
    url: str
    width: Literal[1080] = 1080
    height: Literal[1350] = 1350
    feedback: str | None = None
    style_snapshot: dict


class GenerationJob(Model):
    id: str
    project_id: str | None
    request_id: str
    kind: str
    status: Literal['queued', 'running', 'succeeded', 'failed']
    error: str | None = None


class Command(Model):
    request_id: Identifier


class ProjectCommand(Command):
    expected_revision: int = Field(ge=1)


class CreateContentProject(Command):
    first_message: Text | None = None
    context: SetupContext = Field(default_factory=SetupContext)


class SaveBrand(ProjectCommand):
    choice: int | None = Field(default=None, ge=1, le=10)
    text: Text | None = None
    logo_asset_id: Identifier | None = None
    colors: list[Annotated[str, StringConstraints(pattern=r'^#[0-9a-fA-F]{6}$')]] | None = Field(default=None, min_length=1, max_length=8)


class CreateCarousel(ProjectCommand):
    brief: Brief | None = None


class EditScript(ProjectCommand):
    changes: Text


class SelectCover(ProjectCommand):
    choice: Literal[1, 2]


class NextSlide(ProjectCommand):
    confirmed_slide: int = Field(ge=2, le=8)


class EditSlide(ProjectCommand):
    slide_number: int = Field(ge=2, le=8)
    changes: Text
