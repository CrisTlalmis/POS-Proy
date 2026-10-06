#!/bin/sh
# Punto de Venta — servidor para toda la red local (tablet incluida).
cd "$(dirname "$0")" || exit 1
PYTHONPATH="$HOME/pv-flask/usr/lib/python3/dist-packages" exec python3 -m waitress --host=0.0.0.0 --port=5000 --threads=8 app:app
