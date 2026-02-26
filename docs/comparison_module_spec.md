# Спецификация модуля сравнения (comparison_app)

> Первичный справочник по архитектуре клиента и сервера.
> Описывает состояние **после рефакторинга** монолитного `comparison.js` (2836 строк) в ES6-модули.

---

## 1. Обзор модуля сравнения

Flask-приложение для визуального сравнения исходного документа DOCX с сгенерированным
S1000D XML-модулем. Интерфейс разделён на две панели:

- **Левая панель** -- PDF-рендер (через MS Word COM) или HTML-рендер (через mammoth) исходного DOCX.
- **Правая панель** -- HTML-рендер S1000D XML с аннотациями (`data-anno-idx`, `data-anno-type`, `data-element-id`).

Аннотации связывают элементы между панелями: каждый элемент получает числовой индекс (`idx`),
тип (`type`) и цветовую метку. Пользователь может редактировать эталонную разметку (reference),
запускать верификацию и цикл автоматического форматирования.

**Точка входа:** `GET /compare/<dmc_string>` -- загружает шаблон `comparison.html` с обеими панелями.

---

## 2. Архитектура клиента (после рефакторинга)

### Структура файлов

```
comparison_app/static/js/
├── comparison.js          <- entry point: импорты + init + window exports
└── modules/
    ├── config.js          <- ANNO_TYPE_LABELS, ANNO_COLORS, NESTED_LIST_TYPES
    ├── state.js           <- shared state (referenceData, refEditMode, currentIdx, DOM refs)
    ├── logger.js          <- структурированное логирование (debug/info/warn/error, area-based)
    ├── utils.js           <- normType, normTypeForOrder, _normForMatch, _getCleanText, _filterTopLevel
    ├── layout.js          <- scroll sync (syncScroll), divider resize
    ├── badges.js          <- injectBadges, rebuildBadges, getAnnoColor, recalcMaxIdx, getMaxIdx, updatePosition
    ├── pdf-sync.js        <- _syncPdfMarkers, _syncPdfMarkersBbox, _syncPdfMarkersSequential,
    │                         _renderMarkerBrackets, _markUnassigned, _getMarkerOverlay,
    │                         _getMarkerPage, _markerTopToAbsolute
    ├── html-sync.js       <- _syncHtmlElements, _syncHtmlElementsText,
    │                         _syncHtmlElementsSequential, _clearAnnoEl
    ├── xml-sync.js        <- _syncS1000dElements (3-фазный: stable_id -> text similarity -> type-group)
    ├── pdf-overlay.js     <- analyzePdfTextContent, _buildServerBlocks, createPdfOverlayFn
    ├── navigation.js      <- navigateTo, scrollToAnno, highlightAnno, getCurrentIdx,
    │                         toggleAnnotations, makeNavHandler, keyboard handlers
    ├── mismatch.js        <- detectMismatch, collectAnnoTypes, highlightMismatches, computeLCS,
    │                         isNormalizedSame, explainTypeMismatch, buildIssuesList, issue navigation
    ├── verification.js    <- saveReference, runVerification, runVerifyLoop,
    │                         refreshS1000dPanel, renderXsdIssues, hideXsdIssues
    └── edit-mode.js       <- showContextMenu, hideContextMenu, enterEditMode, exitEditMode,
                              loadReference, merge/split/delete/create handlers,
                              _determineInsertPosition, renumberRefElements
```

### Роль каждого модуля

