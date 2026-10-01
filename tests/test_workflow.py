from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError

from backend.app.models import (
    BrandInput, Brief, CreateCarousel, EditScript, EditSlide, NextSlide,
    ProjectCommand, SaveBrand, SelectCover, Style,
)
from backend.app.providers import MockImageProvider
from backend.app.storage import Store
from backend.app.workflow import CarouselService, WorkflowError
from conftest import make_project


def command(result, key, **extra):
    return dict(request_id=key, expected_revision=result['project']['revision'], **extra)


def covers(service, result):
    pid = result['project']['id']
    return service.approve_script(pid, ProjectCommand(**command(result, 'approve')))


def selected(service, result, choice=1):
    result = covers(service, result)
    return service.select_cover(result['project']['id'], SelectCover(**command(result, 'select', choice=choice)))


def test_script_gate_and_full_script(service, project):
    pid = project['project']['id']
    assert project['project']['state'] == 'SCRIPT_REVIEW'
    assert [s['number'] for s in project['script']['slides']] == list(range(1, 6))
    assert project['slides'] == []
    actions = [
        lambda: service.generate_cover_options(pid, ProjectCommand(**command(project, 'illegal-covers'))),
        lambda: service.select_cover(pid, SelectCover(**command(project, 'illegal-select', choice=1))),
        lambda: service.generate_next_slide(pid, NextSlide(**command(project, 'illegal-next', confirmed_slide=2))),
        lambda: service.edit_slide(pid, EditSlide(**command(project, 'illegal-edit', slide_number=2, changes='Text'))),
    ]
    for action in actions:
        with pytest.raises(WorkflowError): action()
    assert not service.images.calls


@pytest.mark.parametrize('count', [5, 6, 7, 8])
def test_complete_carousel_one_at_a_time(service, brand_input, brief, count):
    brief.slide_count = count
    result = make_project(service, brand_input, brief)
    result = selected(service, result, choice=2)
    pid = result['project']['id']
    assert len(result['slides']) == 3  # two cover options + slide 2
    assert result['project']['current_slide'] == 2
    for current in range(2, count + 1):
        before = len(service.images.calls)
        assert result['project']['state'] == 'SLIDE_REVIEW'
        assert result['project']['current_slide'] == current
        result = service.generate_next_slide(pid, NextSlide(**command(result, f'next-{current}', confirmed_slide=current)))
        assert len(service.images.calls) == before + (current < count)
    assert result['project']['state'] == 'COMPLETED'
    assert len(result['slides']) == count + 1
    assert len({s['asset_id'] for s in result['slides']}) == count + 1
    assert all(s['script_version'] == 1 for s in result['slides'])
    for slide in result['slides']:
        with Image.open(service.asset_path(slide['asset_id'])) as image:
            assert image.size == (1080, 1350)
            assert image.format == 'PNG'
    for request, _ in service.images.calls[2:]:
        assert request.style_snapshot == result['project']['locked_style']
        assert request.style_snapshot['person_mode'] == 'without_person'
        assert request.output_count == 1
        assert 'contact sheet' in request.forbidden_layouts
    with pytest.raises(WorkflowError):
        service.generate_next_slide(pid, NextSlide(**command(result, 'after-end', confirmed_slide=count)))


def test_script_versions_and_frozen_approval(service, project):
    pid = project['project']['id']
    editing = service.begin_script_edit(pid,ProjectCommand(**command(project,'choose-script-edit')))
    result = service.edit_script(pid, EditScript(**command(editing, 'edit-script', changes='Оновлений сценарій')))
    assert result['script']['version'] == 2
    assert not result['script']['approved']
    assert service.get_script(pid, 1)['slides'][0]['body'] != result['script']['slides'][0]['body']
    result = covers(service, result)
    assert all(s['script_version'] == 2 for s in result['slides'])
    with pytest.raises(WorkflowError):
        service.edit_script(pid, EditScript(**command(result, 'edit-approved', changes='Запізнілі правки')))


