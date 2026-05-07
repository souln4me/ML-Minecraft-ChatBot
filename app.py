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
    
    # 1. Buscar en Recetas (LA SOLUCIÓN DEFINITIVA: Listas Markdown Nativas)
    if quiere_receta and DB_RECETAS:
        recetas_encontradas = ""
        for item, receta in DB_RECETAS.items():
            if item in mensaje_limpio:
                # A. Si es una armadura agrupada (separada por ///)
                if "///" in receta:
                    piezas = receta.split("///")
                    for p in piezas:
                        p = p.strip()
                        if ":" in p and "Fila" in p:
                            titulo, filas = p.split(":", 1) # Separa el título de las filas
                            # Convertimos en lista Markdown
                            filas_md = "- " + filas.replace("|", "\n- ").strip()
                            recetas_encontradas += f"### {titulo.strip()}\n{filas_md}\n\n"
                        else:
                            recetas_encontradas += f"{p}\n\n"
                
                # B. Si es una receta individual (Picos, flechas, etc.)
                else:
                    if "Fila" in receta:
                        filas_md = "- " + receta.replace("|", "\n- ").strip()
                        recetas_encontradas += f"### Receta de {item.title()}\n{filas_md}\n\n"
                    else:
                        recetas_encontradas += f"### {item.title()}\n{receta}\n\n"
        
        if recetas_encontradas:
            contexto_encontrado.append(f"[INICIO_RECETAS]\n{recetas_encontradas.strip()}\n[FIN_RECETAS]\n")
                
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
Eres un experto guía de Minecraft Vanilla (sin mods) para principiantes. Tu misión es ayudar al jugador manteniendo siempre una actitud de compañero de aventuras.

REGLAS DE COMPORTAMIENTO Y FORMATO:
1. CONVERSACIÓN PRIMERO: Tu rasgo principal es ser conversacional. NUNCA entregues datos crudos o recetas de inmediato. SIEMPRE debes iniciar tu mensaje con 1 o 2 líneas de charla amigable y útil sobre el tema antes de dar la información técnica.
2. ESTRUCTURAS: Portales (Nether/End) y refugios se CONSTRUYEN en el mundo, NO se craftean. Nunca des recetas para ellos.
3. ESTILO VISUAL: Usa emojis temáticos de Minecraft de forma natural. Usa párrafos cortos para facilitar la lectura.
4. FORMATO MARKDOWN: Para hacer listas, NUNCA uses asteriscos. Usa siempre guiones "- " (guion y espacio). Debes hacer un salto de línea antes de cada guion.
5. JERARQUÍA VISUAL: NUNCA uses viñetas (*) para títulos o encabezados. Usa texto en negrita (**Día 1:**) o títulos Markdown (### Día 1) para separar secciones.
6. TERMINOLOGÍA OFICIAL: Usa exclusivamente los nombres oficiales del juego en español. Di "Pico" (NUNCA "piqueta"), "Craftear", "Mesa de crafteo", "Adoquín", "Lingote de hierro", etc.
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
        textos_usuario = " ".join([msg["content"] for msg in history[-3:] if msg["role"] == "user"]).lower()
        
        # MOTOR DE INTENCIÓN (Añadimos "craftean" y "armadura" para asegurar)
        palabras_crafteo = ["hacer", "crafte", "crear", "receta", "fabrica", "construir", "como se hace", "armadura"]
        quiere_receta = any(palabra in textos_usuario for palabra in palabras_crafteo)
        
        # Buscar contexto pasando la intención
        contexto_oficial = buscar_contexto(textos_usuario, quiere_receta)
        
        if contexto_oficial:
            instruccion_rag = f"""
            [DATOS OFICIALES EXTRAÍDOS]
            {contexto_oficial}
            
            GENERA TU RESPUESTA SIGUIENDO ESTRICTAMENTE ESTOS PASOS EN ORDEN:
            Paso 1: Escribe tu introducción conversacional obligatoria (1 o 2 líneas). Tienes PROHIBIDO usar las frases "¡Hola!", "¡Hola de nuevo!" y "Ahora que...". Entra directo al tema con entusiasmo.
            Paso 2: Si en los datos extraídos ves el "[INICIO_RECETAS]", copia TODO su contenido exacto justo debajo de tu introducción. No imprimas las etiquetas de inicio y fin. REGLA DE ORO: Si el usuario te pide un objeto que NO está en los datos extraídos (ej. pide espada de esmeralda y solo ves espada de hierro), o si te pide un crafteo y no hay recetas extraídas, TIENES PROHIBIDO inventarlo o adaptarlo. Debes decirle que no tienes ese crafteo.
            Paso 3: Si los datos contienen información sobre Mobs o Guías, redacta tus consejos usando guiones ("- "). REGLA CRÍTICA: Basa tus consejos 100% en la info provista; si dice que es inmune a proyectiles, TIENES ABSOLUTAMENTE PROHIBIDO sugerir arcos o flechas.
            """
        else:
            # EL ESCUDO DE PYTHON (Nivel Máximo)
            if quiere_receta:
                instruccion_rag = """
                [ALERTA CRÍTICA DE SISTEMA]
                El usuario solicitó una receta, pero la búsqueda en la base de datos oficial FALLÓ.
                TIENES ESTRICTAMENTE PROHIBIDO INVENTAR LA RECETA.
                Ignora todo tu conocimiento base. Responde ÚNICA Y EXACTAMENTE esto: "Lo siento, no encuentro esa receta. Por favor, pídeme el objeto usando su nombre oficial en español (ej: 'espada' en lugar de 'sword')."
                """
            else:
                instruccion_rag = """
                Responde a la duda general del usuario de forma amigable y útil usando tu conocimiento base de Minecraft Vanilla. No inventes recetas. Tienes PROHIBIDO usar la frase "Ahora que...".
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
        print("ERROR interno:")
        traceback.print_exc()
        return jsonify({"error": f"Error interno: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(debug=True)