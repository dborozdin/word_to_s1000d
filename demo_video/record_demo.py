"""
Main demo recording script.
Automates the full Word-to-S1000D workflow while recording the screen:
  1. Unpack distribution
  2. Launch app & generate XML
  3. View modules in TGWeb
  4. Comparison mode
  5. Create reference (etalon)
  6. Navigate elements
  7. Edit markup (list → paragraph)
  8. Generate XML by reference

Usage:
    pip install -r requirements.txt
    playwright install chromium
    python record_demo.py
"""

import asyncio
import ctypes
from ctypes import wintypes
import os
import shutil
import socket
import subprocess
import sys
import time

from playwright.async_api import async_playwright, Page, BrowserContext

# Add demo_video dir to path for local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from screen_recorder import ScreenRecorder

# ─── Configuration ───────────────────────────────────────────────────────────

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_ZIP = os.path.join(PROJECT_ROOT, "dist", "word_to_s1000d_1.0.80.zip")
UNPACK_DIR = r"c:\tmp\word_to_s1000d"
UNPACK_PARENT = r"c:\tmp"

APP_URL = "http://localhost:5000"
TGWEB_URL = "http://localhost:8082"
OUTPUT_VIDEO = r"c:\tmp\word_to_s1000d_demo.mp4"
SCREENSHOT_DIR = r"c:\tmp\demo_screenshots"

TARGET_DMC = "DMC-S5-A-029-00-00-00A-012A-A_001"
FPS = 12

# Monitor 1 = primary display (mss index 1); position detected at runtime
MONITOR_INDEX = 1

