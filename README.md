# AutoContent — carousel + MCP MVP

Самостійний застосунок для покрокового створення каруселей. Python 3.11+, FastAPI,
Pydantic, SQLite, офіційний Python MCP SDK (`mcp==1.26.0`) зі Streamable HTTP.
Frontend — HTML/CSS/JavaScript, без Node-збірки.

**Mock MVP:** тестові сценарії та позначені MOCK PNG 1080×1350. Реальних AI-запитів,
API-ключів, OAuth, оплати, публікації, Cloudflare або deployment немає.
CloudForge до цього проєкту не входить.

## Запуск у Windows / PowerShell

З кореня репозиторію, якщо Python встановлений у PATH:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m backend.app
```

Для запуску без тестових залежностей достатньо `requirements.txt`.
Наявні `.venv` і `.env` повторно створювати/перезаписувати не потрібно.
У поточному середовищі Python знайдений у runtime Codex, `.venv` уже створено,
тому достатньо останньої команди.

- UI: http://127.0.0.1:8000/
- Swagger / REST: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health
- MCP Streamable HTTP: http://127.0.0.1:8000/mcp

За замовчуванням сервер слухає лише loopback. Зупинка — Ctrl+C.
Цей mock MVP запускається з одним Uvicorn worker.

## Конфігурація

`.env` читається з робочої папки; змінні середовища мають пріоритет:

| Змінна | Значення за замовчуванням |
|---|---|
| `HOST` | `127.0.0.1` |
| `PORT` | `8000` |
| `AUTOCONTENT_DATA_DIR` | `data` |
| `AUTOCONTENT_PROVIDER` | `mock` — єдиний доступний режим |

`data/autocontent.db` та `data/assets/` містять стан і файли. `.env`, `.venv` і
`data/` виключені з Git. Для відновлення потрібно зберігати **весь data-каталог**.

## Структура

```text
backend/app/
  __main__.py       запуск Uvicorn через .env
  main.py           FastAPI, REST, health, static UI, mount MCP
  config.py         налаштування
  models.py         Brand, Project, Script, Slide, GenerationJob та команди
  storage.py        SQLite, транзакції, журнал операцій
  workflow.py       спільна бізнес-логіка та state machine
  providers.py      TextProvider, ImageProvider, VideoProvider + mocks
  mcp_server.py     12 MCP tools, без копії workflow
frontend/
  index.html
  app.js
  style.css
tests/
  conftest.py
  test_workflow.py
  test_api_mcp.py
  test_config.py
.env.example
requirements.txt
requirements-dev.txt
pytest.ini
```

## Workflow

```text
create_carousel
  → SCRIPT_REVIEW
      edit_script → SCRIPT_REVIEW (нова версія)
      approve_script → COVERS_PENDING
  → generate_cover_options → COVER_SELECTION
  → select_cover → SLIDE_REVIEW (слайд 2)
      edit_slide → SLIDE_REVIEW (нова версія лише поточного слайда)
      generate_next_slide → SLIDE_REVIEW (наступний слайд)
      підтвердження останнього → COMPLETED
