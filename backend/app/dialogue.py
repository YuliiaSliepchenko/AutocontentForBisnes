"""Exact product copy and numeric menus; no state transitions live here."""
NICHES = ['Освіта / курси / школа', 'Послуги', 'Краса / здоров’я / б’юті',
          'Товари / магазин / e-commerce', 'IT / технології', 'Експерт / коуч / наставник',
          'Ресторан / HoReCa / їжа', 'Виробництво', 'Нерухомість', 'Інше']
STYLES = ['Реалізм', 'Pixar', 'Minecraft', '3D Cartoon', 'Anime', 'Cinematic', 'Мінімалізм', 'Власний стиль']
FORMATS = ['Пост', 'Reels', 'Карусель', 'Прогрів', 'Контент-план', 'Тригерні заголовки',
           'CTA', 'Опис профілю', 'Stories', 'Лід-магніт']
UNAVAILABLE = 'Цей формат буде доступний у наступній версії.'
INTRO = ('Привіт! 👋 Я твій АвтоКонтент для бізнесу.\n'
         'Допоможу створити пости, Reels, каруселі, Stories, прогріви, CTA та контент-плани — від ідеї до готового контенту.')


def menu(items):
    return '\n'.join(f'{n} — {label}' for n, label in enumerate(items, 1))


def prompt(project):
    from .models import State
    p = project
    if p.pending_question == 'niche_description':
        return 'Опиши свою нішу одним реченням.'
    if p.pending_question == 'custom_colors':
        return 'Введіть власні HEX-коди кольорів.'
    if p.pending_question == 'custom_style':
        return 'Опиши власний стиль.'
    if p.pending_question == 'script_changes':
        return 'Що саме потрібно змінити у сценарії?'
    if p.state == State.NICHE_SETUP:
        return INTRO + '\n\nПочнемо з головного. Обери свою нішу 👇\n\n' + menu(NICHES) + '\n\nНапиши номер своєї ніші.'
    if p.state == State.LOGO_SETUP:
        return 'Додай логотип бренду 🖼️ Якщо він є — завантаж його. Якщо немає — напиши “немає”.'
    if p.state == State.COLOR_SETUP:
        return 'Обери брендову палітру:\n\n' + '\n'.join(
            f"{i} — {option['name']}: {', '.join(option['colors'])}" for i, option in enumerate(p.palette_options, 1)
        ) + '\n8 — 🎨 Власні кольори — введіть HEX-коди.'
    if p.state == State.STYLE_SETUP:
        return 'Обери стиль:\n\n' + menu(STYLES)
    if p.state == State.CONTENT_TYPE:
        return 'Який тип контенту вам потрібен?\n\n' + menu(FORMATS)
    if p.state == State.FORMAT_SETUP:
        labels = {'topic':'тему', 'goal':'ціль', 'audience':'аудиторію', 'product':'продукт / послугу'}
        missing = [label for key, label in labels.items() if not getattr(p.setup, key)]
        return ('Для каруселі вкажи: ' + ', '.join(missing) + '.' if missing else 'Дані для каруселі збережені.') + '\nКількість слайдів: 5–8, включно з обкладинкою.'
    if p.state == State.SCRIPT_REVIEW:
        return 'Сценарій готовий. Що робимо далі?\n\n1 — Так, усе підходить. Створюй окремі зображення.\n2 — Редагувати сценарій.'
    if p.state == State.COVER_SELECTION:
        return 'Обери варіант стилю для всієї каруселі:\n\n1 — З людиною\n2 — Без людини'
    if p.state == State.SLIDE_EDIT:
        return f'Що саме потрібно змінити у слайді {p.current_slide}?'
    if p.state == State.SLIDE_REVIEW:
        if p.brief and p.current_slide == p.brief.slide_count:
            return f'Слайд {p.current_slide} готовий. Що далі?\n\n1 — Завершити карусель\n2 — Редагуємо'
        return f'Слайд {p.current_slide} готовий. Що далі?\n\n1 — Наступний\n2 — Редагуємо'
    if p.state == State.COMPLETED:
        return 'Карусель готова. Кожен слайд збережено окремим файлом.'
    return 'Виконується погоджене завдання. Наступні слайди автоматично не створюються.'
