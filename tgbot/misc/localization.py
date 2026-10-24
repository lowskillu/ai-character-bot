"""Локализация текстов для бота"""

# Тексты для кастомизации профиля
CUSTOMIZATION_TEXTS = {
    "ru": {
        "profile_preview": "🔍 Вот как сейчас выглядит твой персонаж:",
        "name_label": "Имя",
        "appearance_label": "Внешность", 
        "body_label": "Телосложение",
        "clothing_label": "Одежда",
        "personality_label": "Характер",
        "location_label": "Локация",
        "role_label": "Роль",
        "skin_color_label": "Цвет кожи",
        "style_label": "Стиль",
        "body_type_label": "Телосложение",
        "height_label": "Рост",
        "can_change_params": "Ты можешь изменить любой параметр, просто выбери нужный пункт в меню ниже 😊",
        "save_warning": "⚠️ Чтобы сохранить и применить образ — обязательно нажми:",
        "finish_setup": "✅ Завершить настройку",
        "random_profile": "🎲 Случайный образ",
        "back": "🔙 Назад",
        "random_name": "🎲 Случайное имя",
        "choose_name_title": "👑 Давай выберем имя для персонажа",
        "choose_name_desc": "Просто выбери понравившееся имя из списка ниже! 🙂",
        "current_name": "Текущее имя",
        "appearance_title": "💇 Настроим внешность персонажа",
        "appearance_desc": "Выбери цвет волос, кожи и стиль — так, как тебе нравится 🙂",
        "random_generated": "Случайный образ сгенерирован!",
        "random_name_selected": "Случайное имя выбрано!",
        "name_required": "Пожалуйста, укажите хотя бы имя персонажа!",
        "profile_error": "Ошибка при создании профиля",
        "use_menu_buttons": "Пожалуйста, используйте кнопки меню для настройки",
        "value_saved": "✅ Значение сохранено!"
    },
    "en": {
        "profile_preview": "🔍 Here's how your character looks now:",
        "name_label": "Name",
        "appearance_label": "Appearance",
        "body_label": "Build",
        "clothing_label": "Clothing",
        "personality_label": "Personality",
        "location_label": "Location",
        "role_label": "Role",
        "skin_color_label": "Skin Color",
        "style_label": "Style",
        "body_type_label": "Body Type", 
        "height_label": "Height",
        "can_change_params": "You can change any parameter, just select the needed item in the menu below 😊",
        "save_warning": "⚠️ To save and apply the look — be sure to press:",
        "finish_setup": "✅ Finish Setup",
        "random_profile": "🎲 Random Look",
        "back": "🔙 Back",
        "random_name": "🎲 Random Name",
        "choose_name_title": "👑 Let's choose a name for your character",
        "choose_name_desc": "Just pick a name you like from the list below! 🙂",
        "current_name": "Current name",
        "appearance_title": "💇 Let's set up the character's look",
        "appearance_desc": "Pick the hair, skin tone and style you like 🙂",
        "random_generated": "Random profile generated!",
        "random_name_selected": "Random name selected!",
        "name_required": "Please set at least the character name!",
        "profile_error": "Error creating profile",
        "use_menu_buttons": "Please use the menu buttons for customization",
        "value_saved": "✅ Value saved!"
    }
}

# Кнопки главного меню кастомизации
CUSTOMIZATION_BUTTONS = {
    "ru": {
        "name": "👑 Имя",
        "appearance": "💇 Внешность", 
        "body": "📐 Телосложение",
        "clothing": "👕 Одежда",
        "personality": "🐱 Характер",
        "location": "🌇 Локация",
        "role": "🎭 Роль"
    },
    "en": {
        "name": "👑 Name",
        "appearance": "💇 Appearance",
        "body": "📐 Build",
        "clothing": "👕 Clothing",
        "personality": "🐱 Personality",
        "location": "🌇 Location",
        "role": "🎭 Role"
    }
}

# Опции для локации с локализацией
LOCATION_OPTIONS_LOCALIZED = {
    "ru": [
        ("🍽️ Кафе", "cafe"),
        ("🌳 Парк", "park"),
        ("📚 Библиотека", "library"),
        ("🌆 Вечерний город", "city_evening"),
    ],
    "en": [
        ("🍽️ Cafe", "cafe"),
        ("🌳 Park", "park"),
        ("📚 Library", "library"),
        ("🌆 City in the evening", "city_evening"),
    ]
}