| Модуль | Назначение |
|--------|-----------|
| `config.js` | Константы: метки типов (`ANNO_TYPE_LABELS`), палитра цветов (`ANNO_COLORS`), карта вложенных списков (`NESTED_LIST_TYPES`). Не содержит логики. |
| `state.js` | Единый объект shared state. Все модули читают/пишут через него. Инициализация DOM-ссылок в `initState()`. |
| `logger.js` | Обёртка над `console` с уровнями и областями (area). Позволяет фильтровать вывод: `logger.debug('pdf-sync', ...)`. |
| `utils.js` | Чистые функции нормализации и DOM-утилиты. Не зависит от state. |
| `layout.js` | Scroll sync (пропорциональный, двунаправленный) и drag-resize разделителя панелей. |
| `badges.js` | Создание/обновление визуальных бейджей (`anno-badge-start`, `anno-badge-end`) на аннотированных элементах. `rebuildBadges()` -- ключевая функция: очищает, пересинхронизирует, пересоздаёт. |
| `pdf-sync.js` | Привязка PDF-маркеров (`.anno-marker`) к элементам referenceData. Два алгоритма: bbox-based (для XML-derived) и sequential (для старых). |
| `html-sync.js` | Привязка HTML-блоков (div/p с `data-anno-idx`) к referenceData. Два алгоритма: text prefix (для XML-derived) и sequential span-based. |
| `xml-sync.js` | Привязка элементов правой (S1000D) панели к referenceData. 3-фазный алгоритм с fallback. |
| `pdf-overlay.js` | Создание overlay-слоя на PDF-страницах с маркерами. Использует серверные блоки (PyMuPDF) или JS-эвристику (pdf.js textContent). |
| `navigation.js` | Навигация по элементам: scroll, highlight, клавиатурные сочетания (j/k, стрелки). Поддерживает два режима: `all` и `issues`. |
| `mismatch.js` | Обнаружение расхождений между панелями. 3-уровневая подсветка: exact match / type mismatch (orange) / unmatched (red). Построение `issuesList` из `ComparisonReport`. |
| `verification.js` | Взаимодействие с API верификации: сохранение эталона, запуск проверки, запуск цикла форматирования, обновление правой панели, отображение XSD-ошибок. |
| `edit-mode.js` | Контекстное меню редактирования: смена типа, merge prev/next, split, delete, create. Вход/выход из режима редактирования. |

---

## 3. Shared State (state.js)

Все переменные состояния хранятся в одном модуле и экспортируются для чтения/записи из любого модуля.

### DOM-ссылки

Инициализируются в `initState()` через `document.getElementById(...)`.

| Переменная | Тип | Элемент | Назначение |
|-----------|-----|---------|-----------|
| `docxPanel` | `HTMLElement` | `#content-docx` | Контейнер левой панели (DOCX/PDF) |
| `s1000dPanel` | `HTMLElement` | `#content-s1000d` | Контейнер правой панели (S1000D XML) |
| `syncCheckbox` | `HTMLInputElement` | `#sync-scroll` | Чекбокс синхронизации прокрутки |
| `frameCheckbox` | `HTMLInputElement` | `#anno-frame` | Чекбокс отображения рамок аннотаций |
| `divider` | `HTMLElement` | `#divider` | Разделитель панелей (draggable) |
| `leftPanel` | `HTMLElement` | `#panel-docx` | Обёртка левой панели (flex-контейнер) |
| `rightPanel` | `HTMLElement` | `#panel-s1000d` | Обёртка правой панели (flex-контейнер) |
| `toggleBtn` | `HTMLElement` | `#toggle-anno` | Кнопка вкл/выкл аннотаций |
| `prevBtn` | `HTMLElement` | `#anno-prev` | Кнопка "предыдущий элемент" |
| `nextBtn` | `HTMLElement` | `#anno-next` | Кнопка "следующий элемент" |
| `positionSpan` | `HTMLElement` | `#anno-position` | Счётчик позиции "K / N" |
| `mismatchBadge` | `HTMLElement` | `#mismatch-badge` | Бейдж количества расхождений |
| `navModeSelect` | `HTMLSelectElement` | `#nav-mode` | Переключатель режима навигации (all/issues) |
| `issueTooltip` | `HTMLElement` | `#issue-tooltip` | Тултип с описанием текущего issue |
| `contextMenu` | `HTMLElement` | `#anno-context-menu` | Контекстное меню редактирования |
| `ctxLabel` | `HTMLElement` | `#ctx-label` | Заголовок контекстного меню |
| `ctxTypeSelect` | `HTMLSelectElement` | `#ctx-type-select` | Выпадающий список типов |
| `ctxPreview` | `HTMLElement` | `#ctx-preview` | Превью текста элемента |
| `ctxMergePrev` | `HTMLElement` | `#ctx-merge-prev` | Кнопка "Объединить с предыдущим" |
| `ctxMergeNext` | `HTMLElement` | `#ctx-merge-next` | Кнопка "Объединить со следующим" |
| `ctxDelete` | `HTMLElement` | `#ctx-delete` | Кнопка "Удалить" |
| `ctxSplit` | `HTMLElement` | `#ctx-split` | Кнопка "Разделить" |
| `ctxCreate` | `HTMLElement` | `#ctx-create` | Кнопка "Создать" |
| `ctxSave` | `HTMLElement` | `#ctx-save` | Кнопка "Сохранить" в контекстном меню |

