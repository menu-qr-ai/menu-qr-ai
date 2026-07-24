# HostAI MenuQR

SaaS para cartas QR multi-restaurante con FastAPI, SQLAlchemy, Jinja2, JavaScript, Alembic, Docker y una capa de analytics propia.

## Instalacion local

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

## Migraciones

Configura como mínimo `DATABASE_URL` y un `SECRET_KEY` propio en `.env`. Para
una instalación nueva, Alembic crea el esquema completo desde una base vacía:

```dotenv
DATABASE_URL=sqlite:///./menu.db
SECRET_KEY=reemplaza-este-valor-por-un-secreto-largo
```

```bash
python -m alembic upgrade head
```

Tambien puedes usar:

```bash
python scripts/migrate.py
```

## Datos demo

El seed oficial es explicito e idempotente. No se ejecuta automaticamente.
Ejecútalo únicamente después de aplicar las migraciones:

```bash
python -m app.utils.demo_seed
```

Genera o actualiza:

- restaurante demo con slug `demo-restaurant`
- branding
- categorias
- platos
- imagenes
- ingredientes y alergenos
- eventos reales de Analytics de los ultimos 30 dias
- usuario propietario demo `owner@demo.hostai.local`

La contraseña local de la demo es `HostAI-demo-2026`. Estas credenciales se crean
únicamente al ejecutar el seed explícito y no deben utilizarse en producción.

Reset demo:

```bash
python scripts/reset_demo.py
```

## Ejecutar

```bash
python -m uvicorn main:app --reload
```

Rutas utiles:

- `/login`
- `/app`
- `/r/demo/menu`
- `/r/demo-restaurant/menu`
- `/menu`
- `/admin`
- `/admin/restaurants`
- `/admin/dashboard`
- `/staff/waiter`
- `/staff/kitchen`
- `/menu/table/{table_qr_token}`
- `/menu/session/{customer_session_token}`
- `/api/dashboard/summary`
- `/api/analytics/events`
- `/health`
- `/openapi.json`

## Identidad y acceso por restaurante

`User` representa la identidad. El acceso operativo se concede únicamente mediante
`RestaurantMembership`, con un rol independiente por restaurante: `owner`,
`manager`, `waiter`, `cook` o `viewer`.

La sesión usa una cookie firmada, `HttpOnly` y `SameSite=Lax`. El local activo
facilita la navegación, pero cada endpoint vuelve a validar la membresía en base de
datos. Los campos históricos `users.role` y `users.restaurant_id` se conservan
solo para compatibilidad y migración; no autorizan peticiones.

Rutas de acceso principales:

- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/access/restaurants`
- `GET /api/access/context`
- `PUT /api/access/active-restaurant`
- `POST /api/access/restaurants/{restaurant_id}/memberships`
- `PATCH /api/access/restaurants/{restaurant_id}/memberships/{membership_id}`

## Seguridad de sesion web

Las sesiones autenticadas conservan la cookie firmada existente y añaden una
duracion absoluta configurable. La cookie usa `HttpOnly`, `SameSite=Lax`,
`Path=/`, `Max-Age` y `Expires`; en produccion tambien usa `Secure`. El login
rota el identificador de sesion y el token CSRF. El logout es una accion `POST`
protegida e invalida la cookie del navegador.

Todas las mutaciones autenticadas por cookie (`POST`, `PUT`, `PATCH` y
`DELETE`) requieren un token CSRF ligado a la sesion. Jinja lo incluye como
campo oculto y el helper compartido `app/static/js/security.js` lo envia en
`X-CSRF-Token` para las llamadas `fetch`. El token no se almacena en
`localStorage`. Login y los endpoints publicos de carta/analytics
explicitamente auditados quedan fuera de esta comprobacion; el login rota
siempre la sesion para evitar fijacion. Las mutaciones anonimas de cliente usan
un token-capacidad temporal, no envian cookies (`credentials: omit`) y tienen
una excepcion CSRF acotada a `/api/customer/sessions/`.

La duracion y el limite basico de intentos fallidos de login se configuran con:

```dotenv
SESSION_MAX_AGE_SECONDS=43200
LOGIN_RATE_LIMIT_ATTEMPTS=5
LOGIN_RATE_LIMIT_WINDOW_SECONDS=900
```

El limitador agrupa por IP y email normalizado: por defecto bloquea temporalmente
la pareja tras cinco fallos en quince minutos, con umbrales adicionales por
email e IP. Es una defensa en memoria por proceso: no coordina contadores entre
varios workers o instancias y debe complementarse con infraestructura compartida
antes de escalar horizontalmente.

En produccion (`ENVIRONMENT=production`) el arranque exige una `SECRET_KEY` de
al menos 32 caracteres y diversidad suficiente, `APP_URL` HTTPS y orígenes CORS
explicitos sin comodines. Genera una clave nueva, por ejemplo:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

No reutilices la clave del ejemplo ni la registres en logs. Desarrollo y test
admiten HTTP local; produccion activa `Secure` y HSTS. El middleware añade
protecciones de tipo de contenido, referrer, framing, permisos, CSP y
`Cache-Control: no-store` para contenido autenticado. La CSP mantiene
`style-src 'unsafe-inline'` por compatibilidad con estilos existentes y las
rutas de documentación tienen una excepcion acotada para sus assets; ambos
puntos quedan como endurecimiento futuro.

## Politica monetaria

Los precios comerciales usan `Decimal` en Python y `NUMERIC(12, 2)` en la
base de datos. Los inputs persistidos admiten como maximo dos decimales
significativos y los calculos derivados usan `ROUND_HALF_UP` desde
`app/core/money.py`.

Las APIs serializan precio unitario, subtotal y total como strings decimales
con dos posiciones. El frontend solo los formatea; el backend es la fuente de
verdad. La moneda procede de `Restaurant.currency` y no se realizan
conversiones de divisa.

Los costes de inventario, historicos y WAC conservan temporalmente sus tipos
anteriores. Su migracion requiere un sprint independiente para no recalcular
ni alterar el ledger historico.

## Pedidos de cliente por QR

Cada mesa activa puede tener un unico QR vigente. Owner y manager pueden
generarlo o rotarlo; el waiter puede consultarlo para operar la sala:

- `GET /api/dining/{restaurant_id}/tables/{table_id}/customer-qr`
- `POST /api/dining/{restaurant_id}/tables/{table_id}/customer-qr`
- `GET /api/dining/{restaurant_id}/tables/{table_id}/customer-qr.png`

El QR no contiene IDs secuenciales: contiene un token aleatorio de 256 bits.
Al escanearlo se exige una `ServiceSession` abierta para la mesa y se crea o
recupera una `CustomerSession` anonima, absoluta y temporal de cuatro horas. La
rotacion del QR revoca las sesiones de cliente activas de esa mesa.

El cliente ve exclusivamente carta, precios, ingredientes, alergenos y
disponibilidad calculada con la receta tecnica y el stock actual. Su pedido
queda en `draft_customer` y, al enviarlo, en `submitted_customer`. Solo owner,
manager o waiter pueden aceptarlo; esa aceptacion reutiliza el submit
transaccional existente y crea la comanda. Rechazarlo lo conserva auditado como
`cancelled`. El cliente nunca ejecuta cocina, fulfillment, settlement ni pagos.

El token de sesion es una credencial bearer: no debe aparecer en logs, capturas
o herramientas de analitica. HostAI lo enmascara en sus logs y errores, y la
pagina usa `Referrer-Policy: no-referrer` y `Cache-Control: no-store`. En
staging/produccion desactiva el access log HTTP sin redaccion; proxies o CDN
tambien deben omitir o sanear estas rutas.

## URLs de desarrollo

Servidor local en PC:

```text
http://127.0.0.1:8000
```

Demo desde movil en la misma WiFi:

```text
http://IP_DEL_PC:8000/r/demo/menu
```

Rutas oficiales de demo:

- demo corto: `/r/demo/menu`
- slug real: `/r/demo-restaurant/menu`
- menu publico oficial: `/r/{slug}/menu`
- health: `/health`
- OpenAPI: `/openapi.json`

`/menu` sigue disponible como ruta local legacy para el restaurante por defecto, pero la URL publica compartible debe usar `/r/{slug}/menu`.

## QA movil manual

- Carga inicial sin 404 inesperados.
- Layout responsive en vertical y horizontal.
- Platos visibles.
- Categorias visibles.
- Cambio de idioma operativo si esta disponible.
- Busqueda operativa si esta disponible.
- Eventos analytics generados al navegar.
- Dashboard refleja actividad despues de usar la demo.
- Cliente QR puede preparar un borrador y el camarero puede aceptarlo.
- Consola del navegador sin errores relevantes.
- HTML, CSS y JS sin rutas hardcodeadas a `localhost` o `127.0.0.1`.

La pantalla de cocina requiere además validación manual pendiente en Android,
iPhone y tablet de 10 pulgadas, tanto vertical como horizontal. Deben probarse
doble pulsación, cambio de local, membresía revocada, pérdida temporal de red y
una sala con muchas comandas. Estas pruebas no se consideran realizadas hasta
ejecutarlas en dispositivos físicos.

## Docker

```bash
docker compose up --build
```

## Render

Configura variables de entorno desde `.env.example`. La guía completa de
PostgreSQL, proxy, HTTPS, health checks y validación está en
[`docs/STAGING.md`](docs/STAGING.md).

Comando recomendado de arranque (el log estructurado de HostAI conserva la
trazabilidad y enmascara tokens-capacidad):

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips "$FORWARDED_ALLOW_IPS" --no-access-log
```

Antes del primer arranque productivo ejecuta:

```bash
python -m alembic upgrade head
```

Configura `/health` como health check. El seed demo es siempre manual y no debe
ejecutarse automáticamente en staging o producción.

## Estructura

```text
app/
  core/       configuracion, version, logging, errores
  models/     modelos SQLAlchemy
  routers/    rutas HTTP delgadas
  schemas/    contratos Pydantic v2
  services/   logica de negocio
  templates/  vistas Jinja2
  static/     CSS y JS
  utils/      utilidades ejecutables
migrations/   Alembic
scripts/      comandos utiles
tests/        smoke y regresion
```

## Calidad

```bash
python -m compileall app tests
python -m unittest discover -s tests
python -m pytest
python -m ruff check .
```

O todo junto:

```bash
python scripts/test.py
```

## Roadmap HostAI

HostAI evoluciona como sistema operativo inteligente para restaurantes. MenuQR AI es el primer modulo comercial; Analytics, Dashboard e Inventario son la base para decisiones operativas cada vez mas precisas.

- Sprint 8 Prediction Engine: predicciones operativas basadas en historico, demanda real y estado de inventario.
- Sprint 9 HostAI Assistant: asistente conversacional para consultar el negocio, preparar servicios y entender prioridades.
- Sprint 10 HostAI Vision: el usuario podra hacer una foto del plato y HostAI resolvera el `dish_id` para mostrar ingredientes, alergenos y ficha del plato.
- Sprint 11 Language Engine: el sistema detectara automaticamente el idioma del usuario y lo reutilizara en menu, traducciones, chat y futuras respuestas IA.
- Sprint 12 Safe Plate / Director IA: evaluacion personalizada de alergenos y restricciones alimentarias por plato, con una capa directiva para recomendaciones seguras.