# Опции для роли с локализацией
ROLE_OPTIONS_LOCALIZED = {
    "ru": [
        ("🤝 Друг", "friend"),
        ("☕ Бариста", "barista"),
        ("📚 Репетитор", "tutor"),
    ],
    "en": [
        ("🤝 Friend", "friend"),
        ("☕ Barista", "barista"),
        ("📚 Tutor", "tutor"),
    ]
}

# get_text() used to sit here as the intended i18n entry point and was never
# called from anywhere — handlers write `if lang == "ru"` inline instead. The
# tables below are the real shared asset; when the inline branches are finally
# consolidated, that migration should bring its own accessor.

# --- Appearance (Внешность) ---
APPEARANCE_HAIR_OPTIONS = {
    "ru": [
        ("🤍 Светлые", "light"),
        ("🤎 Каштановые", "brown"),
        ("🧡 Рыжие", "red"),
        ("🖤 Чёрные", "black"),
    ],
    "en": [
        ("🤍 Light", "light"),
        ("🤎 Brown", "brown"),
        ("🧡 Red", "red"),
        ("🖤 Black", "black"),
    ]
}

APPEARANCE_SKIN_OPTIONS = {
    "ru": [
        ("⬜ Светлая", "light skin"),
        ("🏽 Смуглая", "tanned skin"),
        ("🏿 Тёмная", "dark skin"),
        ("🌾 Оливковая", "olive skin"),
    ],
    "en": [
        ("⬜ Light", "light skin"),
        ("🏽 Tanned", "tanned skin"),
        ("🏿 Dark", "dark skin"),
        ("🌾 Olive", "olive skin"),
    ]
}

APPEARANCE_STYLE_OPTIONS = {
    "ru": [
        ("🧣 Уютный", "cozy style"),
        ("💼 Деловой", "business style"),
        ("🧥 Минимализм", "minimalist style"),
        ("🎨 Творческий", "artsy style"),
        ("🎧 Стритстайл", "streetwear style"),
        ("💫 Классика", "classic style"),
    ],
    "en": [
        ("🧣 Cozy", "cozy style"),
        ("💼 Business", "business style"),
        ("🧥 Minimalist", "minimalist style"),
        ("🎨 Artsy", "artsy style"),
        ("🎧 Streetwear", "streetwear style"),
        ("💫 Classic", "classic style"),
    ]
}

APPEARANCE_HAIR_VALUE_TO_TEXT = {
    "ru": {v: t for t, v in APPEARANCE_HAIR_OPTIONS["ru"]},
    "en": {v: t for t, v in APPEARANCE_HAIR_OPTIONS["en"]}
}
APPEARANCE_SKIN_VALUE_TO_TEXT = {
    "ru": {v: t for t, v in APPEARANCE_SKIN_OPTIONS["ru"]},
    "en": {v: t for t, v in APPEARANCE_SKIN_OPTIONS["en"]}
}
APPEARANCE_STYLE_VALUE_TO_TEXT = {
    "ru": {v: t for t, v in APPEARANCE_STYLE_OPTIONS["ru"]},
    "en": {v: t for t, v in APPEARANCE_STYLE_OPTIONS["en"]}
}

# --- Build (Телосложение) ---
BODY_TYPE_OPTIONS = {
    "ru": [
        ("🌿 Худощавое", "slim build"),
        ("🙂 Обычное", "average build"),
        ("🏋️ Спортивное", "athletic build"),
    ],
    "en": [
        ("🌿 Slim", "slim build"),
        ("🙂 Average", "average build"),
        ("🏋️ Athletic", "athletic build"),
    ]
}

HEIGHT_OPTIONS = {
    "ru": [
        ("🐾 Невысокий рост", "short"),
        ("📏 Средний рост", "average"),
        ("🗼 Высокий рост", "tall"),
    ],
    "en": [
        ("🐾 Short", "short"),
        ("📏 Average height", "average"),
        ("🗼 Tall", "tall"),
    ]
}

