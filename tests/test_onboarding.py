import pytest

from backend.app.models import (CreateContentProject, CreateCarousel, ProjectCommand,
                                SaveBrand, SetupContext, State)
from backend.app.storage import Store
from backend.app.workflow import CarouselService, WorkflowError


def answer(service, result, **values):
    p = result['project']
    return service.save_brand(p['id'], SaveBrand(request_id=f"setup-{p['id']}-{p['revision']}",
                                               expected_revision=p['revision'], **values))


def setup(service, count=7):
    result = service.create_content_project(CreateContentProject(request_id=f'project-{count}'))
    for values in ({'choice':7},{'text':'немає'},{'choice':1},{'choice':2},{'choice':3}):
        result = answer(service,result,**values)
    return result


def test_every_onboarding_state_and_no_early_script(service, brief):
    result = service.create_content_project(CreateContentProject(request_id='new'))
    assert result['project']['state'] == 'NICHE_SETUP'
    assert 'Привіт!' in result['message'] and '10 — Інше' in result['message']
    assert result['script'] is None
    pid = result['project']['id']
    for expected, values in [('LOGO_SETUP',{'choice':2}),('COLOR_SETUP',{'text':'немає'}),
                             ('STYLE_SETUP',{'choice':1}),('CONTENT_TYPE',{'choice':7}),
                             ('FORMAT_SETUP',{'choice':3})]:
        with pytest.raises(WorkflowError):
            service.create_carousel(pid,CreateCarousel(request_id=f'early-{expected}',expected_revision=result['project']['revision'],brief=brief))
        result = answer(service,result,**values)
        assert result['project']['state'] == expected
    result = service.create_carousel(pid,CreateCarousel(request_id='script',expected_revision=result['project']['revision'],brief=brief))
    assert [e['to_state'] for e in result['events']] == ['IDLE','NICHE_SETUP','LOGO_SETUP','COLOR_SETUP','STYLE_SETUP','CONTENT_TYPE','FORMAT_SETUP','SCRIPT_CREATION','SCRIPT_REVIEW']
    assert result['script']['slides'][0]['role'] == 'cover'
    assert result['script']['slides'][-1]['role'] == 'cta'
    assert all(s['main_idea'] for s in result['script']['slides'])
    assert not result['slides']


def test_custom_answers_and_restart(service):
    result = service.create_content_project(CreateContentProject(request_id='custom'))
    result = answer(service,result,choice=10)
    assert result['project']['pending_question'] == 'niche_description'
    result = answer(service,result,text='Ремонт велосипедів')
    result = answer(service,result,text='немає')
    assert len(result['project']['palette_options']) == 7
    result = answer(service,result,choice=8)
    assert 'HEX' in result['message']
    restored = CarouselService(Store(service.store.directory))
    result = restored.get_project(result['project']['id'])
    result = answer(restored,result,colors=['#102030','#FFFFFF'])
    result = answer(restored,result,choice=8)
    assert result['project']['pending_question'] == 'custom_style'
    result = answer(restored,result,text='Акварель')
    result = answer(restored,result,choice=3)
    assert result['project']['brand']['custom_style'] == 'Акварель'
    assert result['project']['brand']['colors'] == ['#102030','#FFFFFF']


@pytest.mark.parametrize('choice',[1,2,4,5,6,7,8,9,10])
def test_unavailable_formats_do_not_generate(service, choice):
    result = service.create_content_project(CreateContentProject(request_id='not-ready',context=SetupContext(
        niche='IT',no_logo=True,colors=['#102030'],style='Anime')))
    result = answer(service,result,choice=choice)
    assert result['message'] == 'Цей формат буде доступний у наступній версії.'
    assert result['project']['state'] == 'CONTENT_TYPE'
    assert result['script'] is None
    assert not result['slides'] and not service.images.calls
    with service.store.connect() as db:
        assert db.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0


def test_known_context_is_not_requested_again_but_states_are_recorded(service):
    result = service.create_content_project(CreateContentProject(request_id='known',first_message='Потрібна карусель для кав’ярні',context=SetupContext(
        niche='Кав’ярня',no_logo=True,colors=['#123456'],style='Реалізм',content_type=3,
        topic='Зерно',goal='Продаж',audience='Місцеві',product='Кава',slide_count=8)))
    assert result['project']['state'] == 'FORMAT_SETUP'
    assert len(result['events']) == 7
    assert 'Обери свою нішу' not in result['message']
    assert 'Дані для каруселі збережені' in result['message']
    p=result['project']
    result=service.create_carousel(p['id'],CreateCarousel(request_id='known-script',expected_revision=p['revision']))
    assert len(result['script']['slides']) == 8
