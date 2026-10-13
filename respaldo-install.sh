# Punto de Venta — respaldo diario en Linux.
# Instalar una sola vez (crea el cron del usuario, 11:30 AM):
#   (crontab -l 2>/dev/null; echo "30 11 * * * $HOME/punto-venta/respaldo.sh") | crontab -
# Para quitarlo: crontab -e y borrar la linea.
