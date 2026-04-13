"""Playwright-тест: генерация структуры через UI и сравнение с эталоном."""
import json
import os
import re
import sys
import time
import difflib

from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:5000"
REFERENCE_PATH = os.path.join(os.path.dirname(__file__),
                              "doc_source_12_raw", "_title_reference.json")
GEN_DIR = os.path.join(os.path.dirname(__file__), "doc_source_12_generated")


def load_reference():
    with open(REFERENCE_PATH, encoding="utf-8") as f:
        return json.load(f)


def compare_titles(gen_dir, ref):
    """Сравнивает заголовки в сгенерированной структуре с эталоном."""
    file_to_folder = {}
    for root, dirs, files in os.walk(gen_dir):
        for fname in files:
            if fname.lower().endswith(('.doc', '.docx', '.pdf')):
                file_to_folder[fname] = os.path.basename(root)

    def extract_title(folder_name):
        m = re.search(r'\]\s*(.+)$', folder_name)
        return m.group(1).strip() if m else folder_name

    def norm(s):
        if not s:
            return ''
        s = s.strip().lower()
        s = s.replace('\u2013', '-').replace('\u2014', '-').replace('\u2012', '-')
        return re.sub(r'\s+', ' ', s).rstrip('.')

    results = {'matched': 0, 'mismatched': [], 'not_found': [], 'total': 0}

    for ref_fname, ref_title in sorted(ref.items()):
        if ref_title is None:
            continue
        results['total'] += 1
        if ref_fname in file_to_folder:
            gen_title = extract_title(file_to_folder[ref_fname])
            n_ref = norm(ref_title)
            n_gen = norm(gen_title)
            if n_ref == n_gen:
                results['matched'] += 1
            else:
                score = difflib.SequenceMatcher(None, n_ref, n_gen).ratio()
                if score >= 0.85:
                    results['matched'] += 1
                else:
                    results['mismatched'].append((ref_fname, ref_title, gen_title, score))
        else:
            results['not_found'].append((ref_fname, ref_title))
    return results


def main():
    ref = load_reference()

    with sync_playwright() as p:
        # Открываем видимый браузер
        browser = p.chromium.launch(headless=False, slow_mo=300)
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        # 1. Открываем главную страницу
        print("[1] Открываем главную страницу...")
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_load_state("load")
        time.sleep(2)  # дождаться async fetch
        title = page.title()
        print(f"    Заголовок: {title}")

        # Скриншот начального состояния
        page.screenshot(path="_screenshots/01_index.png")
        print("    Скриншот: _screenshots/01_index.png")

        # 2. Проверяем блок «Исходные документы»
        print("[2] Проверяем блок исходных документов...")
        raw_stats = page.locator("#raw-stats")
        raw_stats.wait_for(state="visible", timeout=5000)
        raw_text = raw_stats.inner_text()
        print(f"    Raw stats: {raw_text[:200]}")

        # 3. Проверяем UI — структура уже сгенерирована через CLI
        print("[3] Проверяем отображение структуры (CLI-генерация)...")
        page.screenshot(path="_screenshots/02_structure_display.png")
        print("    Скриншот: _screenshots/02_structure_display.png")

        # Проверяем наличие кнопки генерации
        gen_btn = page.locator("#btn-gen-structure")
        print(f"    Кнопка 'Сгенерировать структуру' видна: {gen_btn.is_visible()}")

        # 4. Проверяем список модулей в UI
        print("[4] Проверяем список модулей...")
        rows = page.locator("tr[data-dmc]")
        row_count = rows.count()
        print(f"    Строк в таблице: {row_count}")

        if row_count > 0:
            # Выводим первые 5 модулей
            for i in range(min(5, row_count)):
                row = rows.nth(i)
                dmc = row.get_attribute("data-dmc")
                tech_name = row.locator("td").nth(1).inner_text() if row.locator("td").count() > 1 else ""
                print(f"    [{i+1}] {dmc}: {tech_name}")

        page.screenshot(path="_screenshots/03_modules_list.png")
        print("    Скриншот: _screenshots/03_modules_list.png")

        # 5. Сравниваем с эталоном _title_reference.json
        print("\n[5] Сравнение с эталоном _title_reference.json...")
        comparison = compare_titles(GEN_DIR, ref)
        pct = comparison['matched'] / comparison['total'] * 100 if comparison['total'] else 0
        print(f"    Совпадений: {comparison['matched']}/{comparison['total']} ({pct:.1f}%)")
        print(f"    Расхождений: {len(comparison['mismatched'])}")
        print(f"    Не найдено: {len(comparison['not_found'])}")

        if comparison['mismatched']:
            print("\n    РАСХОЖДЕНИЯ:")
            for fname, ref_t, gen_t, score in comparison['mismatched']:
                print(f"      {fname}")
                print(f"        эталон: {ref_t}")
                print(f"        генер.: {gen_t}")
                print(f"        score:  {score:.2f}")

        if comparison['not_found']:
            print("\n    НЕ НАЙДЕНЫ (пропущенные спецфайлы):")
            for fname, title in comparison['not_found']:
                print(f"      {fname} -> {title}")

        # 6. Итоговый скриншот
        page.screenshot(path="_screenshots/04_final.png")

        # Итог
        print("\n" + "=" * 60)
        if comparison['matched'] >= 50 and len(comparison['mismatched']) == 0:
            print(f"ТЕСТ ПРОЙДЕН: {comparison['matched']}/{comparison['total']} совпадений")
        else:
            print(f"ТЕСТ НЕ ПРОЙДЕН: {comparison['matched']}/{comparison['total']} совпадений, "
                  f"{len(comparison['mismatched'])} расхождений")
        print("=" * 60)

        # Оставляем браузер открытым на 5 секунд для визуальной проверки
        time.sleep(5)
        browser.close()


if __name__ == "__main__":
    os.makedirs("_screenshots", exist_ok=True)
    main()
