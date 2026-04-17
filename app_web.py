import streamlit as st
import pandas as pd
import googlemaps
from datetime import datetime
import io
import urllib.parse
import uuid  # NUEVO: Para crear IDs únicos y evitar que los textos se mezclen
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors

# ==========================================
# 1. CONFIGURACIÓN Y SEGURIDAD
# ==========================================
st.set_page_config(page_title="Sistema Logístico", layout="wide")

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    gmaps = googlemaps.Client(key=API_KEY)
except Exception:
    st.error("⚠️ Error: Configura 'GOOGLE_API_KEY' en los Secrets de Streamlit.")
    st.stop()

# LOGIN LATERAL
with st.sidebar:
    st.header("🔒 Acceso")
    pwd = st.text_input("Contraseña", type="password")
    
    # Extraemos la contraseña de la caja fuerte virtual
    CLAVE_SECRETA = st.secrets["APP_PASSWORD"]
    
    if pwd != CLAVE_SECRETA:
        st.warning("Ingresa la clave para activar.")
        st.stop()

    
    st.divider()
    st.header("📍 Puntos Base")
    dir_inicio = st.text_input("Inicio", "Av. Grecia 3401, Peñalolén")
    dir_fin = st.text_input("Término", "Av. Grecia 3401, Peñalolén")

# ==========================================
# 2. FUNCIONES DE INGENIERÍA (PORTADAS 1:1)
# ==========================================
def leer_excel_robusto(archivo):
    df_crudo = pd.read_excel(archivo, header=None)
    mejor_fila, max_coincidencias = 0, 0
    claves = ['nombre', 'cliente', 'direcc', 'calle', 'comuna', 'fono', 'contacto', 'producto', 'cant']
    for i in range(min(20, len(df_crudo))):
        fila_txt = " ".join([str(x).lower() for x in df_crudo.iloc[i].values if pd.notna(x)])
        coincidencias = sum(1 for p in claves if p in fila_txt)
        if coincidencias > max_coincidencias:
            max_coincidencias, mejor_fila = coincidencias, i
    df = pd.read_excel(archivo, header=mejor_fila)
    df.columns = [str(c).strip() if not str(c).startswith('Unnamed') else f"Col {i}" for i, c in enumerate(df.columns)]
    return df.dropna(how='all')

def limpiar_dato(valor):
    if pd.isna(valor): return None
    # EL ESCUDO ANTI-DECIMALES: Si es un número, le quita el .0 antes de hacerlo texto
    if isinstance(valor, (int, float)):
        return str(int(valor)) if valor == int(valor) else str(valor)
    texto = str(valor).strip()
    return None if texto.lower() in ["nan", "", "none"] else texto

def formatear_telefono(numero):
    """Convierte cualquier número desordenado en un formato limpio y profesional"""
    if not numero: return None
    # Quitamos espacios, guiones o cualquier texto, dejando solo números
    num = "".join(c for c in str(numero) if c.isdigit())
    
    # Formateo visual (Ajustado para Chile)
    if len(num) == 11 and num.startswith("56"): 
        return f"+{num[:2]} {num[2]} {num[3:7]} {num[7:]}"
    elif len(num) == 8: 
        return f"+56 9 {num[:4]} {num[4:]}"
    elif len(num) == 9 and num.startswith("9"): 
        return f"+56 {num[:1]} {num[1:5]} {num[5:]}"
    return f"+{num}" if num else None
def validar_direccion(entrada):
    try:
        res = gmaps.geocode(f"{entrada}, Santiago, Chile")
        if res:
            tipos = res[0].get('types', [])
            if 'street_address' not in tipos and 'premise' not in tipos and 'subpremise' not in tipos:
                return None, False
            return res[0]['formatted_address'], True
        return None, False
    except: return None, False

def obtener_matriz_tiempos_completa(direcciones):
    n = len(direcciones)
    matriz = [[0 for _ in range(n)] for _ in range(n)]
    for i in range(0, n, 10):
        for j in range(0, n, 10):
            try:
                res = gmaps.distance_matrix(direcciones[i:i+10], direcciones[j:j+10], mode='driving')
                for f_idx, fila in enumerate(res['rows']):
                    for c_idx, elem in enumerate(fila['elements']):
                        matriz[i+f_idx][j+c_idx] = elem['duration']['value'] if elem['status'] == 'OK' else 999999
            except:
                pass 
    return matriz

def optimizar_con_ortools(matriz):
    n = len(matriz)
    manager = pywrapcp.RoutingIndexManager(n, 1, [0], [n - 1])
    routing = pywrapcp.RoutingModel(manager)
    def cb(f, t): return matriz[manager.IndexToNode(f)][manager.IndexToNode(t)]
    idx_cb = routing.RegisterTransitCallback(cb)
    routing.SetArcCostEvaluatorOfAllVehicles(idx_cb)
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    solucion = routing.SolveWithParameters(params)
    if solucion:
        ruta = []
        idx = routing.Start(0)
        while not routing.IsEnd(idx):
            ruta.append(manager.IndexToNode(idx))
            idx = solucion.Value(routing.NextVar(idx))
        ruta.append(manager.IndexToNode(idx))
        return ruta
    return None

