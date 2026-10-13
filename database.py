import libsql_experimental as libsql

# === CREDENCIALES TURSO CLOUD - SUCURSAL PACHUCA ===
TURSO_URL = "libsql://decar-pachuca-alfredogongar-netizen.aws-us-east-1.turso.io"
TURSO_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3OTE5MDIwMzUsImlkIjoiMDFhMTM1YWUtYjQwMS03YzQxLWIzMDAtNWVmNDJhZWI3YTQzIiwia2lkIjoiOVFWNV9kbVE2cHhENW1LZ1NEYTdpamhQcmdKMUpDVlY4RzRGYnktYXVLUSIsInJpZCI6ImRlYzQzNjE4LWIzNmQtNDljZi05N2EyLWQwM2M1MWI0YTM2NiJ9._qYcmH2hyVnfTsX_SSLk8ZsvC5hSothZDUcpx_wL4CJzpzPQcresUmF1BLPPo2luVA9dfzU-mMsPgxx2O_cmCg"

def get_connection():
    """Establece la conexión directa con la base de datos de Turso Pachuca."""
    return libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Tabla Usuarios
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        rol TEXT NOT NULL CHECK(rol IN ('Maestro', 'Tienda', 'Vendedor')),
        pin TEXT NOT NULL
    )
    """)

    # Verificar estructura de productos
    cursor.execute("PRAGMA table_info(productos)")
    cols_p = [column[1] for column in cursor.fetchall()]
    if cols_p and 'stock_garantia' not in cols_p:
        cursor.execute("DROP TABLE productos")

    # Verificar estructura de ventas
    cursor.execute("PRAGMA table_info(ventas)")
    cols_v = [column[1] for column in cursor.fetchall()]
    if cols_v and 'cliente_nombre' not in cols_v:
        cursor.execute("DROP TABLE detalle_ventas")
        cursor.execute("DROP TABLE ventas")

    # Verificar estructura de apartados
    cursor.execute("PRAGMA table_info(apartados)")
    cols_a = [column[1] for column in cursor.fetchall()]
    if cols_a and 'comision_vendedor' not in cols_a:
        cursor.execute("DROP TABLE detalle_apartados")
        cursor.execute("DROP TABLE abonos")
        cursor.execute("DROP TABLE apartados")

    # Verificar estructura de devoluciones
    cursor.execute("PRAGMA table_info(devoluciones)")
    cols_d = [column[1] for column in cursor.fetchall()]
    if cols_d and 'estado_producto' not in cols_d:
        cursor.execute("DROP TABLE devoluciones")

    # Tabla Productos
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT UNIQUE NOT NULL,
        nombre TEXT NOT NULL,
        marca TEXT,
        tipo TEXT NOT NULL,
        capacidad TEXT DEFAULT '',
        unidad_medida TEXT DEFAULT 'PZA',
        condicion TEXT CHECK(condicion IN ('Nuevo', 'Saldo')) DEFAULT 'Nuevo',
        observaciones_saldo TEXT DEFAULT '',
        costo_compra REAL NOT NULL DEFAULT 0,
        precio_pvp REAL NOT NULL DEFAULT 0,
        precio_minimo_pvp REAL DEFAULT 0,
        precio_mayoreo REAL DEFAULT 0,
        precio_minimo_mayoreo REAL DEFAULT 0,
        stock INTEGER DEFAULT 1,
        stock_apartado INTEGER DEFAULT 0,
        stock_garantia INTEGER DEFAULT 0
    )
    """)

    # Tabla Ventas Directas
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ventas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        folio TEXT UNIQUE NOT NULL,
        fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
        tipo_venta TEXT CHECK(tipo_venta IN ('Menudeo', 'Mayoreo')),
        cliente_nombre TEXT DEFAULT 'PÚBLICO EN GENERAL',
        cliente_telefono TEXT DEFAULT '',
        monto_efectivo REAL DEFAULT 0,
        monto_tarjeta REAL DEFAULT 0,
        monto_transferencia REAL DEFAULT 0,
        total_venta REAL NOT NULL,
        vendedor_id INTEGER,
        comisionista_id INTEGER,
        comision_vendedor REAL DEFAULT 0,
        comision_comisionista REAL DEFAULT 0
    )
    """)

    # Detalle Ventas
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS detalle_ventas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venta_id INTEGER,
        producto_id INTEGER,
        cantidad INTEGER,
        precio_unitario_real REAL,
        FOREIGN KEY(venta_id) REFERENCES ventas(id),
        FOREIGN KEY(producto_id) REFERENCES productos(id)
    )
    """)

    # Tabla Devoluciones y Garantías
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS devoluciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        folio_devolucion TEXT UNIQUE NOT NULL,
        fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
        folio_venta TEXT NOT NULL,
        sku TEXT NOT NULL,
        tipo_devolucion TEXT NOT NULL,
        estado_producto TEXT NOT NULL,
        motivo TEXT NOT NULL,
        monto_reembolsado REAL DEFAULT 0,
        metodo_reembolso TEXT,
        usuario_id INTEGER,
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
    )
    """)

    # Tabla Apartados
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS apartados (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        folio_apartado TEXT UNIQUE NOT NULL,
        cliente_nombre TEXT NOT NULL,
        cliente_telefono TEXT NOT NULL,
        fecha_inicio DATETIME DEFAULT CURRENT_TIMESTAMP,
        monto_total REAL NOT NULL,
        monto_pagado REAL DEFAULT 0,
        saldo_pendiente REAL NOT NULL,
        tipo_atencion TEXT DEFAULT 'VendedorTienda',
        vendedor_id INTEGER DEFAULT 1,
        comisionista_id INTEGER,
        comision_vendedor REAL DEFAULT 0,
        comision_comisionista REAL DEFAULT 0,
        motivo_cancelacion TEXT DEFAULT '',
        estatus TEXT CHECK(estatus IN ('Activo', 'Liquidado', 'Cancelado')) DEFAULT 'Activo'
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS detalle_apartados (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        apartado_id INTEGER,
        producto_id INTEGER,
        cantidad INTEGER,
        precio_pactado REAL,
        FOREIGN KEY(apartado_id) REFERENCES apartados(id),
        FOREIGN KEY(producto_id) REFERENCES productos(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS abonos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        apartado_id INTEGER,
        fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
        monto_abono REAL NOT NULL,
        monto_efectivo REAL DEFAULT 0,
        monto_tarjeta REAL DEFAULT 0,
        monto_transferencia REAL DEFAULT 0,
        metodo_pago TEXT,
        FOREIGN KEY(apartado_id) REFERENCES apartados(id)
    )
    """)

    # Caja Chica
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS caja_chica (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
        monto_inicial REAL NOT NULL,
        estatus TEXT CHECK(estatus IN ('Abierta', 'Cerrada')) DEFAULT 'Abierta'
    )
    """)

    # Tabla Gastos Operativos
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS gastos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
        concepto TEXT NOT NULL,
        categoria TEXT NOT NULL,
        monto REAL NOT NULL,
        usuario_id INTEGER
    )
    """)

    # Usuarios Base Pachuca
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        usuarios_base = [
            ('AdminMaestro', 'Maestro', '1234'),
            ('AdminPachuca', 'Tienda', '5678'),
            ('Vendedor01', 'Vendedor', '0000')
        ]
        cursor.executemany("INSERT INTO usuarios (nombre, rol, pin) VALUES (?, ?, ?)", usuarios_base)

    cursor.execute("UPDATE productos SET stock_apartado = 0")

    cursor.execute("""
        SELECT da.producto_id, COUNT(da.id)
        FROM detalle_apartados da
        JOIN apartados a ON da.apartado_id = a.id
        WHERE a.estatus = 'Activo'
        GROUP BY da.producto_id
    """)
    conteo_activos = cursor.fetchall()

    for p_id, cant_activa in conteo_activos:
        cursor.execute("UPDATE productos SET stock_apartado = ? WHERE id = ?", (cant_activa, p_id))

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
