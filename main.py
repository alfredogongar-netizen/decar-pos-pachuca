import pandas as pd
import io
import os
import sqlite3
import shutil
import base64
import barcode
from barcode.writer import ImageWriter
from datetime import datetime, timedelta
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler

from database import init_db, get_connection

BACKUP_DIR = "backups"
if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

def realizar_respaldo_bd():
    try:
        print(f"[{datetime.now()}] Turso gestiona el respaldo automático continuo en la nube para Pachuca.")
    except Exception as e:
        print(f"[{datetime.now()}] Error en verificación de respaldo: {str(e)}")

scheduler = BackgroundScheduler()
scheduler.add_job(realizar_respaldo_bd, 'cron', day_of_week='mon', hour=8, minute=0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(title="DECAR POS Core - Bodega Pachuca v2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

init_db()

class ProductoCreate(BaseModel):
    sku: Optional[str] = None
    tipo: str
    nombre: str
    marca: str
    capacidad: Optional[str] = ""
    unidad_medida: Optional[str] = "PZA"
    observaciones_saldo: Optional[str] = ""
    costo_compra: float = 0.0
    precio_mayoreo: float = 0.0
    precio_minimo_mayoreo: float = 0.0
    precio_pvp: float = 0.0
    precio_minimo_pvp: float = 0.0
    stock: int = 1

class ProductoEdit(BaseModel):
    nombre: str
    tipo: str
    marca: str
    capacidad: Optional[str] = ""
    unidad_medida: Optional[str] = "PZA"
    observaciones_saldo: Optional[str] = ""
    costo_compra: float
    precio_pvp: float
    precio_minimo_pvp: float
    precio_mayoreo: float
    precio_minimo_mayoreo: float
    stock: int

class CargaTextoExcelRequest(BaseModel):
    contenido_texto: str
    modo_carga: str = "acumular"

class DevolucionCreate(BaseModel):
    folio_venta: str
    sku: str
    tipo_devolucion: str
    estado_producto: str
    motivo: str
    monto_reembolsado: float = 0.0
    metodo_reembolso: Optional[str] = "Efectivo"
    usuario_id: Optional[int] = 1

class ItemVenta(BaseModel):
    sku: str
    cantidad: int = 1
    precio_final_aplicado: float

class VentaCreate(BaseModel):
    tipo_venta: str
    cliente_nombre: Optional[str] = "PÚBLICO EN GENERAL"
    cliente_telefono: Optional[str] = ""
    tipo_atencion: Optional[str] = "VendedorTienda"
    monto_efectivo: float = 0.0
    monto_tarjeta: float = 0.0
    monto_transferencia: float = 0.0
    vendedor_id: Optional[int] = 1
    comisionista_id: Optional[int] = None
    items: list[ItemVenta]

class ItemApartado(BaseModel):
    sku: str
    cantidad: int = 1
    precio_pactado: float

class ApartadoCreate(BaseModel):
    cliente_nombre: str
    cliente_telefono: str
    tipo_atencion: Optional[str] = "VendedorTienda"
    monto_efectivo: float = 0.0
    monto_tarjeta: float = 0.0
    monto_transferencia: float = 0.0
    vendedor_id: Optional[int] = 1
    comisionista_id: Optional[int] = None
    items: list[ItemApartado]

class AbonoCreate(BaseModel):
    monto_efectivo: float = 0.0
    monto_tarjeta: float = 0.0
    monto_transferencia: float = 0.0

class AperturaCaja(BaseModel):
    monto_inicial: float

class GastoCreate(BaseModel):
    concepto: str
    categoria: str
    monto: float
    fecha_gasto: Optional[str] = None
    usuario_id: Optional[int] = 1

class GastoEdit(BaseModel):
    concepto: str
    categoria: str
    monto: float

class LoginRequest(BaseModel):
    nombre_usuario: str
    pin_credencial: str

class AutorizarDescuento(BaseModel):
    pin_autorizador: str

def obtener_rango_semana():
    today = datetime.now().date()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    return str(start_of_week), str(end_of_week)

@app.get("/")
def home():
    return FileResponse("static/index.html")

@app.get("/sistema/descargar-bd/")
def descargar_base_datos():
    conn = get_connection()
    cursor = conn.cursor()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"DECAR_Pachuca_{timestamp}.db"
    file_path = os.path.join(BACKUP_DIR, filename)

    if os.path.exists(file_path):
        os.remove(file_path)

    loc_conn = sqlite3.connect(file_path)
    loc_cursor = loc_conn.cursor()

    tablas = ["usuarios", "productos", "ventas", "detalle_ventas", "devoluciones", "apartados", "detalle_apartados", "abonos", "caja_chica", "gastos"]

    for tabla in tablas:
        cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{tabla}'")
        tbl_sql = cursor.fetchone()
        if tbl_sql and tbl_sql[0]:
            loc_cursor.execute(tbl_sql[0])
            cursor.execute(f"SELECT * FROM {tabla}")
            rows = cursor.fetchall()
            if rows:
                placeholders = ",".join(["?"] * len(rows[0]))
                loc_cursor.executemany(f"INSERT INTO {tabla} VALUES ({placeholders})", rows)

    loc_conn.commit()
    loc_conn.close()
    conn.close()

    return FileResponse(path=file_path, filename=filename, media_type="application/octet-stream")

@app.delete("/sistema/limpiar-todo/")
def limpiar_sistema_completo(rol_usuario: str, pin_maestro: Optional[str] = None):
    if rol_usuario != "Maestro":
        raise HTTPException(status_code=403, detail="Solo el Administrador Maestro puede reiniciar el sistema.")
    
    conn = get_connection()
    cursor = conn.cursor()

    if pin_maestro:
        cursor.execute("SELECT id FROM usuarios WHERE pin = ? AND rol = 'Maestro'", (pin_maestro.strip(),))
        if not cursor.fetchone():
            conn.close()
            raise HTTPException(status_code=401, detail="PIN de Administrador Maestro incorrecto.")

    cursor.execute("DELETE FROM detalle_ventas")
    cursor.execute("DELETE FROM ventas")
    cursor.execute("DELETE FROM devoluciones")
    cursor.execute("DELETE FROM detalle_apartados")
    cursor.execute("DELETE FROM abonos")
    cursor.execute("DELETE FROM apartados")
    cursor.execute("DELETE FROM gastos")
    cursor.execute("DELETE FROM caja_chica")
    cursor.execute("DELETE FROM productos")
    conn.commit()
    conn.close()
    return {"estatus": "exito", "mensaje": "Base de datos de Pachuca reiniciada limpiamente."}

@app.post("/sistema/respaldo-manual/")
def respaldo_manual_sistema():
    realizar_respaldo_bd()
    return {"estatus": "exito", "mensaje": "Turso Cloud mantiene tus datos respaldados en la nube."}

@app.post("/login/")
def iniciar_sesion(credenciales: LoginRequest):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nombre, rol FROM usuarios WHERE nombre = ? AND pin = ?", (credenciales.nombre_usuario, credenciales.pin_credencial))
    user = cursor.fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=401, detail="Usuario o PIN incorrectos.")
    return {"estatus": "exito", "usuario_id": user[0], "nombre": user[1], "rol": user[2]}

@app.post("/autorizar-descuento/")
def autorizar_descuento(req: AutorizarDescuento):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT nombre, rol FROM usuarios WHERE pin = ? AND rol IN ('Maestro', 'Tienda')", (req.pin_autorizador,))
    user = cursor.fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=403, detail="PIN de autorización inválido o sin permisos suficientes.")
    return {"estatus": "exito", "autorizado_por": f"{user[0]} ({user[1]})"}

