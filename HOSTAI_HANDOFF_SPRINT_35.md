# HostAI — Handoff tras Sprint 35

Fecha de cierre: 2026-07-24

Este documento conserva el contexto técnico y de producto necesario para
continuar HostAI en otro chat. El Sprint 35 está terminado. El Sprint 36 está
documentado únicamente como roadmap y no ha sido iniciado.

## Producto

HostAI es un Restaurant Operating System SaaS. No es solamente una carta QR:
coordina la operación del restaurante desde el contacto del cliente con la
carta hasta cocina, inventario, valoración, analítica y cobro registrado.

Perfiles principales:

- Cliente: consulta la carta, alérgenos, disponibilidad y prepara un pedido
  anónimo desde la mesa.
- Camarero: abre servicios, toma pedidos, valida pedidos de cliente, sigue
  cocina, confirma fulfillment, liquida la sesión y registra pagos manuales.
- Cocina: recibe comandas, gestiona preparación y entrega, consulta recetas,
  disponibilidad, producción y mermas según permisos.
- Encargado: supervisa sala, cocina, inventario, costes, operaciones, usuarios
  y pagos del local.
- Dueño: controla configuración, permisos y operación completa.
- Operador multilocal: cambia de restaurante sin cerrar sesión y conserva un
  rol independiente en cada local.

La arquitectura es SaaS, multirrestaurante y mobile-first. El restaurante
activo es contexto de navegación, nunca una autorización. Todo acceso interno
revalida una membresía activa y el restaurante de cada recurso.

La única fuente de verdad operativa sigue esta cadena:

```text
Restaurante
→ Carta
→ Platos
→ Recetas técnicas
→ Ingredientes
→ Inventario
→ Ledger y movimientos
→ Operaciones y ventas
→ Analytics
→ Prediction
→ Planning
→ Costing
→ Business Insights
```

No deben crearse módulos paralelos que reconstruyan pedidos, recetas,
inventario, ventas, costes o analítica.

## Estado actual

- Versión: `0.35.0`
- Build: `sprint-35`
- Alembic head: `0022_add_customer_qr_ordering_foundation`
- Suite local: `323 passed`, `3 skipped`, `110 subtests`
- Warning conocido: deprecación externa Starlette/TestClient/httpx
- SQLite: validado desde base vacía y mediante upgrades/round-trips
- PostgreSQL: DDL y suite dialectal validados; la integración real requiere
  `HOSTAI_TEST_POSTGRES_URL`

Módulos operativos:

- identidad, login, sesión firmada y contexto multilocal;
- `RestaurantMembership`, RBAC e IDOR;
- carta, platos, recetas técnicas e ingredientes;
- inventario, ledger inmutable, recepciones, ajustes y reconciliación;
- mermas, producción, WAC, valoración histórica y costes;
- sala, zonas, mesas y sesiones de servicio;
- pedidos, líneas y snapshots monetarios;
- comandas y workflow de cocina;
- fulfillment transaccional e idempotente;
- settlement por sesión;
- pagos manuales parciales y mixtos;
- Analytics, Prediction, Planning, Costing y Business Insights;
- seguridad web transversal;
- validación y runbook de staging;
- CustomerSession, QR de mesa y pedidos anónimos con aprobación.

Superficies principales:

- HTML interno: `/login`, `/app`, `/staff/waiter`, `/staff/kitchen`,
  `/admin/dashboard`.
- Carta pública: `/r/{slug}/menu`.
- Cliente QR: `/menu/table/{qr_token}` y
  `/menu/session/{customer_session_token}`.
- Acceso: `/api/auth/*` y `/api/access/*`.
- Sala: `/api/dining/{restaurant_id}/*`.
- Pedidos: `/api/orders/{restaurant_id}/*`.
- Cocina: `/api/kitchen/{restaurant_id}/*`.
- Payments: `/api/settlements/{restaurant_id}/*`.
- Salud y contrato: `/health`, `/openapi.json`.

Modelo de seguridad:

- contraseñas PBKDF2;
- cookie firmada `HttpOnly`, `SameSite=Lax`, `Secure` en producción,
  expiración absoluta y rotación al iniciar sesión;
- CSRF sincronizado para mutaciones autenticadas por cookie;
- rate limiting básico del login por IP/email en memoria por proceso;
- RBAC centralizado por membresía y restaurante;
- protección IDOR en servicios;
- CSP, HSTS en producción, no-store y cabeceras defensivas;
- tokens-capacidad del cliente aleatorios, revocables y temporales;
- redacción de tokens de cliente en logs y errores;
- access log HTTP sin redacción desactivado en el comando recomendado.

Política monetaria:

