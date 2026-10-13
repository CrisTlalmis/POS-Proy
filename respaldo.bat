@echo off
rem Punto de Venta — respaldo diario de la base de datos (Windows).
rem Copia consistente a respaldo-pos-YYYYMMDD.db y conserva los ultimos 60.
cd /d "%~dp0"
set salida=respaldo-pos-%date:~6,4%%date:~3,2%%date:~0,2%.db
.venv\Scripts\python.exe -c "import sqlite3,sys; sqlite3.connect('pos.db').execute(\"VACUUM INTO '%salida%'\")" || exit /b 1
forfiles /m respaldo-pos-*.db /d -60 /c "cmd /c del @path" 2>nul
