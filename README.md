# Punto de Venta (práctica)

Flask + SQLite. Flask 3.1.1 está instalado sin root extrayendo los .deb de Debian:

```bash
cd ~/punto-venta
PYTHONPATH=~/pv-flask/usr/lib/python3/dist-packages python3 app.py
```

Abre http://127.0.0.1:5000 — la BD `pos.db` se crea y siembra sola al primer arranque.

## En red local (tablet)

```bash
~/punto-venta/arrancar.sh
```

Sirve en todas las interfaces con waitress (sin modo debug). En la tablet abre
`http://<IP-de-esta-máquina>:5000` — mira la IP con `ip -4 addr show scope global`.
Pide usuario `pos` y la clave definida en `app.py` (`USUARIO`/`CLAVE`).

## En Windows

1. Instala [Python](https://www.python.org/downloads/) marcando **"Add python.exe to PATH"**, y [Git](https://git-scm.com/download/win).
2. En PowerShell o CMD:

```bat
git clone https://github.com/CrisTlalmis/POS-Proy.git
cd POS-Proy
iniciar.bat
```

`iniciar.bat` crea el entorno virtual e instala dependencias la primera vez;
después basta doble clic sobre él. Abre http://127.0.0.1:5000 (en red local,
misma instrucción de arriba; Windows preguntará por el firewall la primera vez:
permite acceso en redes privadas). La BD `pos.db` se crea y siembra sola.