def test_edit_current_only_preserves_all_versions(service, project):
    result = selected(service, project)
    pid = result['project']['id']
    before = result['slides']
    original_bytes = {s['id']: service.asset_path(s['asset_id']).read_bytes() for s in before}
    result = service.begin_slide_edit(pid,ProjectCommand(**command(result,'choose-edit')))
    with pytest.raises(WorkflowError):
        service.edit_slide(pid, EditSlide(**command(result, 'wrong-slide', slide_number=3, changes='wrong')))
    result = service.edit_slide(pid, EditSlide(**command(result, 'edit', slide_number=2, changes='Більший заголовок')))
    assert result['slides'][:2] == before[:2]
    versions = service.get_slide(pid, 2)['versions']
    assert [s['version'] for s in versions] == [1, 2]
    assert result['project']['current_slide'] == 2
    assert result['project']['state'] == 'SLIDE_REVIEW'
    assert service.images.calls[-1][0].changes == 'Більший заголовок'
    assert service.images.calls[-1][0].base_asset_id == before[-1]['asset_id']
    for slide in before:
        assert service.asset_path(slide['asset_id']).read_bytes() == original_bytes[slide['id']]


def test_retries_and_stale_commands_cannot_skip(service, project):
    result = selected(service, project)
    pid = result['project']['id']
    cmd = NextSlide(**command(result, 'next', confirmed_slide=2))
    first = service.generate_next_slide(pid, cmd)
    count = len(service.images.calls)
    assert service.generate_next_slide(pid, cmd) == first
    assert len(service.images.calls) == count
    with pytest.raises(WorkflowError):
        service.generate_next_slide(pid, NextSlide(**command(result, 'different-key', confirmed_slide=2)))
    with pytest.raises(WorkflowError):
        service.generate_next_slide(pid, NextSlide(**command(first, 'next', confirmed_slide=3)))
    with pytest.raises(WorkflowError):
        service.generate_next_slide(pid, NextSlide(**command(first, 'wrong-confirmation', confirmed_slide=2)))
    with pytest.raises(WorkflowError):
        service.generate_cover_options(pid, ProjectCommand(**command(first, 'repeat-cover')))
    assert service.get_project(pid)['project']['current_slide'] == 3


def test_concurrent_duplicate_job(service, project):
    result = selected(service, project)
    pid = result['project']['id']
    cmd = NextSlide(**command(result, 'concurrent', confirmed_slide=2))
    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs = list(pool.map(lambda _: service.generate_next_slide(pid, cmd), range(4)))
    assert outputs == [outputs[0]] * 4
    assert len(service.images.calls) == 4
    with service.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM jobs WHERE request_id=?', ('concurrent',)).fetchone()[0] == 1


def test_restart_resumes_state_and_replays_response(service, project):
    result = selected(service, project)
    pid = result['project']['id']
    restored = CarouselService(Store(service.store.directory))
    assert restored.get_project(pid) == {k: v for k, v in result.items() if k != 'job_id'}
    next_cmd = NextSlide(**command(result, 'next', confirmed_slide=2))
    next_result = restored.generate_next_slide(pid, next_cmd)
    again = CarouselService(Store(service.store.directory))
    assert again.generate_next_slide(pid, next_cmd) == next_result
    assert again.get_project_status(pid)['project']['current_slide'] == 3


