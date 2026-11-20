@echo off
echo Starting RoadCare AI
echo.

if not exist .env (
    echo [!] .env file not found.
    echo     Copy .env.example to .env and set SECRET_KEY and ADMIN_PASSWORD first.
    echo.
    pause
    exit /b 1
)

echo Citizen Portal:  http://127.0.0.1:5000
echo Admin Dashboard: http://127.0.0.1:5000/admin/login
echo.
py app.py
pause