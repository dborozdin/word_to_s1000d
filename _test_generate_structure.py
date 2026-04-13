"""Playwright-тест: полный цикл — генерация структуры + XML через UI."""
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
    os.makedirs("_screenshots", exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=200)
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        # ═══════════════════════════════════════════
        # 1. Открываем главную страницу
        # ═══════════════════════════════════════════
        print("[1] Открываем главную страницу...")
        page.goto(BASE_URL, wait_until="load")
        time.sleep(2)
        page.screenshot(path="_screenshots/01_index.png")
        print(f"    Заголовок: {page.title()}")

        # ═══════════════════════════════════════════
        # 2. Нажимаем «Генерировать все (структура+XML)»
        # ═══════════════════════════════════════════
        print("[2] Нажимаем 'Генерировать все (структура+XML)'...")
        gen_all_btn = page.locator("#btn-gen-all")

        if gen_all_btn.is_visible():
            # Кнопка вызывает generateStructure() → reload → autoStartXml
            gen_all_btn.click()
            print("    Кнопка нажата. Ждём генерацию структуры...")

            # Ждём reload после генерации структуры (до 5 минут для COM)
            try:
                page.wait_for_event("load", timeout=300000)
            except Exception:
                pass
            time.sleep(3)

            page.screenshot(path="_screenshots/02_after_structure.png")
            print("    Структура сгенерирована. Скриншот: 02_after_structure.png")

            # ═══════════════════════════════════════════
            # 3. Ждём автозапуска генерации XML
            # ═══════════════════════════════════════════
            print("[3] Ждём генерацию XML...")

            # XML генерируется последовательно для каждого DM
            # Ждём пока прогресс-бар покажет "Завершено" или исчезнет
            # Максимум ждём 30 минут (XML-генерация может быть долгой)
            xml_timeout = 1800  # 30 минут
            start = time.time()
            last_screenshot = 0

            while time.time() - start < xml_timeout:
                # Проверяем прогресс
                progress = page.locator("#progress-bar")
                if progress.is_visible():
                    try:
                        text = progress.inner_text()
                    except Exception:
                        text = ""

                    # Скриншоты каждые 30 сек
                    elapsed = time.time() - start
                    if elapsed - last_screenshot > 30:
                        idx = int(elapsed // 30) + 3
                        page.screenshot(path=f"_screenshots/{idx:02d}_xml_progress.png")
                        # Извлечём прогресс-число
                        match = re.search(r'(\d+)/(\d+)', text)
                        if match:
                            print(f"    [{int(elapsed)}с] XML: {match.group(0)}")
                        last_screenshot = elapsed

                    # Завершено?
                    if 'Завершено' in text or 'завершено' in text.lower():
                        print(f"    XML генерация завершена: {text[:100]}")
                        break
                else:
                    # Прогресс-бар скрылся — возможно XML тоже завершился
                    # Проверим: есть ли зелёные статусы
                    ok_count = page.locator(".xml-status .status-ok").count()
                    gen_btns = page.locator(".gen-btn[data-dmc]").count()
                    if ok_count > 0 and ok_count >= gen_btns * 0.5:
                        print(f"    XML: {ok_count}/{gen_btns} модулей готовы")
                        break

                time.sleep(2)

            page.screenshot(path="_screenshots/90_after_xml.png")
            print("    Скриншот: 90_after_xml.png")
        else:
            print("    Кнопка 'Генерировать все' не найдена!")

        # ═══════════════════════════════════════════
        # 4. Подсчитываем результаты в UI
        # ═══════════════════════════════════════════
        print("\n[4] Проверяем результаты в UI...")
        time.sleep(2)
        page.screenshot(path="_screenshots/91_results.png")

        # Считаем статусы XML
        xml_ok = page.locator(".xml-status .status-ok").count()
        xml_missing = page.locator(".xml-status .status-missing").count()
        xml_warn = page.locator(".xml-status .status-warn").count()
        total_dm = page.locator(".gen-btn[data-dmc]").count()

        print(f"    Модулей данных: {total_dm}")
        print(f"    XML готовы: {xml_ok}")
        print(f"    XML отсутствуют: {xml_missing}")
        if xml_warn:
            print(f"    XML с предупреждениями: {xml_warn}")

        # ═══════════════════════════════════════════
        # 5. Сравнение заголовков с эталоном
        # ═══════════════════════════════════════════
        print("\n[5] Сравнение заголовков с _title_reference.json...")
        comparison = compare_titles(GEN_DIR, ref)
        pct = comparison['matched'] / comparison['total'] * 100 if comparison['total'] else 0
        print(f"    Совпадений: {comparison['matched']}/{comparison['total']} ({pct:.1f}%)")
        print(f"    Расхождений: {len(comparison['mismatched'])}")
        print(f"    Не найдено (спецфайлы): {len(comparison['not_found'])}")

        if comparison['mismatched']:
            print("\n    РАСХОЖДЕНИЯ:")
            for fname, ref_t, gen_t, score in comparison['mismatched']:
                print(f"      {fname}: ref='{ref_t[:60]}' gen='{gen_t[:60]}' ({score:.2f})")

        # ═══════════════════════════════════════════
        # 6. Итог
        # ═══════════════════════════════════════════
        page.screenshot(path="_screenshots/99_final.png")

        print("\n" + "=" * 60)
        ok = comparison['matched'] >= 45 and len(comparison['mismatched']) <= 2
        if ok:
            print(f"ТЕСТ ПРОЙДЕН")
        else:
            print(f"ТЕСТ НЕ ПРОЙДЕН")
        print(f"  Заголовки: {comparison['matched']}/{comparison['total']} ({pct:.1f}%)")
        print(f"  XML: {xml_ok}/{total_dm}")
        print("=" * 60)

        time.sleep(5)
        browser.close()


if __name__ == "__main__":
    main()
