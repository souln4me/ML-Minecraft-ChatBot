import os
import json
import traceback
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
app = Flask(__name__)
CORS(app)

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY")
)
MODEL_NAME = os.getenv("MODEL_NAME", "meta/llama-3.3-70b-instruct")

# 1. CARGA DE DATOS EN MEMORIA (ARQUITECTURA MULTI-DOCUMENTO Y ONTOLÓGICA)
try:
    with open("data/recetas.json", "r", encoding="utf-8") as archivo:
        DB_RECETAS = json.load(archivo)
    print(f"Base de recetas cargada: {len(DB_RECETAS)} ítems.")
except Exception as e:
    print(f"Error al cargar recetas.json: {e}")
    DB_RECETAS = {}

try:
    with open("data/mobs.json", "r", encoding="utf-8") as archivo:
        DB_MOBS = json.load(archivo)
    # Verificamos si tiene la estructura nueva (entidades)
    entidades_count = len(DB_MOBS.get("entidades", {}))
    print(f"Base de conocimiento (mobs/diccionario) cargada: {entidades_count} entidades.")
except Exception as e:
    print(f"Aviso: No se encontró mobs.json o hubo un error: {e}")
    DB_MOBS = {}
    
try:
    with open("data/guias.json", "r", encoding="utf-8") as archivo:
        DB_GUIAS = json.load(archivo)
    print(f"Guías cargadas: {len(DB_GUIAS)} ítems.")
except Exception as e:
    print(f"Error al cargar guias.json: {e}")
    DB_GUIAS = {}

# 2. FUNCIÓN DE BÚSQUEDA UNIFICADA (CON BÚSQUEDA CRUZADA)
def buscar_contexto(mensaje_usuario, quiere_receta):
    mensaje_limpio = mensaje_usuario.lower()
    contexto_encontrado = []
    
    # 1. Buscar en Recetas (SOLO SI EL USUARIO QUIERE CRAFTEAR)
    if quiere_receta and DB_RECETAS:
        for item, receta in DB_RECETAS.items():
            if item in mensaje_limpio:
                if "\n" in receta:
                    cuerpo = receta
                else:
                    cuerpo = "* " + receta.replace(" | ", "\n* ")
                contexto_encontrado.append(f"### Receta de {item.title()}\n{cuerpo}\n\n")
                
    # 2. Buscar en Mobs 
    if DB_MOBS and "entidades" in DB_MOBS:
        for mob, info in DB_MOBS["entidades"].items():
            if mob in mensaje_limpio:
                texto_mob = f"### Info sobre {mob.title()}\n{info}"
                if "diccionario" in DB_MOBS:
                    terminos_diccionario = []
                    for termino, definicion in DB_MOBS["diccionario"].items():
                        if termino in info.lower() or termino in mensaje_limpio:
                            terminos_diccionario.append(f"- {termino.title()}: {definicion}")
                    if terminos_diccionario:
                        texto_mob += "\n\n**Glosario Aplicable:**\n" + "\n".join(terminos_diccionario)
                contexto_encontrado.append(texto_mob)
                
    # 3. Buscar en Guías
    if DB_GUIAS:
        for tema, info in DB_GUIAS.items():
            if tema in mensaje_limpio:
                contexto_encontrado.append(f"### Guía sobre {tema.title()}\n{info}\n\n")
                
    if contexto_encontrado:
        return "\n\n".join(contexto_encontrado)
    return ""

# 3. PROMPT DEL SISTEMA
SYSTEM_PROMPT = """
Eres un experto guía de Minecraft Vanilla (sin mods) para principiantes. Tu misión es ayudar al jugador.

REGLAS GENERALES:
1. Proporcionas información clara sobre mobs, biomas y progresión con un tono amigable.
2. ESTRUCTURAS: Portales (Nether/End) y refugios se CONSTRUYEN en el mundo, NO se craftean. Nunca des recetas para ellos.
3. ESTILO VISUAL: Eres un bot moderno y amigable. Debes usar emojis temáticos de Minecraft de forma natural. Usa párrafos cortos.
4. FORMATO MARKDOWN: Para hacer listas, NUNCA uses asteriscos. Usa siempre guiones "- " (guion y espacio). Debes hacer un salto de línea antes de cada guion.
5. JERARQUÍA VISUAL: NUNCA uses viñetas (*) para títulos o encabezados (como "Día 1", "Día 2"). Usa texto en negrita (**Día 1:**) o títulos Markdown (### Día 1) para separar secciones.
6. TERMINOLOGÍA OFICIAL: Usa exclusivamente los nombres oficiales del juego en español. Di "Pico" (NUNCA "piqueta"), "Craftear", "Mesa de crafteo", "Adoquín", "Lingote de hierro", etc.
"""

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        history = data.get("messages", [])
        
        # Analizar intención de los últimos mensajes
        last_user_msg = next((m["content"] for m in reversed(history) if m["role"] == "user"), "").lower()
        
        # MOTOR DE INTENCIÓN (Añadimos "craftean" y "armadura" para asegurar)
        palabras_crafteo = ["hacer", "craftear", "craftean", "crear", "receta", "fabrica", "construir", "como se hace", "armadura"]
        quiere_receta = any(palabra in textos_usuario for palabra in palabras_crafteo)
        
        # Buscar contexto pasando la intención
        contexto_oficial = buscar_contexto(textos_usuario, quiere_receta)
        
        if contexto_oficial:
            instruccion_rag = f"""
            INFORMACION PARA TU RESPUESTA:
            {contexto_oficial}
            
            INSTRUCCIÓN DE RESPUESTA DE OBLIGADO CUMPLIMIENTO:
            1. INICIO FLUÍDO: Entra SIEMPRE directo al tema con entusiasmo (ej: "¡Claro que sí!", "¡Buena pregunta!"). TIENES ESTRICTAMENTE PROHIBIDO repetir siempre "¡Hola!" u "¡Hola de nuevo!".
            2. RECETAS: Si en la información arriba ves "### Receta de...", CÓPIALA EXACTAMENTE respetando sus saltos de línea.
            3. MOBS Y GUÍAS: Úsalos como tu conocimiento interno para redactar consejos usando guiones (-). REGLA INQUEBRANTABLE: NUNCA des consejos que contradigan esta información.
            4. CIERRE: Deja una línea en blanco al final y da una despedida dinámica.
            """
        else:
            # EL ESCUDO DE PYTHON: Si quiere receta y no hay datos, la IA es amordazada.
            if quiere_receta:
                instruccion_rag = """
                [ALERTA DE SISTEMA]
                El usuario está pidiendo una receta que NO EXISTE en tu base de datos oficial.
                TIENES ESTRICTAMENTE PROHIBIDO INVENTAR LA RECETA O DAR INSTRUCCIONES DE CRAFTEO.
                Tu única respuesta debe ser EXACTAMENTE esta: "Lo siento, no tengo esa receta en mi manual. Asegúrate de pedirme el objeto usando su nombre exacto en español."
                """
            else:
                instruccion_rag = """
                Responde a la duda general del usuario de forma amigable y útil usando tu conocimiento base de Minecraft Vanilla. No inventes recetas.
                """

        PROMPT_DINAMICO = SYSTEM_PROMPT + "\n" + instruccion_rag
        full_messages = [{"role": "system", "content": PROMPT_DINAMICO}] + history

        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=full_messages,
            temperature=0.1, 
            max_tokens=2048,
            stream=True
        )
        
        def generate():
            for chunk in completion:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        return Response(stream_with_context(generate()), content_type='text/plain')

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)