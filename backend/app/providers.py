"""Provider contracts are independent of REST, MCP and persistence."""
from abc import ABC, abstractmethod
from io import BytesIO
import re

from PIL import Image, ImageDraw
from pydantic import Field

from .models import Brand, Brief, Model, ScriptItem


class ImageRequest(Model):
    project_id: str
    slide: ScriptItem
    script_version: int
    slide_version: int
    variant: str
    brand: Brand
    style_snapshot: dict
    changes: str | None = None
    base_asset_id: str | None = None
    width: int = 1080
    height: int = 1350
    output_count: int = 1
    forbidden_layouts: list[str] = Field(default_factory=lambda: [
        'collage', 'grid', 'storyboard', 'contact sheet', 'sprite sheet',
        'whole-carousel preview', 'multiple slides in one file'
    ])


class TextProvider(ABC):
    @abstractmethod
    def create_script(self, brief: Brief, brand: Brand, *, idempotency_key: str) -> list[ScriptItem]: ...

    @abstractmethod
    def edit_script(self, script, changes: str, *, idempotency_key: str) -> list[ScriptItem]: ...


class ImageProvider(ABC):
    @abstractmethod
    def generate(self, request: ImageRequest, *, idempotency_key: str) -> bytes:
        """Return exactly one PNG. Reuse idempotency_key on retries."""
        ...


class VideoProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, *, idempotency_key: str) -> bytes: ...


class MockTextProvider(TextProvider):
    def create_script(self, brief, brand, *, idempotency_key):
        return [ScriptItem(
            number=n,
            title=brief.topic if n == 1 else ('Заклик до дії' if n == brief.slide_count else f'Крок {n - 1}'),
            body=(f'{brief.product}: {brief.goal}. Для: {brief.audience}. '
                  + ('Зверніться, щоб дізнатися більше.' if n == brief.slide_count else f'Тестовий зміст слайда {n}.')),
            visual=f'{brand.style.value}; {brand.niche}; окремий вертикальний слайд {n}',
            main_idea=brief.goal if n == brief.slide_count else f'Головна думка {n}: {brief.topic}',
            role='cover' if n == 1 else ('cta' if n == brief.slide_count else 'body'),
        ) for n in range(1, brief.slide_count + 1)]

    def edit_script(self, script, changes, *, idempotency_key):
        slides = [s.model_copy(deep=True) for s in script.slides]
        match = re.search(r'(?:слайд|slide)\s*(\d+)', changes, re.IGNORECASE)
        number = int(match.group(1)) if match else 1
        if not 1 <= number <= len(slides):
            raise ValueError('Slide number is outside script')
        slides[number-1].body += f'\n[Mock правки: {changes}]'
        for n,s in enumerate(slides,1):
            s.role = 'cover' if n == 1 else ('cta' if n == len(slides) else 'body')
            s.main_idea = s.main_idea or s.title
        return slides


class MockImageProvider(ImageProvider):
    def generate(self, request, *, idempotency_key):
        image = Image.new('RGB', (request.width, request.height), request.brand.colors[0])
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((50, 50, 1030, 1300), radius=35, fill='#ffffff')
        draw.text((85, 100), 'AUTOCONTENT / MOCK', fill='#222222', font_size=48)
        draw.text((85, 210), f'SLIDE {request.slide.number}', fill='#222222', font_size=70)
        draw.text((85, 320), request.variant, fill='#222222', font_size=32)
        draw.text((85, 390), f'Version {request.slide_version} / Script {request.script_version}', fill='#222222', font_size=32)
        if request.style_snapshot.get('person_mode') == 'with_person':
            draw.ellipse((400, 520, 680, 800), fill='#d4a373')
            draw.rounded_rectangle((300, 820, 780, 1150), radius=90, fill='#457b9d')
        else:
            draw.ellipse((270, 580, 810, 1120), fill='#457b9d')
        # A mock is deliberately labelled and does not pretend to render AI artwork.
        draw.text((85, 1220), idempotency_key[:36], fill='#555555', font_size=20)
        out = BytesIO()
        image.save(out, format='PNG')
        return out.getvalue()


class MockVideoProvider(VideoProvider):
    def generate(self, prompt, *, idempotency_key):
        return b'AUTOCONTENT MOCK VIDEO - NOT A PLAYABLE VIDEO'
