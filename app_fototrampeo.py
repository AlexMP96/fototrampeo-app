import streamlit as st
import easyocr
import pandas as pd
import requests
from datetime import datetime
from PIL import Image
import io
import re
from astral import moon
import numpy as np
from supabase import create_client, Client
import uuid

st.set_page_config(page_title="Registro Fototrampeo", layout="wide")
st.title("📋 Registro de Fototrampeo")
st.markdown("Sube fotos → se leen solas y se guardan **permanentemente**.")

# ========== CONFIGURACIÓN SUPABASE ==========
# Sustituye estos valores por los de tu proyecto Supabase
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "TU_SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "TU_SUPABASE_ANON_KEY")
BUCKET_NAME = "fototrampeo"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Sidebar
st.sidebar.header("Datos del lote")
especie = st.sidebar.text_input("Especie", placeholder="Ej: Jabalí")
camara = st.sidebar.text_input("Cámara", placeholder="Ej: Cam1")
localidad = st.sidebar.text_input("Localidad", placeholder="Ej: Coto El Roble")
lat = st.sidebar.number_input("Latitud", value=40.0, format="%.6f")
lon = st.sidebar.number_input("Longitud", value=-3.7, format="%.6f")

uploaded_files = st.file_uploader(
    "Sube las fotos",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True
)

def extract_datetime(image_bytes):
    try:
        reader = easyocr.Reader(['en'], gpu=False, verbose=False)
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        crop = img.crop((0, int(height * 0.85), width, height))
        results = reader.readtext(np.array(crop), detail=0)
        text = " ".join(results)
        
        patterns = [
            r'(\d{4}[/-]\d{2}[/-]\d{2})\s+(\d{2}:\d{2}:\d{2})',
            r'(\d{2}[/-]\d{2}[/-]\d{4})\s+(\d{2}:\d{2}:\d{2})',
            r'(\d{4}[/-]\d{2}[/-]\d{2})\s+(\d{2}:\d{2})',
            r'(\d{2}[/-]\d{2}[/-]\d{4})\s+(\d{2}:\d{2})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                date_str, time_str = match.groups()
                date_str = date_str.replace('/', '-')
                if len(date_str.split('-')[0]) == 2:
                    parts = date_str.split('-')
                    date_str = f"{parts[2]}-{parts[1]}-{parts[0]}"
                dt_str = f"{date_str} {time_str}"
                try:
                    return datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                except:
                    try:
                        return datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                    except:
                        continue
        return None
    except:
        return None

def get_weather_data(lat, lon, dt):
    try:
        date_str = dt.strftime("%Y-%m-%d")
        hour = dt.hour
        url = "https://archive-api.open-meteo.com/v1/archive"
        params = {
            "latitude": lat, "longitude": lon,
            "start_date": date_str, "end_date": date_str,
            "hourly": "temperature_2m,relative_humidity_2m,cloud_cover,wind_speed_10m,wind_direction_10m,surface_pressure,precipitation,shortwave_radiation",
            "timezone": "auto"
        }
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        if "hourly" in data and len(data["hourly"]["temperature_2m"]) > hour:
            return {
                "temperatura": data["hourly"]["temperature_2m"][hour],
                "humedad": data["hourly"]["relative_humidity_2m"][hour],
                "nubes": data["hourly"]["cloud_cover"][hour],
                "viento_vel": data["hourly"]["wind_speed_10m"][hour],
                "viento_dir": data["hourly"]["wind_direction_10m"][hour],
                "presion": data["hourly"]["surface_pressure"][hour],
                "precipitacion": data["hourly"]["precipitation"][hour],
                "radiacion": data["hourly"]["shortwave_radiation"][hour],
            }
    except:
        pass
    return {}

def get_moon_phase(dt):
    try:
        phase = moon.phase(dt.date())
        if phase < 1: return "Luna nueva", 0
        elif phase < 7: return "Creciente", round(phase / 14 * 100)
        elif phase < 14: return "Llena", 100
        elif phase < 21: return "Menguante", round((28 - phase) / 14 * 100)
        else: return "Luna nueva", 0
    except:
        return "Desconocida", None

def load_registros():
    try:
        response = supabase.table("registros_fototrampeo").select("*").order("id", desc=True).execute()
        return response.data
    except:
        return []

# Procesar y guardar permanentemente
if st.button("➕ Procesar y guardar permanentemente", type="primary") and uploaded_files:
    if not especie or not camara:
        st.error("Rellena especie y cámara.")
    else:
        with st.spinner("Procesando y guardando en la nube..."):
            for uploaded_file in uploaded_files:
                image_bytes = uploaded_file.getvalue()
                dt = extract_datetime(image_bytes)
                
                if dt is None:
                    st.warning(f"No se leyó fecha/hora en {uploaded_file.name}")
                    continue
                
                weather = get_weather_data(lat, lon, dt)
                moon_name, moon_pct = get_moon_phase(dt)
                
                # Subir foto a Supabase Storage
                file_name = f"{uuid.uuid4()}.jpg"
                try:
                    supabase.storage.from_(BUCKET_NAME).upload(
                        file_name,
                        image_bytes,
                        {"content-type": "image/jpeg", "upsert": "true"}
                    )
                    # Obtener URL pública
                    public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_name)
                except Exception as e:
                    st.error(f"Error subiendo foto: {e}")
                    continue
                
                # Insertar registro en la tabla
                registro = {
                    "archivo": uploaded_file.name,
                    "fecha": dt.strftime("%Y-%m-%d"),
                    "hora": dt.strftime("%H:%M:%S"),
                    "especie": especie,
                    "camara": camara,
                    "localidad": localidad,
                    "lat": lat,
                    "lon": lon,
                    "temperatura": weather.get("temperatura"),
                    "humedad": weather.get("humedad"),
                    "nubes": weather.get("nubes"),
                    "viento_vel": weather.get("viento_vel"),
                    "viento_dir": weather.get("viento_dir"),
                    "presion": weather.get("presion"),
                    "precipitacion": weather.get("precipitacion"),
                    "radiacion": weather.get("radiacion"),
                    "fase_lunar": moon_name,
                    "iluminacion_lunar": moon_pct,
                    "foto_url": public_url,
                }
                supabase.table("registros_fototrampeo").insert(registro).execute()
        
        st.success("¡Fotos guardadas permanentemente!")
        st.rerun()

