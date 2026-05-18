@echo off
title Science Metrics - Система анализа научной активности
color 0A

echo ===============================================
echo    Система анализа научной активности
echo ===============================================
echo.

:: Проверяем Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не найден!
    pause
    exit /b 1
)

:: Проверяем app.py
if not exist "app.py" (
    echo [ОШИБКА] Файл app.py не найден!
    pause
    exit /b 1
)

:: Запускаем сервер
echo Запуск сервера...
start "Science Metrics Server" cmd /c "python app.py & pause"

:: Ждём 10 секунд (серверу нужно время для инициализации)
echo Ожидание запуска сервера...
timeout /t 10 /nobreak >nul

:: Открываем браузер
echo Открытие браузера...
start http://localhost:5000

echo.
echo ===============================================
echo    Сервер запущен: http://localhost:5000
echo    Для остановки закройте окно "Science Metrics Server"
echo ===============================================
echo.

pause