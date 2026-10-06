# Punto de Venta (práctica)

Flask + SQLite. Flask 3.1.1 está instalado sin root extrayendo los .deb de Debian:

```bash
cd ~/punto-venta
PYTHONPATH=~/pv-flask/usr/lib/python3/dist-packages python3 app.py
```

Abre http://127.0.0.1:5000 — la BD `pos.db` se crea y siembra sola al primer arranque.
