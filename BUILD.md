# Сборка дистрибутива

Документ описывает, как из исходников собрать standalone-дистрибутив
**Word to S1000D** (приложение сравнения + конвертер) и вспомогательный
инструмент **genfld** (DMRL). Сборка выполняется под Windows через PyInstaller.

## Предпосылки

- **Windows** (сборка и приложение завязаны на Windows: COM-автоматизация Word,
  бинарники вьюера `tg_web`).
- **Python 3.x** (рекомендуется тот же минор, что использовался при разработке).
- **Microsoft Word** — нужен в рантайме приложения (COM через `pywin32`), для
  самой сборки не обязателен.
- **Git** — `build.bat` берёт номер сборки из количества коммитов
  (`git rev-list --count HEAD`).
- **Git LFS** — бинарники вьюера `tg_web` (`*.dll`, `*.exe`, `*.zip`, графика,
  шрифты) хранятся в LFS. После клона обязательно выполнить:
  ```
  git lfs install
  git lfs pull
  ```
  Без этого вместо бинарников в рабочем дереве окажутся указатели LFS и
  дистрибутив будет нерабочим.

## Установка окружения

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller
```

`build.bat` сам активирует `venv\Scripts\activate.bat`, если папка `venv`
присутствует, и доустанавливает PyInstaller, если его нет.

## Сборка основного приложения

Запустить из корня проекта:

```
build.bat
```

Что он делает по шагам ([build.bat](build.bat)):

1. Активирует `venv` (если есть) и ставит PyInstaller при отсутствии.
2. Записывает номер сборки в `_build_number` из `git rev-list --count HEAD`
   (нужен для `version.py` во frozen-режиме, см. [version.py](version.py)).
3. Чистит предыдущие `build\` и `dist\word_to_s1000d\`.
4. Запускает `pyinstaller word_to_s1000d.spec --noconfirm` (one-folder, console).
5. Копирует во внешнюю часть дистрибутива:
   - `config.ini` — пользовательская конфигурация (редактируемая);
   - `doc_source_29_raw\` — исходные документы;
   - `docs\user_guide.html` — руководство пользователя;
   - `tg_web\` — встроенный веб-вьюер (с бинарниками);
   - чистит `tg_web\suites\66935\` (генерируемые DM в дистрибутив не входят,
     каталог остаётся пустым).
6. Собирает версионированный архив `dist\word_to_s1000d_<version>.zip`
   (`<version>` берётся из [version.py](version.py), формат `MAJOR.MINOR.BUILD`).

### Что лежит в `word_to_s1000d.spec`

PyInstaller-спецификация ([word_to_s1000d.spec](word_to_s1000d.spec)) — one-folder
console EXE. Ключевое:

- **`datas`** (бандлятся в `_internal` / `sys._MEIPASS`):
  XSD-схемы (`xsd\`), `parsing_rules.json`, шаблоны и статика Flask
  (`comparison_app\templates`, `comparison_app\static`), `_build_number`.
- **`hiddenimports`** — лениво подгружаемые модули, невидимые трассировщику:
  `win32com.client`/`pythoncom`/`pywintypes`/`win32api` (COM-автоматизация Word),
  `fitz`/`pymupdf`/`pymupdf.mupdf`/`pymupdf.utils` (PyMuPDF) и др.

> Файл `word_to_s1000d.spec` хранится в git как исключение из общего правила
> `*.spec` в [.gitignore](.gitignore) — без него `build.bat` не запустится.

## Сборка genfld (инструмент DMRL)

Отдельный инструмент генерации структуры папок из DMRL. Сборка:

```
cd dmrl
build_exe.bat
```

[dmrl/build_exe.bat](dmrl/build_exe.bat) собирает `genfld.exe` через
`pyinstaller --onefile` (spec генерируется на лету, отдельный файл не нужен) и
кладёт рядом `1.1 DMRL (без разбиения).xls`, `source_docs\` и
`generate_folders.bat`. Результат — в `dmrl\dist\`.

## Встроенный вьюер `tg_web`

`tg_web\` — мобильный веб-сервер-вьюер (TGWeb Mobile Server), который копируется
в дистрибутив и обслуживает просмотр публикаций.

- Происхождение: исходный архив
  `tg_web\TGWeb_MobileSever_2.2.3_x64.zip` (хранится в репозитории как референс).
- Бинарники (`tg_web\bin\*.dll`, `tgwebserver.exe`) и статика
  (`tg_web\dist\`, шрифты, графика) хранятся в **Git LFS** — см. предпосылки.
- **Генерируемое/рантайм** не коммитится (см. [.gitignore](.gitignore)):
  `tg_web\suites\66935\` (сгенерированные DM и графика — `build.bat` их и так
  вычищает из дистрибутива), `tg_web\cache\`, все `*.log`.
  Каталог `tg_web\suites\66935\` сохраняется пустым через `.gitkeep`.
- Управление сервисом: `tg_web\service_install_start.bat`,
  `service_start.bat`, `service_stop.bat`, `service_uninstall_stop.bat`,
  `run_consoled.bat`.

## Результат сборки

- `dist\word_to_s1000d\` — готовый дистрибутив:
  - `word_to_s1000d.exe` — запуск приложения сравнения;
  - `config.ini` — конфигурация (редактируемая);
  - `doc_source_29_raw\` — исходные документы;
  - `docs\user_guide.html` — руководство пользователя;
  - `tg_web\` — встроенный вьюер;
  - `_internal\` — забандленные зависимости.
- `dist\word_to_s1000d_<version>.zip` — версионированный архив дистрибутива.
