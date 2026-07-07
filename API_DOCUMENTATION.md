# 📚 API Documentation — PartsBot (FCH AutoLab)

Base URL (local): `http://localhost:8000`
Documentación interactiva: `http://localhost:8000/docs`

Autenticación: los endpoints protegidos requieren el header
`Authorization: Bearer <access_token>` (JWT obtenido en `/auth/login` o `/auth/registro`).

---

## Índice
- [Salud](#salud)
- [Autenticación](#autenticación)
- [Catálogo y búsqueda](#catálogo-y-búsqueda)
- [Carrito](#carrito)
- [Órdenes](#órdenes)
- [IA](#ia)
- [Sincronización](#sincronización)

---

## Salud

### `GET /api/health`
Devuelve el estado de la API.
```json
{ "status": "ok", "version": "2.0.0", "margen": 0.06 }
```

---

## Autenticación

### `POST /auth/registro`
Crea un usuario y devuelve un token JWT.

**Body**
```json
{ "email": "cliente@empresa.com", "password": "secret123", "nombre": "Mi Empresa", "tipo_cliente": "B2B" }
```
**Respuesta 201**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "usuario": { "id": 1, "email": "cliente@empresa.com", "nombre": "Mi Empresa", "tipo_cliente": "B2B" }
}
```
Errores: `400` email ya registrado.

### `POST /auth/login`
**Body**: `{ "email": "...", "password": "..." }`
**Respuesta 200**: igual que registro (token + usuario).
Errores: `401` credenciales inválidas, `403` usuario inactivo.

### `GET /auth/perfil` 🔒
Devuelve los datos del usuario autenticado.
```json
{ "id": 1, "email": "cliente@empresa.com", "nombre": "Mi Empresa", "tipo_cliente": "B2B" }
```

---

## Catálogo y búsqueda

### `GET /consultar`
Búsqueda principal con JOIN Autoparte ↔ Compatibilidad ↔ CatalogoVehiculos.

**Query params (todos opcionales):**
| Param | Tipo | Descripción |
|-------|------|-------------|
| `marca` | string | Marca del vehículo |
| `modelo` | string | Modelo del vehículo |
| `anio` | int | Año (filtra compatibilidades cuyo rango lo contiene) |
| `pieza` | string | Nombre/descr. de la pieza |
| `numero_parte` | string | Busca en numero_oem/OE/OEM/Aftermarket |

**Respuesta 200**
```json
{
  "total": 1,
  "resultados": [
    {
      "id": 1,
      "numero_oem": "F4J16-3705110AB",
      "codigo_oe": "F4J16-3705110AB",
      "codigo_oem": "F4J16-3705110AB",
      "codigo_aftermarket": null,
      "marca": "CHERY",
      "descripcion": "Ignition coil",
      "categoria": "Ignition coil",
      "calidad": "ORIGINAL",
      "imagen_url": "https://i.plenty.parts/i/850/pictures_ppp_pc2015china_630_S1137051001.jpg",
      "precio_fob": 11.07,
      "precio_venta": 11.74,
      "precio": 11.74,
      "moneda": "USD",
      "compatibilidades": [
        { "marca": "TOYOTA", "modelo": "Corolla", "desde": 2012, "hasta": 2015, "etiqueta": "TOYOTA Corolla (2012-2015)" }
      ],
      "precios": [
        { "calidad": "ORIGINAL", "marca_repuesto": "CHERY", "precio_fob": 11.07, "precio_venta": 11.74, "moneda": "USD", "disponibilidad": "ONSALE", "store_name": "CHERY-Original00001" }
      ]
    }
  ],
  "vehiculos_catalogo": [
    { "marca": "CHERY", "modelo": "TIGGO", "desde": 2010, "hasta": 2023, "etiqueta": "CHERY TIGGO (2010-2023)" }
  ],
  "criterios": { "marca": "CHERY", "modelo": null, "anio": null, "pieza": null, "numero_parte": null }
}
```

### `POST /busqueda/semantica`
Búsqueda bilingüe ES/EN. Expande el término con la tabla de traducciones.

**Body**
```json
{ "termino": "brake pads", "marca": null, "modelo": null, "anio": null }
```
**Respuesta 200**
```json
{
  "termino": "brake pads",
  "terminos_expandidos": ["brake pads", "pastillas de freno"],
  "total": 3,
  "resultados": [ /* misma forma que /consultar */ ]
}
```

### `GET /catalogo/marcas`
```json
{ "marcas": ["ACURA", "AUDI", "BMW", "CHERY", ...] }
```

### `GET /catalogo/modelos?marca=BMW`
```json
{ "marca": "BMW", "modelos": [ { "modelo": "116i", "anio_min": 2004, "anio_max": 2014 } ] }
```

### `GET /exportar_csv`
Descarga un CSV con todas las autopartes (códigos + precios con margen).

---

## Carrito 🔒
Todos requieren autenticación. Operan sobre el carrito **activo** del usuario
(se crea automáticamente si no existe).

### `POST /carrito/agregar`
**Body**: `{ "autoparte_id": 1, "cantidad": 2 }`
Si el item ya existe, suma la cantidad.

### `GET /carrito/ver`
```json
{
  "carrito_id": 1,
  "items": [
    { "item_id": 1, "autoparte_id": 1, "descripcion": "Ignition coil", "codigo_oe": "F4J16-3705110AB",
      "imagen_url": "https://sc04.alicdn.com/kf/H956d83efb19d4a679b0b75ac099eb182v.png", "precio_unitario": 11.74, "cantidad": 2, "subtotal": 23.48 }
  ],
  "total": 23.48,
  "cantidad_items": 2
}
```

### `PUT /carrito/actualizar`
**Body**: `{ "autoparte_id": 1, "cantidad": 3 }` — `cantidad: 0` elimina el item.

### `DELETE /carrito/eliminar/{autoparte_id}`
Elimina el item del carrito. Devuelve el carrito actualizado.

---

## Órdenes 🔒

### `POST /ordenes/crear`
Convierte el carrito activo en una orden con estado **"Pendiente"** y cierra el carrito.
```json
{
  "id": 1, "estado": "Pendiente", "total": 23.48,
  "fecha_creacion": "2026-07-07T04:52:26", "cantidad_items": 1,
  "items": [ { "autoparte_id": 1, "descripcion": "Ignition coil", "codigo_oe": "F4J16-3705110AB",
               "cantidad": 2, "precio_unitario": 11.74, "subtotal": 23.48 } ]
}
```
Errores: `400` carrito vacío.

### `GET /ordenes/listar`
```json
{ "total": 1, "ordenes": [ { "id": 1, "estado": "Pendiente", "total": 23.48, "fecha_creacion": "...", "cantidad_items": 1 } ] }
```

### `GET /ordenes/detalle/{orden_id}`
Devuelve la orden con sus items (mismo formato que `crear`). `404` si no existe o no pertenece al usuario.

---

## IA 🔒

### `POST /ia/completar_datos`
Completa modelos/años de marcas (chinas) marcadas con `necesita_completar`.

**Body**
```json
{ "vehiculo_id": null, "limite": 10 }
```
- Con `GEMINI_API_KEY` configurada: infiere y crea filas de modelos/años.
- Sin la clave: devuelve la lista de pendientes sin fallar.

**Respuesta (con IA)**
```json
{ "status": "ok", "procesados": 2, "detalle": [ { "marca": "CHERY", "modelos_creados": 42 } ] }
```

---

## Sincronización

### `POST /sincronizar/vehiculos`
Dispara la Fase A (catálogo de vehículos) desde la API.
```json
{ "status": "ok", "vehiculos": 2798 }
```

### `POST /sincronizar/piezas`
**Body**: `{ "items": ["F4J16-3705110AB", "OTRO-CODIGO"] }`
```json
{ "status": "ok", "piezas": 2 }
```

> Recomendado ejecutar la sincronización pesada por CLI (`python sincronizador.py`)
> en lugar de la API para lotes grandes.

---

## Códigos de error comunes
| Código | Significado |
|--------|-------------|
| 400 | Datos inválidos / carrito vacío / email duplicado |
| 401 | Token ausente o inválido |
| 403 | Usuario inactivo |
| 404 | Recurso no encontrado |
| 500 | Error interno |
| 502 | Error al comunicarse con CassChoice |
