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

# --- 1. CARGA DE BASES DE DATOS ---
def cargar_json(ruta):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error cargando {ruta}: {e}")
        return {}

DB_RECETAS = cargar_json("data/recetas.json")
DB_MOBS = cargar_json("data/mobs.json")
DB_GUIAS = cargar_json("data/guias.json")

# --- 2. MOTOR DE BÚSQUEDA RAG ---
def buscar_contexto(query, es_receta):
    query = query.lower()
    contexto = []

    # Búsqueda de Recetas
    if es_receta:
        recetas_encontradas = ""
        for item, valor in DB_RECETAS.items():
            if item in query:
                # Manejo de armaduras agrupadas (separadas por ///)
                if "///" in valor:
                    piezas = valor.split("///")
                    for p in piezas:
                        p = p.strip()
                        if ":" in p and "Fila" in p:
                            titulo, filas = p.split(":", 1)
                            filas_md = "- " + filas.replace("|", "\n- ").strip()
                            recetas_encontradas += f"### {titulo.strip()}\n{filas_md}\n\n"
                else:
                    # Recetas simples o instrucciones de fundición
                    if "Fila" in valor:
                        filas_md = "- " + valor.replace("|", "\n- ").strip()
                        recetas_encontradas += f"### Receta de {item.title()}\n{filas_md}\n\n"
                    else:
                        recetas_encontradas += f"### {item.title()}\n{valor}\n\n"
        
        if recetas_encontradas:
            contexto.append(f"[INICIO_RECETAS]\n{recetas_encontradas.strip()}\n[FIN_RECETAS]")

    # Búsqueda de Mobs (Entidades)
    for mob, info in DB_MOBS.get("entidades", {}).items():
        if mob in query:
            contexto.append(f"### Info sobre {mob.title()}\n{info}")

    # Búsqueda en Guías
    for guia, contenido in DB_GUIAS.items():
        if guia in query:
            contexto.append(f"### Guía de {guia.title()}\n{contenido}")

    return "\n\n".join(contexto)

# --- 3. CONFIGURACIÓN DEL PROMPT ---
SYSTEM_PROMPT = """
Eres un experto guía de Minecraft Vanilla con un toque ingenioso y aventurero. 
REGLAS DE ORO:
1. NUNCA menciones frases como "Según los datos oficiales", "En el bloque de datos" o "En el JSON". Úsalos para informar, pero haz que parezca que es TU conocimiento experto.
2. Usa nombres oficiales en español (Adoquín, Mesa de crafteo, etc.).
3. Formato: Usa guiones "- " para listas y "###" para títulos de secciones.
4. Tono: Sé amigable, motivador y usa emojis relacionados a Minecraft.
5. No menciones mods.
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
        
        palabras_receta = ["hacer", "crafte", "crear", "receta", "fabrica", "como se hace", "armadura"]
        quiere_receta = any(p in last_user_msg for p in palabras_receta)
        
        contexto_oficial = buscar_contexto(last_user_msg, quiere_receta)

        # 🛡️ CORTOCIRCUITO: Si pide receta y no existe en el JSON
        if quiere_receta and not contexto_oficial:
            error_msg = "Lo siento, no encuentro esa receta en mi libro oficial. 😅 ¿Podrías intentar con el nombre exacto en español?"
            return Response(stream_with_context(lambda: (yield error_msg)), content_type='text/plain')

        # Definir instrucciones RAG
        if contexto_oficial:
            instruccion = f"""
            [DATOS OFICIALES]
            {contexto_oficial}
            
            REGLAS DE GENERACIÓN (DE CUMPLIMIENTO ESTRICTO):
            1. REACCIÓN NARRATIVA OBLIGATORIA: Tu mensaje DEBE comenzar con una frase completa de entusiasmo o advertencia sobre el objeto (Mínimo 10 palabras). Ejemplo: "¡Preparar equipo de diamante es el paso definitivo para conquistar el End!" o "¡El oro brilla mucho pero ten cuidado con su durabilidad!". Tienes PROHIBIDO usar solo emojis o las frases "¡Hola!", "¡Hola de nuevo!" o "Ahora que...".
            2. REPRODUCCIÓN EXACTA: Si hay "[INICIO_RECETAS]", pega las recetas JUSTO DEBAJO de tu charla tal cual está. 
            3. SILENCIO TÉCNICO: Tras pegar la receta, TIENES TERMINANTEMENTE PROHIBIDO explicar con palabras dónde colocar los materiales (Ej: No digas "Pon el adoquín arriba..."). La receta en lista ya lo explica sola.
            4. REGLA ANTIFRAUDE: Si el material pedido no está en los datos, niégate. Prohibido inventar o adaptar materiales.
            5. CONSEJO DE AVENTURA: Finaliza con un solo consejo breve sobre la UTILIDAD del objeto o cómo conseguir los materiales (basado 100% en los datos), y un emoji de cierre.
            """
        else:
            instruccion = "Responde amigablemente. Tienes PROHIBIDO inventar recetas si no se te proveen en [DATOS OFICIALES]."

        messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n" + instruccion}] + history

        # Streaming a la API de Nvidia
        def generate():
            completion = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                temperature=0.1, # Temperatura baja para mayor precisión técnica
                stream=True
            )
            for chunk in completion:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        return Response(stream_with_context(generate()), content_type='text/plain')

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)