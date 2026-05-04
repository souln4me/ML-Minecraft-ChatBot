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

client = OpenAI(base_url="https://integrate.api.nvidia.com/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "meta/llama-3.3-70b-instruct")

# CARGA DE DATOS EN MEMORIA
try:
    with open("data/recetas.json", "r", encoding="utf-8") as archivo:
        BASE_DE_DATOS = json.load(archivo)
    print(f"Base de datos cargada. Total de recetas: {len(BASE_DE_DATOS)}")
except Exception as e:
    print(f"Error al cargar el archivo JSON: {e}")
    BASE_DE_DATOS = {}

# FUNCIÓN DE BÚSQUEDA
def buscar_datos_crafteo(mensaje_usuario):
    if not BASE_DE_DATOS:
        return ""
    
    mensaje_limpio = mensaje_usuario.lower()
    recetas_encontradas = []
    
    for item, receta in BASE_DE_DATOS.items():
        if item in mensaje_limpio:
            # Añadimos \n\n al principio para separar del saludo de la IA
            if "\n" in receta:
                recetas_encontradas.append(f"\n\n**Receta de {item.title()}**\n{receta}")
            else:
                receta_formateada = receta.replace(" | ", "\n* ")
                recetas_encontradas.append(f"\n\n**Receta de {item.title()}**\n* {receta_formateada}")
                
    if recetas_encontradas:
        return "\n\n".join(recetas_encontradas)
    return ""

SYSTEM_PROMPT = """
Eres un experto guía de Minecraft Vanilla (sin mods) para principiantes. Tu misión es ayudar al jugador.

REGLAS GENERALES:
1. Proporcionas información clara sobre mobs, biomas y progresión con un tono amigable.
2. ESTRUCTURAS: Portales (Nether/End) y refugios se CONSTRUYEN en el mundo, NO se craftean. Nunca des recetas para ellos.
3. FRASE DE AYUDA: Si mencionas un objeto y NO estás dando su receta en este mensaje, añade al final: "*(Pregúntame cómo craftearlo si no lo sabes)*". 
   - REGLA DE ORO: Si ya incluiste la receta (las filas de crafteo) en esta respuesta, tienes ESTRICTAMENTE PROHIBIDO usar esa frase. Es redundante.
4. ESTILO VISUAL: Eres un bot moderno y amigable. Debes usar emojis temáticos de Minecraft (⛏️, 💎, 🧟, ⚔️, 🌲, 🥩, 🌋) de forma natural en tus respuestas para que el texto sea dinámico y atractivo. Usa párrafos cortos.
5. FORMATO MARKDOWN: Cuando enumeres pasos, consejos o materiales usando viñetas (con asteriscos *), es OBLIGATORIO que cada elemento vaya en una línea nueva (salto de línea). NUNCA escribas los asteriscos seguidos en un mismo párrafo.
6. JERARQUÍA VISUAL: NUNCA uses viñetas (*) para títulos o encabezados (como "Día 1", "Día 2"). Usa texto en negrita (**Día 1:**) o títulos Markdown (### Día 1) para separar secciones, y usa las viñetas ÚNICAMENTE para los pasos que van debajo de esos títulos.
7. ACTUALIZACIÓN VERSIÓN 1.20+: Es vital que des información actualizada. 
   - DIAMANTES: Se encuentran en capas negativas (lo ideal es la -59). Ya NO se encuentran en la capa 12.
"""

# RUTAS DE FLASK
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        if not data or "messages" not in data:
            return jsonify({"error": "Mensaje no válido"}), 400

        history = data["messages"]
        
        # Leer SOLO los últimos 3 mensajes del USUARIO
        textos_usuario = " ".join([msg["content"] for msg in history[-3:] if msg["role"] == "user"])
        contexto_crafteo = buscar_datos_crafteo(textos_usuario)
        
        # Enrutamiento RAG
        if contexto_crafteo:
            instruccion_rag = f"""
            [DATOS OFICIALES PARA ESTA CONSULTA]
            {contexto_crafteo}
            
            INSTRUCCIONES DE RESPUESTA: 
            1. Comienza con una introducción amigable y breve.
            2. Deja una línea en blanco y luego pega los [DATOS OFICIALES].
            3. REGLA DE ORO DE CIERRE: Al terminar la "Fila Inferior", presiona la tecla ENTER DOS VECES antes de escribir cualquier consejo final o despedida. 
            4. NUNCA menciones la frase "(Pregúntame cómo craftearlo...)" si ya diste la receta arriba.
            """
        else:
            instruccion_rag = """
            [DATOS OFICIALES PARA ESTA CONSULTA]
            (Vacío. No hay datos para esta consulta).
            
            INSTRUCCIÓN ESTRICTA: Si el usuario te está pidiendo DIRECTAMENTE CÓMO HACER, CREAR o CRAFTEAR un objeto, TIENES PROHIBIDO inventar la receta. Aborta la respuesta y di ÚNICAMENTE esto: "No encuentro esa receta en mi manual. Asegúrate de pedirme el objeto usando su nombre exacto en español (ej: 'hacha de piedra' en lugar de 'stone axe')."
            (Si el usuario solo saluda o pide una guía general, ignora esta instrucción y responde normalmente).
            """

        PROMPT_DINAMICO = SYSTEM_PROMPT + instruccion_rag
        full_messages = [{"role": "system", "content": PROMPT_DINAMICO}] + history

        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=full_messages,
            temperature=0.1, 
            max_tokens=2048,
            stream=True
        )
        
        # Texto de respuesta generativa
        def generate():
            for chunk in completion:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        return Response(stream_with_context(generate()), content_type='text/plain')

    except Exception as e:
        print("ERROR interno:")
        traceback.print_exc()
        return jsonify({"error": f"Error interno: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(debug=True)