# Filled at runtime by detect_monitor_geometry()
MON_LEFT = 0
MON_TOP = 0
MON_W = 1920
MON_H = 1080


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def wait_for_port(port: int, host: str = "localhost", timeout: float = 60) -> bool:
    """Poll until a TCP port is accepting connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError, TimeoutError):
            await asyncio.sleep(0.5)
    raise TimeoutError(f"Port {port} not available after {timeout}s")


def cleanup_processes() -> None:
    """Kill application processes."""
    for proc_name in ("word_to_s1000d.exe", "tgwebserver.exe"):
        subprocess.run(
            ["taskkill", "/F", "/IM", proc_name],
            capture_output=True,
        )


def is_port_in_use(port: int, host: str = "localhost") -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def manage_windows(
    title_keywords: list[str],
    action: str = "minimize",
    move_rect: tuple[int, int, int, int] | None = None,
) -> None:
    """Find visible windows by title keywords.
    Actions: 'minimize', 'close', 'move' (requires move_rect=(x,y,w,h)).
    """
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    SW_MINIMIZE = 6
    WM_CLOSE = 0x0010

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value.lower()
        if any(kw.lower() in title for kw in title_keywords):
            if action == "minimize":
                user32.ShowWindow(hwnd, SW_MINIMIZE)
            elif action == "close":
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            elif action == "move" and move_rect:
                x, y, w, h = move_rect
                user32.MoveWindow(hwnd, x, y, w, h, True)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)


def detect_monitor_geometry(monitor_index: int) -> tuple[int, int, int, int]:
    """Return (left, top, width, height) for the given mss monitor index."""
    import mss as _mss
    with _mss.mss() as sct:
        if monitor_index < len(sct.monitors):
            m = sct.monitors[monitor_index]
            return m["left"], m["top"], m["width"], m["height"]
    return 0, 0, 1920, 1080


async def screenshot(page: Page, name: str) -> None:
    """Save a Playwright screenshot for debug verification."""
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    try:
        await page.screenshot(path=path, full_page=False)
        print(f"[Screenshot] {path}")
    except Exception as e:
        print(f"[Screenshot] FAILED {name}: {e}")


# ─── CSS highlight for buttons ──────────────────────────────────────────────

HIGHLIGHT_CSS = """
el.dataset._origOutline = el.style.outline || '';
el.dataset._origBoxShadow = el.style.boxShadow || '';
el.style.outline = '3px solid #e74c3c';
el.style.outlineOffset = '3px';
el.style.boxShadow = '0 0 20px rgba(231,76,60,0.7)';
el.scrollIntoView({block: 'center', behavior: 'smooth'});
"""

UNHIGHLIGHT_CSS = """
el.style.outline = el.dataset._origOutline || '';
el.style.boxShadow = el.dataset._origBoxShadow || '';
el.style.outlineOffset = '';
delete el.dataset._origOutline;
delete el.dataset._origBoxShadow;
"""


async def highlight_and_click(
    page: Page,
    selector: str,
    recorder: ScreenRecorder | None = None,
    label: str | None = None,
    pause: float = 1.5,
) -> None:
    """Add red highlight to element, set overlay, wait, then click and remove."""
    # Highlight
    await page.evaluate(f"""(sel) => {{
        const el = document.querySelector(sel);
        if (el) {{ {HIGHLIGHT_CSS} }}
    }}""", selector)
    if label and recorder:
        recorder.set_overlay(label)
    await page.wait_for_timeout(int(pause * 1000))
    # Click
    await page.click(selector)
    # Remove highlight
    await page.evaluate(f"""(sel) => {{
        const el = document.querySelector(sel);
        if (el) {{ {UNHIGHLIGHT_CSS} }}
    }}""", selector)


async def highlight_element(page: Page, selector: str) -> None:
    """Add red highlight to element without clicking."""
    await page.evaluate(f"""(sel) => {{
        const el = document.querySelector(sel);
        if (el) {{ {HIGHLIGHT_CSS} }}
    }}""", selector)


async def unhighlight_element(page: Page, selector: str) -> None:
    """Remove highlight from element."""
    await page.evaluate(f"""(sel) => {{
        const el = document.querySelector(sel);
        if (el) {{ {UNHIGHLIGHT_CSS} }}
    }}""", selector)


def console_window_rect() -> tuple[int, int, int, int]:
    """Return (x, y, w, h) for a console window positioned on the target monitor."""
    # Place console in the center-left area, about 80x30 chars
    cw, ch = min(900, MON_W // 2), min(600, MON_H // 2)
    cx = MON_LEFT + (MON_W - cw) // 2
    cy = MON_TOP + (MON_H - ch) // 2
    return cx, cy, cw, ch


# ─── Scene 1: Unpack distribution ───────────────────────────────────────────

async def scene_1_unpack(recorder: ScreenRecorder) -> None:
    recorder.inject_transition("Шаг 1", "Распаковка дистрибутива", duration=2.5)
    recorder.set_overlay("Распаковка дистрибутива во временную папку c:\\tmp\\word_to_s1000d")

    # Find actual ZIP file (version may vary)
    zip_path = DIST_ZIP
    if not os.path.isfile(zip_path):
        dist_dir = os.path.join(PROJECT_ROOT, "dist")
        for f in os.listdir(dist_dir):
            if f.startswith("word_to_s1000d") and f.endswith(".zip"):
                zip_path = os.path.join(dist_dir, f)
                break

    # Clean previous unpack
    if os.path.isdir(UNPACK_DIR):
        shutil.rmtree(UNPACK_DIR, ignore_errors=True)

    # Create helper script that extracts with a visible progress bar
    import tempfile
    helper_script = os.path.join(tempfile.gettempdir(), "_demo_unpack.py")
    with open(helper_script, "w", encoding="utf-8") as f:
        f.write(f'''import zipfile, os, sys, time
zip_path = r"{zip_path}"
dest = r"{UNPACK_DIR}"
os.makedirs(dest, exist_ok=True)
print("=" * 60)
print("  Распаковка дистрибутива Word to S1000D")
print("=" * 60)
print()
print(f"  Архив: {{zip_path}}")
print(f"  Назначение: {{dest}}")
print()
zf = zipfile.ZipFile(zip_path)
names = zf.namelist()
total = len(names)
for i, name in enumerate(names):
    zf.extract(name, dest)
    if i % 50 == 0 or i == total - 1:
        pct = int((i + 1) / total * 100)
        bar = "#" * (pct // 2) + "." * (50 - pct // 2)
        print(f"\\r  [{{bar}}] {{pct:3d}}%  ({{i+1}}/{{total}})", end="", flush=True)
zf.close()
print()
print()
print("  Готово! Содержимое:")
print()
for item in sorted(os.listdir(dest)):
    print(f"    {{item}}")
print()
time.sleep(60)
''')

    proc = subprocess.Popen(
        ["python", helper_script],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )

    # Move the extraction console to the target monitor
    await asyncio.sleep(1)
    manage_windows(
        ["_demo_unpack", "python"],
        action="move",
        move_rect=console_window_rect(),
    )

    # Wait for extraction to complete (poll for exe to appear)
    exe_path = os.path.join(UNPACK_DIR, "word_to_s1000d.exe")
    for _ in range(60):
        if os.path.isfile(exe_path):
            break
        await asyncio.sleep(0.5)

    await asyncio.sleep(3)
    recorder.set_overlay("Дистрибутив распакован")
    await asyncio.sleep(2)

    # Close the extraction console
    proc.terminate()
    await asyncio.sleep(0.5)

    # Open Explorer to show the unpacked folder contents
    recorder.set_overlay("Содержимое папки дистрибутива")
    subprocess.Popen(["explorer", UNPACK_DIR])
    await asyncio.sleep(1)
    # Move Explorer to the target monitor
    manage_windows(
        ["word_to_s1000d"],
        action="move",
        move_rect=(MON_LEFT + 50, MON_TOP + 50, MON_W - 100, MON_H - 100),
    )
    await asyncio.sleep(4)

    # Close the Explorer window
    manage_windows(["word_to_s1000d"], action="close")
    await asyncio.sleep(1)


# ─── Scene 2: Launch app & generate XML ─────────────────────────────────────

async def scene_2_launch_and_generate(
    page: Page,
    recorder: ScreenRecorder,
) -> subprocess.Popen:
    recorder.inject_transition("Шаг 2", "Запуск приложения и генерация XML", duration=2.5)
    recorder.set_overlay("Запуск приложения word_to_s1000d.exe")

    # Kill any existing instances
    if is_port_in_use(5000):
        cleanup_processes()
        await asyncio.sleep(2)

    # Launch the exe
    exe_path = os.path.join(UNPACK_DIR, "word_to_s1000d.exe")
    app_proc = subprocess.Popen(
        [exe_path],
        cwd=UNPACK_DIR,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    await asyncio.sleep(2)

    # Move app console to target monitor
    manage_windows(
        ["word_to_s1000d"],
        action="move",
        move_rect=console_window_rect(),
    )
    await asyncio.sleep(1)

    # Wait for Flask to be ready
    recorder.set_overlay("Ожидание запуска серверов...")
    await wait_for_port(5000, timeout=60)
    await asyncio.sleep(2)

    # Show console windows briefly
    recorder.set_overlay("Серверы Flask и TG Web запущены")
    await asyncio.sleep(3)

    # Minimize console windows so they don't cover the browser
    manage_windows(
        ["word_to_s1000d", "tgweb", "python.exe", "cmd.exe"],
        action="minimize",
    )
    await asyncio.sleep(1)

    # Navigate to the app
    recorder.set_overlay("Открываем веб-интерфейс генерации")
    await page.goto(APP_URL, wait_until="networkidle")
    await page.wait_for_timeout(2000)
    await screenshot(page, "s2_main_page")

    # Click "Generate All" with highlight
    await highlight_and_click(
        page, "#btn-gen-all", recorder,
        label="Нажимаем «Сформировать все» для генерации XML",
    )

    # Wait for generation to complete
    recorder.set_overlay("Генерация XML из документов Word...")
    await page.wait_for_function(
        """() => {
            const el = document.getElementById('gen-all-progress');
            return el && el.textContent.includes('Завершено');
        }""",
        timeout=300_000,
    )
    await page.wait_for_timeout(2000)

    recorder.set_overlay("Генерация XML завершена")
    await screenshot(page, "s2_generation_done")
    await page.wait_for_timeout(3000)

    return app_proc


# ─── Scene 3: View modules in TGWeb ─────────────────────────────────────────

async def scene_3_view_tgweb(
    page: Page,
    context: BrowserContext,
    recorder: ScreenRecorder,
) -> None:
    recorder.inject_transition("Шаг 3", "Просмотр модулей данных в TGWeb", duration=2.5)
    recorder.set_overlay("Просмотр сгенерированных модулей данных в TGWeb")

    # Wait for tg_web server
    try:
        await wait_for_port(8082, timeout=15)
    except TimeoutError:
        recorder.set_overlay("TGWeb сервер недоступен, пропуск...")
        await asyncio.sleep(3)
        return

    await asyncio.sleep(1)

    # Get view links (only enabled ones)
    view_links = await page.query_selector_all("a.view-link[data-dmc]")
    shown = 0

    for link in view_links:
        if shown >= 3:
            break

        classes = await link.get_attribute("class") or ""
        if "disabled" in classes:
            continue

        dmc = await link.get_attribute("data-dmc")
        short_dmc = dmc.replace("DMC-", "").rsplit("_", 1)[0] if dmc else ""

        # Highlight the view link
        await highlight_element(page, f'a.view-link[data-dmc="{dmc}"]')
        recorder.set_overlay(f"Просмотр модуля: {short_dmc}")
        await page.wait_for_timeout(1000)

        # Click to open in new tab
        async with context.expect_page() as new_page_info:
            await link.click()
        await unhighlight_element(page, f'a.view-link[data-dmc="{dmc}"]')

        new_page = await new_page_info.value
        await new_page.wait_for_load_state("load")
        await new_page.wait_for_timeout(4000)

        # Close the TGWeb tab
        await new_page.close()
        await page.bring_to_front()
        await page.wait_for_timeout(1000)
        shown += 1

    recorder.set_overlay("")
    await page.wait_for_timeout(1000)


# ─── Scene 4: Comparison mode ───────────────────────────────────────────────

async def scene_4_comparison(page: Page, recorder: ScreenRecorder) -> None:
    recorder.inject_transition("Шаг 4", "Режим сравнения", duration=2.5)
    recorder.set_overlay("Переходим в режим сравнения документа")

    # Highlight the compare link for the target DMC (link has href, not data-dmc)
    compare_sel = f'a.compare-link[href="/compare/{TARGET_DMC}"]'
    # Fallback: if exact selector fails, navigate directly
    link_exists = await page.query_selector(compare_sel)
    if link_exists:
        await highlight_and_click(
            page, compare_sel, recorder,
            label="Открываем режим сравнения для выбранного документа",
        )
        await page.wait_for_load_state("networkidle")
    else:
        recorder.set_overlay("Открываем режим сравнения")
        await page.goto(f"{APP_URL}/compare/{TARGET_DMC}", wait_until="networkidle")

    # Wait for PDF to render
    await page.wait_for_selector("canvas.pdf-page", timeout=60_000)
    await page.wait_for_timeout(3000)

    recorder.set_overlay("Слева — PDF из Word, справа — S1000D XML")
    await screenshot(page, "s4_comparison_view")
    await page.wait_for_timeout(3000)

    # Scroll panels to show content
    await page.evaluate("""() => {
        const docx = document.getElementById('content-docx');
        if (docx) docx.scrollBy(0, 300);
    }""")
    await page.wait_for_timeout(2000)

    # Scroll back
    await page.evaluate("""() => {
        const docx = document.getElementById('content-docx');
        if (docx) docx.scrollTo(0, 0);
    }""")
    await page.wait_for_timeout(1000)


# ─── Scene 5: Create reference ──────────────────────────────────────────────

async def scene_5_create_reference(page: Page, recorder: ScreenRecorder) -> None:
    recorder.inject_transition("Шаг 5", "Создание эталонной разметки", duration=2.5)
    recorder.set_overlay("Создание эталонной разметки для контроля качества")

    # Click "Эталон" button with highlight
    await highlight_and_click(
        page, "#edit-ref-btn", recorder,
        label="Нажимаем «Эталон» для создания эталонной разметки",
    )
    await page.wait_for_timeout(1000)

    # Wait for splash to appear
    try:
        await page.wait_for_selector(
            '#regen-splash:not([style*="display: none"])',
            timeout=5000,
        )
    except Exception:
        pass

    # Wait for reference loading to complete
    await page.wait_for_function(
        """() => {
            const splash = document.getElementById('regen-splash');
            const saveBtn = document.getElementById('save-ref-btn');
            return (!splash || splash.style.display === 'none' || splash.style.display === '') &&
                   saveBtn && saveBtn.style.display !== 'none';
        }""",
        timeout=30_000,
    )
    await page.wait_for_timeout(2000)

    recorder.set_overlay("Элементы размечены бейджами с типами")
    await screenshot(page, "s5_badges_created")
    await page.wait_for_timeout(3000)

    # Toggle annotations on/off/on
    recorder.set_overlay("Переключение видимости разметки")
    await highlight_and_click(page, "#toggle-anno", pause=1.0)
    await page.wait_for_timeout(1500)
    await highlight_and_click(page, "#toggle-anno", pause=1.0)
    await page.wait_for_timeout(2000)


# ─── Scene 6: Navigate elements ─────────────────────────────────────────────

async def scene_6_navigate(page: Page, recorder: ScreenRecorder) -> None:
    recorder.inject_transition("Шаг 6", "Навигация по элементам", duration=2.5)
    recorder.set_overlay("Навигация по элементам документа")

    # Navigate forward through elements with highlight on >> button
    await highlight_element(page, "#anno-next")
    for i in range(6):
        await page.click("#anno-next")
        await page.wait_for_timeout(800)
    await unhighlight_element(page, "#anno-next")

    # Navigate backward
    recorder.set_overlay("Навигация назад")
    await highlight_element(page, "#anno-prev")
    for i in range(2):
        await page.click("#anno-prev")
        await page.wait_for_timeout(800)
    await unhighlight_element(page, "#anno-prev")

    await page.wait_for_timeout(1000)

    # Switch to issues mode
    await highlight_and_click(
        page, "#nav-mode", recorder,
        label="Переключение на навигацию по расхождениям",
    )
    await page.select_option("#nav-mode", "issues")
    await page.wait_for_timeout(1500)

    # Navigate through issues
    recorder.set_overlay("Навигация по расхождениям между PDF и XML")
    await highlight_element(page, "#anno-next")
    for i in range(3):
        await page.click("#anno-next")
        await page.wait_for_timeout(1000)
    await unhighlight_element(page, "#anno-next")

    recorder.set_overlay("Подсветка расхождений между исходным документом и XML")
    await screenshot(page, "s6_issues_navigation")
    await page.wait_for_timeout(2000)


# ─── Scene 7: Edit markup ───────────────────────────────────────────────────

async def scene_7_edit_markup(page: Page, recorder: ScreenRecorder) -> None:
    recorder.inject_transition("Шаг 7", "Редактирование разметки", duration=2.5)
    recorder.set_overlay("Редактирование разметки: разделение списка на параграфы")

    # Switch back to "all" navigation mode
    await page.select_option("#nav-mode", "all")
    await page.wait_for_timeout(500)

    # Scroll to the top of the left panel
    await page.evaluate("""() => {
        const panel = document.getElementById('content-docx') ||
                      document.getElementById('panel-docx');
        if (panel) panel.scrollTo(0, 0);
    }""")
    await page.wait_for_timeout(500)

    # ── Debug: inventory of markers in LEFT panel (PDF mode uses .anno-marker) ──
    debug = await page.evaluate("""() => {
        const markers = document.querySelectorAll('#content-docx .anno-marker[data-anno-idx]');
        const samples = Array.from(markers).slice(0, 10).map(m => ({
            idx: m.getAttribute('data-anno-idx'),
            type: m.getAttribute('data-anno-type'),
            label: m.querySelector('.marker-label')
                   ? m.querySelector('.marker-label').textContent.trim() : ''
        }));
        return {count: markers.length, samples: samples};
    }""")
    print(f"[Scene7] PDF marker inventory: {debug}")

    # ── Step 1: Find a list marker in the LEFT panel ──
    # In PDF mode, badges are .anno-marker elements inside #content-docx
    marker_info = await page.evaluate("""() => {
        const markers = document.querySelectorAll('#content-docx .anno-marker[data-anno-idx]');
        for (const m of markers) {
            const label = m.querySelector('.marker-label');
            const text = label ? label.textContent.trim() : '';
            const type = m.getAttribute('data-anno-type') || '';
            // Match list-type markers (type contains 'list' or label contains 'спис')
            if (/list/i.test(type) || /спис/i.test(text)) {
                return {
                    idx: m.getAttribute('data-anno-idx'),
                    type: type,
                    label: text
                };
            }
        }
        return null;
    }""")

    if not marker_info:
        print("[Scene7] No list marker found in left panel!")
        recorder.set_overlay("Элемент-список не найден, пропуск...")
        await screenshot(page, "s7_list_not_found")
        await page.wait_for_timeout(2000)
        return

    marker_idx = marker_info["idx"]
    marker_label = marker_info["label"]
    print(f"[Scene7] Found list marker: idx={marker_idx} label='{marker_label}' type={marker_info['type']}")

    # ── Scroll & highlight the found marker ──
    sel = f'#content-docx .anno-marker[data-anno-idx="{marker_idx}"]'
    await page.evaluate(f"""() => {{
        const m = document.querySelector('{sel}');
        if (m) {{
            m.scrollIntoView({{block: 'center', behavior: 'smooth'}});
            m.style.outline = '3px solid #e74c3c';
            m.style.boxShadow = '0 0 20px rgba(231,76,60,0.7)';
        }}
    }}""")
    recorder.set_overlay(f"Найден элемент: {marker_label}")
    await page.wait_for_timeout(2000)
    await screenshot(page, "s7_01_found_list_marker")

    # ── Step 2: Click the marker to open context menu ──
    # Use Playwright click (not JS el.click()) to provide real clientX/clientY
    recorder.set_overlay("Открываем контекстное меню элемента (клик)")
    await page.evaluate(f"""() => {{
        const m = document.querySelector('{sel}');
        if (m) {{ m.style.outline = ''; m.style.boxShadow = ''; }}
    }}""")
    try:
        await page.locator(sel).first.click(timeout=5000)
    except Exception as e:
        print(f"[Scene7] Playwright click failed: {e}, trying JS click")
        await page.evaluate(f"""() => {{
            const m = document.querySelector('{sel}');
            if (m) m.click();
        }}""")
    await page.wait_for_timeout(1500)

    # Verify context menu is visible
    # Note: offsetParent is null for fixed/absolute positioned elements, use getBoundingClientRect
    ctx_visible = await page.evaluate("""() => {
        const m = document.getElementById('anno-context-menu');
        if (!m) return false;
        if (m.style.display === 'none') return false;
        const rect = m.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }""")
    await screenshot(page, "s7_02_context_menu")
    print(f"[Scene7] Context menu visible: {ctx_visible}")

    if not ctx_visible:
        recorder.set_overlay("Контекстное меню не открылось")
        await page.wait_for_timeout(2000)
        return

    # ── Step 3: Check if split button is available ──
    split_info = await page.evaluate("""() => {
        const btn = document.getElementById('ctx-split');
        if (!btn) return {exists: false};
        const rect = btn.getBoundingClientRect();
        const vis = btn.style.display !== 'none' && rect.width > 0 && rect.height > 0;
        return {exists: true, visible: vis, text: btn.textContent};
    }""")
    print(f"[Scene7] Split button: {split_info}")

    if not split_info.get("visible"):
        recorder.set_overlay("Кнопка «Разделить» недоступна — ищем другой элемент...")
        await screenshot(page, "s7_03_no_split")
        await page.wait_for_timeout(1500)

        # Close menu
        await page.evaluate("""() => {
            const m = document.getElementById('anno-context-menu');
            if (m) m.style.display = 'none';
        }""")

        # Fallback: try all list markers to find one with split available
        marker_idx = await _find_splittable_marker(page)
        if not marker_idx:
            recorder.set_overlay("Нет элементов для разделения, пропуск...")
            await page.wait_for_timeout(2000)
            return

        fsell = f'#content-docx .anno-marker[data-anno-idx="{marker_idx}"]'
        await page.evaluate(f"""() => {{
            const m = document.querySelector('{fsell}');
            if (m) m.scrollIntoView({{block: 'center'}});
        }}""")
        await page.locator(fsell).first.click(timeout=5000)
        await page.wait_for_timeout(1500)
        await screenshot(page, "s7_03b_fallback_menu")

    # ── Step 4: Click "Разделить" ──
    recorder.set_overlay("Нажимаем «Разделить» для разбиения на отдельные элементы")
    await highlight_and_click(page, "#ctx-split", pause=1.0)
    await page.wait_for_timeout(3000)  # wait for rebuildBadges + syncPdfMarkers

    recorder.set_overlay("Элемент разделён на отдельные части")
    await screenshot(page, "s7_04_after_split")
    await page.wait_for_timeout(2000)

    # ── Step 5: Change split list elements to para ──
    # After split, rebuildBadges() renumbers markers. Re-query.
    list_markers = await page.evaluate("""() => {
        const result = [];
        const markers = document.querySelectorAll('#content-docx .anno-marker[data-anno-idx]');
        for (const m of markers) {
            const label = m.querySelector('.marker-label');
            const text = label ? label.textContent.trim() : '';
            const type = m.getAttribute('data-anno-type') || '';
            if (/list/i.test(type) || /спис/i.test(text)) {
                result.push({
                    idx: m.getAttribute('data-anno-idx'),
                    label: text
                });
            }
        }
        return result;
    }""")
    print(f"[Scene7] List markers after split: {list_markers}")

    changed_count = 0
    for marker in list_markers[:5]:
        idx = marker["idx"]
        label = marker["label"]
        msel = f'#content-docx .anno-marker[data-anno-idx="{idx}"]'

        # Scroll & highlight marker
        await page.evaluate(f"""() => {{
            const m = document.querySelector('{msel}');
            if (m) {{
                m.scrollIntoView({{block: 'center', behavior: 'smooth'}});
                m.style.outline = '3px solid #e74c3c';
                m.style.boxShadow = '0 0 15px rgba(231,76,60,0.6)';
            }}
        }}""")
        recorder.set_overlay(f"Изменяем [{label}] на параграф ({changed_count + 1})")
        await page.wait_for_timeout(800)

        # Click marker via Playwright to open context menu
        await page.evaluate(f"""() => {{
            const m = document.querySelector('{msel}');
            if (m) {{ m.style.outline = ''; m.style.boxShadow = ''; }}
        }}""")
        try:
            await page.locator(msel).first.click(timeout=3000)
        except Exception:
            await page.evaluate(f"() => {{ document.querySelector('{msel}')?.click(); }}")
        await page.wait_for_timeout(1000)

        # Verify context menu opened
        ctx_ok = await page.evaluate("""() => {
            const m = document.getElementById('anno-context-menu');
            if (!m || m.style.display === 'none') return false;
            const rect = m.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        }""")
        if not ctx_ok:
            print(f"[Scene7] Context menu didn't open for marker idx={idx}")
            continue

        # Change type to para
        await page.evaluate("""() => {
            const sel = document.getElementById('ctx-type-select');
            if (sel) {
                sel.value = 'para';
                sel.dispatchEvent(new Event('change', {bubbles: true}));
            }
        }""")
        await page.wait_for_timeout(500)

        # Save (closes menu, triggers rebuildBadges)
        await page.click("#ctx-save")
        await page.wait_for_timeout(1500)

        changed_count += 1
        if changed_count == 1:
            await screenshot(page, "s7_05_first_type_change")

    recorder.set_overlay(f"Разметка изменена: {changed_count} элементов списка -> параграфы")
    await screenshot(page, "s7_06_all_changes_done")
    await page.wait_for_timeout(2000)


async def _find_splittable_marker(page: Page) -> str | None:
    """Click through list markers in the left panel to find one where #ctx-split is visible."""
    all_markers = await page.evaluate("""() => {
        const result = [];
        const markers = document.querySelectorAll('#content-docx .anno-marker[data-anno-idx]');
        for (const m of markers) {
            const label = m.querySelector('.marker-label');
            const text = label ? label.textContent.trim() : '';
            const type = m.getAttribute('data-anno-type') || '';
            if (/list/i.test(type) || /спис/i.test(text)) {
                result.push(m.getAttribute('data-anno-idx'));
            }
        }
        return result;
    }""")

    for idx in all_markers:
        msel = f'#content-docx .anno-marker[data-anno-idx="{idx}"]'
        await page.evaluate(f"""() => {{
            const m = document.querySelector('{msel}');
            if (m) m.scrollIntoView({{block: 'center'}});
        }}""")
        try:
            await page.locator(msel).first.click(timeout=3000)
        except Exception:
            await page.evaluate(f"() => {{ document.querySelector('{msel}')?.click(); }}")
        await page.wait_for_timeout(800)

        split_ok = await page.evaluate("""() => {
            const btn = document.getElementById('ctx-split');
            if (!btn || btn.style.display === 'none') return false;
            const rect = btn.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        }""")
        if split_ok:
            print(f"[Scene7] Found splittable marker: idx={idx}")
            return idx

        # Close menu
        await page.evaluate("""() => {
            const m = document.getElementById('anno-context-menu');
            if (m) m.style.display = 'none';
        }""")

    return None