### Переменные навигации

| Переменная | Тип | Начальное значение | Назначение |
|-----------|-----|--------------------|-----------|
| `currentIdx` | `number` | `0` | Текущий выбранный индекс аннотации |
| `maxLeftIdx` | `number` | `0` | Максимальный idx в левой панели |
| `maxRightIdx` | `number` | `0` | Максимальный idx в правой панели |
| `maxIdx` | `number` | `0` | `Math.max(maxLeftIdx, maxRightIdx)` |
| `annotationsVisible` | `boolean` | `false` | Видимы ли аннотации |

### Переменные навигации по issues

| Переменная | Тип | Начальное значение | Назначение |
|-----------|-----|--------------------|-----------|
| `navMode` | `'all' \| 'issues'` | `'all'` | Режим навигации: все элементы или только расхождения |
| `issuesList` | `Array<Issue>` | `[]` | Список расхождений `[{idx, side, category, explanation}]` |
| `currentIssuePos` | `number` | `-1` | Индекс текущего issue в `issuesList` |
| `lastReport` | `ComparisonReport \| null` | `null` | Последний отчёт сравнения от `/api/verify` |

### Переменные scroll sync

| Переменная | Тип | Начальное значение | Назначение |
|-----------|-----|--------------------|-----------|
| `isSyncing` | `boolean` | `false` | Флаг предотвращения рекурсивной синхронизации |
| `manualNavActive` | `boolean` | `false` | Подавляет пропорциональный sync во время навигации по элементам (300ms) |

### Переменные divider resize

| Переменная | Тип | Начальное значение | Назначение |
|-----------|-----|--------------------|-----------|
| `isDragging` | `boolean` | `false` | Активен ли drag разделителя |
| `startX` | `number` | `0` | Начальная X-координата drag |
| `startLeftWidth` | `number` | `0` | Ширина левой панели в начале drag |

### Переменные режима редактирования

| Переменная | Тип | Начальное значение | Назначение |
|-----------|-----|--------------------|-----------|
| `refEditMode` | `boolean` | `false` | Активен ли режим редактирования эталона |
| `referenceData` | `ReferenceJSON \| null` | `null` | Загруженные данные эталона `{dmc_string, source, elements}` |
| `ctxTargetIdx` | `number` | `-1` | idx элемента в контекстном меню; `-999` = режим Create |
| `_createDomPosition` | `number` | `-1` | Позиция в DOM для операции Create |
| `_createBlock` | `HTMLElement \| null` | `null` | DOM-элемент для операции Create |

---

## 4. Жизненный цикл страницы

```
1. HTML загружается  ->  <script type="module" src="comparison.js">
2. comparison.js выполняется:
   a. initState()            <- кешируются DOM-ссылки из state.js
   b. initLayout()           <- scroll sync + divider resize из layout.js
   c. Если PDF-режим:
      - pdf.js рендерит страницы
      - для каждой страницы вызывается window.createPdfOverlay(wrapper, textContent, viewport, startIdx, pageIndex)
      - createPdfOverlay создаёт .anno-marker элементы на overlay-слое
   d. initAnnotations():
      - Для non-PDF: injectBadges(docxPanel) -- бейджи на HTML-элементах
      - _syncS1000dElements() -- привязка правой панели к referenceData (3-фазная)
      - injectBadges(s1000dPanel)
      - recalcMaxIdx() + updatePosition()
      - Для non-PDF: detectMismatch()
   e. autoLoadReference():
      - GET /api/reference/{dmc}
      - Если reference существует: referenceData = data; enterEditMode()
3. enterEditMode():
   - refEditMode = true
   - rebuildBadges(docxPanel) -- пересинхронизирует с referenceData
   - _syncS1000dElements() + injectBadges(s1000dPanel)
   - recalcMaxIdx() + updatePosition()
4. Пользовательское взаимодействие:
   - Навигация: prev/next, клавиши j/k, клик на бейдж
   - Редактирование: клик на бейдж/маркер -> контекстное меню
   - Верификация: кнопка "Проверить" -> /api/verify
   - Цикл: кнопка "Форматировать согласно эталону" -> /api/verify-loop
```

---

## 5. Sync Pipeline (критическая подсистема)

