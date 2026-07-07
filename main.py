from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import io, csv, httpx, google.generativeai as genai
import models, database
import os
from dotenv import load_dotenv

load_dotenv() # Carga el archivo .env


# CONFIGURACIÓN
TOKEN = os.getenv("CASS_TOKEN")
SID = os.getenv("CASS_SID")
URL_CASS = "https://merchant.casschoice.com/api/method/merchant_app.api.product.ProductController.query_commodity"
genai.configure(api_key="AQ.Ab8RN6LZxt7Tp2b5YXle4s0KE-J1KOgNUcocKnCtMaCpSwjdMw") 

app = FastAPI(title="Middleware de Inteligencia de Repuestos - FCH AutoLab")

app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_methods=["*"], 
    allow_headers=["*"],
)

models.Base.metadata.create_all(bind=database.engine)

# --- MODELO PARA SINCRONIZACIÓN MANUAL ---
class CatalogoRequest(BaseModel):
    items: list

# --- IA: TRADUCCIÓN Y DESCRIPCIÓN PROFESIONAL ---
def obtener_info_ia(marca, modelo, anio, pieza):
    try:
        model = genai.GenerativeModel('gemini-pro')
        prompt = f"Para un {marca} {modelo} {anio} '{pieza}', dame: 1. El código OEM exacto. 2. Una descripción comercial profesional en español. Formato exacto: OEM|DESCRIPCION"
        response = model.generate_content(prompt)
        res = response.text.strip().split('|')
        return res[0], res[1] if len(res) > 1 else pieza
    except Exception as e:
        print(f"Error IA: {e}")
        return pieza, f"{marca} {modelo} {anio} - {pieza}"

# --- LÓGICA DE API CASSCHOICE ---
async def obtener_datos_cass(codigo_oe):
    headers = {"X-Frappe-CSRF-Token": TOKEN, "Referer": "https://merchant.casschoice.com/store/", "Content-Type": "application/json"}
    cookies = {"sid": SID, "x-frappe-csrf-token": TOKEN}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(URL_CASS, json={"partsNumbers": [codigo_oe]}, headers=headers, cookies=cookies, timeout=15.0)
            return resp.json() if resp.status_code == 200 else {"message": {"data": {"results": []}}}
        except Exception as e:
            print(f"Error de red: {e}")
            return {"message": {"data": {"results": []}}}

# --- PERSISTENCIA ---
def guardar_en_db(db: Session, codigo_oe: str, marca: str, modelo: str, anio: int, descripcion_profesional: str, data: dict):
    resultados = data.get('message', {}).get('data', {}).get('results', [])
    if not resultados: return None
    
    nueva_parte = models.Autoparte(numero_oem=codigo_oe, descripcion=descripcion_profesional, marca=marca, modelo=modelo)
    db.add(nueva_parte)
    db.commit()
    db.refresh(nueva_parte)
    
    for res in resultados:
        for prod in res.get('products', []):
            precios = prod.get('price', {}).get('prices', [])
            usd_precio = next((p['default_price'] for p in precios if p['currency'] == 'USD'), None)
            nueva_opcion = models.PrecioCassChoice(
                autoparte_id=nueva_parte.id, 
                calidad=prod.get('brand_type'), 
                marca_repuesto=prod.get('brand_name'), 
                precio_fob=usd_precio
            )
            db.add(nueva_opcion)
    db.commit()
    return nueva_parte

# --- ENDPOINT CONSULTA ---
# --- REEMPLAZA ESTE ENDPOINT EN TU main.py ---
@app.get("/consultar")
async def consultar_repuestos(
    marca: Optional[str] = None, 
    modelo: Optional[str] = None,
    anio: Optional[int] = None,
    pieza: Optional[str] = None,
    numero_parte: Optional[str] = None,
    db: Session = Depends(database.get_db)
):
    try:
        # 1. Búsqueda prioritaria por Número de Parte si se proporcionó
        parte = None
        if numero_parte:
            parte = db.query(models.Autoparte).filter(models.Autoparte.numero_oem == numero_parte).first()
        
        # 2. Si no hubo match por OEM, intentamos por descripción de pieza
        if not parte and pieza:
            parte = db.query(models.Autoparte).filter(models.Autoparte.descripcion.ilike(f"%{pieza}%")).first()

        # 3. Búsqueda de vehículos compatibles
        # Ahora unimos Autoparte con Compatibilidad para filtrar correctamente por marca/modelo
        query_vehiculos = db.query(models.CatalogoVehiculos)
        
        # Si se busca por marca o modelo, filtramos el catálogo
        if marca:
            query_vehiculos = query_vehiculos.filter(models.CatalogoVehiculos.marca.ilike(f"%{marca}%"))
        if modelo:
            query_vehiculos = query_vehiculos.filter(models.CatalogoVehiculos.modelo.ilike(f"%{modelo}%"))
            
        vehiculos = query_vehiculos.all()

        # 4. Construcción de respuesta
        if not parte:
            return {
                "oem": numero_parte or "N/A", 
                "origen": "N/A", 
                "descripcion": "Pieza no encontrada para estos criterios",
                "precio": "0.00", 
                "disponibilidad": "N/A",
                "compatibilidades": [{"marca": v.marca, "modelo": v.modelo, "desde": str(anio or ""), "hasta": "Actual"} for v in vehiculos]
            }

        # Obtener precio vinculado de la tabla corregida
        precio_info = db.query(models.PrecioCassChoice).filter(models.PrecioCassChoice.autoparte_id == parte.id).first()
        precio = precio_info.precio_fob if precio_info else "Consultar"

        # Obtenemos las compatibilidades reales de la pieza encontrada
        compatibilidades_data = [
            {"marca": c.marca_vehiculo, "modelo": c.modelo_vehiculo, "desde": str(c.anio_inicio or ""), "hasta": str(c.anio_fin or "Actual")} 
            for c in parte.compatibilidades
        ]

        return {
            "oem": parte.numero_oem,
            "origen": "CassChoice",
            "descripcion": parte.descripcion,
            "precio": str(precio),
            "disponibilidad": "En stock",
            "compatibilidades": compatibilidades_data if compatibilidades_data else [{"marca": v.marca, "modelo": v.modelo, "desde": str(anio or ""), "hasta": "Actual"} for v in vehiculos]
        }
        
    except Exception as e:
        print(f"Error en consulta: {e}")
        raise HTTPException(status_code=500, detail="Error interno al procesar la consulta")

