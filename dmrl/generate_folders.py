"""
Генерация структуры папок из DMRL (1.1 DMRL (без разбиения).xls).

Создаёт двухуровневую структуру:
  output/<Код системы> <Название>/[<Код МД>] <Название МД>/

При указании --source-dir копирует исходные файлы в папки МД.
"""

import os
import re
import shutil
import sys
import xlrd


def sanitize(name: str) -> str:
    """Убирает символы, недопустимые в именах папок Windows."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name).strip()


def build_file_index(source_dir: str) -> dict:
    """Строит индекс {имя_файла: полный_путь} рекурсивно по source_dir."""
    index = {}
    for root, dirs, files in os.walk(source_dir):
        for f in files:
            index[f] = os.path.join(root, f)
    return index


def main():
    if len(sys.argv) < 2:
        print(f"Использование: {os.path.basename(sys.argv[0])} <XLS файл> [--source-dir <папка>]")
        sys.exit(1)

    xls_path = sys.argv[1]
    if not os.path.isfile(xls_path):
        print(f"Файл не найден: {xls_path}")
        sys.exit(1)

    # Парсинг --source-dir
    source_dir = None
    if "--source-dir" in sys.argv:
        idx = sys.argv.index("--source-dir")
        if idx + 1 < len(sys.argv):
            source_dir = sys.argv[idx + 1]
            if not os.path.isdir(source_dir):
                print(f"Папка не найдена: {source_dir}")
                sys.exit(1)

    output_dir = os.path.join(os.path.dirname(os.path.abspath(xls_path)), "output")

    # Индекс исходных файлов
    file_index = build_file_index(source_dir) if source_dir else {}

    wb = xlrd.open_workbook(xls_path)
    sh = wb.sheet_by_index(0)

    current_system = None
    created = []
    copied = 0
    not_found = []

    for r in range(1, sh.nrows):
        col_file = str(sh.cell_value(r, 0)).strip()
        col_system = str(sh.cell_value(r, 1)).strip()
        col_dm_code = str(sh.cell_value(r, 2)).strip()
        col_name = str(sh.cell_value(r, 3)).strip()

        # Строка-система: колонка 1 заполнена, колонка 2 пустая
        if col_system and not col_dm_code:
            current_system = sanitize(f"{col_system} {col_name}")
            system_path = os.path.join(output_dir, current_system)
            os.makedirs(system_path, exist_ok=True)
            continue

        # Строка-МД: колонка 2 заполнена
        if col_dm_code and current_system:
            dm_folder = sanitize(f"[{col_dm_code}] {col_name}")
            dm_path = os.path.join(output_dir, current_system, dm_folder)
            os.makedirs(dm_path, exist_ok=True)
            created.append(f"  {current_system}/{dm_folder}")

            # Копирование исходного файла
            if col_file and file_index:
                if col_file in file_index:
                    shutil.copy2(file_index[col_file], dm_path)
                    copied += 1
                else:
                    not_found.append(col_file)

    print(f"Создано папок МД: {len(created)}")
    if source_dir:
        print(f"Скопировано файлов: {copied}")
        if not_found:
            print(f"Не найдено файлов: {len(not_found)}")
            for f in not_found:
                print(f"  ! {f}")
    print(f"Выходная директория: {output_dir}")
    print()
    for line in created:
        print(line)


if __name__ == "__main__":
    main()