- `Decimal` en Python;
- `NUMERIC(12,2)` para importes comerciales;
- `ROUND_HALF_UP`;
- strings con dos decimales en las APIs;
- snapshots en `OrderLine`, settlement y payment;
- totales derivados, no calculados autoritativamente en JavaScript.

Flujo completo actual:

```text
QR cliente
→ CustomerSession anónima
→ draft_customer
→ submitted_customer
→ aprobación de waiter/manager/owner
→ Order submitted
→ KitchenTicket
→ served
→ OrderFulfillment
→ OperationalTransaction
→ inventario + valoración + analytics
→ Order completed
→ ServiceSessionSettlement
→ sesión cerrada y mesa liberada
→ Payment manual parcial/mixto
```

El pedido del cliente no llega a cocina sin aprobación. Settlement no es
Payment. Payment no es TPV, caja ni fiscalidad.

## Sprints completados

### Identidad, acceso y multilocal — Sprints 20 a 22

- Se evolucionó la autenticación existente sin crear un sistema paralelo.
- `RestaurantMembership` representa rol y acceso por restaurante.
- Roles: owner, manager, waiter, cook y viewer.
- Los permisos están centralizados; no se dispersan comparaciones de roles.
- El restaurante activo persiste en sesión, pero cada servicio reautoriza.

### Sala — Sprints 23 a 25

- Zonas, mesas y sesiones de servicio.
- Una mesa solo puede tener una sesión abierta.
- Pedidos y líneas independientes del cierre financiero.
- Workflow de camarero mobile-first y múltiples rondas por sesión.

### Baseline y cocina — Sprint 26A y Sprints 26 a 28

- La revisión raíz 0001 describe las tablas pre-Alembic para que una base
  completamente vacía pueda subir a head.
- Una única comanda por pedido submitted y una línea de cocina por OrderLine.
- Máquina `pending → preparing → ready → served`, con cancelaciones controladas.
- El estado agregado se calcula desde las líneas.
- Cocina no descuenta inventario, no crea ventas y no genera analytics.

### Política monetaria — Sprint 29

- Se eliminó Float del dinero comercial.
- Snapshots, totales y serialización se centralizaron en `money.py`.

### Fulfillment — Sprint 30

- Acción explícita posterior a cocina served.
- `OrderFulfillment` idempotente por pedido.
- Frontera transaccional única alrededor de todas las líneas.
- Reutiliza `OperationalTransactionService`; no duplica inventario ni analytics.
- El pedido pasa a completed, pero la sesión no se cierra.

### Settlement — Sprint 31

- Cuenta congelada e idempotente por ServiceSession.
- Snapshots de pedidos y líneas.
- Cierra la sesión y libera la mesa de forma derivada.
- No registra pagos.

### Payments — Sprint 32

- Uno o varios pagos completed por settlement finalizado.
- Métodos manuales `cash`, `card` y `other`.
- Saldo pagado/restante derivado y protección de sobrepago.
- Idempotencia por clave de cliente.
- No existe TPV, caja, proveedor bancario ni fiscalidad.

### Seguridad web — Sprint 33

- CSRF transversal para formularios y fetch autenticados por cookie.
- Rotación y expiración de sesión, logout POST, cookies endurecidas.
- Rate limiting del login y respuesta anti-enumeración.
- Validación estricta de `SECRET_KEY` y entorno de producción.
- Cabeceras, CSP inicial, no-store y respuestas HTML/JSON coherentes.

### Staging y runtime — Sprint 34

- Auditoría de migraciones y DDL PostgreSQL.
- Política explícita de proxy y forwarded headers.
- Runbook HTTPS/Render/PostgreSQL.
- Suite PostgreSQL opcional y pruebas de concurrencia.
- Matriz de QA móvil automatizada/emulada.
- No se ha afirmado staging PostgreSQL real sin credenciales disponibles.

### Cliente QR — Sprint 35

- `CustomerSession` anónima asociada a restaurante, mesa y ServiceSession.
- QR persistente por mesa, con token seguro y rotación.
- Sesión de cliente absoluta de cuatro horas y revocable.
- Carta móvil sin exposición de IDs internos.
- Disponibilidad basada en receta técnica e inventario actual.
- Pedido reutiliza Order y OrderLine con estados customer específicos.
- Waiter/manager/owner aceptan o rechazan.
- Solo la aceptación reutiliza el submit existente y crea KitchenTicket.
- QR y líneas están protegidos frente a IDOR.
- Tokens redactados en logs; la infraestructura debe evitar logs de URL crudos.

## Invariantes arquitectónicas

