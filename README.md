# 🐉 Asistente de Supervivencia - Rumbo a la Dragona

Un asistente de supervivencia para Minecraft Vanilla basado en una arquitectura **RAG (Retrieval-Augmented Generation)**. Este chatbot ayuda a los jugadores desde su primer día talando árboles hasta la batalla final contra la Enderdragón, proporcionando información precisa sobre crafteos, debilidades de mobs y estrategias de supervivencia.

## 🛠️ Tecnologías Utilizadas

* **Backend:** Python, Flask, Flask-CORS.
* **IA & LLMs:** OpenAI SDK (NVIDIA API Integration), Prompt Engineering avanzado.
* **Frontend:** HTML5, CSS3, Vanilla JavaScript, Marked.js.
* **Almacenamiento de Conocimiento:** Archivos JSON estructurados.

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
   OPENAI_API_KEY=tu_clave_api_aqui
   MODEL_NAME=meta/llama-3.3-70b-instruct
   ```

3. Reemplaza `tu_clave_api_aqui` con tu clave de API de NVIDIA (o el proveedor que uses)

**Importante**: El archivo `.env` ya está incluido en `.gitignore` y NO debe subirse al repositorio para proteger tus credenciales.

## Ejecución

```bash
python app.py
```

La aplicación estará disponible en `http://localhost:5000`