@app.get("/productos/")
def listar_productos():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, sku, tipo, nombre, marca, capacidad, unidad_medida, 
               observaciones_saldo, costo_compra, precio_mayoreo, 
               precio_minimo_mayoreo, precio_pvp, precio_minimo_pvp, 
               stock, stock_apartado, stock_garantia 
        FROM productos
    """)
    filas = cursor.fetchall()
    conn.close()
    return [{
        "id": f[0], "sku": f[1], "tipo": f[2], "nombre": f[3], "marca": f[4] or "GENÉRICA",
        "capacidad": f[5] or "", "unidad_medida": f[6] or "PZA", "observaciones": f[7] or "",
        "costo_compra": f[8], "precio_mayoreo": f[9], "precio_minimo_mayoreo": f[10],
        "precio_pvp": f[11], "precio_minimo_pvp": f[12], "stock": f[13], "stock_apartado": f[14], "stock_garantia": f[15]
    } for f in filas]

@app.put("/productos/{producto_id}/")
def editar_producto(producto_id: int, p: ProductoEdit, rol_usuario: str):
    if rol_usuario != "Maestro":
        raise HTTPException(status_code=403, detail="Solo el Administrador Maestro puede editar información de productos.")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE productos 
        SET nombre = ?, tipo = ?, marca = ?, capacidad = ?, unidad_medida = ?, observaciones_saldo = ?,
            costo_compra = ?, precio_pvp = ?, precio_minimo_pvp = ?, precio_mayoreo = ?, precio_minimo_mayoreo = ?, stock = ?
        WHERE id = ?
    """, (p.nombre, p.tipo, p.marca, p.capacidad, p.unidad_medida, p.observaciones_saldo, 
          p.costo_compra, p.precio_pvp, p.precio_minimo_pvp, p.precio_mayoreo, p.precio_minimo_mayoreo, p.stock, producto_id))
    conn.commit()
    conn.close()
    return {"estatus": "exito", "mensaje": "Producto actualizado correctamente por el Administrador Maestro."}

