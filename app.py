"""Punto de Venta — Flask + SQLite (práctica)."""
import sqlite3

from flask import (Flask, g, flash, jsonify, redirect, render_template,
                   request, url_for)

app = Flask(__name__)
app.secret_key = "pos-practica"
DB = "pos.db"


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
  precio       REAL NOT NULL CHECK (precio >= 0),
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
  id    INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  total REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS venta_detalles (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  venta_id        INTEGER NOT NULL REFERENCES ventas(id),
  producto_id     INTEGER NOT NULL REFERENCES productos(id),
  cantidad        REAL NOT NULL CHECK (cantidad > 0),
  precio_unitario REAL NOT NULL
);
"""

SEED = [
    ("Coca-Cola 600ml", 18.00, 50, "unidad"), ("Sabritas", 16.00, 50, "unidad"),
    ("Agua 1L", 12.00, 50, "unidad"), ("Pan dulce", 9.00, 50, "unidad"),
    ("Leche 1L", 26.00, 50, "unidad"), ("Huevo kg", 48.00, 50, "kg"),
    ("Arroz kg", 22.00, 50, "kg"), ("Frijol kg", 30.00, 50, "kg"),
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
    if db.execute("SELECT 1 FROM productos LIMIT 1").fetchone() is None:
        db.executemany(
            "INSERT INTO productos (nombre, precio, stock, unidad)"
            " VALUES (?, ?, ?, ?)", SEED
        )
        db.commit()


# ---------- helpers ----------

def validar_producto(form):
    """Devuelve (nombre, precio, stock, stock_minimo, unidad) o None si es inválido."""
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
    return nombre, round(precio, 2), round(stock, 3), round(stock_minimo, 3), unidad


def fmt_cantidad(cant, unidad):
    """2 → '2'; 1.5 con 'kg' → '1.5 kg'; 0.25 con 'kg' → '0.25 kg'."""
    if unidad != "kg":
        return str(int(cant))
    return f"{cant:.3f}".rstrip("0").rstrip(".") + " kg"


# ---------- venta ----------

@app.route("/")
def venta():
    productos = get_db().execute("SELECT * FROM productos ORDER BY nombre").fetchall()
    return render_template("venta.html", productos=productos)


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

    # Los precios y el stock se leen de la BD, nunca del cliente.
    db = get_db()
    lineas = []
    total = 0.0
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
        total += row["precio"] * cant
    total = round(total, 2)

    with db:
        venta_id = db.execute(
            "INSERT INTO ventas (total) VALUES (?)", (total,)
        ).lastrowid
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
    return jsonify(venta_id=venta_id, total=total), 201


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


# ---------- historial y ticket ----------

@app.route("/historial")
def historial():
    db = get_db()
    ventas = db.execute(
        "SELECT id, fecha, total FROM ventas ORDER BY id DESC"
    ).fetchall()
    hoy = db.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS total"
        " FROM ventas WHERE date(fecha) = date('now', 'localtime')"
    ).fetchone()
    rows = db.execute(
        "SELECT p.nombre, p.unidad, SUM(d.cantidad) AS vendidos,"
        " SUM(d.cantidad * d.precio_unitario) AS ingreso"
        " FROM venta_detalles d JOIN productos p ON p.id = d.producto_id"
        " GROUP BY p.id ORDER BY vendidos DESC LIMIT 5"
    ).fetchall()
    mas_vendidos = [
        dict(r) | {"vendidos_txt": fmt_cantidad(r["vendidos"], r["unidad"])}
        for r in rows
    ]
    return render_template("historial.html", ventas=ventas, hoy=hoy,
                           mas_vendidos=mas_vendidos)


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
        dict(r) | {"cantidad_txt": fmt_cantidad(r["cantidad"], r["unidad"])}
        for r in rows
    ]
    return render_template("ticket.html", venta=venta, detalles=detalles)


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True, host="127.0.0.1", port=5000)
