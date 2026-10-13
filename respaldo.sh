#!/bin/sh
# Punto de Venta — respaldo diario de la base de datos.
# Guarda una copia consistente en respaldo-pos-YYYYMMDD.db y conserva
# solo los últimos 60. Instalar con respaldo-install.sh (Linux) o
# autostart-backup.bat (Windows).
cd "$(dirname "$0")" || exit 1
salida="respaldo-pos-$(date +%Y%m%d).db"
sqlite3 pos.db ".backup '$salida'" || exit 1
ls -1t respaldo-pos-*.db 2>/dev/null | tail -n +61 | xargs -r rm --
