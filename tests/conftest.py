import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.models import BrandInput, Brief, CreateCarousel, CreateContentProject, SetupContext
from backend.app.providers import MockImageProvider
from backend.app.storage import Store
from backend.app.workflow import CarouselService


class RecordingImages(MockImageProvider):
    def __init__(self):
        self.calls = []

    def generate(self, request, *, idempotency_key):
        self.calls.append((request, idempotency_key))
        return super().generate(request, idempotency_key=idempotency_key)


@pytest.fixture
def service(tmp_path):
    return CarouselService(Store(tmp_path), image_provider=RecordingImages())


@pytest.fixture
def brand_input():
    return BrandInput(niche='Кава', logo='logo.png', colors=['#264653', '#E9C46A'],
                      style='Реалізм', typography='Inter', visual_rules=['Читабельність'])


@pytest.fixture
def brief():
    return Brief(topic='Кава', goal='Запис', audience='Кияни', product='Дегустація', slide_count=5)


@pytest.fixture
def project(service, brand_input, brief):
    return make_project(service, brand_input, brief)


def make_project(service, brand_input, brief):
    context = SetupContext(niche=brand_input.niche,no_logo=True,colors=brand_input.colors,
                           style=brand_input.style,typography=brand_input.typography,
                           visual_rules=brand_input.visual_rules,content_type=3)
    result = service.create_content_project(CreateContentProject(request_id='new-project',context=context))
    p = result['project']
    return service.create_carousel(p['id'],CreateCarousel(request_id='create',expected_revision=p['revision'],brief=brief))


@pytest.fixture
def client(service, tmp_path):
    with TestClient(create_app(Settings(autocontent_data_dir=tmp_path), service), base_url='http://localhost:8000') as client:
        yield client