Три стратегии синхронизации, выбираемые по контексту.
Каждая стратегия связывает DOM-элементы панели с записями `referenceData.elements[]`.

### 5.1. PDF markers <-> Reference (pdf-sync.js)

Вызывается из `rebuildBadges(docxPanel)` при `window.RENDER_MODE === 'pdf'`.

**Вход:** NodeList из `.anno-marker` элементов (по одному на PDF-блок) + `referenceData.elements[]`.

**Выбор алгоритма:** `_isXmlDerivedRef()` проверяет `referenceData.source === 'auto_xml_derived'` или наличие `type_source === 'xml_derived'` хотя бы у одного элемента.

#### _syncPdfMarkersBbox (XML-derived references)

Текстово-позиционное сопоставление:

1. Построить карту маркеров по страницам (`byPage`), для каждого маркера вычислить `normText = _normForMatch(data-anno-text)`.
2. Для каждого элемента reference (пропуская `_skip`, `_extra_pdf`, `_unmatched_xml`):
   a. `refNorm = _normForMatch(text_start)`
   b. Определить кандидатов: маркеры на `bbox.page` + соседних страницах (или все, если bbox отсутствует).
   c. **Text prefix matching:** для каждого кандидата подсчитать `score = commonPrefixLen / refNorm.length`. Выбрать кандидата с максимальным score. При равенстве -- предпочесть маркер на той же странице, что и `bbox.page`.
   d. **Position fallback** (если `bestScore < 0.3` и bbox задан): найти ближайший по Y-позиции маркер на `bbox.page` (порог: `dist < 5%`).
   e. Присвоить маркеру `data-anno-idx`, `data-anno-type`, цвет.
   f. Claim дополнительных маркеров по `span - 1` (consecutive unused в DOM-порядке).
   g. `_renderMarkerBrackets()` -- отображение label + скобок для группы маркеров.
3. Неиспользованные маркеры -> `_markUnassigned()` (зелёный пунктир, label "+", доступны для Create).

#### _syncPdfMarkersSequential (старые references)

Последовательное span-based сопоставление:

1. Итерировать `referenceData.elements[]` и `sorted[]` параллельно.
2. Для `_skip`: скрыть `span` маркеров, перейти к следующему элементу.
3. Для обычных: присвоить `span` маркеров текущему элементу, сгруппировать по страницам, отрисовать скобки.
4. Оставшиеся маркеры -> `_markUnassigned()`.

### 5.2. HTML blocks <-> Reference (html-sync.js)

Вызывается из `rebuildBadges(docxPanel)` при non-PDF режиме.

**Вход:** NodeList `[data-anno-idx], [data-anno-idx-cleared]` -> фильтрация `_filterTopLevel()` -> `annoEls[]`.

#### _syncHtmlElementsText (XML-derived references)

1. `_clearAnnoEl()` для всех блоков (сброс в доступное для Create состояние).
2. Предвычислить `domNorms[i] = _normForMatch(_getCleanText(el))`.
3. Для каждого элемента reference (пропуская `_skip`, `_extra_pdf`, `_unmatched_xml`):
   a. `textStart = _normForMatch(text_start)`
   b. Найти DOM-блок с лучшим prefix-match (score > 0.3).
   c. Claim `span` блоков начиная с найденного (consecutive unused).

#### _syncHtmlElementsSequential (старые references)

Аналогично PDF sequential: параллельная итерация по ref elements и DOM blocks.
`_skip` -> `_clearAnnoEl()` для `span` блоков.

### 5.3. S1000D elements <-> Reference (xml-sync.js)

Вызывается из `initAnnotations()` и `enterEditMode()`.

**Вход:** элементы правой панели `[data-anno-idx], [data-anno-type]` -> `_filterTopLevel()`.

3-фазный алгоритм:

**Фаза 1: stable_id matching**
- Построить `refByStableId{}` из `referenceData.elements` (ключ: `stable_id`, значение: ref element).
- Для каждого DOM-элемента: если `data-element-id` совпадает с `stable_id` -- присвоить `data-anno-idx` из ref.
- Результат: точное сопоставление по content-hash.

**Фаза 2: text prefix similarity**
- Собрать неспаренные ref elements в `refUnused[]`.
- Для каждого неспаренного DOM-элемента: `elPrefix = innerText[:60].toLowerCase()`.
- Для каждого кандидата из `refUnused`: подсчитать `score = matchChars / cmpLen` (prefix match), бонус +0.05 за совпадение типа.
- Принять, если `score > 0.5`.