# --- SINCRONIZACIÓN AUTOMÁTICA ---
@app.post("/sincronizar_catalogo")
async def sincronizar_catalogo(db: Session = Depends(database.get_db)):
    headers = {"X-Frappe-CSRF-Token": TOKEN, "Cookie": f"sid={SID}; x-frappe-csrf-token={TOKEN}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://merchant.casschoice.com/api/method/merchant_app.api.vehicle.VehicleRelationController.list_vehicle_relations", headers=headers, timeout=30.0)
        if resp.status_code == 200:
            datos = resp.json().get('message', [])
            db.query(models.CatalogoVehiculos).delete()
            for item in datos:
                db.add(models.CatalogoVehiculos(marca=item.get('brand'), modelo=item.get('model')))
            db.commit()
            return {"status": "Sincronización exitosa", "items_procesados": len(datos)}
    raise HTTPException(status_code=500, detail="Error al sincronizar")

# --- SINCRONIZACIÓN MANUAL (INYECCIÓN DE DATOS) ---
@app.post("/sincronizar_catalogo_manual")
async def guardar_masivo(req: CatalogoRequest, db: Session = Depends(database.get_db)):
    try:
        db.query(models.CatalogoVehiculos).delete()
        for item in req.items:
            marca = item.get('make', 'Desconocido')
            modelo = item.get('model', 'Desconocido')
            db.add(models.CatalogoVehiculos(marca=marca, modelo=modelo))
        db.commit()
        return {"status": "Éxito", "total": len(req.items)}
    except Exception as e:
        db.rollback()
        return {"status": "Error", "detalle": str(e)}

@app.post("/sincronizar_datos_completos")
async def sincronizar_datos(payload: dict, db: Session = Depends(database.get_db)):
    items = payload.get("items", [])
    for item in items:
        # 1. Asegurar que el vehículo existe en el catálogo
        vehiculo = db.query(models.CatalogoVehiculos).filter_by(
            marca=item["marca"], modelo=item["modelo"]
        ).first()
        
        if not vehiculo:
            vehiculo = models.CatalogoVehiculos(marca=item["marca"], modelo=item["modelo"])
            db.add(vehiculo)
            db.commit()
            db.refresh(vehiculo)

        # 2. Si hay datos de pieza, crear la Autoparte y la Compatibilidad
        if item.get("oem"):
            autoparte = db.query(models.Autopartes).filter_by(numero_oem=item["oem"]).first()
            if not autoparte:
                autoparte = models.Autopartes(
                    numero_oem=item["oem"], 
                    descripcion=item.get("pieza_descripcion", "N/A")
                )
                db.add(autoparte)
                db.commit()
                db.refresh(autoparte)
            
            # 3. Crear la relación en la tabla compatibilidades
            compat = models.Compatibilidad(
                autoparte_id=autoparte.id,
                marca_vehiculo=vehiculo.marca,
                modelo_vehiculo=vehiculo.modelo
            )
            db.add(compat)
    
    db.commit()
    return {"status": "success", "procesados": len(items)}

@app.get("/exportar_csv")
def exportar_a_csv(db: Session = Depends(database.get_db)):
    resultados = db.query(models.Autoparte, models.PrecioCassChoice).join(models.PrecioCassChoice).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Numero OEM", "Calidad", "Marca", "Precio FOB"])
    for parte, opc in resultados:
        writer.writerow([parte.numero_oem, opc.calidad, opc.marca_repuesto, opc.precio_fob])
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=inventario.csv"})