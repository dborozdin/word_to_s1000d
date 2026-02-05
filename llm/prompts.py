"""
Prompts for LLM-based document structure classification.
"""

from typing import Dict, Any


def get_system_prompt() -> str:
    """
    Get system prompt for document structure classification.
    """
    return """Ты - эксперт по структуре технических документов в формате S1000D.

Твоя задача - классифицировать элементы документа Word для конвертации в XML.

## Типы элементов:
1. HEADER - заголовок раздела (короткий, описывает тему, без точки в конце)
2. LIST_ITEM - элемент списка (часть перечисления, часто заканчивается на ; или .)
3. PARAGRAPH - обычный параграф (описательный текст, полные предложения)
4. TABLE_INTRO - вводный текст перед таблицей или списком (заканчивается на :)

## Признаки элемента списка (LIST_ITEM):
- Следует после текста, заканчивающегося на ":"
- Заканчивается на ";" (не последний элемент) или "." (последний)
- Имеет маркер: •, -, –, *, цифра с точкой
- Похож по структуре на соседние элементы
- Короткий текст, не полное предложение
- Паттерны типа "N шт. - описание"

## Признаки заголовка (HEADER):
- Краткий (менее 10-15 слов)
- Без точки в конце
- Называет компонент, раздел или тему
- Примеры: "Блок БИ-М-01М", "ОБЩИЕ СВЕДЕНИЯ", "Автоматический режим работы"

## Признаки параграфа (PARAGRAPH):
- Полные предложения с подлежащим и сказуемым
- Описательный характер
- Обычно заканчивается точкой
- Длинный текст (более 20-30 слов)

Отвечай ТОЛЬКО JSON объектом без дополнительного текста."""


def get_classification_prompt(text: str, context: Dict[str, Any]) -> str:
    """
    Generate classification prompt for a specific element.

    Args:
        text: Element text to classify
        context: Context dict with:
            - prev_element: Previous element type and content
            - prev_text_ending: How previous text ended (., :, ;, etc.)
            - section_name: Current section name
            - style_name: Paragraph style name

    Returns:
        Formatted prompt string
    """
    prev_element = context.get('prev_element', {})
    prev_type = prev_element.get('type', 'unknown')
    prev_content = prev_element.get('content', '')[:100]
    prev_ending = context.get('prev_text_ending', '')
    style_name = context.get('style_name', 'Normal')

    # Truncate long text for the prompt
    display_text = text[:500] + '...' if len(text) > 500 else text

    prompt = f"""## Контекст:
- Предыдущий элемент: {prev_type}
- Окончание предыдущего текста: "{prev_ending}"
- Стиль параграфа: {style_name}
- Предыдущий контент (фрагмент): "{prev_content}"

## Анализируемый текст:
"{display_text}"

## Характеристики текста:
- Длина: {len(text)} символов
- Начинается с: "{text[:30] if text else ''}"
- Заканчивается на: "{text[-20:] if len(text) > 20 else text}"

Классифицируй этот элемент. Ответь JSON:
{{"type": "HEADER|LIST_ITEM|PARAGRAPH|TABLE_INTRO", "confidence": 0.0-1.0, "reasoning": "краткое объяснение"}}"""

    return prompt


def get_batch_classification_prompt(elements: list, context: Dict[str, Any]) -> str:
    """
    Generate prompt for batch classification of multiple elements.

    Args:
        elements: List of text elements to classify
        context: Shared context

    Returns:
        Formatted prompt for batch classification
    """
    elements_text = "\n".join([
        f"{i+1}. \"{elem[:200]}...\"" if len(elem) > 200 else f"{i+1}. \"{elem}\""
        for i, elem in enumerate(elements)
    ])

    prompt = f"""## Контекст раздела:
{context.get('section_name', 'Неизвестный раздел')}

## Элементы для классификации:
{elements_text}

Классифицируй каждый элемент. Ответь JSON массивом:
[{{"index": 1, "type": "...", "confidence": 0.0-1.0}}, ...]"""

    return prompt