# ==========================================
# 3. GENERACIÓN DE PDF Y URLs
# ==========================================
def generar_pdf_original(ruta, todas_dir, todos_nom, pedidos):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, "HOJA DE RUTA - DESPACHO INTELIGENTE")
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 65, "Generado por Sistema de Optimización Logística")
    c.line(50, height - 75, width - 50, height - 75)

    y = height - 100
    for i, idx in enumerate(ruta):
        if y < 100: c.showPage(); y = height - 50
        p = pedidos[idx]
        c.setFont("Helvetica-Bold", 12)
        tipo = f"PARADA #{i}" if (0 < i < len(ruta)-1) else "PUNTO DE CONTROL"
        c.drawString(50, y, f"{tipo}: {todos_nom[idx]}")
        y -= 15
        
        c.setFont("Helvetica", 10)
        
        # --- SOLUCIÓN: Agregamos el Depto a la dirección del PDF ---
        direccion_str = todas_dir[idx]
        if p.get('depto'): 
            direccion_str += f" (Depto: {p['depto']})"
            
        c.drawString(70, y, f"Dirección: {direccion_str}")
        y -= 12
        
        if p.get('contacto'): c.drawString(70, y, f"Tel: {p['contacto']}"); y -= 12
        
        items = [f"{v} {k}" for k, v in p.get('productos', {}).items()]
        if items:
            c.setFont("Helvetica-BoldOblique", 10); c.setFillColor(colors.darkgreen)
            c.drawString(70, y, "PRODUCTOS: " + " | ".join(items)); c.setFillColor(colors.black); y -= 15
            
        if p.get('efectivo') and str(p['efectivo']).lower() in ['si', 'sí', '1', 'true', 'efectivo']:
            c.setFont("Helvetica-Bold", 10); c.setFillColor(colors.red)
            c.drawString(70, y, "⚠️ COBRAR EN EFECTIVO"); c.setFillColor(colors.black); y -= 15
            
        y -= 20; c.line(50, y+10, width-50, y+10)
    c.save()
    buffer.seek(0)
    return buffer

def generar_url_maps(tramo_indices, todas_dir):
    base_url = "https://www.google.com/maps/dir/"
    puntos = [urllib.parse.quote(todas_dir[idx]) for idx in tramo_indices]
    return base_url + "/".join(puntos)

# ==========================================
# 4. INTERFAZ WEB Y FLUJO DE VALIDACIÓN
# ==========================================
st.title("🚚 Sistema Logístico")

archivo = st.file_uploader("Sube tu Excel", type=["xlsx"])

