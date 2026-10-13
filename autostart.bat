@echo off
rem Punto de Venta — instala el arranque automatico al iniciar sesion.
rem Ejecutar una sola vez. Crea una tarea programada que lanza iniciar.bat
rem minimizado en cada inicio de sesion de este usuario.
cd /d "%~dp0"
schtasks /create /tn "PuntoVenta" /tr "cmd /c start /min \"\" \"%~dp0iniciar.bat\"" /sc onlogon /rl limited /f || goto :error
echo Listo: el servidor arrancara solo cada vez que inicies sesion.
echo (Para quitarlo: schtasks /delete /tn "PuntoVenta" /f)
pause
goto :eof
:error
echo Fallo al crear la tarea programada.
pause