# Mostrar registros permanentes
registros = load_registros()

if registros:
    st.subheader(f"📊 Registros permanentes ({len(registros)})")
    st.caption("Las fotos están en la nube. Puedes borrarlas del iPhone.")
    
    for reg in registros:
        with st.expander(f"{reg.get('fecha', '')} {reg.get('hora', '')} · {reg.get('especie', '')} · {reg.get('camara', '')}", expanded=False):
            col1, col2 = st.columns([1, 2])
            
            with col1:
                if reg.get("foto_url"):
                    st.image(reg["foto_url"], caption="Foto guardada", use_container_width=True)
                    st.link_button("🔗 Abrir foto", reg["foto_url"])
            
            with col2:
                st.markdown(f"""
                **Fecha:** {reg.get('fecha')}  
                **Hora:** {reg.get('hora')}  
                **Especie:** {reg.get('especie')}  
                **Cámara:** {reg.get('camara')}  
                **Localidad:** {reg.get('localidad')}  
                
                **Temperatura:** {reg.get('temperatura')} °C  
                **Humedad:** {reg.get('humedad')} %  
                **Nubes:** {reg.get('nubes')} %  
                **Viento:** {reg.get('viento_vel')} km/h ({reg.get('viento_dir')}°)  
                **Presión:** {reg.get('presion')} hPa  
                **Precipitación:** {reg.get('precipitacion')} mm  
                **Radiación solar:** {reg.get('radiacion')} W/m²  
                **Fase lunar:** {reg.get('fase_lunar')} ({reg.get('iluminacion_lunar')}%)
                """)
                
                if st.button("🗑️ Borrar", key=f"del_{reg.get('id')}"):
                    # Borrar de la tabla y del storage
                    try:
                        # Extraer nombre de archivo de la URL
                        file_name = reg["foto_url"].split("/")[-1].split("?")[0]
                        supabase.storage.from_(BUCKET_NAME).remove([file_name])
                    except:
                        pass
                    supabase.table("registros_fototrampeo").delete().eq("id", reg["id"]).execute()
                    st.rerun()
    
    # Descargar Excel
    if st.button("📥 Descargar Excel"):
        df = pd.DataFrame(registros)
        if "foto_url" in df.columns:
            df = df.drop(columns=["foto_url"])
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        buffer.seek(0)
        st.download_button("Descargar", data=buffer, file_name="registro.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
else:
    st.info("Aún no hay registros permanentes. Sube fotos y pulsa el botón.")

st.markdown("---")
st.caption("Almacenamiento permanente con Supabase (gratis).")