# ─── Scene 8: Generate by reference ─────────────────────────────────────────

async def scene_8_generate_by_ref(page: Page, recorder: ScreenRecorder) -> None:
    recorder.inject_transition("Шаг 8", "Генерация XML по эталону", duration=2.5)
    recorder.set_overlay("Генерация XML по эталону: применение исправленной разметки")

    # Check if button exists and is visible
    run_loop_btn = await page.query_selector("#run-loop-btn")
    if not run_loop_btn:
        recorder.set_overlay("Кнопка «Форматировать согласно эталону» не найдена")
        await screenshot(page, "s8_no_button")
        await page.wait_for_timeout(3000)
        return

    btn_style = await run_loop_btn.get_attribute("style") or ""
    if "display: none" in btn_style or "display:none" in btn_style:
        recorder.set_overlay("Кнопка скрыта — эталон не активен")
        await page.wait_for_timeout(3000)
        return

    # Highlight and click
    await highlight_and_click(
        page, "#run-loop-btn", recorder,
        label="Нажимаем «Форматировать согласно эталону»",
        pause=2.0,
    )
    await page.wait_for_timeout(1000)

    # Wait for progress bar
    recorder.set_overlay("Выполняется цикл верификации...")
    try:
        await page.wait_for_selector(
            '#loop-progress:not([style*="display: none"])',
            timeout=5000,
        )
    except Exception:
        pass

    # Wait for completion — verify-score badge appears
    try:
        await page.wait_for_function(
            """() => {
                const score = document.getElementById('verify-score');
                return score && score.style.display !== 'none' && score.textContent.trim() !== '';
            }""",
            timeout=180_000,
        )
    except Exception:
        recorder.set_overlay("Ожидание результата...")
        await page.wait_for_timeout(5000)

    await page.wait_for_timeout(2000)

    # Read the score
    score_el = await page.query_selector("#verify-score")
    score_text = ""
    if score_el:
        score_text = (await score_el.text_content() or "").strip()

    if score_text:
        recorder.set_overlay(f"Результат верификации: {score_text}")
    else:
        recorder.set_overlay("Генерация по эталону завершена")

    await screenshot(page, "s8_verification_result")
    await page.wait_for_timeout(4000)

    # Final frame
    recorder.set_overlay("Демонстрация завершена")
    await page.wait_for_timeout(3000)