BODY_TYPE_VALUE_TO_TEXT = {
    "ru": {v: t for t, v in BODY_TYPE_OPTIONS["ru"]},
    "en": {v: t for t, v in BODY_TYPE_OPTIONS["en"]}
}
HEIGHT_VALUE_TO_TEXT = {
    "ru": {v: t for t, v in HEIGHT_OPTIONS["ru"]},
    "en": {v: t for t, v in HEIGHT_OPTIONS["en"]}
}


# Personality, Clothing, Location, Role.
# Russian labels agree with «характер» (masculine noun), so they say nothing
# about the character's gender.
PERSONALITY_OPTIONS_RU = [
    ("🤗 Добрый", "Kind"),
    ("🧐 Рассудительный", "Thoughtful"),
    ("😄 Весёлый", "Cheerful"),
    ("📋 Серьёзный", "Serious"),
    ("😎 Уверенный", "Confident"),
    ("🌱 Скромный", "Modest and quiet"),
    ("⚡ Энергичный", "Energetic"),
    ("💬 Разговорчивый", "Talkative"),
    ("🧠 Спокойный", "Calm"),
]
PERSONALITY_OPTIONS_EN = [
    ("🤗 Kind", "Kind"),
    ("🧐 Thoughtful", "Thoughtful"),
    ("😄 Cheerful", "Cheerful"),
    ("📋 Serious", "Serious"),
    ("😎 Confident", "Confident"),
    ("🌱 Quiet", "Modest and quiet"),
    ("⚡ Energetic", "Energetic"),
    ("💬 Talkative", "Talkative"),
    ("🧠 Calm", "Calm"),
]
CLOTHING_OPTIONS_RU = [
    ("🧥 Свитер и джинсы", "Loose long-sleeved sweater and jeans"),
    ("👔 Рубашка и брюки", "Long-sleeved shirt and trousers"),
    ("🧢 Худи и спортивные брюки", "Loose hoodie and track pants"),
]

CLOTHING_OPTIONS_EN = [
    ("🧥 Sweater and jeans", "Loose long-sleeved sweater and jeans"),
    ("👔 Shirt and trousers", "Long-sleeved shirt and trousers"),
    ("🧢 Hoodie and track pants", "Loose hoodie and track pants"),
]


# Локализованные словари для получения текста по значению
PERSONALITY_VALUE_TO_TEXT = {
    "ru": {v: t for t, v in PERSONALITY_OPTIONS_RU},
    "en": {v: t for t, v in PERSONALITY_OPTIONS_EN}
}
CLOTHING_VALUE_TO_TEXT = {
    "ru": {v: t for t, v in CLOTHING_OPTIONS_RU},
    "en": {v: t for t, v in CLOTHING_OPTIONS_EN}
}
LOCATION_VALUE_TO_TEXT = {
    "ru": {v: t for t, v in LOCATION_OPTIONS_LOCALIZED["ru"]},
    "en": {v: t for t, v in LOCATION_OPTIONS_LOCALIZED["en"]}
}
ROLE_VALUE_TO_TEXT = {
    "ru": {v: t for t, v in ROLE_OPTIONS_LOCALIZED["ru"]},
    "en": {v: t for t, v in ROLE_OPTIONS_LOCALIZED["en"]}
}

# The four *_VALUE_TO_TEXT_RU aliases that stood here "для обратной
# совместимости" had no callers left; the localized dicts above are used
# directly.

# Имена персонажей — нейтральные, без указания пола.
CHARACTER_NAMES_EN = [
    "Alex", "Sam", "Robin", "Jordan", "Taylor", "Casey", "Riley", "Morgan", "Jamie", "Charlie",
    "Avery", "Quinn", "Rowan", "Skyler", "Kai", "Ash", "Rio", "Remy", "Sage", "River",
]

CHARACTER_NAMES_RU = [
    "Саша", "Женя", "Валя", "Слава", "Ким", "Кай", "Рэй", "Нико", "Робин", "Сэм",
    "Алекс", "Мика", "Ари", "Эш", "Рио", "Скай", "Тони", "Лу", "Джо", "Ривер",
]
