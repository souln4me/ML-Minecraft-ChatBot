## Instalación de dependencias

1. Clona el repositorio o descarga los archivos del proyecto

2. **Crea un entorno virtual de Python**:
   ```bash
   python -m venv venv
   ```

3. **Activa el entorno virtual**:
   - En Windows:
     ```bash
     venv\Scripts\Activate
     ```
   - En macOS/Linux:
     ```bash
     source venv/bin/activate
     ```

4. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```

5. Verifica que todas las dependencias se instalaron correctamente

## Configuración del archivo .env

1. Crea un archivo llamado `.env` en la raíz del proyecto (junto a `app.py`)

2. Copia la siguiente estructura en el archivo:
   ```env
   API_KEY=tu_clave_api_aqui
   MODEL_NAME=meta/llama-3.3-70b-instruct
   ```

3. Reemplaza `tu_clave_api_aqui` con tu clave de API de NVIDIA (o el proveedor que uses)

**Importante**: El archivo `.env` ya está incluido en `.gitignore` y NO debe subirse al repositorio para proteger tus credenciales.

## Ejecución

```bash
python app.py
```

La aplicación estará disponible en `http://localhost:5000`
