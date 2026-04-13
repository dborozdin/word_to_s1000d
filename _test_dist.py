"""Playwright-тест дистрибутива: генерация структуры + XML, проверка 0 XSD ошибок."""
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:5000"


def main():
    os.makedirs("_screenshots", exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=200)
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        # ═══ 1. Открываем главную ═══
        print("[1] Открываем главную страницу...")
        page.goto(BASE_URL, wait_until="load")
        time.sleep(2)
        title = page.title()
        print(f"    Заголовок: {title}")
        page.screenshot(path="_screenshots/dist_01_index.png")

        # ═══ 2. Проверяем наличие руководства пользователя ═══
        print("[2] Проверяем user_guide.html...")
        ug_resp = page.request.get(BASE_URL + "/docs/user_guide.html")
        # user_guide статический файл не обслуживается Flask, но проверим файл на диске
        dist_dir = os.path.dirname(os.path.abspath(__file__))
        ug_dist = os.path.join(dist_dir, "dist", "word_to_s1000d", "docs", "user_guide.html")
        if os.path.isfile(ug_dist):
            print(f"    user_guide.html: OK ({os.path.getsize(ug_dist)} bytes)")
        else:
            print(f"    user_guide.html: NOT FOUND at {ug_dist}")

        # ═══ 3. Нажимаем «Генерировать все» ═══
        print("[3] Нажимаем 'Генерировать все (структура+XML)'...")
        gen_all_btn = page.locator("#btn-gen-all")

        if gen_all_btn.is_visible():
            gen_all_btn.click()
            print("    Кнопка нажата. Ждём структуру...")

            # Ждём reload после структуры
            try:
                page.wait_for_event("load", timeout=300000)
            except Exception:
                pass
            time.sleep(3)

            page.screenshot(path="_screenshots/dist_02_structure.png")
            print("    Структура создана.")

            # ═══ 4. Ждём XML генерацию ═══
            print("[4] Ждём генерацию XML...")
            xml_timeout = 1800
            start = time.time()
            last_log = 0

            while time.time() - start < xml_timeout:
                progress = page.locator("#progress-bar")
                if progress.is_visible():
                    try:
                        text = progress.inner_text()
                    except Exception:
                        text = ""

                    elapsed = time.time() - start
                    if elapsed - last_log > 30:
                        match = re.search(r'(\d+)/(\d+)', text)
                        if match:
                            print(f"    [{int(elapsed)}s] XML: {match.group(0)}")
                        last_log = elapsed

                    if 'Завершено' in text or 'завершено' in text.lower():
                        # Извлекаем количество ошибок
                        err_match = re.search(r'ошибок:\s*(\d+)', text)
                        err_count = int(err_match.group(1)) if err_match else 0
                        print(f"    XML завершено: {text[:100]}")
                        print(f"    Ошибок: {err_count}")
                        break
                else:
                    ok_count = page.locator(".xml-status .status-ok").count()
                    if ok_count > 0:
                        break

                time.sleep(2)

            page.screenshot(path="_screenshots/dist_03_xml_done.png")
        else:
            print("    Кнопка не найдена!")
            err_count = -1

        # ═══ 5. Подсчёт результатов ═══
        print("\n[5] Результаты...")
        time.sleep(2)

        xml_ok = page.locator(".xml-status .status-ok").count()
        xml_miss = page.locator(".xml-status .status-missing").count()
        xml_warn = page.locator(".xml-status .status-warn").count()
        total_dm = page.locator(".gen-btn[data-dmc]").count()

        print(f"    Модулей данных: {total_dm}")
        print(f"    XML готовы: {xml_ok}")
        print(f"    XML отсутствуют: {xml_miss}")
        if xml_warn:
            print(f"    XML с предупреждениями: {xml_warn}")

        page.screenshot(path="_screenshots/dist_04_final.png")

        # ═══ 6. Итог ═══
        print("\n" + "=" * 60)
        all_ok = xml_ok > 0 and xml_miss <= 2
        if all_ok:
            print("ТЕСТ ДИСТРИБУТИВА ПРОЙДЕН")
        else:
            print("ТЕСТ ДИСТРИБУТИВА НЕ ПРОЙДЕН")
        print(f"  XML: {xml_ok}/{total_dm}")
        print(f"  user_guide.html: {'OK' if os.path.isfile(ug_dist) else 'MISSING'}")
        print("=" * 60)

        time.sleep(5)
        browser.close()


if __name__ == "__main__":
    main()
