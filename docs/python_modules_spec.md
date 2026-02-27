# Спецификация Python-модулей

> Справочник по архитектуре серверных модулей конвейера Word → S1000D XML.
> Описывает анализ элементов DOCX, генерацию XML, гибридный matching и headless-сравнение.

---

## Содержание

1. [elements_analyzer.py](#1-elements_analyzerpy-parsers) — анализ элементов DOCX
2. [descriptive_processor.py](#2-descriptive_processorpy-processing_scripts) — генерация S1000D XML
3. [hybrid_matcher.py](#3-hybrid_matcherpy-parsers) — гибридный PDF↔XML↔DOCX matching
4. [headless_extractor.py + headless_comparator.py](#4-headless_extractorpy--headless_comparatorpy-comparison_app) — extraction и comparison

---

## 1. elements_analyzer.py (parsers/)

### Назначение

Основной модуль анализа структуры Word-документа (DOCX). Обходит параграфы и таблицы
документа в порядке XML body, классифицирует каждый элемент по типу (заголовок, абзац,
список, таблица, иллюстрация, предупреждение и т.д.) и формирует список словарей-элементов
с позиционной информацией, текстом, примером XML и stable_id для content-hash matching.

Также реализует механизм наложения пользовательской эталонной разметки
(`apply_reference_markup`) — 4-фазный алгоритм сопоставления эталонных элементов
с автоматически классифицированными.

### Публичные функции

| Функция | Параметры | Возвращает | Описание |
|---------|-----------|-----------|----------|
| `compute_stable_id(seq_index, element_type, text)` | `int`, `str`, `str` | `str` (12 hex chars) | Генерация content-hash идентификатора элемента из DOCX. Использует SHA-256 от `"{seq_index}\|{element_type}\|{text[:80].lower()}"`. |
| `get_parsing_rules()` | — | `dict` | Загрузка правил парсинга из `parsing_rules.json` (корень проекта). |
| `analyze_document_elements(doc, illustrations, illustration_positions, llm_config, graphic_ident_prefix)` | `Document`, `Dict[str,str]`, `Dict[str,Dict]`, `Dict[str,Any]`, `str` | `List[Dict[str,Any]]` | Главная функция анализа: обход элементов DOCX, классификация, пост-обработка, назначение stable_id. |
| `apply_reference_markup(elements, dmc_string)` | `List[Dict]`, `str` | `List[Dict]` | 4-фазное наложение эталонной разметки на авто-элементы. Модифицирует типы IN PLACE. |
| `apply_overrides(elements, dmc_string)` | `List[Dict]`, `str` | `List[Dict]` | Применение overrides из `_overrides/{dmc}.json` (legacy + новый формат). |
| `get_last_markup_result(dmc_string)` | `str` | `Optional[List[Dict]]` | Возврат кешированного результата последнего вызова `apply_reference_markup()`. |
| `generate_elements_log(document_path, elements, output_path)` | `str`, `List[Dict]`, `str` | `str` (путь к логу) | Генерация текстового лога анализа элементов. |

### Архитектура analyze_document_elements()

Главный конвейер обработки документа:

```
1. Инициализация:
   - LLM classifier (опционально, через Ollama)
   - Счётчики нумерации, позиции строк/символов
   - Итерация doc.element.body → список (type, index) пар

2. Извлечение enhanced_tables через table_parser

3. Основной цикл по doc_elements:
   Для каждого (element_type, element_idx):

   3a. TABLE → создать element dict с type='table', xml_example из enhanced_table_to_s1000d

   3b. PARAGRAPH:
       - Извлечь text, style_name, numPr (OOXML numbering)
       - numPr fallback: прямой поиск в raw XML (MockNumPr)
       - Обновить позиционные счётчики (line_number, char_position)

       Классификация (приоритет сверху вниз):
       ┌─ _is_likely_list_item() → пропустить header-детекцию
       ├─ LLM classifier (если включён, для неоднозначных случаев)
       ├─ Numbered paragraph header (numPr + Heading style + эвристики)
       ├─ Regular header (Heading style, < 100 символов, без описательных слов)
       ├─ Main section header (regex: ^\d+\.?\s+)
       ├─ List item (_get_list_type → numbered_list / unnumbered_list)
       │   └─ Nested detection: item_level > list_base_level → nested_*
       ├─ Illustration (_has_embedded_image → blip в runs)
       ├─ Warning (_is_warning → ключевые слова)
       ├─ References (_find_references → table/illustration/DM refs)
       └─ Default: paragraph

4. Пост-обработка:
   - Объединение illustration_reference + следующий "Рисунок N" paragraph → illustration
   - Удаление table references из предшествующих параграфов
   - Назначение stable_id каждому элементу (compute_stable_id)
```

### compute_stable_id() — алгоритм content-hash

```python
def compute_stable_id(seq_index: int, element_type: str, text: str) -> str:
    prefix = text[:80].strip().lower()
    raw = f"{seq_index}|{element_type}|{prefix}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
```

**Свойства:**
- Детерминистичный: одинаковый вход → одинаковый выход
- Уникальный для дубликатов: `seq_index` различает одинаковые параграфы
- Стабильный при малых правках: text[:80] покрывает большинство заголовков целиком
- Длина: 12 hex-символов (48 бит) — достаточно для уникальности в пределах документа

### apply_reference_markup() — 4-фазный matching

Наложение пользовательской эталонной разметки (reference) на автоматически
классифицированные элементы. Не перестраивает порядок элементов — только
переопределяет `type` IN PLACE.

```
Фаза 1: Single-element matching
  Для каждого ref_elem (кроме _skip):
  - mapped_type = type_map[ref_type]
  - Специальная логика: numbered_list с depth≤2 → numbered_paragraph_header
  - _find_best_match(cursor, text_start, text_end, used) → best_idx
    - Окно: cursor-5 .. cursor+50 (затем full scan fallback)
    - _combined_score: prefix_score * 0.7 + end_score * 0.3
    - Fallback: _strip_list_prefix, _collapse_spaced_letters
    - Порог: 0.2 (короткий текст) или 0.3 (обычный)
  - Если span > 1: defer span_forward на фазу 3

Фаза 2: _skip matching
  Для каждого _skip ref_elem:
  - _find_best_match(0, text_start, text_end, used)
  - Пометить элемент type='_skip'

Фаза 3: Deferred span_forward
  Для каждого deferred (start_idx, span, text_end, type, ref_idx):
  - _apply_span_forward: сканирование вперёд от start_idx+1
  - Максимум: ref_span * 1.5 элементов
  - Стоп: used элемент (кроме _skip), illustration при не-illustration типе
  - Стоп: ref_text_end найден в content[-40:]

Фаза 4: Post-match fixups
  4a. Extend: если text_end ref-элемента попадает в соседний unused элемент,
      включить его в match (PDF-блок покрывает несколько DOCX-параграфов)
  4b. Split: если text_start unmatched ref найден ВНУТРИ matched элемента,
      добавить _split_points metadata для генератора
```

**Маппинг типов (reference → analyzer):**

| Reference тип | Analyzer тип |
|--------------|-------------|
| `heading` | `header` |
| `para`, `paragraph` | `paragraph` |
| `numbered_list` | `numbered_list` |
| `unnumbered_list`, `list` | `unnumbered_list` |
| `table` | `table` |
| `figure` | `illustration` |
| `warning` | `warning` |
| `caution` | `caution` |
| `note` | `note` |

### Формат выходных данных (element dict)

```json
{
  "type": "numbered_paragraph_header",
  "start_line": 45,
  "start_char": 0,
  "end_line": 45,
  "end_char": 42,
  "start_para": 12,
  "end_para": 12,
  "content": "1. Общие сведения о системе",
  "xml_example": "<levelledPara><title>1. Общие сведения о системе</title></levelledPara>",
  "details": "Нумерованный заголовок параграфа (уровень 1)",
  "stable_id": "a1b2c3d4e5f6",
  "_ref_annotated": true,
  "_original_type": "numbered_list",
  "_ref_idx": 3,
  "_ref_type_raw": "heading",
  "_element_id": "abc123def456",
  "_split_points": [{"position": 120, "type": "paragraph", "ref_idx": 5}]
}
```

**Поля element dict:**

| Поле | Тип | Описание |
|------|-----|----------|
| `type` | `str` | Тип элемента: `header`, `numbered_paragraph_header`, `paragraph`, `numbered_list`, `unnumbered_list`, `nested_numbered_list`, `nested_unnumbered_list`, `table`, `illustration`, `illustration_reference`, `table_reference`, `data_module_reference`, `warning`, `_skip` |
| `start_line`, `end_line` | `int` | Начальная/конечная строка в документе |
| `start_char`, `end_char` | `int` | Начальная/конечная позиция символа в строке |
| `start_para`, `end_para` | `int` | Начальный/конечный индекс параграфа в `doc.paragraphs` |
| `content` | `str` | Текстовое содержание элемента |
| `xml_example` | `str` | Пример целевого S1000D XML |
| `details` | `str` | Человекочитаемое описание |
| `stable_id` | `str` | Content-hash ID (12 hex) |
| `list_level` | `int` | Уровень вложенности списка (только для list-типов) |
| `_ref_annotated` | `bool` | Был ли тип переопределён reference markup |
| `_original_type` | `str` | Исходный авто-тип до override |
| `_ref_idx` | `int` | Индекс reference-элемента |
| `_ref_type_raw` | `str` | Исходный тип из reference |
| `_element_id` | `str` | Стабильный ID из hybrid pipeline |
| `_split_points` | `list` | Точки разбиения для генератора |

### Вспомогательные функции (private)

| Функция | Описание |
|---------|----------|
| `_is_likely_list_item(text, paragraphs, para_idx, elements)` | 5 проверок: маркеры, `;` в конце, `:` в предыдущем, предыдущий — список, короткий текст |
| `_is_main_section_header(text)` | Regex `^\d+\.?\s+` — начинается с числа |
| `_get_list_type(paragraph, para_idx)` | OOXML numPr → тип списка; fallback на текстовые эвристики |
| `_get_list_level(paragraph)` | Уровень вложенности: numPr.ilvl → raw XML → left_indent |
| `_clean_list_item_text(paragraph, list_type)` | Удаление маркеров списка из текста |
| `_has_embedded_image(paragraph)` | Проверка `a:blip` в runs |
| `_is_warning(text)` | Ключевые слова: внимание, осторожно, предупреждение |
| `_find_references(text)` | Regex-поиск ссылок на таблицы, рисунки, DM |
| `_is_after_colon_intro(doc, para_idx)` | Предыдущий параграф заканчивается на `:` |
| `_detect_colon_intro_list(doc, para_idx)` | Обнаружение списка после вводного абзаца с двоеточием |

### Настраиваемые пороги и константы

| Константа | Значение | Назначение |
|-----------|---------|-----------|
| `compute_stable_id text prefix` | 80 символов | Длина текстового префикса для hash |
| `_prefix_score min prefix_len` | 3 символа | Минимальная длина совпадающего префикса |
| `_find_best_match min_threshold (short)` | 0.2 | Порог для коротких текстов (< 10 символов) |
| `_find_best_match min_threshold (normal)` | 0.3 | Стандартный порог matching |
| `_find_best_match window` | cursor-5 .. cursor+50 | Окно поиска |
| `_combined_score weights` | start: 0.7, end: 0.3 | Веса prefix/suffix в комбинированном score |
| `_apply_span_forward max scan` | ref_span * 1.5 | Максимальная дальность scan вперёд |
| `_ends_match suffix_len` | 15 символов (min 8) | Длина суффикса для suffix matching |
| `is_real_header max_len` | 100 символов | Максимальная длина "настоящего" заголовка |
| `is_likely_list_item max_len` | 300 символов | Максимальная длина элемента списка |

---

## 2. descriptive_processor.py (processing_scripts/)

### Назначение

Оркестратор конвейера генерации S1000D XML из описательных (descriptive) DOCX-документов.
Координирует парсинг документа (text, tables, lists, illustrations, elements),
маппинг секций на infoCodes, группировку секций в модули данных (DM), сборку
XML-контента и генерацию файлов.

Также генерирует sidecar-файл `_element_map.json` для связывания элементов XML
с content-hash ID из DOCX-анализа.

### Публичные функции

| Функция | Параметры | Возвращает | Описание |
|---------|-----------|-----------|----------|
| `process_descriptive_document(doc_path, output_dir, llm_config, dm_code_override, tech_name_override, info_name_override, skip_pmc, graphic_ident_prefix)` | `str`, `str`, `Dict`, `Dict`, `str`, `str`, `bool`, `str` | `Tuple[List[dict], Dict]` (dm_refs, illustrations) | Главная точка входа: полный конвейер обработки документа. |
| `normalize_title_case(text)` | `str` | `str` | Нормализация регистра заголовка: UPPER → UPPER, иначе capitalize (сохранение содержимого в скобках). |
| `extract_document_title(document)` | `Document` | `str` | Извлечение заголовка из первого абзаца или headings. |
| `extract_organization_from_document(document)` | `Document` | `str` | Извлечение названия организации из headers/footers. |
| `map_heading_to_info_code(heading, component_index)` | `str`, `int` | `Dict` | Маппинг заголовка на компоненты DMC-кода (infoCode). |
| `group_sections_for_modules(analysis_results, split_into_modules)` | `List[Dict]`, `bool` | `Dict[str, Dict]` | Группировка секций для генерации модулей. |
| `group_sections_by_type(headings)` | `List[str]` | `Dict[str, List[int]]` | Группировка индексов секций по типу: purpose, description, operation, components. |
| `assemble_content_for_section(section, document, tables, lists_data, elements, ...)` | `Dict`, `Document`, ... | `Dict` | Сборка XML-частей для одной секции из проанализированных элементов. |
| `assemble_content(sections, text_sections, tables, lists_data)` | `List[str]`, `Dict`, `Dict`, `List[Dict]` | `Dict` | Legacy: сборка контента из парсеров (paragraphs, tables, lists). |
| `dm_code_to_string(dm_code)` | `Dict` | `str` | Конвертация DMC-кода в строку `"DMC-S5-A-120-..."`. |
| `validate_content_inclusion(doc_path, generated_files, illustrations, output_dir)` | `str`, `List[str]`, `Dict`, `str` | `List[str]` | Валидация полноты включения контента в XML. |
| `get_dm_code_for_section(section, component_counter)` | `Dict`, `int` | `Dict` | Получение DMC-кода для секции. |

### Pipeline: process_descriptive_document()

```
1. Конфигурация:
   - Чтение config.ini → split_into_modules (bool)
   - Загрузка Document(doc_path)

2. Извлечение метаданных:
   - extract_organization_from_document() → organization
   - extract_document_title() → document_title

3. Парсинг контента:
   - extract_illustrations(doc, output_dir) → illustrations, illustration_positions
   - copy_publication_logo(output_dir)
   - analyze_document_content(doc) → analysis_results
   - analyze_document_elements(doc, illustrations, ...) → elements
   - process_multi_sheet_illustrations(elements) → elements (updated)

4. Наложение reference markup (если dm_code_override задан):
   - dm_code_to_string(dm_code_override) → dmc_str
   - apply_reference_markup(elements, dmc_str) → elements

5. Логирование:
   - generate_elements_log(doc_path, elements, output_dir)

6. Дополнительный парсинг:
   - extract_text_by_headings(doc) → text_sections
   - get_tables_by_reference(doc) → tables
   - extract_lists(doc) → lists_data

7. Группировка и генерация модулей:
   - group_sections_for_modules(analysis_results, split_into_modules) → section_groups
   - Для каждой группы:
     a. assemble_content_for_section() → combined_content
     b. Определение DMC-кода (override или content-based)
     c. create_data_module_config() → dm_config
     d. generator.generate_data_module(dm_config, output_dir) → filepath
     e. _save_element_map_sidecar(filepath, elements) → sidecar JSON
     f. ensure_missing_placeholders(figure_info, output_dir)

8. PMC (Publication Module):
   - create_pm_config() → pm_config
   - pm_generator.generate_publication_module() → pm_filepath

9. Валидация:
   - validate_content_inclusion() → validation_errors
```

### Секционирование: group_sections_for_modules()

Две стратегии:

**split_into_modules = False (по умолчанию):**
```
Все секции → одна группа 'combined'
info_name = объединение всех уникальных info_name через запятую
```

**split_into_modules = True:**
```
Каждая секция → отдельная группа по типу:
- 'component_{start_para}' — каждый компонент отдельно
- 'function_description' — описание функций
- '{section_type}_{info_name}' — purpose, description, operation
- 'misc_{start_para}' — fallback
```

### Сборка контента: assemble_content_for_section()

Ключевая функция, преобразующая список element dicts в XML-строки для S1000D.

```
Входы:
  - section: {start_para, end_para, info_name}
  - elements: полный список element dicts
  - document, tables, lists_data: данные парсеров

Алгоритм:
  1. Фильтрация элементов по диапазону параграфов (start_para..end_para)
  2. Пре-обработка: удаление table refs из paragraph, обработка figure refs
  3. Pre-merge: объединение consecutive элементов с одинаковым _ref_idx
  4. Основной цикл по элементам:

     ┌─ _skip → пропуск
     ├─ paragraph (первый) → проверка techName+infoName, возможный skip
     ├─ header → flush list, close levelledPara, start new levelledPara с <title>
     ├─ numbered_paragraph_header → аналогично header, strip numbering
     ├─ numbered_list / unnumbered_list → накопление в current_list_items
     │   ├─ section-numbered item → levelledPara с title (вместо randomList)
     │   └─ nested → продолжение в текущий список с level=1
     ├─ paragraph → <para> в текущий levelledPara (с _split_points → multiple <para>)
     ├─ table → xml_example если начинается с <table, иначе pending_table_title
     ├─ illustration → <figure> с <graphic> и infoEntityIdent
     ├─ warning/caution → <warning>/<caution> с <warningAndCautionPara>
     ├─ note → <note> с <notePara>
     └─ default → <para>

  5. flush_current_list(): нормализация уровней → _build_nested_list_xml()
  6. Закрытие оставшегося levelledPara
```

**Формат вложенных списков:**

```
current_list_items = [(text, 0), (text, 1), (text, 1), (text, 0)]
                        ↓
Нормализация: raw EMU/ilvl → relative 0,1,2...
                        ↓
<para>
  <randomList listItemPrefix="pf02">
    <listItem><para>text
      <randomList listItemPrefix="pf02">
        <listItem><para>nested1</para></listItem>
        <listItem><para>nested2</para></listItem>
      </randomList>
    </para></listItem>
    <listItem><para>text2</para></listItem>
  </randomList>
</para>
```

### Sidecar _element_map.json

Генерируется функцией `_save_element_map_sidecar()` после создания XML-файла.

**Алгоритм:**
1. Парсинг готового XML через `extract_xml_elements()` → получение элементов
   в порядке обхода дерева (тот же порядок, что использует s1000d_renderer)
2. Построение lookup из DOCX-элементов: `{stable_id, type, text}`
3. Для каждого XML-элемента: подбор лучшего DOCX-кандидата по `SequenceMatcher.ratio()`
   с бонусом +0.1 за совпадение типа; порог: 0.3
4. Сохранение в `{output_dir}/user_finetune/{dmc}_element_map.json`

**Формат:**

```json
{
  "element_map": [
    {
      "seq": 1,
      "stable_id": "a1b2c3d4e5f6",
      "type": "heading",
      "text_start": "Общие сведения о системе"
    },
    {
      "seq": 2,
      "stable_id": "b2c3d4e5f6g7",
      "type": "para",
      "text_start": "Система предназначена для..."
    }
  ]
}
```

### Маппинг типов элементов → XML-узлы

| Тип элемента | XML-узел |
|-------------|---------|
| `header` | `<levelledPara><title>...</title></levelledPara>` |
| `numbered_paragraph_header` | `<levelledPara><title>{stripped_number}</title></levelledPara>` |
| `paragraph` | `<para>...</para>` (внутри levelledPara) |
| `numbered_list` | `<para><randomList listItemPrefix="pf01">...</randomList></para>` |
| `unnumbered_list` | `<para><randomList listItemPrefix="pf02">...</randomList></para>` |
| `nested_*_list` | Вложенный `<randomList>` внутри `<listItem><para>` |
| `table` | `<table><tgroup>...</tgroup></table>` |
| `illustration` | `<figure><title>...</title><graphic .../></figure>` |
| `warning` | `<warning><warningAndCautionPara>...</warningAndCautionPara></warning>` |
| `caution` | `<caution><warningAndCautionPara>...</warningAndCautionPara></caution>` |
| `note` | `<note><notePara>...</notePara></note>` |
| `_skip` | (пропускается, не генерируется) |

### Маппинг heading → infoCode

| Ключевые слова в heading | infoCode | Описание |
|--------------------------|----------|----------|
| `общие сведения` | `011A` | Purpose |
| `состав`, `описание` | `012A` | Description |
| `структурно представляет` | `013A` | Operation structure |
| `информацион` | `014A` | Info exchange |
| `режимы работы` | `013A` | General operation |
| `автомати*` | `015A` | Automatic mode |
| `автоном*` | `015B` | Autonomous mode |
| `аварийн*` | `015C` | Emergency mode |
| `учебно*` | `015D` | Training mode |
| `управлени* + створками/платформ*` | `016A` | Additional operations |
| component keywords | `017A` | Component description |
| default | `012A` | Description fallback |

---

## 3. hybrid_matcher.py (parsers/)

### Назначение

Гибридный matching элементов между PDF-визуальными границами (bounding boxes),
S1000D XML-структурой и DOCX-семантическими типами. Используется для создания
XML-derived эталонной разметки (reference), где XML-элементы являются якорями,
а PDF-блоки предоставляют визуальные позиции.

Также реализует обратное направление: привязка PDF-блоков к DOCX-элементам
для гибридного режима (hybrid reference).

### Публичные функции

| Функция | Параметры | Возвращает | Описание |
|---------|-----------|-----------|----------|
| `compute_element_id(page_num, y0, text)` | `int`, `float`, `str` | `str` (12 hex) | Стабильный ID из PDF-позиции. y0 квантуется к кратным 10. |
| `match_xml_to_pdf(xml_elements, pdf_blocks, stable_ids)` | `list`, `list`, `list` | `list` | XML-first matching: XML → PDF. 2-pass стратегия. |
| `match_pdf_to_docx(pdf_pages, docx_elements)` | `list`, `list` | `List[UnifiedElement]` | PDF → DOCX sequential matching с interpolation. |
| `prefix_score(ref_text, content_text)` | `str`, `str` | `float` | Prefix-based similarity score. |
| `combined_score(ref_text_start, ref_text_end, content)` | `str`, `str`, `str` | `float` | Комбинированный score: start*0.7 + end*0.3. |

### UnifiedElement dataclass

```python
@dataclass
class UnifiedElement:
    element_id: str          # 12-hex стабильный ID
    idx: int                 # Порядковый номер (1-based)
    type: str                # Тип элемента
    type_source: str         # Источник типа: 'ooxml', 'heuristic', 'pdf_heuristic',
                             #   'pdf_table_detect', 'user_override'
    bbox: Dict[str, float]   # {page, x0, y0, x1, y1}
    bbox_pages: List[Dict]   # Optional: [{page, x0, y0, x1, y1}, ...] для multi-page элементов
    text: str                # Полный текст
    text_start: str = ""     # Первые 60 символов
    text_end: str = ""       # Последние 40 символов
    span: int = 1            # Количество PDF-блоков
    docx_para_idx: int = -1  # Индекс параграфа DOCX (-1 = не сопоставлен)
    match_confidence: float = 0.0  # Confidence сопоставления
    font_info: Optional[Dict] = None  # {max_size, is_bold, is_italic}
```

**Методы:**
- `to_dict()` → словарь для JSON-сериализации (с docx_match и font_info если присутствуют)
- `to_legacy_element_dict()` → формат, совместимый с `assemble_content_for_section()`

### match_xml_to_pdf() — 2-pass алгоритм

XML-first matching: XML-элементы — якоря, PDF-блоки — позиции.

```
Подготовка:
  1. Фильтрация page headers/footers (_is_page_footer)
  2. Вычисление median_gap между PDF-блоками (для forward expansion)

Pass 1: window-based (сохранение порядка документа)
  Для каждого XML-элемента (по порядку):
  1. Нормализация: _normalize_for_match(text_start)
  2. Определение min_threshold:
     - table/figure: 0.18 (PDF текст структурно отличается)
     - короткий текст (< 10 символов): 0.15
     - стандартный: 0.3
  3. Поиск в окне [cursor-3 .. cursor+80]:
     - score = max(combined_score(normalized), combined_score(raw))
     - score *= _type_context_factor (penalty для warning/caution без ключевых слов)
  4. Forward expansion (claim adjacent blocks):
     - Максимум 30 дополнительных блоков
     - Стоп-условия:
       a. Следующая страница > anchor+1
       b. gap > median_gap * 3 (на той же странице)
       c. Другой XML-элемент лучше соответствует блоку (score > 0.4)
       d. X-offset > 40px (кроме close vertical на той же странице)
       e. text_end найден (prefix_score > 0.4)
  5. Результат: element dict с bbox, span, stable_id
  6. Unmatched → sentinel {type: '_unmatched_xml'}

Pass 2: global scan для оставшихся unmatched
  Для каждого _unmatched_xml из pass 1:
  - Поиск по ВСЕМ unclaimed блокам (без window ограничения)
  - Та же логика forward expansion
  - Замена sentinel в pass1_result

Финализация:
  - _unmatched_xml → placeholder с interpolated bbox
  - Unclaimed PDF-блоки → type '_extra_pdf'
  - Перенумерация idx (1-based)
```

**Формат результата (element dict для reference):**

```json
{
  "idx": 1,
  "type": "heading",
  "type_source": "xml_derived",
  "text_start": "Общие сведения",
  "text_end": "о системе",
  "span": 2,
  "element_id": "abc123def456",
  "stable_id": "a1b2c3d4e5f6",
  "bbox": {
    "page": 1,
    "x0": 72.0,
    "y0": 125.5,
    "x1": 540.0,
    "y1": 145.2
  }
}
```

### match_pdf_to_docx() — sequential matching

PDF → DOCX сопоставление для hybrid reference (без XML).

```
1. Flatten: pdf_pages → flat_blocks (с page_num, page_width, page_height)
2. Median font: для fallback-классификации по шрифту
3. Основной цикл по flat_blocks:
   a. is_table блок → поиск ближайшего DOCX table-элемента (cursor-2..cursor+10)
   b. Обычный блок → _find_best_docx_match(pdf_text, docx_elements, cursor, used)
      - Окно: cursor-5 .. cursor+50
      - combined_score ≥ min_threshold (0.2 / 0.3)
      - Fallback: full scan
   c. Нет match → _classify_by_font (header, unnumbered_list, paragraph)
4. Insert unmatched DOCX elements (tables, illustrations, warnings, cautions):
   - Позиция: после последнего matched элемента с docx_idx < current
   - bbox: interpolation между соседями
5. Перенумерация idx
```

### Text normalization (_normalize_for_match)

Нормализация текста для robust matching между PDF и DOCX:

```
1. strip()
2. Удаление bullet/dash маркеров: –, —, •, и т.д.
3. Удаление numbered-list prefix: 1., 1)
4. Удаление section-heading prefix: 1 , 1.2
5. lower()
6. Collapse spaced-out letters: 'п р и м е ч а н и е' → 'примечание'
7. Удаление пробелов перед пунктуацией: 'примечание :' → 'примечание:'
```

### _type_context_factor — контекстный штраф

Предотвращает ложное сопоставление XML warning/caution/note с обычными
параграфами/заголовками в PDF:

| XML-тип | PDF-блок содержит ключевые слова | Множитель |
|---------|--------------------------------|-----------|
| `warning`, `caution`, `note` | Да (внимание, предупреждение и т.д.) | 1.0 |
| `warning`, `caution`, `note` | Нет | 0.1 (сильный штраф) |
| Любой другой | — | 1.0 (без эффекта) |

### Font classification fallback

Когда PDF-блок не сопоставлен с DOCX:

| Условие | Результат |
|---------|----------|
| `font_size > median * 1.3` | `header` |
| Текст начинается с dash/bullet/number | `unnumbered_list` |
| Default | `paragraph` |

### Настраиваемые пороги и константы

| Константа | Значение | Назначение |
|-----------|---------|-----------|
| `compute_element_id y0 quantize` | round(y0, -1) — кратные 10 | Стабилизация при re-render |
| `compute_element_id text prefix` | 30 символов | Длина текста для hash |
| `prefix_score min prefix_len` | 3 символа | Минимум совпадения для non-zero score |
| `combined_score weights` | start: 0.7, end: 0.3 | Веса start/end |
| `_find_best_docx_match threshold (short)` | 0.2 | Для текстов < 10 символов |
| `_find_best_docx_match threshold (normal)` | 0.3 | Стандартный порог |
| `_find_best_docx_match window` | cursor-5 .. cursor+50 | Окно поиска |
| `match_xml_to_pdf pass 1 window` | 80 | Размер окна pass 1 |
| `forward expansion max steps` | 30 | Максимум дополнительных блоков |
| `forward expansion gap limit` | median_gap * 3 (списки: * 5) | Вертикальный разрыв (увеличен для списков) |
| `forward expansion page-bottom peek` | — | При gap-break перед сменой страницы — продолжить |
| `forward expansion x-offset limit` | 40 px (cross-page: 100 px) | Горизонтальный сдвиг (relaxed cross-page) |
| `forward expansion is_table guard` | — | Не-таблица не может захватить is_table блок |
| `forward expansion vertical close` | median_gap * 1.5 | Порог "близко по вертикали" |
| `text_end stop threshold` | 0.4 | prefix_score для text_end |
| `other element stop threshold` | 0.4 | Score чужого элемента |
| `_type_context_factor penalty` | 0.1 | Штраф за отсутствие ключевых слов |
| `_classify_by_font header multiplier` | 1.3 | Порог: size > median * 1.3 |
| `_is_page_footer max_len` | 200 символов | Максимальная длина footer |

---

## 4. headless_extractor.py + headless_comparator.py (comparison_app/)

### Назначение и структура split

Два модуля реализуют headless (без UI) извлечение элементов и их сравнение.

**headless_extractor.py** — определения структур данных (`ElementInfo`, `ComparisonReport`)
и вся логика извлечения элементов из DOCX (через mammoth HTML) и S1000D XML (через lxml).

**headless_comparator.py** — логика сравнения (`compare_elements`) и re-export
всех символов из extractor для обратной совместимости.

Разделение сделано для того, чтобы extraction можно было использовать независимо
(например, в `reference_store.py`), без подтягивания comparison-зависимостей.

### Data structures: ElementInfo

```python
@dataclass
class ElementInfo:
    idx: int            # Порядковый номер (1-based)
    type: str           # Тип элемента (heading, para, table, figure, ...)
    text_start: str = ''  # Первые 60 символов текста
    text_end: str = ''    # Последние 40 символов текста
    span: int = 1         # Количество DOM-блоков (для reference)
    stable_id: str = ''   # Content-hash: sha256:abc... (для matching)
```

**Методы:**
- `to_dict()` → `dict` (через `dataclasses.asdict`)
- `ElementInfo.from_dict(d)` → `ElementInfo` (фильтрация неизвестных ключей)

### Data structures: ComparisonReport

```python
@dataclass
class ComparisonReport:
    left_count: int = 0
    right_count: int = 0
    matched_pairs: List[Tuple[int, int]]           # [(left_idx, right_idx), ...]
    left_unmatched: List[int]                       # [idx, ...]
    right_unmatched: List[int]                      # [idx, ...]
    type_mismatches: List[Tuple[int,int,str,str]]   # [(l_idx, r_idx, l_type, r_type)]
    text_similarities: List[Tuple[int,int,float]]   # [(l_idx, r_idx, ratio)]
    score: float = 0.0

    @property
    def is_converged(self) -> bool:
        return self.score >= 0.95
```

### Extraction: extract_docx_elements()

```
extract_docx_elements(docx_path: str) → List[ElementInfo]

1. render_docx_to_html(docx_path) → HTML с data-anno-idx аннотациями
   (через mammoth + custom transforms в docx_renderer.py)
2. _parse_annotated_html(html) → List[ElementInfo]
   - _AnnotatedHTMLParser (html.parser):
     - handle_starttag: ищет data-anno-idx → начало элемента
     - handle_data: накопление текста
     - handle_endtag: при depth=0 → _finish_element()
     - _finish_element: создание ElementInfo с text_start[:60], text_end[-40:]
3. Сортировка по idx
```

### Extraction: extract_xml_elements()

```
extract_xml_elements(xml_path: str) → List[ElementInfo]

1. Парсинг XML через lxml (resolve_entities=False, no DTD)
2. Поиск <content> → <description> или <procedure>
3. Рекурсивный обход:
```

### XML walker hierarchy

```
extract_xml_elements()
├── _walk_description(desc, elements, counter, level=2)
│   └── _walk_levelled_para(lp, elements, counter, level)
│       ├── <title> → heading
│       ├── <para> (первый без title, level ≤ 4) → heading
│       ├── <para> → _walk_para()
│       │   ├── Без вложенных списков → para
│       │   └── С randomList/sequentialList:
│       │       ├── Текст перед списком → para
│       │       ├── <randomList> → unnumbered_list
│       │       └── <sequentialList> → numbered_list
│       ├── <table> → table
│       ├── <figure> → figure (title из вложенного <title>)
│       ├── <warning> → warning
│       ├── <caution> → caution
│       ├── <note> → note
│       └── <levelledPara> → рекурсия (level+1)
│
└── _walk_procedure(proc, elements, counter)
    ├── <preliminaryRqmts> → heading + _walk_preliminary_rqmts()
    │   ├── reqSupportEquips/reqSupplies/reqSpares → heading + table
    │   └── reqSafety → warning/caution
    ├── <mainProcedure> → heading + _walk_main_procedure()
    │   └── <proceduralStep> → _walk_procedural_step()
    │       ├── <para> → _walk_para()
    │       ├── <table> → table
    │       ├── <figure> → figure
    │       ├── <warning/caution/note> → соответствующий тип
    │       └── <proceduralStep> → рекурсия
    └── <closeRqmts> → heading
```

### Вспомогательные функции (extractor)

| Функция | Описание |
|---------|----------|
| `_local_tag(elem)` | Локальное имя тега lxml-элемента (без namespace) |
| `_text_content(elem)` | Весь текст элемента и его потомков (itertext) |
| `_text_snippet(elem)` | `(text[:60], text[-40:])` — start/end фрагменты |

### compare_elements() — 4-phase matching

```python
compare_elements(left: List[ElementInfo], right: List[ElementInfo]) → ComparisonReport
```

Сравнение двух списков элементов (обычно: reference vs XML).

```
Фаза 1: Direct stable_id matching
  - Построить right_by_sid: {stable_id → [ri, ...]}
  - Для каждого left с stable_id: найти первый неиспользованный right
  - Результат: точные пары по content-hash

Фаза 2: Content-based matching (text similarity)
  - Для каждой пары (unmatched_left, unmatched_right):
    - Нормализация: _norm_text(text_start), _norm_text(text_start + ' ' + text_end)
    - sim = max(SequenceMatcher(l_start, r_start), SequenceMatcher(l_full, r_full))
    - Порог: sim ≥ 0.35
  - Global best-first: сортировка кандидатов по sim descending
  - Greedy assignment: лучшие пары первыми

Фаза 3: LCS fallback (по нормализованным типам)
  - Для оставшихся unmatched: нормализовать типы (_norm_type)
  - _compute_lcs(ul_types, ur_types) → (left_matched, right_matched)
  - Backtrack LCS → назначение пар

Фаза 4: Implicit (substring) matching
  - Для оставшихся unmatched left:
    - Проверка содержимости text_start внутри right element text
    - text_end similarity (SequenceMatcher ≥ 0.4)
    - Word overlap (≥ 50% слов совпадают, минимум 3 слова)
  - Many-to-one допускается (один right может быть matched несколько раз)
```

### Score formula

```
score = 0.4 * match_ratio + 0.3 * type_ratio + 0.3 * avg_text_sim

Где:
  match_ratio = len(matched_pairs) / max(left_count, right_count)
  type_ratio  = count(types_compatible pairs) / len(matched_pairs)
  avg_text_sim = mean(text_similarity for each pair)

is_converged = score ≥ 0.95
```

**Компоненты:**
- `match_ratio` (40%): доля сопоставленных элементов — штрафует за пропущенные/лишние
- `type_ratio` (30%): доля пар с совместимыми типами — штрафует за mis-classification
- `avg_text_sim` (30%): средняя текстовая похожесть — штрафует за потерю контента

### Text normalization pipeline (_norm_text)

```
1. strip() + lower()
2. Collapse whitespace: \s+ → ' '
3. _collapse_spaced_letters:
   - Замена известных: 'п р и м е ч а н и е' → 'примечание'
   - 'в н и м а н и е' → 'внимание'
   - 'примечание :' → 'примечание:'
4. Dehyphenate: 'про- мыть' → 'промыть' (regex: [а-яa-z]-\s+[а-яa-z])
5. Strip numbered prefix: '1.2 Текст' → 'Текст'
6. Strip figure prefix: 'рисунок 1 – Название' → 'Название'
7. Strip dash prefix: '– текст' → 'текст'
```

### Type normalization (_norm_type)

```python
'paragraph', 'para'     → 'para'
'illustration', 'figure', 'illustration_reference' → 'figure'
'numbered_list', 'unnumbered_list',
'nested_numbered_list', 'nested_unnumbered_list' → 'list'
'heading', 'header'      → 'heading'
всё остальное           → без изменений
```

### Type compatibility (_types_compatible)

Помимо нормализации, дополнительное правило:
- `list` ↔ `heading` — совместимы (секционные нумерованные списки генерируют `<levelledPara><title>`)

### _compute_lcs — LCS алгоритм

Классический DP O(m*n):
```
1. Построение матрицы dp[m+1][n+1]
2. Backtrack: восстановление matched индексов
3. Возврат: (left_matched: {li → ri}, right_matched: {ri → li})
```

### Text similarity strategies (в compare_elements)

Для каждой matched пары используются три стратегии, выбирается максимум:

| Стратегия | Формула | Когда полезна |
|-----------|---------|--------------|
| Combined | `SequenceMatcher(l_ts + ' ' + l_te, r_ts + ' ' + r_te)` | Длинные элементы |
| Avg parts | `mean(sim(l_ts, r_ts), sim(l_te, r_te))` | Когда точка обрезки различается |
| Best part | `max(sim_ts, sim_te)` если ≥ 0.98 | Absorbed/nested элементы, PDF артефакты |

### Настраиваемые пороги и константы

| Константа | Значение | Назначение |
|-----------|---------|-----------|
| `ElementInfo text_start length` | 60 символов | Максимум для text_start |
| `ElementInfo text_end length` | 40 символов | Максимум для text_end |
| `ComparisonReport convergence` | 0.95 | Порог is_converged |
| `Phase 2 sim threshold` | 0.35 | Минимальный SequenceMatcher ratio |
| `Phase 4 text_end sim` | 0.4 | Минимальный SequenceMatcher для substring |
| `Phase 4 word overlap` | 0.5 (50%) | Минимальная доля совпадающих слов |
| `Phase 4 min words` | 3 | Минимум слов для word overlap |
| `Phase 4 min text_start len` | 8 символов | Минимум для containment check |
| `Score weights` | 0.4 / 0.3 / 0.3 | match_ratio / type_ratio / text_sim |
| `Best part threshold` | 0.98 | Минимум для "perfect part" стратегии |

### Re-exports (headless_comparator.py)

Для обратной совместимости `headless_comparator.py` реэкспортирует:
```python
from comparison_app.headless_extractor import (
    ElementInfo,
    ComparisonReport,
    extract_docx_elements,
    extract_xml_elements,
)
```

Все существующие `from comparison_app.headless_comparator import X` продолжают работать.

---

## 5. Взаимосвязи между модулями

### Граф вызовов

```
process_descriptive_document()                    [descriptive_processor.py]
├── analyze_document_elements()                   [elements_analyzer.py]
│   └── compute_stable_id()                       [elements_analyzer.py]
├── apply_reference_markup(elements, dmc_str)     [elements_analyzer.py]
│   └── get_reference(dmc_string)                 [reference_store.py]
├── assemble_content_for_section()                [descriptive_processor.py]
│   └── Использует element dicts (с _ref_annotated, _split_points)
├── S1000DGenerator.generate_data_module()        [s1000d_generator.py]
└── _save_element_map_sidecar()                   [descriptive_processor.py]
    └── extract_xml_elements()                    [headless_extractor.py]

reference_store.init_reference_from_auto()        [reference_store.py]
├── extract_xml_elements()                        [headless_extractor.py]
├── match_xml_to_pdf()                            [hybrid_matcher.py]
│   └── compute_element_id()                      [hybrid_matcher.py]
├── match_pdf_to_docx()                           [hybrid_matcher.py]
│   └── _find_best_docx_match()                   [hybrid_matcher.py]
└── extract_docx_elements()                       [headless_extractor.py]

app.py /api/verify                                [app.py]
└── compare_elements(left, right)                 [headless_comparator.py]
    ├── _norm_text()                              [headless_comparator.py]
    ├── _compute_lcs()                            [headless_comparator.py]
    └── _types_compatible()                       [headless_comparator.py]

verify_loop.py                                    [verify_loop.py]
├── process_descriptive_document()                [descriptive_processor.py]
├── compare_elements()                            [headless_comparator.py]
└── get_last_markup_result()                      [elements_analyzer.py]
```

### Поток данных

```
DOCX файл
    │
    ▼
analyze_document_elements()──────► List[element dict]
    │                                    │
    │                                    ▼
    │                        apply_reference_markup()
    │                                    │
    │                                    ▼
    │                        List[element dict] (с _ref_annotated)
    │                                    │
    ▼                                    ▼
extract_illustrations()──► assemble_content_for_section()
                                         │
                                         ▼
                              XML parts (строки)
                                         │
                                         ▼
                          S1000DGenerator.generate_data_module()
                                         │
                                         ▼
                              S1000D XML файл
                              ┌────┴────┐
                              ▼          ▼
               _save_element_map    extract_xml_elements()
               _sidecar()               │
                    │                    ▼
                    ▼            List[ElementInfo]
             _element_map.json          │
                                        ▼
                              compare_elements(left, right)
                                        │
                                        ▼
                              ComparisonReport

PDF файл (через Word COM)
    │
    ▼
extract_pdf_blocks_full()──► List[page dict]
    │                              │
    ▼                              ▼
match_xml_to_pdf()          match_pdf_to_docx()
    │                              │
    ▼                              ▼
Reference elements          List[UnifiedElement]
(для auto_xml_derived)      (для auto_hybrid)
```

### Зависимости от внешних модулей

| Модуль | Зависимость | Что используется |
|--------|------------|-----------------|
| `elements_analyzer.py` | `python-docx` | Document, paragraphs, tables, styles, numbering |
| `elements_analyzer.py` | `reference_store.py` | `get_reference()` для apply_reference_markup |
| `descriptive_processor.py` | `parsers/*` | text_parser, table_parser, list_parser, illustration_parser, content_analyzer |
| `descriptive_processor.py` | `generators/*` | S1000DGenerator, PMGenerator |
| `descriptive_processor.py` | `headless_extractor.py` | `extract_xml_elements()` для sidecar |
| `hybrid_matcher.py` | — | Standalone (только stdlib + hashlib) |
| `headless_extractor.py` | `lxml` | etree для XML parsing |
| `headless_extractor.py` | `docx_renderer.py` | `render_docx_to_html()` для mammoth conversion |
| `headless_comparator.py` | `difflib` | `SequenceMatcher` для text similarity |
| `headless_comparator.py` | `headless_extractor.py` | Re-export: ElementInfo, ComparisonReport, extract_* |

---

## Приложение A: Полная карта типов элементов

Типы, используемые в разных модулях, с маппингами между ними:

| DOCX analyzer | Reference | Comparator | XML output |
|--------------|-----------|-----------|-----------|
| `header` | `heading` | `heading` | `<levelledPara><title>` |
| `numbered_paragraph_header` | `heading` | `heading` | `<levelledPara><title>` |
| `paragraph` | `para` | `para` | `<para>` |
| `numbered_list` | `numbered_list` | `list` | `<randomList pf01>` или `<levelledPara><title>` |
| `unnumbered_list` | `unnumbered_list` | `list` | `<randomList pf02>` |
| `nested_numbered_list` | `nested_numbered_list` | `list` | Вложенный `<randomList>` |
| `nested_unnumbered_list` | `nested_unnumbered_list` | `list` | Вложенный `<randomList>` |
| `table` | `table` | `table` | `<table>` |
| `illustration` | `figure` | `figure` | `<figure>` |
| `warning` | `warning` | `warning` | `<warning>` |
| `caution` | `caution` | `caution` | `<caution>` |
| `note` | `note` | `note` | `<note>` |
| — | `_skip` | — | (не генерируется) |
| — | `_extra_pdf` | — | (sentinel, фильтруется) |
| — | `_unmatched_xml` | — | (sentinel, фильтруется) |

## Приложение B: Формулы scoring

### combined_score (hybrid_matcher / elements_analyzer)

```
start_score = prefix_score(text_start, content[:60])
  fallback 1: prefix_score(strip_prefix(text_start), strip_prefix(content))
  fallback 2: prefix_score(collapse_spaced(text_start), content)
  fallback 3: prefix_score(strip_prefix(collapse_spaced(text_start)), ...)

end_score = prefix_score(text_end, content[-40:])

combined = start_score * 0.7 + end_score * 0.3
```

### prefix_score

```
a = ref_text.strip(), b = content_text.strip()
prefix_len = число совпадающих символов с начала
if prefix_len < 3: return 0.0
return prefix_len / max(len(a), 1)
```

### compare_elements score

```
match_ratio   = matched / max(left_count, right_count)
type_ratio    = compatible_types / matched_count
avg_text_sim  = mean(max(sim_combined, sim_parts, sim_best) for each pair)

score = 0.4 * match_ratio + 0.3 * type_ratio + 0.3 * avg_text_sim
```

## Приложение C: Sentinel Types

| Тип | Где создаётся | Где фильтруется | Назначение |
|-----|--------------|----------------|-----------|
| `_skip` | `apply_reference_markup()` Phase 2 | `assemble_content_for_section()`, все sync-алгоритмы | Удалённый пользователем элемент |
| `_extra_pdf` | `match_xml_to_pdf()` finalization | `apply_reference_markup()` (фильтрация ref_elements), sync-алгоритмы | PDF-блок без XML-соответствия |
| `_unmatched_xml` | `match_xml_to_pdf()` pass 1/2 | `apply_reference_markup()` (фильтрация ref_elements), sync-алгоритмы | XML-элемент без PDF-позиции |
