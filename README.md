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

```bash
python -m alembic upgrade head
```

Tambien puedes usar:

```bash
python scripts/migrate.py
```

## Datos demo

El seed oficial es explicito e idempotente. No se ejecuta automaticamente.

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

Reset demo:

```bash
python scripts/reset_demo.py
```

## Ejecutar

```bash
python -m uvicorn main:app --reload
```

Rutas utiles:

- `/menu`
- `/r/demo-restaurant/menu`
- `/admin`
- `/admin/restaurants`
- `/admin/dashboard`
- `/api/dashboard/summary`
- `/api/analytics/events`
- `/health`

## Docker

```bash
docker compose up --build
```

## Render

Configura variables de entorno desde `.env.example`.

Comando recomendado de arranque:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Antes del primer arranque productivo ejecuta:

```bash
python -m alembic upgrade head
python -m app.utils.demo_seed
```

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
