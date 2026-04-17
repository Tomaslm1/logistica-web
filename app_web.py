import streamlit as st
import pandas as pd
import googlemaps
from datetime import datetime
import io
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors

# 1. CONFIGURACIÓN DE SEGURIDAD (Secrets)
# Usaremos st.secrets para no dejar tu llave a la vista en internet
try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    gmaps = googlemaps.Client(key=API_KEY)
except:
    st.error("⚠️ Error: No se configuró la GOOGLE_API_KEY en los Secrets.")
    st.stop()

# --- AQUÍ VAN TUS FUNCIONES DE INGENIERÍA (Heredadas de tu archivo .py) ---
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

def generar_pdf(ruta, todas_dir, todos_nom, pedidos_completos):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    y = 750
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, 800, "HOJA DE RUTA GENERADA")
    for i, idx in enumerate(ruta):
        if y < 100: c.showPage(); y = 750
        c.setFont("Helvetica-Bold", 10)
        c.drawString(50, y, f"PARADA {i}: {todos_nom[idx]}")
        c.setFont("Helvetica", 9)
        c.drawString(70, y-15, f"Dirección: {todas_dir[idx]}")
        y -= 40
    c.save()
    buffer.seek(0)
    return buffer

# ==========================================
# 3. INTERFAZ WEB (STREAMLIT)
# ==========================================
st.set_page_config(page_title="OptiRuta Web", page_icon="🚚")
st.title("🚚 Optimizador de Rutas Universal")

# --- SISTEMA DE LOGIN BÁSICO ---
st.sidebar.header("🔒 Acceso Restringido")
password = st.sidebar.text_input("Ingrese la contraseña:", type="password")

# Si la contraseña no es correcta, detenemos la aplicación aquí mismo
if password != "Timo2026": # Puedes cambiar esta contraseña por la que quieras
    st.warning("✋ Acceso denegado. Por favor, ingresa la contraseña correcta en el menú lateral.")
    st.stop() # Esta instrucción mágica evita que se cargue el resto de la página
# -------------------------------

# Sidebar
with st.sidebar:
    st.header("Configuración")
    inicio = st.text_input("📍 Partida", "Av. Grecia 3401, Peñalolén")
    fin = st.text_input("🏁 Término", "Av. Grecia 3401, Peñalolén")

# Carga de Archivo
archivo = st.file_uploader("📂 Sube tu Excel", type=["xlsx"])

if archivo:
    df = leer_excel_robusto(archivo)
    cols = ["-- No aplica --"] + list(df.columns)
    
    st.subheader("🔗 Mapeo de Columnas")
    c1, c2 = st.columns(2)
    with c1:
        m_dir = st.selectbox("Dirección", cols, index=1 if len(cols)>1 else 0)
        m_com = st.selectbox("Comuna", cols, index=2 if len(cols)>2 else 0)
    with c2:
        m_nom = st.selectbox("Nombre", cols)
        m_cont = st.selectbox("Contacto", cols)

    if st.button("🚀 Optimizar Ahora", type="primary"):
        with st.spinner("Calculando ruta óptima con Google Maps e IA..."):
            # Lógica de extracción (Filtro anti-ceros y anti-fantasmas)
            dir_ex, nom_ex, ped_ex = [], [], []
            for _, fila in df.iterrows():
                calle = limpiar_dato(fila[m_dir])
                comuna = limpiar_dato(fila[m_com])
                if not calle or not comuna: continue
                
                val = validar_direccion(f"{calle}, {comuna}")
                if val:
                    dir_ex.append(val)
                    nom_ex.append(limpiar_dato(fila[m_nom]) if m_nom != "-- No aplica --" else "Cliente")
                    ped_ex.append({'contacto': limpiar_dato(fila[m_cont]) if m_cont != "-- No aplica --" else None})
            
            ini_val = validar_direccion(inicio)
            fin_val = validar_direccion(fin)
            todas_dir = [ini_val] + dir_ex + [fin_val]
            todos_nom = ["Bodega"] + nom_ex + ["Retorno"]
            pedidos_completos = [{}] + ped_ex + [{}]
            
            matriz = obtener_matriz_tiempos(todas_dir)
            ruta = optimizar_ortools(matriz)
            
            if ruta:
                st.success("¡Ruta Optimizada!")
                pdf = generar_pdf(ruta, todas_dir, todos_nom, pedidos_completos)
                st.download_button("📄 Descargar Hoja de Ruta (PDF)", data=pdf, file_name="Ruta.pdf", mime="application/pdf")
                
                for i, idx in enumerate(ruta):
                    st.write(f"**Parada {i}:** {todos_nom[idx]} - {todas_dir[idx]}")
