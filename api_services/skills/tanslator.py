from .decorators import register_skill
from deep_translator import GoogleTranslator
translator = GoogleTranslator(source='auto', target='zh-CN')
import logging
logger = logging.getLogger(__name__)

@register_skill
def simple_translate(text: str, translator=translator) -> str:
    """
    Safely translates text to the target language.
    
    :param text: Text to translate.
    :param translator: Instance of GoogleTranslator.
    :return: Translated text or original text if translation fails.
    """
    if not text:
        return ""
    try:
        # Google Translate API usually has a 5000 character limit
        return translator.translate(text[:4999])
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return text