@app.post("/productos/cargar-copiado/")
def cargar_productos_pegados(req: CargaTextoExcelRequest):
    lineas = [l.strip() for l in req.contenido_texto.strip().split('\n') if l.strip()]
    if not lineas:
        raise HTTPException(status_code=400, detail="El área de texto pegada está vacía.")

    conn = get_connection()
    cursor = conn.cursor()

    if req.modo_carga == "reemplazar":
        cursor.execute("DELETE FROM productos")

    cursor.execute("SELECT COUNT(*) FROM productos")
    contador = cursor.fetchone()[0]
    creados = 0

    for idx, linea in enumerate(lineas):
        partes = [p.strip() for p in linea.split('\t')]
        if len(partes) < 3:
            partes = [p.strip() for p in linea.split(',')]

        if idx == 0 and any(h in partes[0].upper() for h in ['SKU', 'TIPO', 'DESCRIPCION', 'NOMBRE']):
            continue

        if len(partes) >= 2:
            sku = partes[0] if len(partes) > 0 and partes[0] else f"GEN-NEW-{contador+1:04d}"
            tipo = partes[1] if len(partes) > 1 and partes[1] else "GENERAL"
            nombre = partes[2] if len(partes) > 2 else partes[0]
            marca = partes[3] if len(partes) > 3 else "GENÉRICA"
            capacidad = partes[4] if len(partes) > 4 else ""
            um = partes[5] if len(partes) > 5 else "PZA"
            obs = partes[6] if len(partes) > 6 else ""

            def safe_float(val, def_v=0.0):
                try: return float(str(val).replace('$', '').replace(',', '').strip())
                except: return def_v

            costo = safe_float(partes[7]) if len(partes) > 7 else 0.0
            pvp = safe_float(partes[8]) if len(partes) > 8 else 0.0
            pvm = safe_float(partes[9]) if len(partes) > 9 else pvp
            stock = int(safe_float(partes[10])) if len(partes) > 10 else 1

            cursor.execute("""
                INSERT OR REPLACE INTO productos (
                    sku, tipo, nombre, marca, capacidad, unidad_medida, observaciones_saldo,
                    costo_compra, precio_pvp, precio_minimo_pvp, precio_mayoreo, precio_minimo_mayoreo, stock
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sku, tipo, nombre, marca, capacidad, um, obs, costo, pvp, pvp, pvm, pvm, stock))
            contador += 1
            creados += 1

    conn.commit()
    conn.close()
    return {"estatus": "exito", "mensaje": f"Se procesaron e importaron {creados} productos correctamente."}

@app.get("/productos/{sku}/codigo-barras/")
def obtener_codigo_barras(sku: str):
    try:
        code128 = barcode.get_barcode_class('code128')
        rv = io.BytesIO()
        code = code128(sku.strip().upper(), writer=ImageWriter())
        code.write(rv)
        b64_str = base64.b64encode(rv.getvalue()).decode('utf-8')
        return {"sku": sku, "imagen_base64": f"data:image/png;base64,{b64_str}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falta librería Pillow o error al generar imagen: {str(e)}")

@app.post("/productos/")
def crear_producto_individual(producto: ProductoCreate):
    conn = get_connection()
    cursor = conn.cursor()

    if not producto.sku or producto.sku.strip() == "":
        cursor.execute("SELECT COUNT(*) FROM productos")
        total = cursor.fetchone()[0] + 1
        prefix_tipo = producto.tipo[:3].upper() if len(producto.tipo) >= 3 else "GEN"
        prefix_marca = producto.marca[:3].upper() if len(producto.marca) >= 3 else "GEN"
        sku_final = f"{prefix_tipo}-{prefix_marca}-{total:04d}-NUEVO"
    else:
        sku_final = producto.sku.strip().upper()

    try:
        cursor.execute("""
            INSERT INTO productos (
                sku, tipo, nombre, marca, capacidad, unidad_medida, 
                observaciones_saldo, costo_compra, precio_mayoreo, 
                precio_minimo_mayoreo, precio_pvp, precio_minimo_pvp, stock, stock_apartado, stock_garantia
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
        """, (
            sku_final, producto.tipo, producto.nombre, producto.marca, 
            producto.capacidad, producto.unidad_medida, producto.observaciones_saldo, 
            producto.costo_compra, producto.precio_mayoreo, producto.precio_minimo_mayoreo, 
            producto.precio_pvp, producto.precio_minimo_pvp, producto.stock
        ))
        conn.commit()
        product_id = cursor.lastrowid
        conn.close()
        return {"estatus": "exito", "id": product_id, "sku": sku_final, "mensaje": "Producto registrado correctamente."}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"El SKU '{sku_final}' ya existe o hubo un error en inventario.")

@app.post("/productos/cargar-excel/")
async def cargar_excel(file: UploadFile = File(...), modo_carga: str = Form("acumular")):
    if not (file.filename.endswith('.xlsx') or file.filename.endswith('.csv')):
        raise HTTPException(status_code=400, detail="El archivo debe ser un Excel (.xlsx) o CSV.")
    
    contents = await file.read()
    try:
        if file.filename.endswith('.xlsx'):
            df_raw = pd.read_excel(io.BytesIO(contents), header=None)
        else:
            df_raw = pd.read_csv(io.BytesIO(contents), header=None)

        header_idx = None
        for i, row in df_raw.iterrows():
            row_items = [str(x).strip().upper() for x in row.tolist() if pd.notna(x)]
            if any('DESCRIPCION' in item or 'TIPO' in item for item in row_items):
                header_idx = i
                break

        if header_idx is not None:
            df = df_raw.iloc[header_idx + 1:].copy()
            df.columns = [str(x).strip().upper() if pd.notna(x) else f"COL_{idx}" for idx, x in enumerate(df_raw.iloc[header_idx])]
        else:
            df = df_raw

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error en la estructura del Excel: {str(e)}")

    def parse_float(val, default=0.0):
        if pd.isna(val):
            return default
        s_val = str(val).strip().replace(',', '').replace('$', '')
        if s_val in ['-', '', 'nan', 'NONE', 'None']:
            return default
        try:
            return float(s_val)
        except Exception:
            return default

    def obtener_columna(df_row, posibles_nombres, default=''):
        for col in df_row.index:
            col_clean = str(col).strip().upper()
            if any(pos in col_clean for pos in posibles_nombres):
                val = df_row[col]
                return str(val).strip() if pd.notna(val) else default
        return default

    conn = get_connection()
    cursor = conn.cursor()

    if modo_carga == "reemplazar":
        cursor.execute("DELETE FROM productos")

    cursor.execute("SELECT COUNT(*) FROM productos")
    contador_global = cursor.fetchone()[0]
    productos_creados = 0

    try:
        for _, row in df.iterrows():
            sku_val = obtener_columna(row, ['SKU'])
            if sku_val in ['-', 'nan', 'NONE', 'None']:
                sku_val = ''

            tipo = obtener_columna(row, ['TIPO'], 'GENERAL')
            marca = obtener_columna(row, ['MARCA'], 'GENERICA')
            descripcion = obtener_columna(row, ['DESCRIPCION', 'PRODUCTO', 'NOMBRE'])
            
            if not descripcion or descripcion.upper() in ['NAN', 'NONE', '-']:
                continue

            capacidad = obtener_columna(row, ['CAPACIDAD'])
            um = obtener_columna(row, ['U/M', 'UNIDAD'], 'PZA')
            obs = obtener_columna(row, ['OBSERVACIO', 'OBSERVACION', 'OBSERVACIONES'])
            
            costo = parse_float(row.get('PRECIO DE COMPRA', 0))
            pvm = parse_float(row.get('PVM (PRECIO VENTA MAYOREO)', 0))
            pmvm = parse_float(row.get('PMVM (PRECIO MINIMO VENTA MAYOREO)', pvm))
            pvp = parse_float(row.get('PVP (PRECIO VENTA AL PUBLICO)', 0))
            if pvp == 0:
                pvp = parse_float(row.get('PVP (PRECIO VENTA PUBLICO)', 0))
            
            pmvp = parse_float(row.get('PMVP (PRECIO MINIMO VENTA PUBLICO)', pvp))

            if not sku_val:
                contador_global += 1
                prefix_tipo = tipo[:3].upper() if len(str(tipo)) >= 3 else "GEN"
                prefix_marca = marca[:3].upper() if len(str(marca)) >= 3 else "GEN"
                sku_final = f"{prefix_tipo}-{prefix_marca}-{contador_global:04d}-NUEVO"
            else:
                sku_final = sku_val

            stock_val = int(parse_float(row.get('STOCK', 1), default=1))

            cursor.execute("""
                INSERT OR REPLACE INTO productos (
                    sku, tipo, nombre, marca, capacidad, unidad_medida, 
                    observaciones_saldo, costo_compra, precio_mayoreo, 
                    precio_minimo_mayoreo, precio_pvp, precio_minimo_pvp, stock, stock_apartado, stock_garantia
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
            """, (sku_final, tipo, descripcion, marca, capacidad, um, obs, costo, pvm, pmvm, pvp, pmvp, stock_val))
            productos_creados += 1

        cursor.execute("""
            SELECT p.id, COUNT(da.id)
            FROM detalle_apartados da
            JOIN apartados a ON da.apartado_id = a.id
            JOIN productos p ON da.producto_id = p.id
            WHERE a.estatus = 'Activo'
            GROUP BY p.id
        """)
        apartados_activos = cursor.fetchall()
        for prod_id, cant_apt in apartados_activos:
            cursor.execute("""
                UPDATE productos 
                SET stock = MAX(0, stock - ?), stock_apartado = ? 
                WHERE id = ?
            """, (cant_apt, cant_apt, prod_id))

        conn.commit()
    except Exception as err:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Error al guardar en base de datos: {str(err)}")

    conn.close()
    return {"estatus": "exito", "mensaje": f"Se procesaron correctamente {productos_creados} productos en el inventario."}

@app.get("/productos/descargar-excel/")
def descargar_excel(rol_usuario: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT sku, tipo, nombre, marca, capacidad, unidad_medida, observaciones_saldo, costo_compra, precio_mayoreo, precio_minimo_mayoreo, precio_pvp, precio_minimo_pvp, stock, stock_apartado, stock_garantia FROM productos")
    filas = cursor.fetchall()
    conn.close()

    columnas = [
        "SKU", "TIPO", "DESCRIPCION", "MARCA", "CAPACIDAD", "U/M", 
        "OBSERVACIONES", "PRECIO DE COMPRA", "PVM (PRECIO VENTA MAYOREO)", 
        "PMVM (PRECIO MINIMO VENTA MAYOREO)", "PVP (PRECIO VENTA PUBLICO)", 
        "PMVP (PRECIO MINIMO VENTA PUBLICO)", "STOCK DISPONIBLE", "RESERVADO APARTADO", "EN GARANTIA TALLER"
    ]

    datos = []
    for f in filas:
        row = [f[0], f[1], f[2], f[3], f[4], f[5], f[6]]
        costo_mostrar = f[7] if rol_usuario == "Maestro" else 0.0
        row.extend([costo_mostrar, f[8], f[9], f[10], f[11], f[12], f[13], f[14]])
        datos.append(row)

    df = pd.DataFrame(datos, columns=columnas)
    if rol_usuario != "Maestro":
        df.drop(columns=["PRECIO DE COMPRA"], inplace=True)

    stream = io.BytesIO()
    with pd.ExcelWriter(stream, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Inventario_DECAR_Pachuca')
    stream.seek(0)

    headers = {'Content-Disposition': 'attachment; filename="Inventario_Pachuca.xlsx"'}
    return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)

@app.post("/ventas/")
def registrar_venta(venta: VentaCreate):
    conn = get_connection()
    cursor = conn.cursor()
    total_calculado = sum(item.precio_final_aplicado for item in venta.items)
    pago_total = venta.monto_efectivo + venta.monto_tarjeta + venta.monto_transferencia

    if abs(pago_total - total_calculado) > 0.01:
        conn.close()
        raise HTTPException(status_code=400, detail=f"El pago recibido (${pago_total:.2f}) no coincide con el total (${total_calculado:.2f}).")

    comision_vendedor = total_calculado * 0.02 if venta.tipo_atencion == "VendedorTienda" else 0.0
    comision_comisionista = total_calculado * 0.02 if venta.tipo_atencion == "Comisionista" else 0.0

    cursor.execute("SELECT COUNT(*) FROM ventas")
    folio = f"TICK-{cursor.fetchone()[0] + 1:06d}"
    cliente = venta.cliente_nombre.strip() if venta.cliente_nombre and venta.cliente_nombre.strip() else "PÚBLICO EN GENERAL"

    try:
        cursor.execute("""
            INSERT INTO ventas (folio, tipo_venta, cliente_nombre, cliente_telefono, monto_efectivo, monto_tarjeta, monto_transferencia, total_venta, vendedor_id, comisionista_id, comision_vendedor, comision_comisionista)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (folio, venta.tipo_venta, cliente, venta.cliente_telefono, venta.monto_efectivo, venta.monto_tarjeta, venta.monto_transferencia, total_calculado, venta.vendedor_id, venta.comisionista_id, comision_vendedor, comision_comisionista))

        venta_id = cursor.lastrowid

        for item in venta.items:
            cursor.execute("SELECT id, stock FROM productos WHERE sku = ?", (item.sku,))
            prod = cursor.fetchone()
            if not prod or prod[1] < 1:
                conn.rollback()
                conn.close()
                raise HTTPException(status_code=400, detail=f"Stock disponible insuficiente para {item.sku}.")
            cursor.execute("UPDATE productos SET stock = stock - 1 WHERE id = ?", (prod[0],))
            cursor.execute("INSERT INTO detalle_ventas (venta_id, producto_id, cantidad, precio_unitario_real) VALUES (?, ?, 1, ?)", (venta_id, prod[0], item.precio_final_aplicado))

        conn.commit()
    except Exception as err:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=f"Error en base de datos: {str(err)}")

    conn.close()
    return {"estatus": "exito", "folio": folio, "total": total_calculado}

@app.get("/ventas/historial/")
def obtener_historial_ventas(busqueda: Optional[str] = "", fecha_inicio: Optional[str] = "", fecha_fin: Optional[str] = ""):
    conn = get_connection()
    cursor = conn.cursor()
    
    q_val = (busqueda or "").strip()
    query_str = f"%{q_val}%"
    
    sql = """
        SELECT DISTINCT v.folio, v.fecha, COALESCE(v.cliente_nombre, 'PÚBLICO EN GENERAL'), v.total_venta, v.tipo_venta,
               v.monto_efectivo, v.monto_tarjeta, v.monto_transferencia
        FROM ventas v
        LEFT JOIN detalle_ventas dv ON v.id = dv.venta_id
        LEFT JOIN productos p ON dv.producto_id = p.id
        WHERE (v.folio LIKE ? OR v.cliente_nombre LIKE ? OR p.nombre LIKE ? OR p.sku LIKE ?)
    """
    params = [query_str, query_str, query_str, query_str]

    f_ini = (fecha_inicio or "").strip()
    f_fin = (fecha_fin or "").strip()

    if f_ini != "":
        sql += " AND DATE(v.fecha) >= DATE(?)"
        params.append(f_ini)
    if f_fin != "":
        sql += " AND DATE(v.fecha) <= DATE(?)"
        params.append(f_fin)

    sql += " ORDER BY v.id DESC LIMIT 100"
    
    try:
        cursor.execute(sql, tuple(params))
        filas = cursor.fetchall()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Error en consulta de ventas: {str(e)}")
        
    conn.close()

    resultado = []
    for f in filas:
        try:
            resultado.append({
                "folio": str(f[0] or ""),
                "fecha": str(f[1] or ""),
                "cliente": str(f[2] or "PÚBLICO EN GENERAL"),
                "total": float(f[3] or 0.0),
                "tipo": str(f[4] or ""),
                "efectivo": float(f[5] or 0.0),
                "tarjeta": float(f[6] or 0.0),
                "transferencia": float(f[7] or 0.0)
            })
        except Exception:
            continue

    return resultado

@app.get("/ventas/{folio}/")
def buscar_venta_folio(folio: str):
    conn = get_connection()
    cursor = conn.cursor()
    folio_clean = folio.strip().upper()
    
    cursor.execute("SELECT id, folio, fecha, tipo_venta, total_venta, cliente_nombre, monto_efectivo, monto_tarjeta, monto_transferencia, cliente_telefono FROM ventas WHERE folio = ?", (folio_clean,))
    v = cursor.fetchone()
    
    if not v:
        cursor.execute("SELECT id, folio_apartado, fecha_inicio, 'Apartado Liquidado', monto_total, cliente_nombre, 0, 0, 0, cliente_telefono FROM apartados WHERE folio_apartado = ?", (folio_clean,))
        apt = cursor.fetchone()
        if apt:
            v = apt
            cursor.execute("""
                SELECT p.sku, p.nombre, da.cantidad, da.precio_pactado, COALESCE(p.marca, 'GENÉRICA')
                FROM detalle_apartados da JOIN productos p ON da.producto_id = p.id 
                WHERE da.apartado_id = ?
            """, (apt[0],))
            items_raw = cursor.fetchall()
            items_res = []
            for i in items_raw:
                cursor.execute("SELECT COUNT(*) FROM devoluciones WHERE folio_venta = ? AND sku = ?", (v[1], i[0]))
                devuelto_cant = cursor.fetchone()[0]
                items_res.append({
                    "sku": i[0], "nombre": i[1], "cantidad": i[2], 
                    "precio_pagado": float(i[3]), "marca": i[4], "devuelto": devuelto_cant > 0
                })
            conn.close()
            return {
                "folio": v[1], "fecha": str(v[2]), "tipo_venta": v[3], "total_venta": float(v[4]), "cliente": v[5],
                "efectivo": float(v[6]), "tarjeta": float(v[7]), "transferencia": float(v[8]), "telefono": v[9],
                "items": items_res
            }
        else:
            conn.close()
            raise HTTPException(status_code=404, detail=f"No se encontró la venta '{folio_clean}'.")

    cursor.execute("""
        SELECT p.sku, p.nombre, dv.cantidad, dv.precio_unitario_real, COALESCE(p.marca, 'GENÉRICA')
        FROM detalle_ventas dv JOIN ventas v ON dv.venta_id = v.id JOIN productos p ON dv.producto_id = p.id 
        WHERE dv.venta_id = ?
    """, (v[0],))
    items_raw = cursor.fetchall()
    items_res = []
    for i in items_raw:
        cursor.execute("SELECT COUNT(*) FROM devoluciones WHERE folio_venta = ? AND sku = ?", (v[1], i[0]))
        devuelto_cant = cursor.fetchone()[0]
        items_res.append({
            "sku": i[0], "nombre": i[1], "cantidad": i[2], 
            "precio_pagado": float(i[3]), "marca": i[4], "devuelto": devuelto_cant >= i[2]
        })

    conn.close()
    return {
        "folio": v[1], "fecha": str(v[2]), "tipo_venta": v[3], "total_venta": float(v[4]), "cliente": v[5],
        "efectivo": float(v[6]), "tarjeta": float(v[7]), "transferencia": float(v[8]), "telefono": v[9],
        "items": items_res
    }

@app.post("/apartados/")
def crear_apartado(apartado: ApartadoCreate):
    if not apartado.cliente_nombre.strip() or not apartado.cliente_telefono.strip():
        raise HTTPException(status_code=400, detail="El nombre del cliente y teléfono son OBLIGATORIOS para crear un apartado.")

    pago_inicial = apartado.monto_efectivo + apartado.monto_tarjeta + apartado.monto_transferencia
    monto_total = sum(item.precio_pactado for item in apartado.items)
    saldo_pendiente = monto_total - pago_inicial

    if pago_inicial <= 0:
        raise HTTPException(status_code=400, detail="Debes ingresar al menos una forma de pago para el enganche inicial.")

    comision_vendedor = monto_total * 0.02 if apartado.tipo_atencion == "VendedorTienda" else 0.0
    comision_comisionista = monto_total * 0.02 if apartado.tipo_atencion == "Comisionista" else 0.0

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT COUNT(*) FROM apartados")
        folio = f"APT-{cursor.fetchone()[0] + 1:06d}"

        cursor.execute("""
            INSERT INTO apartados (
                folio_apartado, cliente_nombre, cliente_telefono, monto_total, 
                monto_pagado, saldo_pendiente, tipo_atencion, vendedor_id, 
                comisionista_id, comision_vendedor, comision_comisionista
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            folio, 
            apartado.cliente_nombre.strip(), 
            apartado.cliente_telefono.strip(), 
            monto_total, 
            pago_inicial, 
            saldo_pendiente,
            apartado.tipo_atencion,
            apartado.vendedor_id or 1,
            apartado.comisionista_id,
            comision_vendedor,
            comision_comisionista
        ))
        apartado_id = cursor.lastrowid
        
        metodos_text = []
        if apartado.monto_efectivo > 0: metodos_text.append(f"Efec: ${apartado.monto_efectivo:.2f}")
        if apartado.monto_tarjeta > 0: metodos_text.append(f"Tarj: ${apartado.monto_tarjeta:.2f}")
        if apartado.monto_transferencia > 0: metodos_text.append(f"Trans: ${apartado.monto_transferencia:.2f}")

        cursor.execute("""
            INSERT INTO abonos (apartado_id, monto_abono, monto_efectivo, monto_tarjeta, monto_transferencia, metodo_pago) 
            VALUES (?, ?, ?, ?, ?, ?)
        """, (apartado_id, pago_inicial, apartado.monto_efectivo, apartado.monto_tarjeta, apartado.monto_transferencia, "Enganche Inicial: " + " / ".join(metodos_text)))

        for item in apartado.items:
            cursor.execute("SELECT id, stock, stock_apartado FROM productos WHERE sku = ?", (item.sku,))
            prod = cursor.fetchone()
            if not prod or prod[1] < 1:
                conn.rollback()
                conn.close()
                raise HTTPException(status_code=400, detail=f"Stock disponible insuficiente para apartar {item.sku}.")
            cursor.execute("UPDATE productos SET stock = stock - 1, stock_apartado = stock_apartado + 1 WHERE id = ?", (prod[0],))
            cursor.execute("INSERT INTO detalle_apartados (apartado_id, producto_id, cantidad, precio_pactado) VALUES (?, ?, 1, ?)", (apartado_id, prod[0], item.precio_pactado))

        conn.commit()
        conn.close()
        return {"estatus": "exito", "folio_apartado": folio, "monto_total": monto_total, "monto_pagado": pago_inicial, "saldo_pendiente": saldo_pendiente}
    
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=f"Error interno en base de datos al apartar: {str(e)}")

@app.get("/apartados/historial/")
def obtener_historial_apartados(busqueda: Optional[str] = "", fecha_inicio: Optional[str] = "", fecha_fin: Optional[str] = ""):
    conn = get_connection()
    cursor = conn.cursor()
    
    q_val = (busqueda or "").strip()
    query_str = f"%{q_val}%"
    
    sql = """
        SELECT DISTINCT a.id, a.folio_apartado, a.fecha_inicio, a.cliente_nombre, a.cliente_telefono, 
                        a.monto_total, a.monto_pagado, a.saldo_pendiente, a.estatus
        FROM apartados a
        LEFT JOIN detalle_apartados da ON a.id = da.apartado_id
        LEFT JOIN productos p ON da.producto_id = p.id
        WHERE (a.folio_apartado LIKE ? OR a.cliente_nombre LIKE ? OR a.cliente_telefono LIKE ? OR p.nombre LIKE ? OR p.sku LIKE ?)
    """
    params = [query_str, query_str, query_str, query_str, query_str]

    f_ini = (fecha_inicio or "").strip()
    f_fin = (fecha_fin or "").strip()

    if f_ini != "":
        sql += " AND DATE(a.fecha_inicio) >= DATE(?)"
        params.append(f_ini)
    if f_fin != "":
        sql += " AND DATE(a.fecha_inicio) <= DATE(?)"
        params.append(f_fin)

    sql += " ORDER BY a.id DESC LIMIT 100"
    
    try:
        cursor.execute(sql, tuple(params))
        filas = cursor.fetchall()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Error en consulta de apartados: {str(e)}")
        
    conn.close()

    resultado = []
    for f in filas:
        try:
            resultado.append({
                "id": f[0],
                "folio": str(f[1] or ""),
                "fecha": str(f[2] or ""),
                "cliente": str(f[3] or "PÚBLICO EN GENERAL"),
                "telefono": str(f[4] or ""),
                "monto_total": float(f[5] or 0.0),
                "monto_pagado": float(f[6] or 0.0),
                "saldo_pendiente": float(f[7] or 0.0),
                "estatus": str(f[8] or "Activo")
            })
        except Exception:
            continue

    return resultado

@app.get("/apartados/exportar-excel/")
def exportar_apartados_excel(tipo: str = "todos"):
    conn = get_connection()
    cursor = conn.cursor()
    
    sql = "SELECT folio_apartado, fecha_inicio, cliente_nombre, cliente_telefono, monto_total, monto_pagado, saldo_pendiente, estatus FROM apartados"
    if tipo == "pendientes":
        sql += " WHERE estatus = 'Activo' AND saldo_pendiente > 0"
    
    cursor.execute(sql)
    filas = cursor.fetchall()
    conn.close()

    columnas = ["Folio Apartado", "Fecha Registro", "Cliente", "Teléfono", "Monto Total", "Total Abonado", "Saldo Pendiente", "Estatus"]
    df = pd.DataFrame(filas, columns=columnas)

    stream = io.BytesIO()
    with pd.ExcelWriter(stream, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Apartados_Pachuca')
    stream.seek(0)

    nombre_archivo = "Apartados_Pendientes_Pachuca.xlsx" if tipo == "pendientes" else "Historico_Apartados_Pachuca.xlsx"
    headers = {'Content-Disposition': f'attachment; filename="{nombre_archivo}"'}
    return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)

@app.get("/apartados/{folio}/estado-cuenta/")
def obtener_estado_cuenta_apartado(folio: str):
    conn = get_connection()
    cursor = conn.cursor()
    folio_clean = folio.strip().upper()

    cursor.execute("SELECT id, folio_apartado, cliente_nombre, cliente_telefono, monto_total, monto_pagado, saldo_pendiente, estatus, fecha_inicio FROM apartados WHERE folio_apartado = ?", (folio_clean,))
    apt = cursor.fetchone()
    if not apt:
        conn.close()
        raise HTTPException(status_code=404, detail="Apartado no encontrado.")

    cursor.execute("""
        SELECT p.sku, p.nombre, da.precio_pactado, COALESCE(p.marca, 'GENÉRICA'), COALESCE(p.capacidad, '')
        FROM detalle_apartados da JOIN productos p ON da.producto_id = p.id
        WHERE da.apartado_id = ?
    """, (apt[0],))
    muebles = [{"sku": m[0], "nombre": m[1], "precio_pactado": float(m[2]), "marca": m[3], "capacidad": m[4]} for m in cursor.fetchall()]

    cursor.execute("SELECT fecha, monto_abono, metodo_pago FROM abonos WHERE apartado_id = ? ORDER BY id ASC", (apt[0],))
    abonos = [{"fecha": str(a[0]), "monto": float(a[1]), "metodo": a[2]} for a in cursor.fetchall()]

    conn.close()
    return {
        "folio": apt[1], "cliente": apt[2], "telefono": apt[3],
        "monto_total": float(apt[4]), "monto_pagado": float(apt[5]), "saldo_pendiente": float(apt[6]),
        "estatus": apt[7], "fecha_inicio": str(apt[8]), "muebles": muebles, "abonos": abonos
    }

@app.post("/apartados/{folio}/abonos/")
def registrar_abono_apartado(folio: str, abono: AbonoCreate):
    monto_abono = abono.monto_efectivo + abono.monto_tarjeta + abono.monto_transferencia
    if monto_abono <= 0:
        raise HTTPException(status_code=400, detail="Ingresa al menos una forma de pago válida para el abono.")

    conn = get_connection()
    cursor = conn.cursor()
    folio_clean = folio.strip().upper()

    cursor.execute("SELECT id, monto_total, monto_pagado, saldo_pendiente, estatus FROM apartados WHERE folio_apartado = ?", (folio_clean,))
    apt = cursor.fetchone()

    if not apt:
        conn.close()
        raise HTTPException(status_code=404, detail="Apartado no encontrado.")

    if apt[4] == 'Cancelado':
        conn.close()
        raise HTTPException(status_code=400, detail="Este apartado está CANCELADO.")

    if apt[4] == 'Liquidado':
        conn.close()
        raise HTTPException(status_code=400, detail="Este apartado ya se encuentra 100% LIQUIDADO.")

    nuevo_pagado = float(apt[2]) + monto_abono
    nuevo_saldo = max(0.0, float(apt[1]) - nuevo_pagado)
    nuevo_estatus = 'Liquidado' if nuevo_saldo <= 0 else 'Activo'

    metodos_text = []
    if abono.monto_efectivo > 0: metodos_text.append(f"Efec: ${abono.monto_efectivo:.2f}")
    if abono.monto_tarjeta > 0: metodos_text.append(f"Tarj: ${abono.monto_tarjeta:.2f}")
    if abono.monto_transferencia > 0: metodos_text.append(f"Trans: ${abono.monto_transferencia:.2f}")

    cursor.execute("UPDATE apartados SET monto_pagado = ?, saldo_pendiente = ?, estatus = ? WHERE id = ?", (nuevo_pagado, nuevo_saldo, nuevo_estatus, apt[0]))
    
    cursor.execute("""
        INSERT INTO abonos (apartado_id, monto_abono, monto_efectivo, monto_tarjeta, monto_transferencia, metodo_pago) 
        VALUES (?, ?, ?, ?, ?, ?)
    """, (apt[0], monto_abono, abono.monto_efectivo, abono.monto_tarjeta, abono.monto_transferencia, " / ".join(metodos_text)))

    if nuevo_estatus == 'Liquidado':
        cursor.execute("SELECT producto_id, cantidad FROM detalle_apartados WHERE apartado_id = ?", (apt[0],))
        items_apt = cursor.fetchall()
        for p_id, cant in items_apt:
            cursor.execute("UPDATE productos SET stock_apartado = MAX(0, stock_apartado - ?) WHERE id = ?", (cant, p_id))

    conn.commit()
    conn.close()
    return {
        "estatus": "exito", 
        "folio": folio_clean, 
        "monto_abono": monto_abono, 
        "saldo_pendiente": nuevo_saldo, 
        "estatus_apartado": nuevo_estatus
    }

@app.get("/devoluciones/historial/")
def obtener_historial_devoluciones():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT d.folio_devolucion, d.fecha, d.folio_venta, d.sku, COALESCE(p.nombre, d.sku), 
               d.tipo_devolucion, d.estado_producto, d.motivo, d.monto_reembolsado
        FROM devoluciones d
        LEFT JOIN productos p ON d.sku = p.sku
        ORDER BY d.id DESC LIMIT 100
    """)
    filas = cursor.fetchall()
    conn.close()
    return [{
        "folio_devolucion": f[0], "fecha": str(f[1]), "folio_venta": f[2], "sku": f[3],
        "mueble_nombre": f[4] or f[3], "tipo_devolucion": f[5], "estado_producto": f[6],
        "motivo": f[7], "monto_reembolsado": float(f[8])
    } for f in filas]

@app.post("/devoluciones/")
def registrar_devolucion(dev: DevolucionCreate):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        folio_vta = dev.folio_venta.strip().upper()
        sku_vta = dev.sku.strip().upper()

        cursor.execute("""
            SELECT dv.cantidad 
            FROM detalle_ventas dv 
            JOIN ventas v ON dv.venta_id = v.id 
            JOIN productos p ON dv.producto_id = p.id 
            WHERE v.folio = ? AND p.sku = ?
        """, (folio_vta, sku_vta))
        vta_item = cursor.fetchone()

        if not vta_item:
            cursor.execute("""
                SELECT da.cantidad 
                FROM detalle_apartados da 
                JOIN apartados a ON da.apartado_id = a.id 
                JOIN productos p ON da.producto_id = p.id 
                WHERE a.folio_apartado = ? AND p.sku = ?
            """, (folio_vta, sku_vta))
            vta_item = cursor.fetchone()

        if not vta_item:
            conn.close()
            raise HTTPException(status_code=400, detail=f"El SKU '{sku_vta}' no forma parte de la venta o apartado '{folio_vta}'.")

        cant_vendida = vta_item[0]

        cursor.execute("""
            SELECT COUNT(*) 
            FROM devoluciones 
            WHERE folio_venta = ? AND sku = ?
        """, (folio_vta, sku_vta))
        cant_ya_devuelta = cursor.fetchone()[0]

        if cant_ya_devuelta >= cant_vendida:
            conn.close()
            raise HTTPException(status_code=400, detail=f"⚠️ OPERACIÓN BLOQUEADA: El producto {sku_vta} del ticket {folio_vta} YA FUE DEVUELTO anteriormente.")

        cursor.execute("SELECT id FROM productos WHERE sku = ?", (sku_vta,))
        p = cursor.fetchone()
        if not p:
            conn.close()
            raise HTTPException(status_code=404, detail=f"El SKU '{sku_vta}' no existe en la base de datos.")

        cursor.execute("SELECT COUNT(*) FROM devoluciones")
        folio_dev = f"DEV-{cursor.fetchone()[0] + 1:06d}"

        cursor.execute("""
            INSERT INTO devoluciones (
                folio_devolucion, folio_venta, sku, tipo_devolucion, 
                estado_producto, motivo, monto_reembolsado, metodo_reembolso, usuario_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            folio_dev, folio_vta, sku_vta, dev.tipo_devolucion, 
            dev.estado_producto, dev.motivo, float(dev.monto_reembolsado), 
            dev.metodo_reembolso, int(dev.usuario_id or 1)
        ))

        if dev.estado_producto == "VentaInmediata":
            cursor.execute("UPDATE productos SET stock = stock + 1 WHERE id = ?", (p[0],))
            estatus_msg = "Mueble reingresado a Stock DISPONIBLE para Venta."
        else:
            cursor.execute("UPDATE productos SET stock_garantia = stock_garantia + 1 WHERE id = ?", (p[0],))
            estatus_msg = "Mueble ingresado como EN GARANTÍA / TALLER (No disponible para venta)."

        if dev.tipo_devolucion == "Devolucion/Dinero" and dev.monto_reembolsado > 0:
            concepto_gasto = f"REEMBOLSO CLIENTE - {folio_dev} (Origen: {folio_vta})"
            cursor.execute("""
                INSERT INTO gastos (concepto, categoria, monto, usuario_id)
                VALUES (?, 'Otros', ?, ?)
            """, (concepto_gasto, float(dev.monto_reembolsado), int(dev.usuario_id or 1)))

        conn.commit()
        conn.close()
        return {
            "estatus": "exito", 
            "folio_devolucion": folio_dev, 
            "mensaje": estatus_msg, 
            "monto_reembolsado": dev.monto_reembolsado
        }

    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=f"Error interno en base de datos: {str(e)}")

@app.post("/caja/abrir/")
def abrir_caja(caja: AperturaCaja):
    if caja.monto_inicial <= 0:
        raise HTTPException(status_code=400, detail="Ingresa un monto inicial válido de caja chica.")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO caja_chica (monto_inicial) VALUES (?)", (caja.monto_inicial,))
    conn.commit()
    conn.close()
    return {"estatus": "exito", "mensaje": f"Caja chica abierta con ${caja.monto_inicial:.2f}"}

@app.get("/gastos/resumen/")
def obtener_resumen_gastos(periodo: str = "semanal"):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        start_w, end_w = obtener_rango_semana()

        if periodo == "diario":
            filtro = "DATE(fecha) = DATE('now', 'localtime')"
        elif periodo == "semanal":
            filtro = f"DATE(fecha) >= '{start_w}' AND DATE(fecha) <= '{end_w}'"
        else:
            filtro = "DATE(fecha) >= DATE('now', '-30 days')"

        cursor.execute(f"SELECT id, fecha, concepto, categoria, monto FROM gastos WHERE {filtro} ORDER BY id DESC")
        gastos_filas = cursor.fetchall()
        total_gastos = sum(float(g[4]) for g in gastos_filas)

        filtro_v = "DATE(fecha) = DATE('now', 'localtime')" if periodo == "diario" else (f"DATE(fecha) >= '{start_w}' AND DATE(fecha) <= '{end_w}'" if periodo == "semanal" else "DATE(fecha) >= DATE('now', '-30 days')")
        filtro_a = "DATE(fecha_inicio) = DATE('now', 'localtime')" if periodo == "diario" else (f"DATE(fecha_inicio) >= '{start_w}' AND DATE(fecha_inicio) <= '{end_w}'" if periodo == "semanal" else "DATE(fecha_inicio) >= DATE('now', '-30 days')")

        cursor.execute(f"SELECT COALESCE(SUM(comision_vendedor), 0), COALESCE(SUM(comision_comisionista), 0) FROM ventas WHERE {filtro_v}")
        res_v = cursor.fetchone()
        com_vta_vendedor = res_v[0] if res_v else 0.0
        com_vta_comisionista = res_v[1] if res_v else 0.0

        cursor.execute(f"SELECT COALESCE(SUM(comision_vendedor), 0), COALESCE(SUM(comision_comisionista), 0) FROM apartados WHERE {filtro_a}")
        res_a = cursor.fetchone()
        com_apt_vendedor = res_a[0] if res_a else 0.0
        com_apt_comisionista = res_a[1] if res_a else 0.0

        total_comision_vendedor = float(com_vta_vendedor + com_apt_vendedor)
        total_comision_comisionista = float(com_vta_comisionista + com_apt_comisionista)
        total_comisiones = total_comision_vendedor + total_comision_comisionista

        cursor.execute(f"SELECT COALESCE(SUM(monto_inicial), 0) FROM caja_chica WHERE {filtro}")
        res_caja = cursor.fetchone()
        caja_inicial = float(res_caja[0]) if res_caja else 0.0

        conn.close()

        return {
            "periodo": periodo,
            "caja_inicial": caja_inicial,
            "total_gastos_registrados": float(total_gastos),
            "comision_vendedor_tienda": total_comision_vendedor,
            "comision_comisionista_redes": total_comision_comisionista,
            "total_comisiones": total_comisiones,
            "total_egresos_reales": float(total_gastos) + total_comisiones,
            "lista_gastos": [{
                "id": g[0], "fecha": str(g[1]), "concepto": g[2], "categoria": g[3], "monto": float(g[4])
            } for g in gastos_filas]
        }
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Error al calcular resumen de gastos: {str(e)}")

@app.post("/gastos/")
def registrar_gasto(gasto: GastoCreate):
    if gasto.monto <= 0 or not gasto.concepto.strip():
        raise HTTPException(status_code=400, detail="Ingresa una descripción y monto válido de gasto.")

    conn = get_connection()
    cursor = conn.cursor()

    fecha_sql = f"'{gasto.fecha_gasto} 12:00:00'" if (gasto.fecha_gasto and gasto.fecha_gasto.strip()) else "CURRENT_TIMESTAMP"

    cursor.execute(f"""
        INSERT INTO gastos (concepto, categoria, monto, fecha, usuario_id)
        VALUES (?, ?, ?, {fecha_sql}, ?)
    """, (gasto.concepto.strip(), gasto.categoria, float(gasto.monto), int(gasto.usuario_id or 1)))
    
    conn.commit()
    conn.close()
    return {"estatus": "exito", "mensaje": f"Gasto de ${gasto.monto:.2f} registrado correctamente."}

@app.put("/gastos/{gasto_id}/")
def editar_gasto(gasto_id: int, g: GastoEdit, rol_usuario: str):
    if rol_usuario != "Maestro":
        raise HTTPException(status_code=403, detail="Solo el Administrador Maestro puede editar gastos.")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE gastos SET concepto = ?, categoria = ?, monto = ? WHERE id = ?", (g.concepto, g.categoria, g.monto, gasto_id))
    conn.commit()
    conn.close()
    return {"estatus": "exito", "mensaje": "Gasto modificado correctamente."}

@app.get("/reportes/arqueo-corte/")
def obtener_reporte_arqueo(periodo: str = "semanal"):
    conn = get_connection()
    cursor = conn.cursor()

    start_w, end_w = obtener_rango_semana()

    if periodo == "diario":
        filtro_v = "DATE(v.fecha) = DATE('now', 'localtime')"
        filtro_a = "DATE(a.fecha) = DATE('now', 'localtime')"
        filtro_g = "DATE(fecha) = DATE('now', 'localtime')"
        filtro_d = "DATE(fecha) = DATE('now', 'localtime')"
        filtro_ab = "DATE(ab.fecha) = DATE('now', 'localtime')"
    elif periodo == "semanal":
        filtro_v = f"DATE(v.fecha) >= '{start_w}' AND DATE(v.fecha) <= '{end_w}'"
        filtro_a = f"DATE(a.fecha) >= '{start_w}' AND DATE(a.fecha) <= '{end_w}'"
        filtro_g = f"DATE(fecha) >= '{start_w}' AND DATE(fecha) <= '{end_w}'"
        filtro_d = f"DATE(fecha) >= '{start_w}' AND DATE(fecha) <= '{end_w}'"
        filtro_ab = f"DATE(ab.fecha) >= '{start_w}' AND DATE(ab.fecha) <= '{end_w}'"
    else:
        filtro_v = "DATE(v.fecha) >= DATE('now', '-30 days')"
        filtro_a = "DATE(a.fecha) >= DATE('now', '-30 days')"
        filtro_g = "DATE(fecha) >= DATE('now', '-30 days')"
        filtro_d = "DATE(fecha) >= DATE('now', '-30 days')"
        filtro_ab = "DATE(ab.fecha) >= DATE('now', '-30 days')"

    cursor.execute(f"""
        SELECT 
            CASE CAST(strftime('%w', fecha) AS INTEGER)
                WHEN 0 THEN 'DOMINGO' WHEN 1 THEN 'LUNES' WHEN 2 THEN 'MARTES'
                WHEN 3 THEN 'MIÉRCOLES' WHEN 4 THEN 'JUEVES' WHEN 5 THEN 'VIERNES' WHEN 6 THEN 'SÁBADO'
            END as dia_nombre,
            strftime('%d-%m', fecha) as fecha_corta,
            COALESCE(SUM(total_venta), 0),
            COALESCE(SUM(monto_efectivo), 0),
            COALESCE(SUM(monto_transferencia), 0),
            COALESCE(SUM(monto_tarjeta), 0)
        FROM ventas v
        WHERE {filtro_v}
        GROUP BY DATE(fecha)
        ORDER BY DATE(fecha) ASC
    """)
    tabla_filas = cursor.fetchall()

    cursor.execute(f"SELECT COALESCE(SUM(monto_efectivo),0), COALESCE(SUM(monto_tarjeta),0), COALESCE(SUM(monto_transferencia),0), COALESCE(SUM(total_venta),0) FROM ventas v WHERE {filtro_v}")
    tot_v = cursor.fetchone()

    cursor.execute(f"SELECT COALESCE(SUM(monto_efectivo),0), COALESCE(SUM(monto_tarjeta),0), COALESCE(SUM(monto_transferencia),0), COALESCE(SUM(monto_abono),0) FROM abonos a WHERE {filtro_a}")
    tot_a = cursor.fetchone()

    cursor.execute(f"SELECT COUNT(*), COALESCE(SUM(monto_reembolsado),0) FROM devoluciones WHERE {filtro_d}")
    tot_d = cursor.fetchone()

    cursor.execute(f"SELECT COALESCE(SUM(monto),0) FROM gastos WHERE {filtro_g}")
    tot_gastos = cursor.fetchone()[0]

    cursor.execute(f"SELECT folio_devolucion, strftime('%Y-%m-%d', fecha), sku, monto_reembolsado FROM devoluciones WHERE {filtro_d}")
    tabla_dev = cursor.fetchall()

    cursor.execute(f"""
        SELECT a.folio_apartado, strftime('%Y-%m-%d', ab.fecha), ab.metodo_pago, ab.monto_abono 
        FROM abonos ab JOIN apartados a ON ab.apartado_id = a.id 
        WHERE {filtro_ab}
    """)
    tabla_apt = cursor.fetchall()

    efectivo_ingresado = float(tot_v[0] + tot_a[0])
    tarjeta_ingresada = float(tot_v[1] + tot_a[1])
    transf_ingresada = float(tot_v[2] + tot_a[2])
    ingresos_totales = float(tot_v[3] + tot_a[3])

    efectivo_neto_caja = max(0.0, efectivo_ingresado - float(tot_gastos))
    balance_neto_total = max(0.0, ingresos_totales - float(tot_gastos))

    conn.close()

    return {
        "periodo": periodo,
        "efectivo_ingresado": efectivo_ingresado,
        "tarjeta_ingresada": tarjeta_ingresada,
        "transf_ingresada": transf_ingresada,
        "ingresos_totales": ingresos_totales,
        "total_gastos": float(tot_gastos),
        "efectivo_neto_caja": efectivo_neto_caja,
        "balance_neto_total": balance_neto_total,
        "ventas_directas": {
            "efectivo": float(tot_v[0]), "tarjeta": float(tot_v[1]), "transferencia": float(tot_v[2]), "total": float(tot_v[3])
        },
        "devoluciones": {
            "cantidad": tot_d[0], "monto_total": float(tot_d[1])
        },
        "apartados_abonos": {
            "efectivo": float(tot_a[0]), "tarjeta": float(tot_a[1]), "transferencia": float(tot_a[2]), "total": float(tot_a[3])
        },
        "tabla_filas": [{
            "dia": f[0], "fecha": f[1], "monto_venta": float(f[2]),
            "efectivo": float(f[3]), "transferencia": float(f[4]), "tarjeta": float(f[5])
        } for f in tabla_filas],
        "tabla_devoluciones": [{"folio": d[0], "fecha": str(d[1]), "sku": d[2], "monto": float(d[3])} for d in tabla_dev],
        "tabla_apartados": [{"folio": a[0], "fecha": str(a[1]), "metodo": a[2], "monto": float(a[3])} for a in tabla_apt]
    }

@app.get("/reportes/analisis-rentabilidad/")
def obtener_analisis_rentabilidad(pin_autorizador: str, periodo: str = "semanal"):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM usuarios WHERE pin = ? AND rol = 'Maestro'", (pin_autorizador.strip(),))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=403, detail="Acceso Restringido: PIN de Administrador Maestro requerido.")

    start_w, end_w = obtener_rango_semana()

    if periodo == "diario":
        filtro_v = "DATE(v.fecha) = DATE('now', 'localtime')"
        filtro_g = "DATE(fecha) = DATE('now', 'localtime')"
    elif periodo == "semanal":
        filtro_v = f"DATE(v.fecha) >= '{start_w}' AND DATE(v.fecha) <= '{end_w}'"
        filtro_g = f"DATE(fecha) >= '{start_w}' AND DATE(fecha) <= '{end_w}'"
    else:
        filtro_v = "DATE(v.fecha) >= DATE('now', '-30 days')"
        filtro_g = "DATE(fecha) >= DATE('now', '-30 days')"

    cursor.execute(f"""
        SELECT p.sku, p.nombre, p.tipo, COUNT(dv.id) as UnidadesVendidas,
               SUM(dv.precio_unitario_real) as VentaTotal,
               SUM(p.costo_compra) as InversionCOGS,
               SUM(dv.precio_unitario_real - p.costo_compra) as GananciaBrutaMueble
        FROM detalle_ventas dv
        JOIN ventas v ON dv.venta_id = v.id
        JOIN productos p ON dv.producto_id = p.id
        WHERE {filtro_v}
        GROUP BY p.id
        ORDER BY GananciaBrutaMueble DESC
    """)
    filas_muebles = cursor.fetchall()

    cursor.execute(f"SELECT COALESCE(SUM(monto), 0) FROM gastos WHERE {filtro_g}")
    total_gastos = float(cursor.fetchone()[0])

    cursor.execute(f"SELECT COALESCE(SUM(comision_vendedor + comision_comisionista), 0) FROM ventas v WHERE {filtro_v}")
    total_comisiones = float(cursor.fetchone()[0])

    ventas_totales = sum(float(f[4]) for f in filas_muebles)
    cogs_inversion = sum(float(f[5]) for f in filas_muebles)
    ganancia_bruta_acumulada = sum(float(f[6]) for f in filas_muebles)
    
    egresos_totales = total_gastos + total_comisiones
    ganancia_neta_real = ganancia_bruta_acumulada - egresos_totales
    roi_porcentaje = ((ganancia_neta_real / cogs_inversion) * 100) if cogs_inversion > 0 else 0.0

    conn.close()

    return {
        "periodo": periodo,
        "ventas_totales": ventas_totales,
        "cogs_inversion": cogs_inversion,
        "ganancia_bruta": ganancia_bruta_acumulada,
        "gastos_operativos": total_gastos,
        "comisiones_pagadas": total_comisiones,
        "ganancia_neta_real": ganancia_neta_real,
        "roi_porcentaje": roi_porcentaje,
        "detalle_muebles": [{
            "sku": m[0], "nombre": m[1], "tipo": m[2],
            "unidades": m[3], "venta_total": float(m[4]),
            "inversion_cogs": float(m[5]), "ganancia_bruta": float(m[6]),
            "roi_mueble": ((float(m[6]) / float(m[5])) * 100) if float(m[5]) > 0 else 0.0
        } for m in filas_muebles]
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