**Фаза 3: type-group counters (fallback)**
- Для оставшихся неспаренных DOM-элементов: `normType(data-anno-type)` -> K-й элемент этого типа в reference.
- Пример: 3-й `para` в DOM -> 3-й `para` в reference.

**Вложенные списки (nested list pass):**
- После основного сопоставления: для `nested_unnumbered_list` / `nested_numbered_list` в reference -- найти родительский list-элемент и внутри него первый `ul`/`ol` без `data-anno-idx`.

---

## 6. Edit Mode & Create Flow

### Вход в режим редактирования

```
editRefBtn.click -> loadReference()
  -> GET /api/reference/{dmc}
  -> if exists: referenceData = data.reference
  -> else: POST /api/reference/{dmc}/init -> referenceData = data.reference
  -> enterEditMode():
     - refEditMode = true
     - document.body.classList.add('ref-editing')
     - показать кнопки: save, reset, verify, loop
     - rebuildBadges(docxPanel)
     - _syncS1000dElements() + injectBadges(s1000dPanel)
```

### Операция Create (детальная трассировка)

```
1. Пользователь кликает на зелёный маркер (+) или cleared-блок
   -> docxPanel.click (capture phase)
   -> обнаружение .anno-marker-unassigned или [data-anno-idx-cleared]

2. showCreateMenu(block, domPosition, x, y):
   - ctxTargetIdx = -999  (специальный маркер Create)
   - contextMenu: показать только кнопку "Создать"
   - ctxTypeSelect = 'para' (по умолчанию)
   - ctxPreview = block.data-anno-text || _getCleanText(block)

3. Пользователь выбирает тип -> нажимает "Создать"

4. ctxCreate.click handler:
   a. type = ctxTypeSelect.value
   b. text = _createBlock.getAttribute('data-anno-text') || _getCleanText(_createBlock)
   c. bbox = { page: _getMarkerPage(_createBlock), y0: _markerTopToAbsolute(_createBlock) }
      (только для PDF-маркеров; null для HTML)
   d. insertAt = _determineInsertPosition(domPosition)
      - считает cumulative span non-sentinel элементов
      - возвращает позицию в referenceData.elements[]
   e. newElem = {
        idx: 0, type, text_start: text[:60], text_end: text[-40:],
        span: 1, bbox (если есть)
      }
   f. referenceData.elements.splice(insertAt, 0, newElem)
   g. renumberRefElements() -- перенумерация idx (skip -> 0, остальные -> 1,2,3...)
   h. hideContextMenu()
   i. rebuildBadges(docxPanel):
      -> очистка старых бейджей
      -> _syncPdfMarkersBbox (или html sync) -- находит newElem по text+bbox
      -> injectBadges -- создаёт визуальный бейдж
      -> recalcMaxIdx + updatePosition + detectMismatch
```

### Операция Delete

Не удаляет элемент из массива -- помечает `type = '_skip'`.
Это сохраняет позиционное соответствие с PDF/HTML-блоками.
Маркер скрывается, слот span потребляется.

### Операция Merge (prev / next)

Расширяет границы одного элемента, поглощая соседний:
- `prev.span += absorbedSpan + curr.span`
- `prev.text_end = curr.text_end`
- `splice` удаляет все элементы между ними (включая sentinels).

### Операция Split

Обратная merge: элемент с `span > 1` разбивается на `span` отдельных элементов.
Тексты берутся из DOM (`_collectSubTexts`).

### renumberRefElements()

Перенумерация после любой мутации:
- `_skip` -> `idx = 0`
- Остальные -> последовательная нумерация `1, 2, 3, ...`

---

## 7. Mismatch Detection

### Сбор аннотаций

`collectAnnoTypes(panel)` -> `[{idx, type}]`:
- Обходит все `[data-anno-idx]` в панели.
- Пропускает `display:none` и `.anno-marker-unassigned`.
- Дедупликация по idx (cross-page span даёт несколько видимых маркеров с одним idx).

### Обнаружение расхождений

`detectMismatchFn()`:
1. Собрать `leftTypes`, `rightTypes`.
2. Если `leftCount === rightCount`:
   - Отфильтровать XSD floating types (`caution`, `warning`) -- их перемещение ожидаемо.
   - Сравнить порядок через `normTypeForOrder()` (коллапс `numbered_list`/`unnumbered_list` -> `list`).
   - Если порядок совпадает: `mismatchBadge = OK`.
   - Иначе: `mismatchBadge = WARN` + `highlightMismatches()`.