- No crear una segunda autenticación para clientes o empleados.
- No crear un segundo modelo de pedido, venta, receta o inventario.
- El contexto activo no concede acceso por sí mismo.
- Todo recurso interno se filtra por restaurante autorizado.
- CustomerSession es una capacidad anónima limitada, no una membresía.
- Kitchen `served` no ejecuta fulfillment automáticamente.
- Fulfillment es la única entrada de Order al núcleo operativo.
- Settlement congela la deuda; Payment registra cobros.
- Inventario solo cambia a través del ledger y servicios existentes.
- Routers resuelven HTTP; la lógica de negocio vive en services.

## Riesgos pendientes

- Ejecutar la cadena completa sobre PostgreSQL real y staging Render.
- QA física en iPhone, iPad, Android y tablet Android.
- El rate limiting del login es por proceso y no coordina instancias.
- Los tokens anónimos se almacenan en claro; una filtración de base de datos
  permite usarlos hasta expiración o revocación.
- Falta rate limiting específico para cliente anónimo.
- Definir una política operativa para QR físico perdido, copiado o expuesto.
- Proxies, CDN y plataformas deben omitir o sanear URLs con bearer tokens.
- Algunos costes legacy e inventario conservan Float fuera del dinero comercial.
- Falta historial móvil consolidado.
- Faltan alertas y recordatorios accionables de stock.
- No existe PWA ni instalación validada en iOS/Android.
- La disponibilidad del cliente no reserva stock; se revalida al aprobar.
- Customer drafts expirados requieren resolución operativa del camarero.
- Dependencia externa Starlette/TestClient/httpx pendiente de actualización.

## Roadmap inmediato — no implementado

### Sprint 36 — Customer Status, Assistance & Anti-Abuse

- estado del pedido para cliente;
- solicitud de asistencia;
- solicitud de cuenta;
- controles antiabuso;
- gestión mínima de QR.

### Sprint 37 — Owner & Manager Operations Center

- ventas operativas;
- settlement y pagos;
- mesas;
- pedidos;
- cocina;
- stock crítico;
- mermas;
- producción;
- alertas;
- mobile-first;
- multilocal básico.

### Sprint 38 — Smart Stock Alerts & Purchase Reminders

- stock crítico;
- cobertura estimada;
- platos afectados;
- riesgo de agotamiento;
- merma elevada;
- lista de compra;
- reconocer, posponer y resolver alertas;
- sin órdenes automáticas.

### Sprint 39 — Multilocation Executive Dashboard

- agregación autorizada;
- comparación entre locales;
- KPIs ejecutivos;
- aislamiento explícito de cada restaurante.

### Sprint 40 — PWA & iOS/Android Installation

- manifest y service worker;
- instalación móvil;
- estrategia offline limitada y segura;
- actualización y expiración controladas.

## Requisitos transversales iOS y móvil

Toda interfaz futura debe revisar:

- iPhone Safari vertical y horizontal;
- iPad Safari vertical y horizontal;
- Android Chrome;
- tablet Android;
- `100dvh`;
- safe areas y notch;
- teclado virtual;
- botones fijos y zonas táctiles;
- doble toque y doble envío;
- polling al volver de segundo plano;
- pérdida y recuperación de conexión;
- expiración y revocación de sesión;
- añadir a pantalla de inicio.

Debe distinguirse siempre:

- QA automatizada: verificaciones ejecutadas por tests;
- emulación: viewport y navegador de escritorio;
- QA física real: dispositivo, navegador y red reales.

Nunca presentar emulación como prueba física.

## Reglas para el siguiente Codex

- Auditar el workspace y la causa raíz antes de modificar.
- Preservar cambios existentes y revisar el estado Git.
- Trabajar en bloques máximos de tres sprints.
- Validar cada sprint antes de continuar.
- No crear fuentes de verdad paralelas.
- No duplicar lógica de services existentes.
- Mantener routers pequeños y tipados.
- Proteger RBAC, membresías, restaurante e IDOR.
- Mantener compatibilidad SQLite/PostgreSQL.
- Mantener Alembic lineal y probar base vacía/upgrade cuando haya esquema.
- No afirmar pruebas reales que no se hayan ejecutado.
- Diferenciar dinero comercial de costes legacy.
- No introducir TPV, caja o fiscalidad dentro de Payment.
- Detenerse ante commits internos, efectos parciales o riesgos estructurales.
- Ejecutar Alembic, Ruff, Pytest, Compileall, JavaScript, OpenAPI,
  `configure_mappers()` y `git diff --check`.

## Punto exacto de continuidad

El siguiente trabajo autorizado, cuando el usuario lo solicite explícitamente,
es auditar y planificar Sprint 36. No existe implementación parcial de Customer
Status, Assistance, anti-abuse, Operations Center, nuevas alertas ni PWA.
