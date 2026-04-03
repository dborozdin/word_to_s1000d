@echo off
chcp 65001 >nul
cd /d %~dp0
echo Сборка genfld.exe...
pyinstaller --onefile --name genfld --distpath dist --workpath build --specpath . generate_folders.py
echo Копирование файлов в dist...
copy "1.1 DMRL (без разбиения).xls" dist\
xcopy /E /I /Y source_docs dist\source_docs
copy generate_folders.bat dist\
echo Готово. Результат в папке dist\
pause