```

1. Вкажіть тему, ціль, аудиторію, продукт/послугу й 5–8 слайдів.
2. Перегляньте **повний** сценарій. `1 — Так, усе підходить`, `2 — Редагувати`.
3. До `approve_script` backend забороняє генерацію зображень.
4. Окрема дія створює два файли слайда 1: `cover_with_person` і `cover_without_person`.
   `COVER_SELECTION` зберігається тільки після успішного створення обох.
5. Виберіть `1 — З людиною` або `2 — Без людини`. Обраний файл стає обкладинкою,
   стиль фіксується, створюється **лише слайд 2**. Обкладинка повторно не генерується.
6. Після кожного слайда: `1 — Наступний`, `2 — Редагуємо`. UI спочатку запитує зміни;
   порожні зміни backend не приймає.
7. Після останнього слайда підтвердження завершує проєкт без нового зображення.

Один слайд — один PNG 1080×1350 (4:5). Для слайда 1 зберігаються два варіанти;
до готової каруселі входить один обраний. Історія версій зберігається. Кожен файл
прив'язаний до версії сценарію. Після погодження сценарій у цьому MVP заморожений;
обкладинка після вибору також не редагується. Редагувати можна поточний основний слайд.

Brand містить `niche`, `logo`, `colors`, `style`, `person_mode`, `typography`,
`visual_rules`, `custom_style`. `person_mode`: `with_person` / `without_person`.
Для каруселі остаточний вибір задається обкладинкою. Стилі: Реалізм, Pixar,
Minecraft, 3D cartoon, Anime, Cinematic, Мінімалізм, Власний стиль.
Останній вимагає `custom_style`. `logo` — збережене посилання/ідентифікатор;
mock не завантажує і не накладає реальний логотип.

## REST API

Усі POST приймають JSON. Повні схеми полів доступні в `/docs`.

| Метод | Endpoint | Дія |
|---|---|---|
| GET | `/health` | Перевірка сервера та SQLite |
| POST | `/api/brands` | `save_brand` |
| POST | `/api/carousels` | `create_carousel` |
| GET | `/api/projects/{id}` | Повний стан, сценарій, версії слайдів, allowed_actions |
| GET | `/api/projects/{id}/status` | Стан та generation jobs |
| GET | `/api/projects/{id}/script?version=1` | Поточний або історичний сценарій |
| POST | `/api/projects/{id}/script/approve` | Погодити сценарій |
| POST | `/api/projects/{id}/script/edit` | Зберегти повністю відредагований сценарій |
| POST | `/api/projects/{id}/covers/generate` | Створити обидві обкладинки |
| POST | `/api/projects/{id}/covers/select` | Вибрати обкладинку та створити слайд 2 |
| POST | `/api/projects/{id}/slides/next` | Погодити поточний і створити наступний |
| POST | `/api/projects/{id}/slides/edit` | Перегенерувати тільки поточний |
| GET | `/api/projects/{id}/slides/{number}` | Усі версії конкретного слайда |
| GET | `/api/jobs/{id}` | Статус завдання |
| GET | `/api/assets/{id}` | Завантажити підтверджений у базі PNG |

### Повтори, конкуренція та відновлення

Кожна POST-команда вимагає унікальний `request_id` (наприклад UUID).
Команди зміни проєкту також вимагають `expected_revision` з останнього `get_project`.

Приклад підтвердження поточного слайда 2:

```json
{
  "request_id": "next-slide-2-unique-id",
  "expected_revision": 4,
  "confirmed_slide": 2
}
```

- Той самий `request_id` + ті самі аргументи повертають збережений результат,
  без нової генерації. Результат повтору — історична відповідь цієї дії;
  для актуального стану викличте `get_project`.
- Той самий ID з іншими аргументами → `409`.
- Застаріла revision, недозволений стан або неправильний поточний слайд → `409`.
- Некоректні поля → `422`, відсутній об'єкт → `404`, помилка провайдера → `502`.
- SQLite `BEGIN IMMEDIATE` серіалізує зміни. Одночасні дублікати не створюють
  повторні jobs; різні запити з однією revision не можуть перестрибнути слайд.
- Намір і job зберігаються перед генерацією. При аварійному завершенні транзакція
  змін проєкту відкочується, job лишається `queued`. Повторіть **ту саму команду**
  з тим самим ID; після звичайної помилки `failed` також допускає такий повтор.
- Готові файли записуються атомарно. Після часткової помилки пари обкладинок
  повтор використовує вже створений файл, а не генерує його вдруге.
- Workflow не залежить від браузерної чи MCP-сесії. UI пам'ятає project ID і
  незавершений запит у localStorage; проєкт також можна відкрити вручну за ID.
- Сервер після перезапуску сам не проходить workflow і не створює наступні слайди.

Mock-генерація синхронна, під транзакцією SQLite. Це обмеження MVP:
довгий реальний provider потребуватиме worker/lease-механізму поза довгою write-транзакцією.

## MCP

Офіційний пакет `mcp`, FastMCP, Streamable HTTP, `stateless_http=True`, JSON-відповіді.
FastAPI lifespan запускає MCP session manager. Бізнес-логіка повністю спільна з REST.

Інструменти:

```text
get_project                 save_brand
create_carousel              get_script
approve_script              edit_script
generate_cover_options      select_cover
generate_next_slide         edit_slide
get_slide                   get_project_status
```

Для команд аргументи вкладені в `command`, наприклад `tools/call`:

```json
{
  "name": "approve_script",
  "arguments": {
    "project_id": "PROJECT_ID",
    "command": {"request_id": "approve-unique-id", "expected_revision": 1}
  }
}
```

HTTP-клієнт має надсилати `Accept: application/json, text/event-stream`.
Схеми інструментів надаються через `tools/list`, результати — `structuredContent`.
Для локального MCP-клієнта вкажіть URL `http://127.0.0.1:8000/mcp`.

MCP та UI повідомляють про необхідність явного підтвердження. Backend перевіряє
стан, revision і поточний слайд: заборонені чи ще не створені матеріали не повертаються.
Без окремої довіреної UI-авторизації backend не може довести, що команда від моделі
дійсно відображає волю людини; цей MVP не додає окремої системи авторизації підтверджень.

Вбудований iframe-віджет ChatGPT поки не реалізований: є MCP tools та локальний
вебінтерфейс. Для подальшого ChatGPT App потрібні UI-ресурс MCP Apps, HTTPS-адреса,
абсолютні URL файлів і налаштування дозволених доменів. Підключення до ChatGPT,
Cloudflare та deployment зараз не виконуються.

## Тести

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

Тести використовують тимчасову SQLite та mock providers. Перевіряють повний
цикл 5–8 слайдів, заборону зображень до approval, версії сценарію, дві обкладинки,
збереження стилю, редагування одного слайда, повтори й конкурентні запити,
перезапуск, перервану генерацію, PNG-розміри, REST і реальні JSON-RPC запити до
Streamable HTTP `/mcp`, включно з повним циклом через усі 12 tools.

## Реальний image provider — наступний етап

1. Реалізувати `ImageProvider.generate(ImageRequest, idempotency_key=...)`.
2. Передавати бренд, погоджений текст, зафіксований стиль, референс обкладинки,
   `base_asset_id` при редагуванні та конкретні зміни. Доступ до asset bytes
   організувати через сховище; файлові шляхи не передаються від клієнта.
3. Повертати один PNG 1080×1350. Backend перевіряє формат, розмір і один кадр.
   Заборона collage/grid/storyboard/contact sheet передається провайдеру;
   зміст реальних AI-зображень додатково потребуватиме візуальної перевірки.
4. Додати timeout, керовані retries, idempotency провайдера та відновлення за його
   job ID. SQLite сама не гарантує exactly-once зовнішнього платного API після аварії.
5. Винести тривалу генерацію з write-транзакції у durable worker з lease.
6. Додати точне накладання логотипу/тексту та перевірку стилю; mock цього не імітує.

`TextProvider` та `VideoProvider` теж абстрактні. Mock video повертає лише тестовий
маркер, не відеофайл; Reels та інші формати не входять у поточний MVP.
