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
    #
 #   for mob, info in DB_MOBS.get("entidades", {}).items():
 #       if mob in query:
 #           contexto.append(f"### Info sobre {mob.title()}\n{info}")

# Búsqueda de Mobs (Entidades y Diccionario cruzado)
    for mob, info in DB_MOBS.get("entidades", {}).items():
        if mob in query: 
            texto_mob = f"### Características de {mob.title()}\n{info}"
            
            # Fase 2: Buscar si alguna palabra del diccionario aplica a esta entidad o a la consulta
            glosario_aplicable = []
            for termino, definicion in DB_MOBS.get("diccionario", {}).items():
                # Buscamos el término tanto en la descripción del mob como en lo que preguntó el usuario
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
Eres un experto guía de Minecraft Vanilla. Tu misión es acompañar al jugador con entusiasmo.
REGLAS:
1. Usa nombres oficiales en español (Adoquín, Mesa de crafteo, etc.).
2. Formato: Usa guiones "- " para listas y "###" para títulos.
3. No menciones mods.
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
        
        palabras_receta = ["como hacer el", "como hacer la", "como hacer un", "como hacer una", "craftear", "receta de", "fabricar"]
        quiere_receta = any(p in last_user_msg for p in palabras_receta)
        
        contexto_oficial = buscar_contexto(last_user_msg, quiere_receta)

        # 🛡️ CORTOCIRCUITO: Si pide receta y no existe en el JSON
        if quiere_receta and not contexto_oficial:
            error_msg = "Lo siento, no encuentro esa receta en mi manual oficial. 😅 Asegúrate de escribir el nombre exacto del objeto (ej: 'hacha de piedra')."
            
            # Función generadora interna para el error
            def generate_error():
                yield error_msg
                
            return Response(stream_with_context(generate_error()), content_type='text/plain')
        
        # Definir instrucciones RAG
        if contexto_oficial:
            instruccion = f"""
            [DATOS OFICIALES]
            {contexto_oficial}
            
            REGLAS SISTEMA DE VERIFICACIÓN Y LÓGICA (PASOS OBLIGATORIOS):
            1. PASO DE SEGURIDAD (CRÍTICO): Antes de responder, busca palabras clave como "Inmunidades", "Advertencias" o "Limitaciones" en los [DATOS OFICIALES]. 
            2. CONTRASTE DE PREMISA: Si la acción que el usuario propone (ej: usar flechas) coincide con una Inmunidad o Advertencia (ej: Inmunidad a Proyectiles), tu respuesta DEBE EMPEZAR INVALIDANDO la propuesta del usuario. Usa frases como: "En realidad, no es posible hacer eso porque..." o "Cuidado, esa estrategia fallará debido a...".
            3. INFERENCIA TÁCTICA: Una vez descartado lo que NO funciona, usa las "Características" (ej: Altura, Debilidades) para construir una alternativa. Si el dato dice "Inmune a X", busca qué cosa "Y" sí le hace daño o qué límite físico tiene.
            4. DEDUCCIÓN DE ESTRATEGIAS: No te limites a leer. Si el usuario pide ayuda, usa las propiedades físicas (ej: Altura, Vida, Debilidades) para deducir consejos lógicos (ej: si mide 3 bloques, sugiere espacios de 2; si le daña el agua, sugiere baldes).
            5. ANTES DE ESTILIZAR LA RESPUESTA: Tomate tu tiempo y piensa, repasa las reglas 1,2,3 y 4 para reafirmar tu respuesta, luego estilizala.

            ESTILO DE RESPUESTA:
            - Sé un guía experto, no un "sí a todo". Si el jugador va a cometer un error técnico basado en los datos, es tu DEBER detenerlo.
            - Si hay [INICIO_RECETAS], transcríbelas sin cambios.
            - Mantén el tono amigable pero firme con la verdad técnica de Minecraft.
            
            PROHIBICIÓN: 
                - Tienes PROHIBIDO validar una estrategia que los [DATOS OFICIALES] marquen como inútil o imposible.
                - Tienes PROHIBIDO poner en tu respuesta similes a "según los [DATOS OFICIALES]" o NOMBRES DE LOS JSON de tu base de conocimiento.
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