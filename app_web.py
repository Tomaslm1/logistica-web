import streamlit as st
import pandas as pd
import googlemaps
from datetime import datetime
import io
import urllib.parse
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors

# ==========================================
# 1. SEGURIDAD Y CONFIGURACIÓN WEB
# ==========================================
st.set_page_config(page_title="Sistema Logístico", layout="wide", initial_sidebar_state="expanded")

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    gmaps = googlemaps.Client(key=API_KEY)
except Exception:
    st.error("⚠️ Configura 'GOOGLE_API_KEY' en los Secrets de Streamlit Cloud.")
    st.stop()

# --- LOGIN ---
with st.sidebar:
    st.header("🔒 Acceso")
    pwd = st.text_input("Contraseña", type="password")
    if pwd != "Timo2026": 
        st.warning("Ingresa la clave para activar el sistema.")
        st.stop()
    
    st.divider()
    st.header("📍 Puntos de Control")
    dir_inicio = st.text_input("Punto de Partida", "Av. Grecia 3401, Peñalolén")
    dir_fin = st.text_input("Punto de Retorno", "Av. Grecia 3401, Peñalolén")

# ==========================================
# 2. FUNCIONES DE INGENIERÍA
# ==========================================
def leer_excel_robusto(archivo):
    df_crudo = pd.read_excel(archivo, header=None)
    mejor_fila, max_coincidencias = 0, 0
    palabras_clave = ['nombre', 'cliente', 'direcc', 'calle', 'comuna', 'ciudad', 'fono', 'contacto']
    for i in range(min(20, len(df_crudo))):
        fila_texto = " ".join([str(x).lower() for x in df_crudo.iloc[i].values if pd.notna(x)])
        coincidencias = sum(1 for p in palabras_clave if p in fila_texto)
        if coincidencias > max_coincidencias:
            max_coincidencias, mejor_fila = coincidencias, i
    df_limpio = pd.read_excel(archivo, header=mejor_fila)
    df_limpio.columns = [str(col).strip() if not str(col).startswith('Unnamed') else f"Columna {i}" for i, col in enumerate(df_limpio.columns)]
    return df_limpio.dropna(how='all')

def limpiar_dato(valor):
    if pd.isna(valor): return None
    texto = str(valor).strip()
    return None if texto.lower() in ["nan", "", "none"] else texto

def validar_direccion(entrada):
    try:
        res = gmaps.geocode(f"{entrada}, Santiago, Chile")
        return res[0]['formatted_address'] if res else None
    except: return None

def obtener_matriz_tiempos(direcciones):
    n = len(direcciones)
    matriz = [[0 for _ in range(n)] for _ in range(n)]
    for i in range(0, n, 10):
        for j in range(0, n, 10):
            res = gmaps.distance_matrix(direcciones[i:i+10], direcciones[j:j+10], mode='driving')
            for f_idx, fila in enumerate(res['rows']):
                for c_idx, elem in enumerate(fila['elements']):
                    matriz[i+f_idx][j+c_idx] = elem['duration']['value'] if elem['status'] == 'OK' else 999999
    return matriz

def optimizar_ortools(matriz):
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

def generar_url_maps(tramo_indices, todas_dir):
    """Genera la URL exacta de Google Maps para el navegador o celular"""
    base_url = "https://www.google.com/maps/dir/"
    puntos = [urllib.parse.quote(todas_dir[idx]) for idx in tramo_indices]
    return base_url + "/".join(puntos)

# ==========================================
# 3. GENERACIÓN DE PDF (DISEÑO ORIGINAL RESTAURADO)
# ==========================================
def generar_pdf_identico(ruta, todas_dir, todos_nom, pedidos):
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
        info = pedidos[idx]
        
        c.setFont("Helvetica-Bold", 12)
        tipo = f"PARADA #{i}" if (i != 0 and i != len(ruta)-1) else "PUNTO DE CONTROL"
        c.drawString(50, y, f"{tipo}: {todos_nom[idx]}")
        y -= 15
        
        c.setFont("Helvetica", 10)
        direccion = todas_dir[idx]
        if info.get('depto'): direccion += f" (Depto: {info['depto']})"
        c.drawString(70, y, f"Dirección: {direccion}")
        y -= 12
        if info.get('contacto'): c.drawString(70, y, f"Teléfono: {info['contacto']}"); y -= 12

        if i != 0 and i != len(ruta)-1:
            items = []
            for nombre_prod, cant_prod in info.get('productos', {}).items():
                items.append(f"{cant_prod} {nombre_prod}")
            
            if items:
                c.setFont("Helvetica-BoldOblique", 10)
                c.setFillColor(colors.darkgreen)
                c.drawString(70, y, "PRODUCTOS: " + " | ".join(items))
                c.setFillColor(colors.black)
                y -= 15
                
            if info.get('efectivo') and str(info['efectivo']).lower() in ['si', 'sí', 'yes', '1', 'true', 'efectivo']:
                c.setFont("Helvetica-Bold", 10)
                c.setFillColor(colors.red)
                c.drawString(70, y, "⚠️ COBRAR EN EFECTIVO")
                c.setFillColor(colors.black)
                y -= 15
                
        y -= 20 
        c.line(50, y+10, width-50, y+10) 
    c.save()
    buffer.seek(0)
    return buffer

