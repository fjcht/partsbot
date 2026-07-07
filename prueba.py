import os
import requests
import json

from dotenv import load_dotenv

load_dotenv()

COOKIES = {"sid": os.getenv("CASS_SID", "")}
CASS_URL = "https://merchant.casschoice.com/api/method/merchant_app.api.vehicle.VehicleRelationController.list_vehicle_relations"

resp = requests.get(CASS_URL, cookies=COOKIES)
data = resp.json()

print(f"Tipo de respuesta: {type(data)}")
print(f"Llaves principales en la respuesta: {data.keys()}")

# A veces el mensaje no está en 'message' sino en 'data' o directamente
if 'message' in data:
    print("Contenido de 'message':", type(data['message']))
    if isinstance(data['message'], list) and len(data['message']) > 0:
        print("Primer elemento:", data['message'][0])
    else:
        print("La lista 'message' está vacía.")
else:
    print("No encontré la llave 'message' en la respuesta.")