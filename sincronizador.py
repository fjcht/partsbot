import requests
import os
from dotenv import load_dotenv

# Cargar variables del archivo .env
load_dotenv()

# Endpoint para sincronizar tanto vehículo como pieza
API_URL = "http://localhost:8000/sincronizar_datos_completos"
CASS_URL_VEHICULOS = "https://merchant.casschoice.com/api/method/merchant_app.api.vehicle.VehicleRelationController.list_vehicle_relations"

SID = os.getenv("CASS_SID")
COOKIES = {"sid": SID}

def sincronizar():
    if not SID:
        print("Error: No se encontró CASS_SID en el archivo .env")
        return

    print("Obteniendo catálogo de vehículos y piezas...")
    resp = requests.get(CASS_URL_VEHICULOS, cookies=COOKIES)
    
    if resp.status_code == 200:
        full_json = resp.json()
        data_list = full_json.get('message', {}).get('data', [])
        
        datos_a_enviar = []
        
        def procesar_nodos(nodos):
            for nodo in nodos:
                # Estructura que enviaremos para que el backend lo separe en tablas
                datos_a_enviar.append({
                    "marca": nodo.get("make"),
                    "modelo": nodo.get("model") or "",
                    # Aquí deberías incluir la lógica para obtener la pieza 
                    # asociada a este nodo si la API lo permite
                    "pieza_descripcion": nodo.get("node_name"), 
                    "oem": nodo.get("name") # Asumiendo que el ID de parte viene en 'name'
                })
                
                hijos = nodo.get("children", [])
                if hijos:
                    procesar_nodos(hijos)

        procesar_nodos(data_list)
        
        print(f"Enviando {len(datos_a_enviar)} registros completos al servidor...")
        res_envio = requests.post(API_URL, json={"items": datos_a_enviar})
        
        if res_envio.status_code == 200:
            print("Sincronización exitosa:", res_envio.json())
        else:
            print("Error al enviar al servidor:", res_envio.text)
    else:
        print(f"Error conectando a CassChoice: {resp.status_code}")

if __name__ == "__main__":
    sincronizar()