# ─── Main orchestration ─────────────────────────────────────────────────────

async def main() -> None:
    global MON_LEFT, MON_TOP, MON_W, MON_H

    print(f"[Demo] Starting video recording -> {OUTPUT_VIDEO}")
    print(f"[Demo] Distribution: {DIST_ZIP}")
    print(f"[Demo] Unpack dir: {UNPACK_DIR}")
    print(f"[Demo] FPS: {FPS}")

    # Validate ZIP exists
    if not os.path.isfile(DIST_ZIP):
        dist_dir = os.path.join(PROJECT_ROOT, "dist")
        found = False
        if os.path.isdir(dist_dir):
            for f in os.listdir(dist_dir):
                if f.startswith("word_to_s1000d") and f.endswith(".zip"):
                    print(f"[Demo] Found ZIP: {f}")
                    found = True
                    break
        if not found:
            print(f"[Demo] ERROR: Distribution ZIP not found at {DIST_ZIP}")
            print("[Demo] Run build.bat first to create the distribution.")
            return

    # Ensure output directories exist
    os.makedirs(os.path.dirname(OUTPUT_VIDEO), exist_ok=True)
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    # Detect monitor geometry
    MON_LEFT, MON_TOP, MON_W, MON_H = detect_monitor_geometry(MONITOR_INDEX)
    print(f"[Demo] Monitor {MONITOR_INDEX}: {MON_W}x{MON_H} at ({MON_LEFT},{MON_TOP})")

    # Minimize all windows (Win+D) so the browser will be front and center
    try:
        ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)       # Win down
        ctypes.windll.user32.keybd_event(0x44, 0, 0, 0)       # D down
        ctypes.windll.user32.keybd_event(0x44, 0, 2, 0)       # D up
        ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)       # Win up
        time.sleep(1)
    except Exception:
        pass

    recorder = ScreenRecorder(OUTPUT_VIDEO, fps=FPS, monitor_index=MONITOR_INDEX)
    app_proc = None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=[
                "--start-maximized",
                f"--window-position={MON_LEFT},{MON_TOP}",
                "--disable-infobars",
                "--no-first-run",
            ],
        )
        context = await browser.new_context(
            no_viewport=True,
        )
        page = await context.new_page()

        # Maximize browser window on the target monitor via CDP
        try:
            cdp = await page.context.new_cdp_session(page)
            win_info = await cdp.send("Browser.getWindowForTarget")
            wid = win_info["windowId"]
            # Position on the correct monitor first
            await cdp.send("Browser.setWindowBounds", {
                "windowId": wid,
                "bounds": {"left": MON_LEFT, "top": MON_TOP,
                           "width": MON_W, "height": MON_H,
                           "windowState": "normal"},
            })
            await asyncio.sleep(0.3)
            # Then maximize
            await cdp.send("Browser.setWindowBounds", {
                "windowId": wid,
                "bounds": {"windowState": "maximized"},
            })
            print("[Demo] Browser maximized via CDP")
        except Exception as e:
            print(f"[Demo] Warning: CDP maximize failed: {e}")

        try:
            # Start recording
            recorder.start()
            # Initial title frame
            recorder.inject_transition(
                "Word -> S1000D",
                "Обзор модуля генерации XML",
                duration=3.0,
            )

            # Scene 1: Unpack
            await scene_1_unpack(recorder)

            # Scene 2: Launch & generate
            app_proc = await scene_2_launch_and_generate(page, recorder)

            # Scene 3: TGWeb
            await scene_3_view_tgweb(page, context, recorder)

            # Scene 4: Comparison
            await scene_4_comparison(page, recorder)

            # Scene 5: Reference
            await scene_5_create_reference(page, recorder)

            # Scene 6: Navigation
            await scene_6_navigate(page, recorder)

            # Scene 7: Edit
            await scene_7_edit_markup(page, recorder)

            # Scene 8: Generate by ref
            await scene_8_generate_by_ref(page, recorder)

            # Final transition
            recorder.inject_transition(
                "Спасибо за внимание!",
                "Word -> S1000D Converter",
                duration=3.0,
            )

        except Exception as e:
            print(f"[Demo] ERROR during recording: {e}")
            import traceback
            traceback.print_exc()
            # Save error screenshot
            try:
                await screenshot(page, "ERROR_final")
            except Exception:
                pass
        finally:
            # Stop recording
            recorder.stop()

            # Close browser
            await browser.close()

            # Cleanup app processes
            if app_proc:
                app_proc.terminate()
            cleanup_processes()

    print(f"\n[Demo] Video saved: {OUTPUT_VIDEO}")
    print(f"[Demo] Screenshots saved: {SCREENSHOT_DIR}")
    print("[Demo] Done!")


if __name__ == "__main__":
    asyncio.run(main())
