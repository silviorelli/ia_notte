"""Prompt templates for story generation and speech synthesis style."""

STORY_PROMPT_TEMPLATE = (
    "Sei un narratore di fiabe della buonanotte per bambini dai 3 ai 7 anni. "
    "Scrivi una storia originale, dolce e rassicurante con protagonista {PERSONAGGIO}. "
    "Requisiti: linguaggio semplice e concreto; tono calmo e caldo; una piccola avventura "
    "con un lieto fine; un valore positivo (gentilezza, coraggio, amicizia, condivisione); "
    "niente paura, violenza o suspense forte; lunghezza circa 400-600 parole "
    "(3-5 minuti letti ad alta voce); una chiusura tranquilla che concili il sonno, "
    "in cui il personaggio si addormenta sereno. Inizia con 'C'era una volta' "
    "e termina con un augurio di buonanotte. Scrivi solo la storia, "
    "senza titoli, note o commenti."
)

TTS_STYLE_INSTRUCTION = (
    "Leggi questa fiaba della buonanotte in italiano con voce calma, dolce e rassicurante, "
    "a ritmo lento, come un genitore che culla un bambino verso il sonno.\n\n"
)


def build_story_prompt(character: str) -> str:
    """Insert the chosen character into the base story prompt.

    Args:
        character: Name of the story protagonist.

    Returns:
        The complete prompt to send to the text model.
    """
    return STORY_PROMPT_TEMPLATE.replace("{PERSONAGGIO}", character)