3. Если `leftCount !== rightCount`: `mismatchBadge = WARN` + `highlightMismatches()`.

### highlightMismatches (3-уровневое)

1. **Фаза 1: stable_id matching** -- построить `leftByEid`, `rightByEid` через `data-element-id`. При совпадении id но различии типа: `.anno-type-mismatch` (оранжевый).
2. **Фаза 2: LCS fallback** -- для неспаренных элементов вычислить LCS на последовательности типов (`computeLCS`). Спаренные в LCS -> matched.
3. **Неспаренные** -> `.anno-mismatch` (красный).

### computeLCS(a, b)

Классический DP-алгоритм O(m*n). Возвращает `{leftMatched, rightMatched}` -- словари индексов, вошедших в LCS.

### buildIssuesList(report)

Преобразует `ComparisonReport` (от `/api/verify`) в навигируемый список:

1. `left_unmatched` -> issue category `unmatched`, side `left`
2. `right_unmatched` -> issue category `unmatched`, side `right`
3. `type_mismatches` (не-нормализованные) -> issue category `type`, side `both`
4. `text_similarities` < 0.95 -> issue category `text`, side `both`
5. Сортировка по idx, merge issues с одинаковым idx.

Навигация: `navigateToNextIssue()` / `navigateToPrevIssue()` -> циклический проход по `issuesList`.

---

## 8. Серверные модули (краткий обзор)

| Модуль | Строк | Роль |
|--------|-------|------|
| `app.py` | 424 | Flask-приложение, 16 эндпоинтов (см. таблицу ниже) |
| `reference_store.py` | 257 | CRUD для `_references/*.json`; 3 стратегии init: XML-derived, hybrid, DOCX-only |
| `headless_comparator.py` | 706 | `ElementInfo`, `ComparisonReport`, `extract_xml_elements`, `extract_docx_elements`, `compare_elements` |
| `s1000d_renderer.py` | 560 | `S1000DHTMLRenderer`: XML -> HTML с `data-anno-idx`, `data-anno-type`, `data-element-id` из sidecar |
| `pdf_block_extractor.py` | 421 | PyMuPDF: извлечение текстовых блоков с bbox, merge строк в абзацы, детекция header/footer |
| `docx_renderer.py` | 282 | DOCX -> PDF (Word COM), DOCX -> HTML (mammoth), DOCX -> Word HTML |
| `pair_resolver.py` | 76 | DMC string -> пути файлов (docx_path, xml_path); сканирование input_dir |

### API-эндпоинты (app.py)

| Метод | Путь | Назначение |
|-------|------|-----------|
| GET | `/` | Главная: список пар DMC |
| GET | `/compare/<dmc>` | Страница сравнения |
| GET | `/pdf/<dmc>` | Генерация и отдача PDF |
| GET | `/api/pdf-blocks/<dmc>` | Текстовые блоки PDF (bbox) через PyMuPDF |
| GET | `/api/hybrid-blocks/<dmc>` | Unified elements: PDF boundaries + DOCX types |
| GET | `/wordhtml_res/<dmc>/<file>` | Ресурсы Word HTML export |
| GET | `/graphics/<file>` | Графика S1000D |
| GET | `/api/reference/<dmc>` | Получить эталон |
| POST | `/api/reference/<dmc>/init` | Создать эталон из автоматической разметки |
| POST | `/api/reference/<dmc>` | Сохранить пользовательский эталон |
| DELETE | `/api/reference/<dmc>` | Удалить эталон |
| POST | `/api/regenerate/<dmc>` | Перегенерировать XML из DOCX |
| POST | `/api/verify/<dmc>` | Запустить headless-сравнение reference vs XML |
| POST | `/api/verify-loop/<dmc>` | Цикл верификации (convert -> compare -> override -> repeat) |
| GET | `/api/verify-loop-progress/<dmc>` | Прогресс цикла верификации |
| GET | `/api/s1000d-html/<dmc>` | Свежий HTML рендер S1000D (после verify-loop) |

### reference_store.py: стратегии инициализации

Приоритет при `init_reference_from_auto()`:

1. **XML-derived** (`xml_path` задан + `element_source === 'hybrid'` + Word доступен):
   XML-элементы дают структуру и типы, stable_id из sidecar JSON, PDF-блоки дают позиции.
   Результат: reference с точным соответствием правой панели.
   `source = 'auto_xml_derived'`.

2. **Hybrid** (`element_source === 'hybrid'` + Word доступен):
   PDF-блоки + DOCX-элементы через `match_pdf_to_docx`.
   `source = 'auto_hybrid'`.

3. **DOCX-only fallback**: mammoth HTML -> `extract_docx_elements`.
   `source = 'auto'`.

### headless_comparator.py: ключевые структуры

```python
@dataclass
class ElementInfo:
    idx: int
    type: str
    text_start: str = ''   # первые 60 символов
    text_end: str = ''     # последние 40 символов
    span: int = 1
    stable_id: str = ''    # sha256:abc123...

@dataclass
class ComparisonReport:
    left_count: int = 0
    right_count: int = 0
    matched_pairs: List[Tuple[int, int]]     # (left_idx, right_idx)
    left_unmatched: List[int]
    right_unmatched: List[int]
    type_mismatches: List[Tuple[int, int, str, str]]  # (left_idx, right_idx, left_type, right_type)
    text_similarities: List[Tuple[int, int, float]]    # (left_idx, right_idx, ratio)
    score: float = 0.0

    @property
    def is_converged(self) -> bool:
        return self.score >= 0.95
```

---

## 9. Форматы данных

### referenceData (JSON)

Хранится в `{output_dir}/user_finetune/{dmc_string}.json`.

```json
{
  "dmc_string": "DMC-GAZPROM-A-66-93-50-00A-040A-A",
  "docx_hash": "sha256:a1b2c3d4e5f6g7h8",
  "created_at": "2025-11-15T14:30:00",
  "modified_at": "2025-11-16T10:15:00",
  "source": "auto_xml_derived",
  "elements": [
    {
      "idx": 1,
      "type": "heading",
      "type_source": "xml_derived",
      "text_start": "Общие сведения о турбодетандерном агрегате",
      "text_end": "турбодетандерном агрегате",
      "span": 1,
      "stable_id": "sha256:abc12345",
      "bbox": { "page": 1, "y0": 125.5 },
      "element_id": "e-1-heading-abc"
    }
  ]
}
```

**Поля элемента:**

| Поле | Тип | Описание |
|------|-----|----------|
| `idx` | `number` | Порядковый номер (1-based); 0 для `_skip` |
| `type` | `string` | Тип элемента (см. ниже) |
| `type_source` | `string` | Источник типа: `xml_derived`, `ooxml`, `pdf_heuristic`, `user_override` |
| `text_start` | `string` | Первые 60 символов текста |
| `text_end` | `string` | Последние 40 символов текста |
| `span` | `number` | Количество DOM-блоков/маркеров, покрываемых элементом (>1 после merge) |
| `stable_id` | `string` | Content-hash: `sha256:{hash}` -- для сопоставления с правой панелью |
| `bbox` | `{page, y0}` | Позиция в PDF-пространстве (необязательно) |
| `element_id` | `string` | Legacy element ID (необязательно) |

**Допустимые типы:**

| Тип | Описание |
|-----|----------|
| `heading` | Заголовок раздела |
| `para` | Абзац |
| `warning` | Предупреждение (S1000D `<warningAndCautionPara>`) |
| `caution` | Внимание |
| `note` | Примечание |
| `table` | Таблица |
| `figure` | Рисунок / иллюстрация |
| `numbered_list` | Нумерованный список |
| `unnumbered_list` | Ненумерованный список |
| `nested_numbered_list` | Вложенный нумерованный список |
| `nested_unnumbered_list` | Вложенный ненумерованный список |
| `_skip` | Удалённый элемент (sentinel: скрыт, span потребляется) |
| `_extra_pdf` | PDF-блок без XML-соответствия (sentinel: фильтруется при sync) |
| `_unmatched_xml` | XML-элемент без PDF-позиции (sentinel: фильтруется при sync) |

### ComparisonReport (JSON от /api/verify)

```json
{
  "score": 0.855,
  "left_count": 48,
  "right_count": 49,
  "matched_pairs": [[1, 1], [2, 2], [3, 4]],
  "left_unmatched": [5, 12],
  "right_unmatched": [3],
  "type_mismatches": [[7, 8, "caution", "para"]],
  "text_similarities": [[1, 1, 0.98], [3, 4, 0.72]],
  "is_converged": false
}
```

