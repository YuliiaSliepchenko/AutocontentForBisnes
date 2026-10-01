from hashlib import sha256
from io import BytesIO
import json
import os

from PIL import Image, UnidentifiedImageError


def save_logo(store, content: bytes):
    if not content or len(content) > 5 * 1024 * 1024:
        raise ValueError('Логотип має бути PNG/JPEG до 5 MB')
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format not in ('PNG', 'JPEG') or image.width * image.height > 16_000_000:
                raise ValueError('Допустимі PNG/JPEG до 16 мегапікселів')
            image.load()
            rgb = image.convert('RGBA')
            background = Image.new('RGBA', rgb.size, 'white')
            background.alpha_composite(rgb)
            palette = background.convert('RGB').resize((100,100)).quantize(colors=4).convert('RGB')
            colors = ['#%02X%02X%02X' % color for _, color in sorted(palette.getcolors(10000), reverse=True)]
            extension = '.png' if image.format == 'PNG' else '.jpg'
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('Некоректний логотип') from exc
    asset_id = sha256(content).hexdigest()
    directory = store.directory / 'logos'
    directory.mkdir(exist_ok=True)
    filename = asset_id + extension
    path = directory / filename
    if not path.exists():
        temp = directory / (asset_id + '.tmp')
        temp.write_bytes(content)
        os.replace(temp, path)
    mime = 'image/png' if extension == '.png' else 'image/jpeg'
    with store.connect(write=True) as db:
        db.execute('INSERT OR IGNORE INTO logos VALUES(?,?,?,?)', (asset_id,filename,json.dumps(colors),mime))
    return {'asset_id':asset_id,'colors':colors,'url':f'/api/logos/{asset_id}'}
