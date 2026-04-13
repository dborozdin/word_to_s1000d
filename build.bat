@echo off
chcp 65001 >nul
echo ============================================
echo  Word to S1000D - PyInstaller Build
echo ============================================
echo.

REM Activate venv if present
if exist "venv\Scripts\activate.bat" call venv\Scripts\activate.bat

REM Install PyInstaller if not present
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

REM Write build number from git for frozen mode
echo Writing build number...
for /f %%n in ('git rev-list --count HEAD') do echo %%n> _build_number
echo   _build_number - OK

REM Clean previous builds
echo Cleaning previous build...
if exist "build" rmdir /s /q build
if exist "dist\word_to_s1000d" rmdir /s /q dist\word_to_s1000d

REM Run PyInstaller
echo.
echo Building with PyInstaller...
pyinstaller word_to_s1000d.spec --noconfirm
if errorlevel 1 (
    echo.
    echo BUILD FAILED!
    pause
    exit /b 1
)

REM Copy external files to dist
echo.
echo Copying external files...

set DIST=dist\word_to_s1000d

REM config.ini (user-editable)
copy /y config.ini "%DIST%\config.ini" >nul
echo   config.ini - OK

REM doc_source_29_raw (raw source documents)
xcopy /E /I /Y /Q doc_source_29_raw "%DIST%\doc_source_29_raw" >nul
echo   doc_source_29_raw\ - OK

REM User guide
if not exist "%DIST%\docs" mkdir "%DIST%\docs"
copy /y docs\user_guide.html "%DIST%\docs\user_guide.html" >nul
echo   docs\user_guide.html - OK

REM tg_web (viewer server with binaries, excluding generated XML in suites)
xcopy /E /I /Y /Q tg_web "%DIST%\tg_web" /EXCLUDE:build_exclude.tmp >nul 2>&1
if not exist "%DIST%\tg_web" xcopy /E /I /Y /Q tg_web "%DIST%\tg_web" >nul
REM Clean generated XML from suites (keep empty dir)
if exist "%DIST%\tg_web\suites\66935" (
    del /q "%DIST%\tg_web\suites\66935\*" >nul 2>&1
    for /d %%d in ("%DIST%\tg_web\suites\66935\*") do rmdir /s /q "%%d" >nul 2>&1
)
if not exist "%DIST%\tg_web\suites\66935" mkdir "%DIST%\tg_web\suites\66935"
echo   tg_web\ - OK (suites/66935 cleaned)

REM Create versioned zip archive
echo.
echo Creating zip archive...
for /f %%v in ('python -c "from version import __version__; print(__version__)"') do set VERSION=%%v
set ZIP_NAME=word_to_s1000d_%VERSION%.zip
REM Remove old zip with same name if exists
if exist "dist\%ZIP_NAME%" del /q "dist\%ZIP_NAME%"
cd dist
powershell -Command "Compress-Archive -Path 'word_to_s1000d\*' -DestinationPath '%ZIP_NAME%' -Force"
cd ..
echo   dist\%ZIP_NAME% - OK

echo.
echo ============================================
echo  Build complete!  v%VERSION%
echo  Output: %DIST%\
echo  Archive: dist\%ZIP_NAME%
echo ============================================
echo.
echo  word_to_s1000d.exe  - Launch comparison app
echo  config.ini          - Configuration (editable)
echo  doc_source_29_raw\  - Source documents
echo  docs\user_guide.html - User guide
echo  tg_web\             - TG Web viewer
echo  _internal\          - Bundled dependencies
echo ============================================
pause