**Компоненты score:**
- `match_ratio` = `matched / max(left_count, right_count)`
- `type_ratio` = доля пар с совпадающим типом
- `avg_text_sim` = средняя текстовая похожесть по парам
- `score` = взвешенная комбинация (вес зависит от конфигурации в `headless_comparator`)

### Issue (клиентская структура)

```javascript
{
  idx: 5,               // annotation index
  side: 'left',         // 'left' | 'right' | 'both'
  category: 'unmatched', // 'unmatched' | 'type' | 'text'
  explanation: 'Элемент эталона [5] не найден в XML'
}
```

---

## 10. Зависимости между модулями (граф импортов)

```
config.js       <- state.js, badges.js, pdf-sync.js, html-sync.js,
                   xml-sync.js, pdf-overlay.js, navigation.js,
                   mismatch.js, edit-mode.js

state.js        <- ВСЕ модули (shared state)

logger.js       <- pdf-sync.js, edit-mode.js, badges.js, verification.js

utils.js        <- badges.js, pdf-sync.js, html-sync.js, xml-sync.js,
                   pdf-overlay.js, mismatch.js, edit-mode.js

layout.js       <- comparison.js (entry point)

badges.js       <- pdf-sync.js, html-sync.js, xml-sync.js,
                   edit-mode.js, verification.js

pdf-sync.js     <- badges.js (через rebuildBadges)

html-sync.js    <- badges.js (через rebuildBadges)

xml-sync.js     <- badges.js (через initAnnotations)

pdf-overlay.js  <- comparison.js (window.createPdfOverlay)

navigation.js   <- badges.js, edit-mode.js, mismatch.js

mismatch.js     <- badges.js, verification.js

verification.js <- edit-mode.js

edit-mode.js    <- comparison.js (entry point)
```

### Визуальная диаграмма (упрощённая)

```
                    comparison.js (entry)
                   /       |        \
             layout.js  pdf-overlay.js  edit-mode.js
                                          |
                                     verification.js
                                          |
                        +-----------+-----+------+-----------+
                        |           |            |           |
                    badges.js  mismatch.js  navigation.js  ...
                   /    |    \
           pdf-sync  html-sync  xml-sync
                \      |       /
                 +-----+------+
                       |
              utils.js + config.js + state.js + logger.js
```

### Циклические зависимости

`badges.js` вызывает `_syncPdfMarkers` (из `pdf-sync.js`) и `_syncHtmlElements` (из `html-sync.js`),
а те в свою очередь используют функции из `badges.js` (например, `getAnnoColor`).
Это решается через re-export или передачу функций как параметров при инициализации модулей.

---

## Приложение A: Нормализация типов

```javascript
// normType: алиасы для сопоставления
'paragraph' -> 'para'
'illustration' -> 'figure'

// normTypeForOrder: грубая нормализация для проверки порядка
'numbered_list' -> 'list'
'unnumbered_list' -> 'list'
'nested_numbered_list' -> 'nested_list'
'nested_unnumbered_list' -> 'nested_list'

// isNormalizedSame: ещё более мягкая для issue-фильтрации
'heading' == 'header'
'list' (any variant) == 'heading'  // секционные списки -> <levelledPara>
```

## Приложение B: Sentinel Types

| Тип | idx | Видимость | Потребление span | Где фильтруется |
|-----|-----|-----------|------------------|----------------|
| `_skip` | `0` | Скрыт | Да | Все sync-алгоритмы |
| `_extra_pdf` | `N` | Скрыт | Нет | `_syncPdfMarkersBbox`, `_syncHtmlElementsText` |
| `_unmatched_xml` | `N` | Скрыт | Нет | `_syncPdfMarkersBbox`, `_syncHtmlElementsText` |

## Приложение C: Window Exports

Модуль `comparison.js` экспортирует на `window`:

| Export | Вызывается из | Назначение |
|--------|--------------|-----------|
| `window.createPdfOverlay(wrapper, textContent, viewport, startIdx, pageIndex)` | PDF-рендер (template script) | Создание overlay + маркеров на PDF-странице |
| `window.detectMismatch()` | PDF-рендер (после загрузки всех страниц) | Запуск обнаружения расхождений |
