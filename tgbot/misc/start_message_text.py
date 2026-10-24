def get_start_message_text(lang: str = "ru") -> str:
    if lang == "ru":
        return (
    "📄 Перед тем как мы начнём...\n\n"
    "💬 Пожалуйста, внимательно ознакомься с пользовательским соглашением.\n"
    "✨ Мы заботимся о твоей безопасности и комфортном опыте 🛡️\n\n"
    "Нажимая «Принимаю», ты соглашаешься с условиями использования ✅"
        )
    else:
        return (
            "📄 Before we start...\n\n"
            "💬 Please carefully read the user agreement.\n"
            "✨ We care about your safety and a comfortable experience 🛡️\n\n"
            "By clicking «Accept», you agree to the terms of use ✅"
        )

def get_profiles_exist_text(lang: str = "ru") -> str:
    if lang == "ru":
        return (
            "✨ С возвращением!\n"
            "Выбери профиль, с которым хочешь продолжить 😌\n"
            "Или создай новый образ — всё в твоих руках 🎀"
        )
    else:
        return (
            "✨ Welcome back!\n"
            "Pick a profile to continue 😌\n"
            "Or create a new one — it’s all up to you 🎀"
        )


def get_profiles_empty_text(lang: str = "ru") -> str:
    if lang == "ru":
        return (
            "👀 Похоже, у тебя ещё нет ни одного образа...\n"
            "Создай свой первый, и начнём приключение ✨"
        )
    else:
        return (
            "👀 Looks like you don’t have a profile yet...\n"
            "Create your first one and let’s begin the adventure ✨"
        )


# choose_lang_continue_ru/en lived here unused; the live copy of that screen is
# LANGUAGE_SELECTED_TEXT_* in misc/language_selected_text.py.


# --- Screens rendered from more than one handler ---------------------------
#
# The "ready to start" invitation was written out three times (twice in
# handlers/user.py, once in handlers/menu.py) and the language picker twice in
# user.py. The copies had already drifted: menu.py's English variant differed
# in punctuation from user.py's.

def get_ready_to_start_text(lang: str = "ru") -> str:
    if lang == "ru":
        return (
            "Создай своего AI-собеседника ✨\n"
            "Выбери имя, внешность и характер —\n"
            "и общайся на любые темы: увлечения, книги, путешествия, планы на день.\n"
            "Персонаж может присылать картинки по твоей просьбе 📸\n"
            "Начнём? 🙂"
        )
    return (
        "Create your own AI conversation partner ✨\n"
        "Pick a name, a look and a personality —\n"
        "and chat about anything: hobbies, books, travel, plans for the day.\n"
        "The character can send pictures when you ask 📸\n"
        "Shall we start? 🙂"
    )


def get_start_button_text(lang: str = "ru") -> str:
    return "Начать 🚀" if lang == "ru" else "Start 🚀"


# Bilingual on purpose: at this point the user has not picked a language yet.
CHOOSE_LANGUAGE_TEXT = (
    "✨ Привет!\nВыбери язык 🌍\n\n"
    "✨ Hi!\nPick your language 🌍"
)