# ==========================================
# 4. INTERFAZ PRINCIPAL
# ==========================================
st.title("🚚 Optimizador de Rutas")
archivo = st.file_uploader("Sube tu Excel de despachos", type=["xlsx"])

if archivo:
    df = leer_excel_robusto(archivo)
    cols = ["-- No aplica --"] + list(df.columns)
    
    st.subheader("📋 Mapeo de Columnas")
    c1, c2, c3 = st.columns(3)
    with c1:
        m_dir = st.selectbox("Dirección (Obligatorio)", cols, index=1 if len(cols)>1 else 0)
        m_nom = st.selectbox("Nombre Cliente", cols)
    with c2:
        m_com = st.selectbox("Comuna (Obligatorio)", cols, index=2 if len(cols)>2 else 0)
        m_cont = st.selectbox("Contacto/Teléfono", cols)
    with c3:
        m_depto = st.selectbox("Depto/Casa", cols)
        m_efect = st.selectbox("Pago Efectivo", cols)

    st.divider()
    st.subheader("📦 Productos")
    if 'dinamicos' not in st.session_state: st.session_state.dinamicos = []
    
    if st.button("+ Agregar Producto"):
        st.session_state.dinamicos.append(len(st.session_state.dinamicos))

    mapa_prod = []
    for i in st.session_state.dinamicos:
        d1, d2, d3 = st.columns([2, 2, 1])
        with d1: n_p = st.text_input(f"Nombre #{i}", key=f"n{i}", placeholder="Ej: Huevos")
        with d2: c_p = st.selectbox(f"Columna #{i}", cols, key=f"c{i}")
        if n_p and c_p != "-- No aplica --":
            mapa_prod.append({"nombre": n_p, "col": c_p})

    if st.button("🚀 Calcular Ruta Óptima", type="primary", use_container_width=True):
        with st.spinner("Procesando direcciones y calculando tráfico..."):
            dir_ex, nom_ex, ped_ex = [], [], []
            for _, fila in df.iterrows():
                calle_l = limpiar_dato(fila[m_dir])
                comuna_l = limpiar_dato(fila[m_com])
                if not calle_l or not comuna_l: continue
                
                nombre_c = limpiar_dato(fila[m_nom]) if m_nom != "-- No aplica --" else None
                if nombre_c and any(p in str(nombre_c).lower() for p in ['total', 'subtotal', 'resumen']): continue
                
                val = validar_direccion(f"{calle_l}, {comuna_l}")
                if val:
                    dir_ex.append(val)
                    nom_ex.append(str(nombre_c) if nombre_c else "Cliente")
                    
                    prods = {}
                    for p in mapa_prod:
                        v = limpiar_dato(fila[p['col']])
                        if v and str(v) not in ["0", "0.0", "0,0"]:
                            prods[p['nombre']] = v
                    
                    ped_ex.append({
                        'contacto': limpiar_dato(fila[m_cont]) if m_cont != "-- No aplica --" else None,
                        'depto': limpiar_dato(fila[m_depto]) if m_depto != "-- No aplica --" else None,
                        'efectivo': fila[m_efect] if m_efect != "-- No aplica --" else None,
                        'productos': prods
                    })

            ini_val = validar_direccion(dir_inicio)
            fin_val = validar_direccion(dir_fin)
            todas_dir = [ini_val] + dir_ex + [fin_val]
            todos_nom = ["INICIO"] + nom_ex + ["FINAL"]
            pedidos_full = [{}] + ped_ex + [{}]
            
            matriz = obtener_matriz_tiempos(todas_dir)
            ruta = optimizar_ortools(matriz)
            
            if ruta:
                st.success("¡Ruta calculada con éxito!")
                
                # --- BOTÓN DE DESCARGA PDF ---
                pdf_file = generar_pdf_identico(ruta, todas_dir, todos_nom, pedidos_full)
                st.download_button("📄 Descargar Hoja de Ruta (PDF)", pdf_file, "Hoja_Ruta.pdf", "application/pdf")
                
                st.divider()
                st.subheader("🗺️ Navegación por Tramos (Google Maps)")
                
                # --- BOTONES DE GOOGLE MAPS RESTAURADOS ---
                # Dividimos la ruta en tramos de 9 paradas (límite clásico de Maps)
                tramos_cols = st.columns(3)
                for i in range(0, len(ruta) - 1, 9):
                    tramo = ruta[i : i + 10]
                    url_maps = generar_url_maps(tramo, todas_dir)
                    num_tramo = i // 9 + 1
                    tramos_cols[(num_tramo - 1) % 3].link_button(f"🚙 Navegar Tramo {num_tramo}", url_maps, use_container_width=True)

                st.divider()
                st.subheader("Detalle de Paradas")
                
                # Renderizado estilo "tarjetas" oscuro de las paradas
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
                        if info.get('efectivo') and str(info['efectivo']).lower() in ['si', 'sí', '1', 'true']:
                            st.error("⚠️ PAGO EN EFECTIVO PENDIENTE")
