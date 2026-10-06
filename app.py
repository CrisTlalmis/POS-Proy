"""Punto de Venta — Flask + SQLite (práctica)."""
import sqlite3
from datetime import date

from flask import (Flask, Response, g, flash, jsonify, redirect,
                   render_template, request, send_file, url_for)

app = Flask(__name__)
app.secret_key = "pos-practica"
DB = "pos.db"
# Recarga plantillas/estáticos al editarlos: la BD ya no vive en modo debug.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Acceso para la tablet: cámbialos aquí. Cualquiera en el WiFi los necesitará.
USUARIO = "pos"
CLAVE = "pos2026"


@app.before_request
def pedir_clave():
    auth = request.authorization
    if not auth or auth.username != USUARIO or auth.password != CLAVE:
        return Response("Acceso requiere clave", 401,
                        {"WWW-Authenticate": 'Basic realm="POS"'})


# ---------- base de datos ----------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


app.teardown_appcontext(close_db)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS productos (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre       TEXT NOT NULL,
  precio       INTEGER NOT NULL CHECK (precio >= 0),
  stock        REAL NOT NULL DEFAULT 0 CHECK (stock >= 0),
  stock_minimo REAL NOT NULL DEFAULT 5 CHECK (stock_minimo >= 0),
  unidad       TEXT NOT NULL DEFAULT 'unidad'
);
CREATE TABLE IF NOT EXISTS movimientos (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha            TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  producto_id      INTEGER NOT NULL REFERENCES productos(id),
  tipo             TEXT NOT NULL CHECK (tipo IN ('entrada', 'salida', 'ajuste')),
  cantidad         REAL NOT NULL CHECK (cantidad > 0),
  stock_resultante REAL NOT NULL,
  nota             TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ventas (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  total       INTEGER NOT NULL,
  estado      TEXT NOT NULL DEFAULT 'activa'
              CHECK (estado IN ('activa', 'cancelada')),
  metodo_pago TEXT NOT NULL DEFAULT 'efectivo'
              CHECK (metodo_pago IN ('efectivo', 'transferencia', 'tarjeta', 'fiado')),
  cliente_id  INTEGER REFERENCES clientes(id)
);
CREATE TABLE IF NOT EXISTS clientes (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre TEXT NOT NULL,
  saldo  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fiado_movs (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha            TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  cliente_id       INTEGER NOT NULL REFERENCES clientes(id),
  tipo             TEXT NOT NULL CHECK (tipo IN ('cargo', 'abono', 'cancelacion')),
  monto            INTEGER NOT NULL CHECK (monto > 0),
  saldo_resultante INTEGER NOT NULL,
  nota             TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS venta_detalles (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  venta_id        INTEGER NOT NULL REFERENCES ventas(id),
  producto_id     INTEGER NOT NULL REFERENCES productos(id),
  cantidad        REAL NOT NULL CHECK (cantidad > 0),
  precio_unitario INTEGER NOT NULL
);
"""

# Precios en centavos enteros: se capturan en pesos y se muestran con |dinero.
SEED = [
    ("Coca-Cola 600ml", 1800, 50, "unidad"), ("Sabritas", 1600, 50, "unidad"),
    ("Agua 1L", 1200, 50, "unidad"), ("Pan dulce", 900, 50, "unidad"),
    ("Leche 1L", 2600, 50, "unidad"), ("Huevo kg", 4800, 50, "kg"),
    ("Arroz kg", 2200, 50, "kg"), ("Frijol kg", 3000, 50, "kg"),
]


def init_db():
    db = get_db()
    db.executescript(ESQUEMA)
    # Migraciones para BDs anteriores; si la columna ya existe, no hace nada.
    # El backfill a 50 piezas corre una sola vez, junto con el ALTER de stock.
    pendiente_commit = False
    try:
        db.execute(
            "ALTER TABLE productos ADD COLUMN stock INTEGER NOT NULL DEFAULT 0"
            " CHECK (stock >= 0)"
        )
        db.execute("UPDATE productos SET stock = 50 WHERE stock = 0")
        pendiente_commit = True
    except sqlite3.OperationalError:
        pass
    try:
        db.execute(
            "ALTER TABLE productos ADD COLUMN stock_minimo INTEGER NOT NULL DEFAULT 5"
            " CHECK (stock_minimo >= 0)"
        )
        pendiente_commit = True
    except sqlite3.OperationalError:
        pass
    try:
        db.execute(
            "ALTER TABLE productos ADD COLUMN unidad TEXT NOT NULL DEFAULT 'unidad'"
        )
        # Solo los productos cuyo nombre trae "kg" se venden a granel.
        db.execute("UPDATE productos SET unidad = 'kg' WHERE nombre LIKE '%kg'")
        pendiente_commit = True
    except sqlite3.OperationalError:
        pass
    if pendiente_commit:
        db.commit()
    # Centavos enteros + estado/metodo de pago en ventas (una sola vez por BD).
    # Las columnas viejas quedan con afinidad REAL pero guardan centavos exactos.
    if db.execute("PRAGMA user_version").fetchone()[0] < 1:
        db.execute(
            "UPDATE productos SET precio = CAST(ROUND(precio * 100) AS INTEGER)"
        )
        db.execute("UPDATE ventas SET total = CAST(ROUND(total * 100) AS INTEGER)")
        db.execute(
            "UPDATE venta_detalles"
            " SET precio_unitario = CAST(ROUND(precio_unitario * 100) AS INTEGER)"
        )
        try:
            db.execute(
                "ALTER TABLE ventas ADD COLUMN estado TEXT NOT NULL DEFAULT 'activa'"
            )
        except sqlite3.OperationalError:
            pass
        try:
            db.execute(
                "ALTER TABLE ventas ADD COLUMN metodo_pago TEXT NOT NULL"
                " DEFAULT 'efectivo' CHECK (metodo_pago IN"
                " ('efectivo', 'transferencia', 'tarjeta'))"
            )
        except sqlite3.OperationalError:
            pass
        db.execute("PRAGMA user_version = 1")
        db.commit()
    # Fiado: reconstruye ventas con cliente_id y 'fiado' en el CHECK de
    # metodo_pago (SQLite no puede extender un CHECK de una columna ALTERada).
    if db.execute("PRAGMA user_version").fetchone()[0] < 2:
        db.executescript("""
        PRAGMA legacy_alter_table = ON;
        CREATE TABLE ventas_nueva (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          fecha       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
          total       INTEGER NOT NULL,
          estado      TEXT NOT NULL DEFAULT 'activa'
                      CHECK (estado IN ('activa', 'cancelada')),
          metodo_pago TEXT NOT NULL DEFAULT 'efectivo'
                      CHECK (metodo_pago IN ('efectivo', 'transferencia', 'tarjeta', 'fiado')),
          cliente_id  INTEGER REFERENCES clientes(id)
        );
        INSERT INTO ventas_nueva (id, fecha, total, estado, metodo_pago)
            SELECT id, fecha, total, estado, metodo_pago FROM ventas;
        DROP TABLE ventas;
        ALTER TABLE ventas_nueva RENAME TO ventas;
        PRAGMA user_version = 2;
        """)
    if db.execute("SELECT 1 FROM productos LIMIT 1").fetchone() is None:
        db.executemany(
            "INSERT INTO productos (nombre, precio, stock, unidad)"
            " VALUES (?, ?, ?, ?)", SEED
        )
        db.commit()


# ---------- helpers ----------

def validar_producto(form):
    """Devuelve (nombre, precio_en_centavos, stock, stock_minimo, unidad) o None."""
    nombre = form.get("nombre", "").strip()
    unidad = form.get("unidad", "unidad")
    try:
        precio = float(form.get("precio", ""))
        stock = float(form.get("stock", 0))
        stock_minimo = float(form.get("stock_minimo", 5))
    except ValueError:
        return None
    if not nombre or unidad not in ("unidad", "kg"):
        return None
    if precio < 0 or stock < 0 or stock_minimo < 0:
        return None
    return nombre, round(precio * 100), round(stock, 3), round(stock_minimo, 3), unidad


def fmt_cantidad(cant, unidad):
    """2 → '2'; 1.5 con 'kg' → '1.5 kg'; 0.25 con 'kg' → '0.25 kg'."""
    if unidad != "kg":
        return str(int(cant))
    return f"{cant:.3f}".rstrip("0").rstrip(".") + " kg"


def dinero(centavos):
    """2001 → '$20.01'; tolera float de BDs heredadas."""
    return f"${centavos / 100:,.2f}"


app.template_filter("dinero")(dinero)


# ---------- venta ----------

@app.route("/")
def venta():
    db = get_db()
    productos = db.execute("SELECT * FROM productos ORDER BY nombre").fetchall()
    clientes = db.execute("SELECT id, nombre FROM clientes ORDER BY nombre").fetchall()
    return render_template("venta.html", productos=productos, clientes=clientes)


@app.post("/api/ventas")
def crear_venta():
    datos = request.get_json(silent=True)
    items = datos.get("items") if isinstance(datos, dict) else None
    if not isinstance(items, list) or not items:
        return jsonify(error="La venta no tiene artículos"), 400

    limpios = []
    for it in items:
        try:
            pid = int(it["producto_id"])
            cant = float(it["cantidad"])
        except (KeyError, TypeError, ValueError):
            return jsonify(error="Artículo inválido"), 400
        limpios.append((pid, cant))

    db = get_db()
    metodo = datos.get("metodo_pago", "efectivo")
    if metodo not in ("efectivo", "transferencia", "tarjeta", "fiado"):
        return jsonify(error="Método de pago inválido"), 400
    cliente = None
    if metodo == "fiado":
        cliente_id = datos.get("cliente_id")
        if isinstance(cliente_id, int):
            cliente = db.execute(
                "SELECT id, nombre, saldo FROM clientes WHERE id = ?",
                (cliente_id,),
            ).fetchone()
        if cliente is None:
            return jsonify(error="El fiado requiere un cliente válido"), 400

    # Los precios y el stock se leen de la BD, nunca del cliente.
    lineas = []
    total = 0  # centavos
    for pid, cant in limpios:
        row = db.execute(
            "SELECT nombre, precio, stock, unidad FROM productos WHERE id = ?", (pid,)
        ).fetchone()
        if row is None:
            return jsonify(error=f"Producto {pid} no existe"), 400
        if row["unidad"] == "unidad":
            if not cant.is_integer() or cant < 1:
                return jsonify(
                    error=f"La cantidad de {row['nombre']} debe ser entera"
                ), 400
        else:
            cant = round(cant, 3)
            if not cant > 0:
                return jsonify(error="La cantidad debe ser mayor a 0"), 400
        if row["stock"] < cant:
            return jsonify(
                error=f"Stock insuficiente de {row['nombre']} (quedan {row['stock']})"
            ), 400
        lineas.append((pid, row["precio"], cant))
        total += round(row["precio"] * cant)

    with db:
        venta_id = db.execute(
            "INSERT INTO ventas (total, metodo_pago, cliente_id) VALUES (?, ?, ?)",
            (total, metodo, cliente["id"] if cliente else None),
        ).lastrowid
        if cliente:
            saldo = cliente["saldo"] + total
            db.execute("UPDATE clientes SET saldo = ? WHERE id = ?",
                       (saldo, cliente["id"]))
            db.execute(
                "INSERT INTO fiado_movs (cliente_id, tipo, monto,"
                " saldo_resultante, nota) VALUES (?, 'cargo', ?, ?, ?)",
                (cliente["id"], total, saldo, f"Venta #{venta_id}"),
            )
        db.executemany(
            "INSERT INTO venta_detalles (venta_id, producto_id, cantidad, precio_unitario)"
            " VALUES (?, ?, ?, ?)",
            [(venta_id, pid, cant, precio) for pid, precio, cant in lineas],
        )
        for pid, _, cant in lineas:
            stock = db.execute(
                "SELECT stock FROM productos WHERE id = ?", (pid,)
            ).fetchone()["stock"]
            restante = stock - cant
            db.execute("UPDATE productos SET stock = ? WHERE id = ?", (restante, pid))
            db.execute(
                "INSERT INTO movimientos (producto_id, tipo, cantidad, stock_resultante, nota)"
                " VALUES (?, 'salida', ?, ?, ?)",
                (pid, cant, restante, f"Venta #{venta_id}"),
            )
    # Aviso inmediato si la venta dejó un producto bajo su mínimo.
    alertas = []
    for pid, _, _ in lineas:
        r = db.execute(
            "SELECT nombre, stock, stock_minimo, unidad FROM productos WHERE id = ?",
            (pid,),
        ).fetchone()
        if r["stock"] <= r["stock_minimo"]:
            alertas.append(
                f"{r['nombre']} quedó en {fmt_cantidad(r['stock'], r['unidad'])}"
                f" (mínimo {fmt_cantidad(r['stock_minimo'], r['unidad'])})"
            )
    return jsonify(venta_id=venta_id, total=total / 100, alertas=alertas), 201


# ---------- productos ----------

@app.route("/productos", methods=["GET", "POST"])
def productos():
    db = get_db()
    if request.method == "POST":
        datos = validar_producto(request.form)
        if datos is None:
            flash("Precio o stock inválido", "error")
        else:
            nombre, precio, stock, stock_minimo, unidad = datos
            cur = db.execute(
                "INSERT INTO productos (nombre, precio, stock, stock_minimo, unidad)"
                " VALUES (?, ?, ?, ?, ?)",
                datos,
            )
            if stock > 0:  # el stock inicial queda visible en el kardex
                db.execute(
                    "INSERT INTO movimientos (producto_id, tipo, cantidad,"
                    " stock_resultante, nota)"
                    " VALUES (?, 'entrada', ?, ?, 'Alta de producto')",
                    (cur.lastrowid, stock, stock),
                )
            db.commit()
            flash("Producto agregado")
        return redirect(url_for("productos"))
    filas = db.execute("SELECT * FROM productos ORDER BY nombre").fetchall()
    return render_template("productos.html", productos=filas)


@app.post("/productos/<int:producto_id>/editar")
def editar_producto(producto_id):
    db = get_db()
    datos = validar_producto(request.form)
    if datos is None:
        flash("Precio o stock inválido", "error")
    else:
        row = db.execute(
            "SELECT stock FROM productos WHERE id = ?", (producto_id,)
        ).fetchone()
        if row is None:
            flash("Producto no encontrado", "error")
            return redirect(url_for("productos"))
        nombre, precio, stock, stock_minimo, unidad = datos
        with db:
            db.execute(
                "UPDATE productos SET nombre = ?, precio = ?, stock = ?,"
                " stock_minimo = ?, unidad = ? WHERE id = ?",
                (nombre, precio, stock, stock_minimo, unidad, producto_id),
            )
            if stock != row["stock"]:
                db.execute(
                    "INSERT INTO movimientos (producto_id, tipo, cantidad,"
                    " stock_resultante, nota) VALUES (?, 'ajuste', ?, ?, ?)",
                    (producto_id, abs(stock - row["stock"]), stock,
                     "Ajuste manual (edición)"),
                )
        flash("Producto actualizado")
    return redirect(url_for("productos"))


@app.post("/productos/<int:producto_id>/eliminar")
def eliminar_producto(producto_id):
    db = get_db()
    vendido = db.execute(
        "SELECT 1 FROM venta_detalles WHERE producto_id = ? LIMIT 1", (producto_id,)
    ).fetchone()
    if vendido:
        flash("No se puede eliminar: ya tiene ventas registradas", "error")
    else:
        db.execute("DELETE FROM productos WHERE id = ?", (producto_id,))
        db.commit()
        flash("Producto eliminado")
    return redirect(url_for("productos"))


# ---------- inventario ----------

@app.get("/inventario")
def inventario():
    # ponytail: últimos 200 movimientos; paginar si el kardex crece años
    rows = get_db().execute(
        "SELECT m.fecha, m.tipo, m.cantidad, m.stock_resultante, m.nota, p.nombre,"
        " p.unidad"
        " FROM movimientos m JOIN productos p ON p.id = m.producto_id"
        " ORDER BY m.id DESC LIMIT 200"
    ).fetchall()
    movimientos = [
        dict(r) | {
            "cantidad_txt": fmt_cantidad(r["cantidad"], r["unidad"]),
            "stock_resultante_txt": fmt_cantidad(r["stock_resultante"], r["unidad"]),
        }
        for r in rows
    ]
    return render_template("inventario.html", movimientos=movimientos)


@app.post("/productos/<int:producto_id>/movimiento")
def registrar_movimiento(producto_id):
    db = get_db()
    tipo = request.form.get("tipo")
    try:
        cantidad = float(request.form.get("cantidad", ""))
    except ValueError:
        cantidad = 0
    if tipo not in ("entrada", "salida"):
        flash("Movimiento inválido", "error")
        return redirect(url_for("productos"))
    row = db.execute(
        "SELECT stock, unidad FROM productos WHERE id = ?", (producto_id,)
    ).fetchone()
    if row is None:
        flash("Producto no encontrado", "error")
        return redirect(url_for("productos"))
    if row["unidad"] == "unidad":
        if not cantidad.is_integer() or cantidad < 1:
            flash("Movimiento inválido", "error")
            return redirect(url_for("productos"))
    else:
        cantidad = round(cantidad, 3)
        if not cantidad > 0:
            flash("Movimiento inválido", "error")
            return redirect(url_for("productos"))
    restante = row["stock"] + (cantidad if tipo == "entrada" else -cantidad)
    if restante < 0:
        flash(f"Stock insuficiente: solo hay {row['stock']}", "error")
        return redirect(url_for("productos"))
    with db:
        db.execute("UPDATE productos SET stock = ? WHERE id = ?", (restante, producto_id))
        db.execute(
            "INSERT INTO movimientos (producto_id, tipo, cantidad, stock_resultante, nota)"
            " VALUES (?, ?, ?, ?, ?)",
            (producto_id, tipo, cantidad, restante,
             request.form.get("nota", "").strip()),
        )
    flash("Movimiento registrado")
    return redirect(url_for("productos"))


# ---------- fiado ----------

@app.route("/fiado", methods=["GET", "POST"])
def fiado():
    db = get_db()
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        if nombre:
            db.execute("INSERT INTO clientes (nombre, saldo) VALUES (?, 0)", (nombre,))
            db.commit()
            flash("Cliente agregado")
        else:
            flash("Nombre inválido", "error")
        return redirect(url_for("fiado"))
    clientes = db.execute("SELECT * FROM clientes ORDER BY nombre").fetchall()
    rows = db.execute(
        "SELECT f.fecha, f.tipo, f.monto, f.saldo_resultante, f.nota, c.nombre"
        " FROM fiado_movs f JOIN clientes c ON c.id = f.cliente_id"
        " ORDER BY f.id DESC LIMIT 200"
    ).fetchall()
    return render_template("fiado.html", clientes=clientes,
                           movimientos=[dict(r) for r in rows])


def _cliente_o_flash(cliente_id):
    """Devuelve el cliente o None tras poner un flash de error."""
    db = get_db()
    cliente = db.execute(
        "SELECT id, nombre, saldo FROM clientes WHERE id = ?", (cliente_id,)
    ).fetchone()
    if cliente is None:
        flash("Cliente no encontrado", "error")
    return cliente


def _monto_centavos(form):
    """Pesos del formulario a centavos enteros > 0, o None."""
    try:
        monto = round(float(form.get("monto", "")) * 100)
    except ValueError:
        return None
    return monto if monto > 0 else None


@app.post("/clientes/<int:cliente_id>/cargo")
def cargar_fiado(cliente_id):
    cliente = _cliente_o_flash(cliente_id)
    monto = _monto_centavos(request.form)
    if cliente and monto:
        with get_db() as db:
            saldo = cliente["saldo"] + monto
            db.execute("UPDATE clientes SET saldo = ? WHERE id = ?",
                       (saldo, cliente_id))
            db.execute(
                "INSERT INTO fiado_movs (cliente_id, tipo, monto,"
                " saldo_resultante, nota) VALUES (?, 'cargo', ?, ?, ?)",
                (cliente_id, monto, saldo, request.form.get("nota", "").strip()),
            )
        flash(f"Fiado de {dinero(monto)} a {cliente['nombre']}")
    elif not monto:
        flash("Monto inválido", "error")
    return redirect(url_for("fiado"))


@app.post("/clientes/<int:cliente_id>/abonar")
def abonar_fiado(cliente_id):
    cliente = _cliente_o_flash(cliente_id)
    monto = _monto_centavos(request.form)
    if cliente and monto:
        with get_db() as db:
            saldo = cliente["saldo"] - monto
            db.execute("UPDATE clientes SET saldo = ? WHERE id = ?",
                       (saldo, cliente_id))
            db.execute(
                "INSERT INTO fiado_movs (cliente_id, tipo, monto,"
                " saldo_resultante, nota) VALUES (?, 'abono', ?, ?, ?)",
                (cliente_id, monto, saldo, request.form.get("nota", "").strip()),
            )
        flash(f"Abono de {dinero(monto)} de {cliente['nombre']}")
    elif not monto:
        flash("Monto inválido", "error")
    return redirect(url_for("fiado"))


# ---------- historial y ticket ----------

@app.route("/historial")
def historial():
    db = get_db()
    ventas = db.execute(
        "SELECT v.id, v.fecha, v.total, v.estado, v.metodo_pago, c.nombre AS cliente"
        " FROM ventas v LEFT JOIN clientes c ON c.id = v.cliente_id"
        " ORDER BY v.id DESC LIMIT 200"
    ).fetchall()
    hoy = db.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS total,"
        " COALESCE(SUM(CASE WHEN metodo_pago = 'efectivo' THEN total END), 0)"
        "   AS efectivo,"
        " COALESCE(SUM(CASE WHEN metodo_pago = 'transferencia' THEN total END), 0)"
        "   AS transferencia,"
        " COALESCE(SUM(CASE WHEN metodo_pago = 'tarjeta' THEN total END), 0)"
        "   AS tarjeta,"
        " COALESCE(SUM(CASE WHEN metodo_pago = 'fiado' THEN total END), 0)"
        "   AS fiado"
        " FROM ventas"
        " WHERE date(fecha) = date('now', 'localtime') AND estado = 'activa'"
    ).fetchone()
    rows = db.execute(
        "SELECT p.nombre, p.unidad, SUM(d.cantidad) AS vendidos,"
        " SUM(d.cantidad * d.precio_unitario) AS ingreso"
        " FROM venta_detalles d"
        " JOIN ventas v ON v.id = d.venta_id AND v.estado = 'activa'"
        " JOIN productos p ON p.id = d.producto_id"
        " GROUP BY p.id ORDER BY vendidos DESC LIMIT 5"
    ).fetchall()
    mas_vendidos = [
        dict(r) | {"vendidos_txt": fmt_cantidad(r["vendidos"], r["unidad"])}
        for r in rows
    ]
    return render_template("historial.html", ventas=ventas, hoy=hoy,
                           mas_vendidos=mas_vendidos)


@app.post("/ventas/<int:venta_id>/cancelar")
def cancelar_venta(venta_id):
    db = get_db()
    venta = db.execute(
        "SELECT fecha, estado FROM ventas WHERE id = ?", (venta_id,)
    ).fetchone()
    if venta is None:
        flash("Venta no encontrada", "error")
        return redirect(url_for("historial"))
    if venta["estado"] != "activa":
        flash("Esa venta ya está cancelada", "error")
    elif venta["fecha"][:10] != date.today().isoformat():
        flash("Solo se pueden cancelar ventas del día", "error")
    else:
        detalles = db.execute(
            "SELECT producto_id, cantidad FROM venta_detalles WHERE venta_id = ?",
            (venta_id,),
        ).fetchall()
        venta2 = db.execute(
            "SELECT total, cliente_id FROM ventas WHERE id = ?", (venta_id,)
        ).fetchone()
        cliente = (
            db.execute(
                "SELECT id, nombre, saldo FROM clientes WHERE id = ?",
                (venta2["cliente_id"],),
            ).fetchone()
            if venta2["cliente_id"]
            else None
        )
        with db:
            for d in detalles:
                stock = db.execute(
                    "SELECT stock FROM productos WHERE id = ?", (d["producto_id"],)
                ).fetchone()["stock"]
                restante = stock + d["cantidad"]
                db.execute(
                    "UPDATE productos SET stock = ? WHERE id = ?",
                    (restante, d["producto_id"]),
                )
                db.execute(
                    "INSERT INTO movimientos (producto_id, tipo, cantidad,"
                    " stock_resultante, nota)"
                    " VALUES (?, 'entrada', ?, ?, ?)",
                    (d["producto_id"], d["cantidad"], restante,
                     f"Cancelación venta #{venta_id}"),
                )
            if cliente:
                saldo = cliente["saldo"] - venta2["total"]
                db.execute("UPDATE clientes SET saldo = ? WHERE id = ?",
                           (saldo, cliente["id"]))
                db.execute(
                    "INSERT INTO fiado_movs (cliente_id, tipo, monto,"
                    " saldo_resultante, nota) VALUES (?, 'cancelacion', ?, ?, ?)",
                    (cliente["id"], venta2["total"], saldo,
                     f"Cancelación venta #{venta_id}"),
                )
            db.execute(
                "UPDATE ventas SET estado = 'cancelada' WHERE id = ?", (venta_id,)
            )
        flash(f"Venta #{venta_id} cancelada y stock repuesto")
    return redirect(url_for("ticket", venta_id=venta_id))


@app.route("/ticket/<int:venta_id>")
def ticket(venta_id):
    db = get_db()
    venta = db.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
    if venta is None:
        flash("Venta no encontrada", "error")
        return redirect(url_for("historial"))
    rows = db.execute(
        "SELECT d.cantidad, d.precio_unitario, p.nombre, p.unidad"
        " FROM venta_detalles d JOIN productos p ON p.id = d.producto_id"
        " WHERE d.venta_id = ? ORDER BY d.id",
        (venta_id,),
    ).fetchall()
    detalles = [
        dict(r) | {
            "cantidad_txt": fmt_cantidad(r["cantidad"], r["unidad"]),
            "linea": round(r["cantidad"] * r["precio_unitario"]),
        }
        for r in rows
    ]
    cliente = None
    if venta["cliente_id"]:
        cliente = db.execute(
            "SELECT nombre FROM clientes WHERE id = ?", (venta["cliente_id"],)
        ).fetchone()["nombre"]
    return render_template("ticket.html", venta=venta, detalles=detalles,
                           hoy=date.today().isoformat(), cliente=cliente)


@app.get("/respaldo")
def respaldo():
    destino = f"respaldo-pos-{date.today().isoformat()}.db"
    with sqlite3.connect(DB) as src, sqlite3.connect(destino) as dst:
        src.backup(dst)
    return send_file(destino, as_attachment=True)


with app.app_context():
    init_db()  # corre también bajo `python3 -m waitress`, no solo __main__

if __name__ == "__main__":
    # Servidor de producción en toda la red local (para la tablet).
    # Sin modo debug: el depurador de Flask permitiría ejecutar código.
    from waitress import serve
    serve(app, host="0.0.0.0", port=5000, threads=8)
