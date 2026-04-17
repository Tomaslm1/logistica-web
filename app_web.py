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
# 1. CONFIGURACIÓN Y SEGURIDAD
# ==========================================
st.set_page_config(page_title="Sistema Logístico Universal", layout="wide")

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    gmaps = googlemaps.Client(key=API_KEY)
except:
    st.error("⚠️ Error: Configura 'GOOGLE_API_KEY' en los Secrets de Streamlit.")
    st.stop()

# LOGIN LATERAL
with st.sidebar:
    st.header("🔒 Acceso")
    pwd = st.text_input("Contraseña", type="password")
    if pwd != "Timo2026":
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
    claves = ['nombre', 'cliente', 'direcc', 'calle', 'comuna', 'fono', 'contacto']
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
    texto = str(valor).strip()
    return None if texto.lower() in ["nan", "", "none"] else texto

def validar_direccion(entrada):
    """Lógica estricta de validación (Igual a tu .py)"""
    try:
        res = gmaps.geocode(f"{entrada}, Santiago, Chile")
        if res:
            tipos = res[0].get('types', [])
            # Solo acepta si es una dirección exacta o recinto
            if 'street_address' not in tipos and 'premise' not in tipos and 'subpremise' not in tipos:
                return None, None
            return res[0]['formatted_address'], True
        return None, False
    except: return None, False

# ==========================================
# 3. GENERACIÓN DE PDF CORPORATIVO
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
        c.drawString(70, y, f"Dirección: {todas_dir[idx]}")
        y -= 12
        if p.get('contacto'): c.drawString(70, y, f"Tel: {p['contacto']}"); y -= 12
        
        # Productos (Verde)
        items = [f"{v} {k}" for k, v in p.get('productos', {}).items()]
        if items:
            c.setFont("Helvetica-BoldOblique", 10); c.setFillColor(colors.darkgreen)
            c.drawString(70, y, "PRODUCTOS: " + " | ".join(items)); c.setFillColor(colors.black); y -= 15
            
        # Efectivo (Rojo)
        if p.get('efectivo') and str(p['efectivo']).lower() in ['si', 'sí', '1', 'true']:
            c.setFont("Helvetica-Bold", 10); c.setFillColor(colors.red)
            c.drawString(70, y, "⚠️ COBRAR EN EFECTIVO"); c.setFillColor(colors.black); y -= 15
            
        y -= 20; c.line(50, y+10, width-50, y+10)
    c.save()
    buffer.seek(0)
    return buffer

# ==========================================
# 4. INTERFAZ WEB Y FLUJO DE VALIDACIÓN
# ==========================================
st.title("🚚 Sistema Logístico Pro (Web)")

archivo = st.file_uploader("Sube tu Excel", type=["xlsx"])

if archivo:
    df = leer_excel_robusto(archivo)
    cols_ex = ["-- No aplica --"] + list(df.columns)
    
    # Mapeador Dinámico
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

    # Productos dinámicos
    if 'campos' not in st.session_state: st.session_state.campos = []
    if st.button("+ Agregar Producto"): st.session_state.campos.append(len(st.session_state.campos))
    
    mapa_p = []
    for i in st.session_state.campos:
        cd1, cd2 = st.columns([2, 2])
        with cd1: np = st.text_input(f"Producto #{i}", key=f"n{i}")
        with cd2: cp = st.selectbox(f"Columna #{i}", cols_ex, key=f"c{i}")
        if np and cp != "-- No aplica --": mapa_p.append({"n": np, "c": cp})

    st.divider()

    # --- PASO 1: VALIDACIÓN DE DIRECCIONES (El reemplazo del Popup) ---
    if st.button("🔍 Validar Direcciones y Datos", type="primary", use_container_width=True):
        st.session_state.listos = []
        st.session_state.errores = []
        
        with st.spinner("Validando con Google Maps..."):
            for _, fila in df.iterrows():
                # Filtro de Totales/Resúmenes
                nom_c = limpiar_dato(fila[m_nom]) if m_nom != "-- No aplica --" else None
                if nom_c and any(x in str(nom_c).lower() for x in ['total', 'subtotal', 'resumen']): continue
                
                calle = limpiar_dato(fila[m_dir])
                comuna = limpiar_dato(fila[m_com])
                
                if not calle or not comuna: continue
                
                full_dir = f"{calle}, {comuna}"
                validada, es_exacta = validar_direccion(full_dir)
                
                # Extracción de productos (Filtro anti-ceros)
                prods = {}
                for p in mapa_p:
                    v = limpiar_dato(fila[p['c']])
                    if v and str(v) not in ["0", "0.0", "0,0"]: prods[p['n']] = v

                datos_cliente = {
                    'nombre': str(nom_c) if nom_c else "Cliente",
                    'dir_original': full_dir,
                    'dir_validada': validada,
                    'contacto': limpiar_dato(fila[m_cont]) if m_cont != "-- No aplica --" else None,
                    'depto': limpiar_dato(fila[m_depto]) if m_depto != "-- No aplica --" else None,
                    'efectivo': fila[m_efec] if m_efec != "-- No aplica --" else None,
                    'productos': prods
                }

                if validada and es_exacta:
                    st.session_state.listos.append(datos_cliente)
                else:
                    st.session_state.errores.append(datos_cliente)

    # Mostrar Errores para corrección manual (FUNCIONALIDAD POPUP)
    if 'errores' in st.session_state and st.session_state.errores:
        st.error(f"⚠️ Se encontraron {len(st.session_state.errores)} direcciones dudosas. Por favor, corrígelas:")
        for i, err in enumerate(st.session_state.errores):
            new_val = st.text_input(f"Corregir para: {err['nombre']}", value=err['dir_original'], key=f"err{i}")
            if st.button(f"Validar Corrección {i}"):
                v, exact = validar_direccion(new_val)
                if v and exact:
                    err['dir_validada'] = v
                    st.session_state.listos.append(err)
                    st.session_state.errores.pop(i)
                    st.rerun()

    # --- PASO 2: OPTIMIZACIÓN FINAL ---
    if 'listos' in st.session_state and st.session_state.listos and not st.session_state.errores:
        st.success(f"✅ {len(st.session_state.listos)} direcciones listas para optimizar.")
        
        if st.button("🚀 CALCULAR RUTA ÓPTIMA", use_container_width=True):
            # Aquí va el motor de OR-Tools que ya tienes
            # ... (obtener matriz, llamar motor, generar PDF, mostrar botones de tramos)
            st.balloons()
