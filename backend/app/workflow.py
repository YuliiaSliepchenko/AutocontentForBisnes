"""Single source of truth for REST and MCP. No transport-specific decisions."""
import hashlib
import json
import logging
import os
from io import BytesIO

from PIL import Image

from .models import (
    Brand, Brief, CreateContentProject, CreateCarousel, EditScript, EditSlide, GenerationJob, NextSlide,
    Project, ProjectCommand, SaveBrand, Script, SelectCover, Slide, State, new_id,
)
from .providers import ImageRequest, MockImageProvider, MockTextProvider
from .storage import Store, dump
from .dialogue import INTRO, UNAVAILABLE, prompt
from .jobs import JobRunner, JobBusy
from . import onboarding

logger = logging.getLogger(__name__)


class WorkflowError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


TRANSITIONS = {
    State.IDLE: {State.NICHE_SETUP},
    State.NICHE_SETUP: {State.LOGO_SETUP},
    State.LOGO_SETUP: {State.COLOR_SETUP},
    State.COLOR_SETUP: {State.STYLE_SETUP},
    State.STYLE_SETUP: {State.CONTENT_TYPE},
    State.CONTENT_TYPE: {State.FORMAT_SETUP},
    State.FORMAT_SETUP: {State.SCRIPT_CREATION},
    State.SCRIPT_CREATION: {State.SCRIPT_REVIEW},
    State.SCRIPT_REVIEW: {State.SCRIPT_CREATION, State.COVER_GENERATION},
    State.COVER_GENERATION: {State.COVER_SELECTION},
    State.COVER_SELECTION: {State.SLIDE_GENERATION},
    State.SLIDE_GENERATION: {State.SLIDE_REVIEW},
    State.SLIDE_REVIEW: {State.SLIDE_EDIT, State.SLIDE_GENERATION, State.COMPLETED},
    State.SLIDE_EDIT: {State.SLIDE_GENERATION},
    State.COMPLETED: set(),
}


