@echo off
rem Punto de Venta — crea el entorno la primera vez y arranca el servidor.
cd /d "%~dp0"
if not exist .venv (
  echo Creando entorno virtual...
  python -m venv .venv || goto :error
  call .venv\Scripts\activate.bat || goto :error
  pip install -r requirements.txt || goto :error
) else (
  call .venv\Scripts\activate.bat
)
python app.py
goto :eof
:error
echo Fallo: revisa que Python este instalado y en el PATH.
pause
