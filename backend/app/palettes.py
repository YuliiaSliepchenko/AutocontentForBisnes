"""Local palette suggestions; no external AI calls."""
def suggest(context, logo_colors=()):
    presets = [
        {'name':'Довіра', 'colors':['#16324F','#F4F7FA','#3E92CC']},
        {'name':'Теплий акцент', 'colors':['#6B4226','#FFF4E6','#D99857']},
        {'name':'Природність', 'colors':['#264653','#E9F5DB','#A3B18A']},
        {'name':'Енергія', 'colors':['#242038','#F7ECE1','#F75C03']},
        {'name':'Пастель', 'colors':['#69585F','#F8EDEB','#D8B4A0']},
        {'name':'Преміум', 'colors':['#171717','#F5F0E8','#B89B72']},
        {'name':'Контраст', 'colors':['#101820','#FFFFFF','#FEE715']},
    ]
    words = ' '.join(filter(None, [context.niche, context.audience, context.positioning])).lower()
    if any(x in words for x in ('їжа','кава','ресторан','кав’яр','кав\'яр')):
        first = 1
    elif any(x in words for x in ('краса','б’юті','діти','ніжн')):
        first = 4
    elif any(x in words for x in ('преміум','люкс','нерухом')):
        first = 5
    else:
        first = 0
    presets.insert(0, presets.pop(first))
    if logo_colors:
        presets[-1] = {'name':'Кольори вашого логотипа', 'colors':list(logo_colors)[:4]}
    return presets
