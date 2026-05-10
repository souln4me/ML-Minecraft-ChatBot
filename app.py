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

    # Búsqueda de Mobs (Entidades y Diccionario cruzado)
    for mob, info in DB_MOBS.get("entidades", {}).items():
        if mob in query: 
            texto_mob = f"### Características de {mob.title()}\n{info}"
            
            # Fase 2: Buscar si alguna palabra del diccionario aplica a esta entidad o a la consulta
            glosario_aplicable = []
            for termino, definicion in DB_MOBS.get("diccionario", {}).items():
                if termino in info.lower() or termino in query:
                    glosario_aplicable.append(f"- **{termino.title()}**: {definicion}")
            
            if glosario_aplicable:
                texto_mob += "\n\n### Glosario Aplicable\n" + "\n".join(glosario_aplicable)
                
            contexto.append(texto_mob)

    # Búsqueda en Guías
    for guia, contenido in DB_GUIAS.items():
        if guia in query:
            contexto.append(f"### Guía de {guia.title()}\n{contenido}")

    return "\n\n".join(contexto)

# --- 3. CONFIGURACIÓN DEL PROMPT ---
SYSTEM_PROMPT = """
Eres un experto guía de Minecraft Vanilla. Tu misión es acompañar al jugador con entusiasmo y precisión técnica.
REGLAS BASE:
1. Usa nombres oficiales en español (Adoquín, Mesa de crafteo, etc.).
2. Formato: Usa guiones "- " para listas y "###" para títulos. Si vas a nombrar una lista o título, asegúrate de dejar un espacio vacío antes de empezar a redactar, NO empieces en la misma línea del texto anterior.
3. No menciones mods.
4. Eres estricto con los datos técnicos: no inventas recetas ni debilidades de mobs.
5. Utiliza emojis relacionados a Minecraft.
6. Portales (Nether/End) y refugios se CONSTRUYEN en el mundo, NO se craftean. Nunca des recetas para ellos.
7. Asegúrate de no ser redundante con las respuestas, no vuelvas a mencionar o recomendar algo si ya hablaste de ello en el mismo mensaje.
"""

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        history = data.get("messages", [])
        
        # Analizar intención (Se eliminan acentos para asegurar el match)
        last_user_msg = next((m["content"] for m in reversed(history) if m["role"] == "user"), "").lower()
        msg_sin_acentos = last_user_msg.replace('ó','o').replace('á','a').replace('é','e').replace('í','i').replace('ú','u')
        
        # Palabras clave súper amplias y tolerantes a errores
        palabras_receta = ["hacer", "crafte", "crear", "receta", "fabrica", "armadura", "espada", "pico", "horno", "cofre"]
        quiere_receta = any(p in msg_sin_acentos for p in palabras_receta)
        
        # Ojo: Pasamos el mensaje original (last_user_msg) al buscador para que matchee con el JSON
        contexto_oficial = buscar_contexto(last_user_msg, quiere_receta)

        # 🛡️ CORTOCIRCUITO: Si pide receta y no existe en el JSON
        if quiere_receta and not contexto_oficial:
            error_msg = "Lo siento, no encuentro esa receta en mi manual oficial. 😅 Asegúrate de escribir el nombre exacto del objeto (ej: 'hacha de piedra')."
            
            def generate_error():
                yield error_msg
                
            return Response(stream_with_context(generate_error()), content_type='text/plain')
        
        # Definir instrucciones RAG
        if contexto_oficial:
            instruccion = f"""
            [DATOS OFICIALES]
            {contexto_oficial}
            
            COMO MOTOR DE PROCESAMIENTO, DEBES EVALUAR LA SITUACIÓN Y APLICAR SOLO EL MÓDULO CORRECTO:

            === MÓDULO A: PREGUNTAS DE CRAFTEO (Si ves [INICIO_RECETAS] en los datos) ===
            1. Apertura: Frase de entusiasmo de +10 palabras.
            2. LA IMPRESORA: Tienes la OBLIGACIÓN ESTRICTA de transcribir todo el contenido exacto entre [INICIO_RECETAS] y [FIN_RECETAS]. ¡NO RESUMAS NI OMITAS LAS FILAS!
            3. SILENCIO TÉCNICO: Tienes PROHIBIDO sumar materiales (ej: "necesitas 8 bloques") y PROHIBIDO explicar cómo usar la mesa de crafteo. 
            4. Cierre: Un consejo rápido de utilidad.

            === MÓDULO B: COMBATE Y SUPERVIVENCIA (Para mobs y guías) ===
            1. VERIFICACIÓN (CRÍTICO): Busca "Inmunidades" o "Advertencias".
            2. INVALIDACIÓN: Si el usuario sugiere algo inútil, EMPIEZA INVALIDANDO su idea (Ej: "Cuidado, no uses proyectiles porque...").
            3. ESTRATEGIA: Usa las características/debilidades para deducir una táctica real que sí funcione.

            REGLAS GLOBALES (PROHIBICIONES CRÍTICAS):   
            - REACCIÓN NARRATIVA OBLIGATORIA: Tu mensaje DEBE comenzar con una frase completa de entusiasmo o advertencia sobre el objeto (Mínimo 10 palabras). Ejemplo: "¡Preparar equipo de diamante es el paso definitivo para conquistar el End!" o "¡El oro brilla mucho pero ten cuidado con su durabilidad!". Tienes PROHIBIDO usar solo emojis o las frases "¡Hola!", "¡Hola de nuevo!" o "Ahora que...".
            - NUNCA menciones que lees [DATOS OFICIALES] o archivos JSON. Habla como un experto humano.
            - NUNCA inventes recetas. Si te piden algo que no está en el texto oficial (como armadura de obsidiana), niégate.
            """
        else:
            instruccion = "Responde amigablemente. Tienes PROHIBIDO inventar recetas o dar datos técnicos específicos si no se te proveen en [DATOS OFICIALES]."

        messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n" + instruccion}] + history

        # Streaming a la API de Nvidia
        def generate():
            completion = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                temperature=0.1, # Baja temperatura para máxima obediencia al contexto
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