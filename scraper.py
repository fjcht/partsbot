import httpx
import json
import os

from dotenv import load_dotenv

load_dotenv()

# CONFIGURACIÓN — leída desde variables de entorno (.env). Nunca hardcodear.
TOKEN = os.getenv("CASS_TOKEN", "")
SID = os.getenv("CASS_SID", "")
URL = os.getenv(
    "CASS_QUERY_COMMODITY_URL",
    "https://merchant.casschoice.com/api/method/merchant_app.api.product.ProductController.query_commodity",
)

def scraper_partes(lista_codigos):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "X-Frappe-CSRF-Token": TOKEN,
        "Referer": "https://merchant.casschoice.com/store/",
        "Content-Type": "application/json"
    }
    cookies = {"sid": SID, "x-frappe-csrf-token": TOKEN}
    
    print(f"Iniciando consulta para: {lista_codigos}")
    
    with httpx.Client(headers=headers, cookies=cookies) as client:
        try:
            response = client.post(URL, json={"partsNumbers": lista_codigos})
            response.raise_for_status()
            data = response.json()
            
            # Guardar el JSON crudo para respaldo
            with open("resultado_raw.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            return data
            
        except Exception as e:
            print(f"Error en la petición: {e}")
            return None

def procesar_y_guardar(data):
    """Extrae solo los productos disponibles y los guarda en un formato útil."""
    if not data or 'message' not in data:
        return

    resultados = []
    for entry in data['message']['data']['results']:
        for prod in entry.get('products', []):
            if prod.get('product_status') == 'ONSALE':
                # Extraer precio USD
                precios = prod.get('price', {}).get('prices', [])
                precio_usd = next((p['default_price'] for p in precios if p['currency'] == 'USD'), "N/A")
                
                resultados.append({
                    "parte": prod['parts_number'],
                    "marca": prod['brand_name'],
                    "titulo": prod['product_title'],
                    "precio": precio_usd
                })
    
    with open("reporte_precios.json", "w", encoding="utf-8") as f:
        json.dump(resultados, f, indent=4, ensure_ascii=False)
    print("Reporte limpio guardado en 'reporte_precios.json'")

if __name__ == "__main__":
    codigos = ["F4J16-3705110AB"] # Puedes agregar más códigos aquí
    datos = scraper_partes(codigos)
    if datos:
        procesar_y_guardar(datos)
        print("Scraping finalizado con éxito.")