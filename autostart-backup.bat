@echo off
rem Instala el respaldo diario (11:30 AM, tarea programada "PuntoVentaRespaldo").
rem Ejecutar una sola vez, despues del primer iniciar.bat.
cd /d "%~dp0"
schtasks /create /tn "PuntoVentaRespaldo" /tr "\"%~dp0respaldo.bat\"" /sc daily /st 11:30 /rl limited /f || goto :error
echo Listo: respaldo diario a las 11:30 en esta carpeta.
echo (Para quitarlo: schtasks /delete /tn "PuntoVentaRespaldo" /f)
pause
goto :eof
:error
echo Fallo al crear la tarea programada.
pause