class CarouselService:
    def __init__(self, store: Store, text_provider=None, image_provider=None):
        self.store = store
        self.text = text_provider or MockTextProvider()
        self.images = image_provider or MockImageProvider()
        self.runner = JobRunner(store)

    def _transition(self, db, project, target, action):
        if target not in TRANSITIONS[project.state]:
            raise WorkflowError(f'Forbidden transition: {project.state} → {target}')
        db.execute('INSERT INTO events(project_id,from_state,to_state,action,revision) VALUES(?,?,?,?,?)',
                   (project.id, project.state, target, action, project.revision + 1))
        project.state = target

    def _read(self, db, table, key, model):
        row = db.execute(f'SELECT data FROM {table} WHERE id=?', (key,)).fetchone()
        if row is None:
            raise WorkflowError(f'{table}: not found', 404)
        return model.model_validate_json(row['data'])

    def _script(self, db, project_id, version):
        row = db.execute('SELECT data FROM scripts WHERE project_id=? AND version=?', (project_id, version)).fetchone()
        if row is None:
            raise WorkflowError('Script not found', 404)
        return Script.model_validate_json(row['data'])

    def _snapshot(self, db, project):
        slides = [json.loads(row['data']) for row in db.execute(
            'SELECT data FROM slides WHERE project_id=? ORDER BY number, variant, version', (project.id,))]
        actions = {
            State.IDLE: [],
            State.NICHE_SETUP: ['save_brand'], State.LOGO_SETUP: ['save_brand'],
            State.COLOR_SETUP: ['save_brand'], State.STYLE_SETUP: ['save_brand'],
            State.CONTENT_TYPE: ['save_brand'], State.FORMAT_SETUP: ['create_carousel'],
            State.SCRIPT_CREATION: ['resume_generation'],
            State.SCRIPT_REVIEW: ['approve_script', 'begin_script_edit'],
            State.COVER_GENERATION: ['generate_cover_options', 'resume_generation'],
            State.COVER_SELECTION: ['select_cover'],
            State.SLIDE_GENERATION: ['resume_generation'],
            State.SLIDE_REVIEW: ['generate_next_slide', 'begin_slide_edit'],
            State.SLIDE_EDIT: ['edit_slide'],
            State.COMPLETED: [],
        }
        if project.pending_question == 'script_changes':
            actions[State.SCRIPT_REVIEW] = ['edit_script']
        events = [dict(row) for row in db.execute('SELECT * FROM events WHERE project_id=? ORDER BY id', (project.id,))]
        return {'project': project.model_dump(mode='json'),
                'script': self._script(db, project.id, project.script_version).model_dump(mode='json') if project.script_version else None,
                'slides': slides, 'allowed_actions': actions[project.state], 'message': prompt(project), 'events': events}

    def get_project(self, project_id: str):
        with self.store.connect() as db:
            return self._snapshot(db, self._read(db, 'projects', project_id, Project))

    def get_project_status(self, project_id: str):
        with self.store.connect() as db:
            result = self._snapshot(db, self._read(db, 'projects', project_id, Project))
            jobs = [GenerationJob(**dict(row)).model_dump() for row in db.execute(
                'SELECT * FROM jobs WHERE project_id=?', (project_id,))]
        return {'project': result['project'], 'allowed_actions': result['allowed_actions'], 'jobs': jobs}

    def get_script(self, project_id: str, version: int | None = None):
        with self.store.connect() as db:
            project = self._read(db, 'projects', project_id, Project)
            return self._script(db, project_id, version or project.script_version).model_dump(mode='json')

    def get_slide(self, project_id: str, slide_number: int):
        snapshot = self.get_project(project_id)
        slides = [s for s in snapshot['slides'] if s['number'] == slide_number]
        if not slides:
            raise WorkflowError('Slide has not been generated', 404)
        return {'versions': slides, 'selected_cover': snapshot['project']['selected_cover']}

    def get_job(self, job_id: str):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if row is None:
                raise WorkflowError('Job not found', 404)
            return GenerationJob(**dict(row)).model_dump()

    def asset_path(self, asset_id: str):
        # Only committed assets can be downloaded, never arbitrary filesystem paths.
        with self.store.connect() as db:
            row = db.execute('SELECT asset_id FROM slides WHERE asset_id=?', (asset_id,)).fetchone()
        if not row:
            raise WorkflowError('Asset not found', 404)
        path = self.store.assets / f'{row[0]}.png'
        if not path.is_file():
            raise WorkflowError('Asset file unavailable', 404)
        return path

    def _execute(self, kind, command, project_id, action):
        payload = command.model_dump(mode='json')
        signature = hashlib.sha256(dump([kind, project_id, payload]).encode()).hexdigest()
        key = command.request_id
        result = None
        with self.store.connect(write=True) as db:
            old = db.execute('SELECT * FROM operations WHERE request_id=?', (key,)).fetchone()
            if old and old['signature'] != signature:
                raise WorkflowError('request_id already used with different arguments')
            if old and old['status'] == 'succeeded':
                result = json.loads(old['response'])
            else:
                if old is None:
                    db.execute('INSERT INTO operations VALUES(?,?,?,?,?,?,?,?)',
                               (key, signature, kind, project_id, dump(payload), 'queued', None, None))
                result = action(db, key)
                db.execute('UPDATE operations SET status=\'succeeded\', response=?, error=NULL WHERE request_id=?', (dump(result), key))
        # Provider work begins only AFTER state, intent and job are committed.
        if result.get('job_id'):
            self._run_job(result['job_id'])
            fresh = self.get_project(result['project']['id'])
            fresh['job_id'] = result['job_id']
            return fresh
        return result

    def create_content_project(self, command: CreateContentProject):
        def work(db, key):
            p = Project(setup=onboarding.initial_context(command.first_message,command.context), first_message=command.first_message)
            db.execute('INSERT INTO events(project_id,from_state,to_state,action,revision) VALUES(?,NULL,?,?,?)',
                       (p.id, State.IDLE, 'create_content_project', p.revision))
            try:
                onboarding.advance_known(db, p, self._transition)
            except ValueError as exc:
                raise WorkflowError(str(exc), 422) from exc
            db.execute('INSERT INTO projects VALUES(?,?)', (p.id, dump(p)))
            result = self._snapshot(db, p)
            if p.state != State.NICHE_SETUP:
                result['message'] = INTRO + '\n\n' + result['message']
            if p.state == State.CONTENT_TYPE and p.setup.content_type not in (None, 3):
                result['message'] = UNAVAILABLE + '\n\n' + result['message']
            return result
        return self._execute('create_content_project', command, None, work)

    def save_brand(self, project_id: str, command: SaveBrand):
        def work(db, p, key):
            try:
                return onboarding.answer(db, p, command, self._transition)
            except ValueError as exc:
                raise WorkflowError(str(exc), 422) from exc
        return self._change('save_brand', project_id, command, set(onboarding.ORDER[1:-1]), work)

    def create_carousel(self, project_id: str, command: CreateCarousel):
        def work(db, p, key):
            if not p.brand or p.setup.content_type != 3:
                raise WorkflowError('Complete brand and carousel selection first')
            try:
                p.brief = command.brief or Brief(**{k:getattr(p.setup,k) for k in Brief.model_fields})
            except ValueError as exc:
                raise WorkflowError('Fill missing carousel brief fields', 422) from exc
            self._queue(db, p, key, 'script', State.SCRIPT_CREATION)
        return self._change('create_carousel', project_id, command, {State.FORMAT_SETUP}, work)

    @staticmethod
    def _validate_script(script, project):
        if [s.number for s in script.slides] != list(range(1, project.brief.slide_count + 1)):
            raise WorkflowError('Script must contain every slide in order, matching slide_count', 422)

    def _change(self, kind, project_id, command, states, action):
        def work(db, key):
            project = self._read(db, 'projects', project_id, Project)
            if project.revision != command.expected_revision:
                raise WorkflowError('Stale project revision; fetch project before the next action')
            if project.state not in states:
                raise WorkflowError(f'{kind} is forbidden in {project.state}')
            message = action(db, project, key)
            project.revision += 1
            db.execute('UPDATE projects SET data=? WHERE id=?', (dump(project), project.id))
            result = self._snapshot(db, project)
            if message:
                result['message'] = message
            if project.active_job_id:
                result['job_id'] = project.active_job_id
            return result
        return self._execute(kind, command, project_id, work)

    def begin_script_edit(self, project_id: str, command: ProjectCommand):
        def work(db, p, key):
            p.pending_question = 'script_changes'
        return self._change('begin_script_edit', project_id, command, {State.SCRIPT_REVIEW}, work)

    def edit_script(self, project_id: str, command: EditScript):
        def work(db, p, key):
            if p.pending_question != 'script_changes':
                raise WorkflowError('Choose edit and provide changes first')
            p.pending_question = None
            self._queue(db, p, key, 'script_edit', State.SCRIPT_CREATION, changes=command.changes)
        return self._change('edit_script', project_id, command, {State.SCRIPT_REVIEW}, work)

    def approve_script(self, project_id: str, command: ProjectCommand):
        def work(db, p, key):
            if p.pending_question:
                raise WorkflowError('Finish script editing before approval')
            script = self._script(db, p.id, p.script_version)
            script.approved = True
            db.execute('UPDATE scripts SET data=? WHERE project_id=? AND version=?', (dump(script), p.id, p.script_version))
            self._queue(db, p, key, 'covers', State.COVER_GENERATION)
        return self._change('approve_script', project_id, command, {State.SCRIPT_REVIEW}, work)

    def _render(self, db, p, job, number, variant, style, changes=None):
        script = self._script(db, p.id, p.script_version)
        if not script.approved:
            raise WorkflowError('Images require an approved script')
        version = db.execute('SELECT COALESCE(MAX(version),0)+1 FROM slides WHERE project_id=? AND number=? AND variant=?',
                             (p.id, number, variant)).fetchone()[0]
        asset_id = hashlib.sha256(f'{job}:{number}:{variant}:{version}'.encode()).hexdigest()
        path = self.store.assets / f'{asset_id}.png'
        request = ImageRequest(project_id=p.id, slide=script.slides[number-1], script_version=p.script_version,
                               slide_version=version, variant=variant, brand=p.brand,
                               style_snapshot=style, changes=changes)
        if changes:
            previous = db.execute('SELECT asset_id FROM slides WHERE project_id=? AND number=? AND variant=? ORDER BY version DESC LIMIT 1',
                                  (p.id, number, variant)).fetchone()
            request.base_asset_id = previous['asset_id'] if previous else None
        # Reuse a complete artifact after crash/partial pair failure. Atomic rename
        # ensures incomplete files are never used or exposed.
        if not path.exists():
            content = self.images.generate(request, idempotency_key=asset_id)
            self._validate_image(content)
            temp = path.with_suffix('.tmp')
            with temp.open('wb') as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp, path)
        self._validate_image(path.read_bytes())
        slide = Slide(id=asset_id, project_id=p.id, number=number, version=version,
                      script_version=p.script_version, variant=variant, asset_id=asset_id,
                      url=f'/api/assets/{asset_id}', feedback=changes, style_snapshot=style)
        return slide

    @staticmethod
    def _validate_image(content):
        with Image.open(BytesIO(content)) as image:
            if image.format != 'PNG' or image.size != (1080, 1350) or getattr(image, 'n_frames', 1) != 1:
                raise WorkflowError('Provider must return one 1080x1350 PNG', 502)
            image.verify()

    def generate_cover_options(self, project_id: str, command: ProjectCommand):
        return self._resume(project_id, command, {State.COVER_GENERATION}, 'generate_cover_options')

    def select_cover(self, project_id: str, command: SelectCover):
        def work(db, p, key):
            variant = 'cover_with_person' if command.choice == 1 else 'cover_without_person'
            row = db.execute('SELECT data FROM slides WHERE project_id=? AND number=1 AND variant=?', (p.id, variant)).fetchone()
            if not row:
                raise WorkflowError('Both cover options must be generated first')
            if db.execute('SELECT COUNT(*) FROM slides WHERE project_id=? AND number=1', (p.id,)).fetchone()[0] != 2:
                raise WorkflowError('Exactly two separate cover options required')
            cover = Slide.model_validate_json(row['data'])
            p.selected_cover = cover.id
            p.locked_style = dict(cover.style_snapshot, reference_asset_id=cover.asset_id)
            p.current_slide = 2
            self._queue(db, p, key, 'slide', State.SLIDE_GENERATION, number=2)
        return self._change('select_cover', project_id, command, {State.COVER_SELECTION}, work)

    def generate_next_slide(self, project_id: str, command: NextSlide):
        def work(db, p, key):
            if command.confirmed_slide != p.current_slide:
                raise WorkflowError('Confirm the current slide only')
            if p.current_slide == p.brief.slide_count:
                self._transition(db, p, State.COMPLETED, 'confirm_last_slide')
            else:
                p.current_slide += 1
                self._queue(db, p, key, 'slide', State.SLIDE_GENERATION, number=p.current_slide)
        return self._change('generate_next_slide', project_id, command, {State.SLIDE_REVIEW}, work)

    def begin_slide_edit(self, project_id: str, command: ProjectCommand):
        def work(db, p, key):
            self._transition(db, p, State.SLIDE_EDIT, 'choose_edit')
        return self._change('begin_slide_edit', project_id, command, {State.SLIDE_REVIEW}, work)

    def edit_slide(self, project_id: str, command: EditSlide):
        def work(db, p, key):
            if command.slide_number != p.current_slide:
                raise WorkflowError('Only the current slide can be edited')
            self._queue(db, p, key, 'slide_edit', State.SLIDE_GENERATION, number=p.current_slide, changes=command.changes)
        return self._change('edit_slide', project_id, command, {State.SLIDE_EDIT}, work)

    def _queue(self, db, p, key, kind, state, **payload):
        if p.active_job_id:
            raise WorkflowError('A generation job is already active')
        job_id = new_id()
        self._transition(db, p, state, kind)
        p.active_job_id = job_id
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)', (job_id,key,p.id,kind,'queued',None))
        db.execute('INSERT INTO generation_tasks(job_id,payload) VALUES(?,?)',
                   (job_id,dump(dict(payload,kind=kind,project_id=p.id))))

    def _resume(self, project_id, command, states, name):
        def work(db, p, key):
            if not p.active_job_id:
                raise WorkflowError('No pending generation')
        return self._change(name, project_id, command, states, work)

    def resume_generation(self, project_id: str, command: ProjectCommand):
        return self._resume(project_id, command,
                            {State.SCRIPT_CREATION,State.COVER_GENERATION,State.SLIDE_GENERATION}, 'resume_generation')

    def _run_job(self, job_id):
        try:
            self.runner.run(job_id, self._generate, self._complete)
        except JobBusy as exc:
            raise WorkflowError(str(exc)) from exc
        except WorkflowError:
            raise
        except Exception as exc:
            logger.exception('Mock generation failed')
            raise WorkflowError('Generation failed. Resume the same job; no next slide was generated.', 502) from exc

    def _generate(self, task, job):
        with self.store.connect() as db:
            p = self._read(db, 'projects', task['project_id'], Project)
            if p.active_job_id != job:
                raise WorkflowError('Job is no longer active')
            kind = task['kind']
            if kind in ('script','script_edit'):
                if kind == 'script':
                    slides = self.text.create_script(p.brief, p.brand, idempotency_key=job)
                else:
                    slides = self.text.edit_script(self._script(db,p.id,p.script_version), task['changes'], idempotency_key=job)
                script = Script(project_id=p.id,version=p.script_version+1,slides=slides)
                self._validate_script(script,p)
                if script.slides[0].role != 'cover' or script.slides[-1].role != 'cta':
                    raise WorkflowError('Script requires a cover and final CTA', 422)
                return script
            if kind == 'covers':
                output = []
                for mode in ('with_person','without_person'):
                    style = dict(p.brand.model_dump(mode='json'),person_mode=mode,
                                 composition='single-slide',characters=[],key_objects=[],atmosphere=p.brand.style.value)
                    output.append(self._render(db,p,job,1,f'cover_{mode}',style))
                return output
            return [self._render(db,p,job,task['number'],'slide',p.locked_style,task.get('changes'))]

    def _complete(self, db, task, job, output):
        p = self._read(db,'projects',task['project_id'],Project)
        if p.active_job_id != job:
            raise WorkflowError('Stale generation result')
        if isinstance(output,Script):
            db.execute('INSERT INTO scripts VALUES(?,?,?)',(p.id,output.version,dump(output)))
            p.script_version = output.version
            target = State.SCRIPT_REVIEW
        else:
            if task['kind'] == 'covers' and (len(output) != 2 or len({s.asset_id for s in output}) != 2):
                raise WorkflowError('Two distinct cover files required')
            for slide in output:
                db.execute('INSERT INTO slides VALUES(?,?,?,?,?,?,?)',
                           (slide.id,p.id,slide.number,slide.version,slide.variant,slide.asset_id,dump(slide)))
            target = State.COVER_SELECTION if task['kind'] == 'covers' else State.SLIDE_REVIEW
            if target == State.COVER_SELECTION:
                p.current_slide = 1
        self._transition(db,p,target,'generation_completed')
        p.active_job_id = None
        p.revision += 1
        db.execute('UPDATE projects SET data=? WHERE id=?',(dump(p),p.id))
