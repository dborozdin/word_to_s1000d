@echo off
chcp 65001 >nul
if "%~1"=="" (
    "%~dp0\generate_folders.exe" "%~dp0\1.1 DMRL (без разбиения).xls"
) else (
    "%~dp0\generate_folders.exe" "%~1"
)
pause
