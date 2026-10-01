import json
import re

from .dialogue import NICHES, UNAVAILABLE
from .models import Brand, State, Style
from .palettes import suggest

ORDER = [State.IDLE, State.NICHE_SETUP, State.LOGO_SETUP, State.COLOR_SETUP,
         State.STYLE_SETUP, State.CONTENT_TYPE, State.FORMAT_SETUP]


def initial_context(message, context):
    """Mock/local extraction. ChatGPT should additionally supply structured known context."""
    result = context.model_copy(deep=True)
    if not message:
        return result
    labels = {'ніша':'niche','тема':'topic','ціль':'goal','аудиторія':'audience','продукт':'product','послуга':'product','позиціонування':'positioning'}
    for label, field in labels.items():
        match = re.search(rf'{label}\s*:\s*([^;\n]+)',message,re.IGNORECASE)
        if match and not getattr(result,field):
            setattr(result,field,match.group(1).strip())
    lower = message.lower()
    if not result.content_type:
        if 'карусел' in lower:
            result.content_type = 3
        elif 'reels' in lower:
            result.content_type = 2
    if not result.niche:
        if any(word in lower for word in ('кав’ярн',"кав'ярн",'кавярн','кафе')):
            result.niche = 'Кав’ярня'
    if not result.topic:
        match = re.search(r'карусел\w*\s+про\s+([^;\n]+)',message,re.IGNORECASE)
        if match:
            result.topic = match.group(1).strip()
    return result


def advance_known(db, p, transition):
    """Consume known, validated fields through EACH state, recording every transition."""
    s = p.setup
    while p.state in ORDER[:-1]:
        ready = {
            State.IDLE: True,
            State.NICHE_SETUP: bool(s.niche),
            State.LOGO_SETUP: bool(s.no_logo or s.logo_asset_id),
            State.COLOR_SETUP: bool(s.colors),
            State.STYLE_SETUP: bool(s.style and (s.style != Style.CUSTOM or s.custom_style)),
            State.CONTENT_TYPE: s.content_type == 3,
        }[p.state]
        if not ready:
            break
        if p.state == State.LOGO_SETUP and s.logo_asset_id:
            if not db.execute('SELECT id FROM logos WHERE id=?', (s.logo_asset_id,)).fetchone():
                raise ValueError('Логотип не знайдено. Спочатку завантажте файл.')
        next_state = ORDER[ORDER.index(p.state) + 1]
        transition(db, p, next_state, 'known_setup_value')
        if next_state == State.COLOR_SETUP and not p.palette_options:
            row = db.execute('SELECT colors FROM logos WHERE id=?', (s.logo_asset_id,)).fetchone() if s.logo_asset_id else None
            p.palette_options = suggest(s, json.loads(row['colors']) if row else ())
    if p.state == State.FORMAT_SETUP and not p.brand:
        p.brand = Brand(niche=s.niche, logo=s.logo_asset_id, colors=s.colors, style=s.style,
                        custom_style=s.custom_style, typography=s.typography, visual_rules=s.visual_rules)
        db.execute('INSERT INTO brands VALUES(?,?)', (p.brand.id, p.brand.model_dump_json()))


def answer(db, p, command, transition):
    s, state = p.setup, p.state
    if state == State.NICHE_SETUP:
        if command.choice == 10:
            p.pending_question = 'niche_description'
            return None
        if command.text:
            s.niche = command.text
        elif command.choice is not None and 1 <= command.choice <= 9:
            s.niche = NICHES[command.choice - 1]
        else:
            raise ValueError('Оберіть нішу 1–10 або опишіть її.')
    elif state == State.LOGO_SETUP:
        if command.logo_asset_id:
            s.logo_asset_id = command.logo_asset_id
            s.no_logo = False
        elif command.text and command.text.lower() == 'немає':
            s.no_logo = True
        else:
            raise ValueError('Завантажте логотип або напишіть «немає».')
    elif state == State.COLOR_SETUP:
        if command.colors:
            s.colors = command.colors
        elif command.choice == 8:
            p.pending_question = 'custom_colors'
            return None
        elif command.choice is not None and 1 <= command.choice <= 7:
            s.colors = p.palette_options[command.choice - 1]['colors']
        else:
            raise ValueError('Оберіть палітру 1–8 або введіть HEX-коди.')
    elif state == State.STYLE_SETUP:
        if p.pending_question == 'custom_style' and command.text:
            s.style, s.custom_style = Style.CUSTOM, command.text
        elif command.choice == 8:
            p.pending_question = 'custom_style'
            return None
        elif command.choice is not None and 1 <= command.choice <= 7:
            s.style = list(Style)[command.choice - 1]
        else:
            raise ValueError('Оберіть стиль 1–8.')
    elif state == State.CONTENT_TYPE:
        if command.choice is None:
            raise ValueError('Оберіть формат 1–10.')
        if command.choice != 3:
            return UNAVAILABLE
        s.content_type = 3
    else:
        raise ValueError('Налаштування бренду на цьому етапі заборонено.')
    p.pending_question = None
    advance_known(db, p, transition)
    return None
