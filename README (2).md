# Calculadora — Puente de Armadura Tipo Warren (Streamlit)

Aplicación web para análisis estructural de una armadura **tipo Warren** (simétrica) usando Streamlit.

## Estructura del proyecto

- `app.py` — Interfaz web (Streamlit)
- `warren.py` — Lógica de cálculo + historial JSON
- `requirements.txt` — Dependencias
- `README.md` — Guía
- `history.json` — Historial (se crea/actualiza automáticamente)

## Ejecutar localmente

1. Crear entorno e instalar dependencias:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
```

2. Ejecutar:

```bash
streamlit run app.py
```

## Despliegue en Streamlit Cloud

### 1) Crear el repositorio en GitHub

- En GitHub: **New repository**
- Nombre: `calculadora-warren`
- (Recomendado) Public

### 2) Subir archivos

Sube estos archivos en la raíz del repo:

- `app.py`
- `warren.py`
- `requirements.txt`
- `README.md`
- `history.json`

### 3) Conectar GitHub con Streamlit Cloud

- En Streamlit Cloud: **New app**
- Selecciona el repo y rama
- Main file: `app.py`
- Deploy

## Errores comunes (dependencias)

- **ModuleNotFoundError**: verifica que `requirements.txt` esté en la raíz y contenga `streamlit`, `pandas`, `plotly`.
- **Version mismatch**: fija versiones como en `requirements.txt`.

## Verificación

- Abre la URL pública de Streamlit Cloud.
- En la **Home**, presiona **▶ INGRESAR**.
- En la barra lateral, cambia parámetros y presiona **CALCULAR**.
- Revisa: **Resumen**, **Miembros**, **Historial**, **Diagrama**.