def test_partial_cover_failure_reuses_first_file(service, project):
    class FailingSecond(MockImageProvider):
        def generate(self, request, *, idempotency_key):
            if request.variant == 'cover_without_person': raise RuntimeError('offline')
            return super().generate(request, idempotency_key=idempotency_key)
    pid = project['project']['id']
    service.images = FailingSecond()
    cmd = ProjectCommand(**command(project, 'approve'))
    with pytest.raises(WorkflowError): service.approve_script(pid, cmd)
    assert service.get_project(pid)['project']['state'] == 'COVER_GENERATION'
    assert service.get_project(pid)['slides'] == []
    files = list(service.store.assets.glob('*.png'))
    assert len(files) == 1
    original_file = files[0].read_bytes()
    with pytest.raises(WorkflowError): service.asset_path(files[0].stem)
    restarted = CarouselService(Store(service.store.directory))
    result = restarted.approve_script(pid, cmd)
    assert result['project']['state'] == 'COVER_SELECTION'
    assert len(result['slides']) == 2
    assert len(list(service.store.assets.glob('*.png'))) == 2
    assert files[0].read_bytes() == original_file
    assert restarted.get_job(result['job_id'])['status'] == 'succeeded'


def test_process_interruption_leaves_recoverable_intent(service, project):
    class Crash(MockImageProvider):
        def generate(self, request, *, idempotency_key):
            raise SystemExit('simulated process termination')
    pid = project['project']['id']
    service.images = Crash()
    cmd = ProjectCommand(**command(project, 'interrupted'))
    with pytest.raises(SystemExit): service.approve_script(pid, cmd)
    status = service.get_project_status(pid)
    assert status['jobs'][-1]['status'] == 'running'
    # A killed process loses ownership when its durable lease expires.
    with service.store.connect(write=True) as db:
        db.execute('UPDATE generation_tasks SET lease_until=0')
    restarted = CarouselService(Store(service.store.directory))
    result = restarted.approve_script(pid, cmd)
    assert result['project']['state'] == 'COVER_SELECTION'
    assert len(result['slides']) == 2


def test_provider_output_dimensions_are_enforced(service, project):
    class BadImage(MockImageProvider):
        def generate(self, request, *, idempotency_key):
            out = BytesIO()
            Image.new('RGB', (100, 100)).save(out, 'PNG')
            return out.getvalue()
    pid = project['project']['id']
    service.images = BadImage()
    with pytest.raises(WorkflowError, match='1080x1350'):
        service.approve_script(pid, ProjectCommand(**command(project, 'bad')))
    assert not list(service.store.assets.glob('*.png'))
    assert service.get_project(pid)['slides'] == []


@pytest.mark.parametrize('count', [4, 9])
def test_slide_count_validation(brief, count):
    with pytest.raises(ValidationError): Brief(**dict(brief.model_dump(), slide_count=count))


@pytest.mark.parametrize('style', list(Style))
def test_brand_styles(brand_input, style):
    data = dict(brand_input.model_dump(), style=style, custom_style='Пастельна акварель' if style == Style.CUSTOM else None)
    assert BrandInput(**data).style == style


def test_empty_edit_and_custom_style_rejected(brand_input):
    with pytest.raises(ValidationError):
        EditSlide(request_id='x', expected_revision=1, slide_number=2, changes='   ')
    with pytest.raises(ValidationError):
        BrandInput(**dict(brand_input.model_dump(), style=Style.CUSTOM))


def test_two_different_commands_for_same_revision_only_one_wins(service, project):
    result = selected(service, project)
    pid = result['project']['id']
    def advance(key):
        try:
            return service.generate_next_slide(pid, NextSlide(**command(result, key, confirmed_slide=2)))
        except WorkflowError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(advance, ['tab-one', 'tab-two']))
    assert sum(x is not None for x in outcomes) == 1
    assert service.get_project(pid)['project']['current_slide'] == 3
    assert len(service.images.calls) == 4


def test_script_must_match_brief_count_and_order(service, project):
    class InvalidScript:
        def edit_script(self, script, changes, *, idempotency_key):
            slides = script.slides
            slides[1].number = 1
            return slides
    service.text = InvalidScript()
    result = service.begin_script_edit(project['project']['id'],ProjectCommand(**command(project,'begin-invalid')))
    with pytest.raises(WorkflowError):
        service.edit_script(project['project']['id'], EditScript(**command(result, 'bad-script', changes='change')))
    assert service.get_script(project['project']['id'])['version'] == 1