if archivo:
    df = leer_excel_robusto(archivo)
    cols_ex = ["-- No aplica --"] + list(df.columns)
    
    st.subheader("🔗 Configuración de Columnas")
    c1, c2, c3 = st.columns(3)
    with c1:
        m_dir = st.selectbox("Dirección *", cols_ex, index=1 if len(cols_ex)>1 else 0)
        m_nom = st.selectbox("Nombre Cliente", cols_ex)
    with c2:
        m_com = st.selectbox("Comuna *", cols_ex, index=2 if len(cols_ex)>2 else 0)
        m_cont = st.selectbox("Teléfono", cols_ex)
    with c3:
        m_depto = st.selectbox("Depto/Casa", cols_ex)
        m_efec = st.selectbox("Pago Efectivo", cols_ex)

    if 'campos' not in st.session_state: st.session_state.campos = []
    if st.button("+ Agregar Producto"): st.session_state.campos.append(len(st.session_state.campos))
    
    mapa_p = []
    for i in st.session_state.campos:
        cd1, cd2 = st.columns([2, 2])
        with cd1: np = st.text_input(f"Producto #{i}", key=f"n{i}")
        with cd2: cp = st.selectbox(f"Columna #{i}", cols_ex, key=f"c{i}")
        if np and cp != "-- No aplica --": mapa_p.append({"n": np, "c": cp})

    st.divider()

    if st.button("🔍 Validar Direcciones y Datos", type="primary", use_container_width=True):
        st.session_state.listos = []
        st.session_state.errores = []
        
        with st.spinner("Validando con Google Maps..."):
            for _, fila in df.iterrows():
                nom_c = limpiar_dato(fila[m_nom]) if m_nom != "-- No aplica --" else None
                if nom_c and any(x in str(nom_c).lower() for x in ['total', 'subtotal', 'resumen']): continue
                
                calle = limpiar_dato(fila[m_dir])
                comuna = limpiar_dato(fila[m_com])
                if not calle or not comuna: continue
                
                full_dir = f"{calle}, {comuna}"
                validada, es_exacta = validar_direccion(full_dir)
                
                prods = {}
                for p in mapa_p:
                    v = limpiar_dato(fila[p['c']])
                    if v and str(v) not in ["0", "0.0", "0,0"]: prods[p['n']] = v

                datos_cliente = {
                    'id': str(uuid.uuid4()),  # <--- ESTO SOLUCIONA EL BUG DE LAS CAJAS DE TEXTO
                    'nombre': str(nom_c) if nom_c else "Cliente",
                    'dir_original': full_dir,
                    'dir_validada': validada,
                    'contacto': formatear_telefono(limpiar_dato(fila[m_cont])) if m_cont != "-- No aplica --" else None,
                    'depto': limpiar_dato(fila[m_depto]) if m_depto != "-- No aplica --" else None,
                    'efectivo': fila[m_efec] if m_efec != "-- No aplica --" else None,
                    'productos': prods
                }

                if validada and es_exacta:
                    st.session_state.listos.append(datos_cliente)
                else:
                    st.session_state.errores.append(datos_cliente)

    # --- PANTALLA DE CORRECCIÓN (SABUESO ANTI-BUGS) ---
    if 'errores' in st.session_state and st.session_state.errores:
        st.error(f"⚠️ Se encontraron {len(st.session_state.errores)} direcciones dudosas. Por favor, corrígelas:")
        
        # Usamos una copia de la lista para iterar seguros
        for err in list(st.session_state.errores):
            cols_err = st.columns([4, 1])
            with cols_err[0]:
                # Usamos el ID único de este error específico para la llave, así Streamlit nunca los mezcla
                new_val = st.text_input(f"Corregir para: {err['nombre']}", value=err['dir_original'], key=f"input_{err['id']}")
            with cols_err[1]:
                st.write("") # Espacio para alinear el botón
                st.write("")
                if st.button("Validar", key=f"btn_{err['id']}"):
                    v, exact = validar_direccion(new_val)
                    if v and exact:
                        err['dir_validada'] = v
                        # Encontramos el error en la lista original y lo sacamos
                        idx = next((index for (index, d) in enumerate(st.session_state.errores) if d["id"] == err["id"]), None)
                        if idx is not None:
                            st.session_state.listos.append(err)
                            st.session_state.errores.pop(idx)
                            st.rerun()
                    else:
                        st.error("Sigue ambigua.")

    if 'listos' in st.session_state and st.session_state.listos and not st.session_state.errores:
        st.success(f"✅ {len(st.session_state.listos)} direcciones listas para optimizar.")
        
        if st.button("🚀 CALCULAR RUTA ÓPTIMA", use_container_width=True):
            with st.spinner("Construyendo matriz de tráfico y calculando con IA..."):
                dir_ex = [d['dir_validada'] for d in st.session_state.listos]
                nom_ex = [d['nombre'] for d in st.session_state.listos]
                ped_ex = [{'contacto': d['contacto'], 'depto': d['depto'], 'efectivo': d['efectivo'], 'productos': d['productos']} for d in st.session_state.listos]

                ini_val, _ = validar_direccion(dir_inicio)
                fin_val, _ = validar_direccion(dir_fin)
                
                todas_dir = [ini_val if ini_val else dir_inicio] + dir_ex + [fin_val if fin_val else dir_fin]
                todos_nom = ["INICIO BODEGA"] + nom_ex + ["FIN TURNO"]
                pedidos_full = [{}] + ped_ex + [{}]
                
                matriz = obtener_matriz_tiempos_completa(todas_dir)
                
                if matriz:
                    ruta = optimizar_con_ortools(matriz)
                    
                    if ruta:
                        st.success("¡Ruta calculada con éxito!")
                        # GLOBOS ELIMINADOS
                        
                        pdf_file = generar_pdf_original(ruta, todas_dir, todos_nom, pedidos_full)
                        st.download_button("📄 Descargar Hoja de Ruta (PDF)", pdf_file, "Hoja_Ruta.pdf", "application/pdf")
                        
                        st.divider()
                        st.subheader("🗺️ Navegación por Tramos (Google Maps)")
                        
                        tramos_cols = st.columns(3)
                        for i in range(0, len(ruta) - 1, 9):
                            tramo = ruta[i : i + 10]
                            url_maps = generar_url_maps(tramo, todas_dir)
                            num_tramo = i // 9 + 1
                            tramos_cols[(num_tramo - 1) % 3].link_button(f"🚙 Navegar Tramo {num_tramo}", url_maps, use_container_width=True)

                        st.divider()
                        st.subheader("Detalle de Paradas")
                        
                        for i, idx in enumerate(ruta):
                            with st.expander(f"Parada {i} - {todos_nom[idx]}", expanded=(i==1)):
                                st.write(f"📍 **Dirección:** {todas_dir[idx]}")
                                info = pedidos_full[idx]
                                if info.get('depto'): st.write(f"🏢 **Depto/Casa:** {info['depto']}")
                                if info.get('contacto'): st.write(f"📞 **Contacto:** {info['contacto']}")
                                if info.get('productos'):
                                    st.markdown("📦 **Productos a entregar:**")
                                    for k, v in info['productos'].items():
                                        st.success(f"{v} {k}")
                                if info.get('efectivo') and str(info['efectivo']).lower() in ['si', 'sí', '1', 'true', 'efectivo']:
                                    st.error("⚠️ PAGO EN EFECTIVO PENDIENTE")
                else:
                    st.error("❌ Error al contactar con Google Maps (Distance Matrix).")
