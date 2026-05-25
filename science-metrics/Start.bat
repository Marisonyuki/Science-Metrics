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

:: Устанавливаем зависимости
echo [1/3] Установка зависимостей...
pip install -r requirements.txt

:: Запускаем сервер
echo [2/3] Запуск сервера...
start "Science Metrics Server" cmd /k "python app.py"

:: Ждём запуска
echo [3/3] Ожидание запуска сервера...
timeout /t 5 /nobreak >nul

:: Открываем браузер
start http://127.0.0.1:5000

echo.
echo ===============================================
echo    Сервер запущен: http://127.0.0.1:5000
echo    PostgreSQL БД: science_metrics
echo ===============================================

exit