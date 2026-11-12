# Avisos con respuesta y llamada por voz — contrato para la app Pedro

Fase 1 de «Jarvis te avisa y puedes llamarle». Tres rutas nuevas del panel, iguales por el **Puente de Tailscale** (la app) y por el
**túnel** (navegador). Todo lo que aquí se dice vale en las dos entradas; lo único que cambia es la `via` con la que queda registrada
una respuesta (`app` por el Puente, `web` por el túnel).

## 0. Cómo se llega (ya existía, no cambia)

1. `POST http://<IP Tailscale>:18765/puente/app` firmado → `{"url": "http://<IP>:18765/a/<token>"}`.
2. `GET` esa url → `302 /app` con `Set-Cookie: sid=…`. La app guarda el `sid` y lo manda en cada llamada.
3. Todas las rutas de este documento son `POST` y exigen:
   - cabecera `Cookie: sid=<sid>` → sin sesión válida: **401** `{"error":"sesion"}`
   - cabecera `X-Jarvis: 1` → sin ella: **403** `{"error":"cabecera"}`
   - `Host: <IP>:18765` (y `Origin` propio, si se manda) → si no: **421**
   - fuera de la red Tailscale el Puente contesta **404** a todo.

Otros códigos comunes: **500** `{"error":"<NombreDeLaExcepción>"}` si algo revienta dentro del PC.

---

## 1. Avisos y preguntas de agentes a David

Un agente (Pedro, un orquestador de T3, cualquier sesión de Claude Code…) deja un aviso. Si es una **pregunta**, se queda esperando
la respuesta. David la ve en la app (pestaña Hablar, tarjeta «Pedro te pregunta») y, por Telegram, un mensaje «❓ <origen> pregunta: …».

### Modelo `Aviso`

```json
{
  "id": "3fa9c1d2",                 // 8 caracteres hex
  "texto": "¿Sigo con el despliegue?",
  "opciones": ["Sí", "No"],         // [] = respuesta libre. Aun con opciones, David puede escribir otra cosa
  "espera": true,                   // true = pregunta (un agente espera); false = solo informativo
  "urgente": false,
  "origen": "Orquestador Gemsy",    // texto libre: quién pregunta
  "creado": "2026-11-12 18:30:05",  // hora local del PC
  "estado": "pendiente",            // pendiente | respondido | caducado | informativo
  "respuesta": null,                // texto de David cuando estado = respondido
  "via": null,                      // app | web | telegram (por dónde respondió)
  "respondido_en": null,            // "YYYY-MM-DD HH:MM:SS"
  "notificado": false               // true cuando Jarvis ya lo entregó a Telegram
}
```

Una pregunta sin responder caduca sola a las **24 h** (`estado: "caducado"`). Los informativos nunca esperan respuesta.

### `POST /api/avisos` — lista

Cuerpo: `{}` o `{"todos": true}`.

- Sin `todos` (o con cualquier valor que no sea el booleano `true`): **solo las pendientes** (preguntas sin responder).
- `{"todos": true}`: también las respondidas, caducadas e informativas.

Respuesta `200`: `{"avisos": [Aviso, …]}` — **más recientes primero**, máximo 50.

```bash
curl -s -X POST http://100.64.0.5:18765/api/avisos -H "Cookie: sid=$SID" -H "X-Jarvis: 1" -H "Content-Type: application/json" -d '{}'
# {"avisos":[{"id":"3fa9c1d2","texto":"¿Sigo con el despliegue?","opciones":["Sí","No"],"espera":true, ... }]}
```

La app puede sondearla cada ~10 s mientras está abierta (el panel web ya lo hace) y usar `avisos.length` como contador.

### `POST /api/avisos/responder` — responder

Cuerpo: `{"id": "3fa9c1d2", "respuesta": "Sí"}`

| Respuesta | Cuándo |
|---|---|
| `200 {"ok": true}` | Registrada. El agente que esperaba la recibe en ≤ 1 s. |
| `400 {"error": "No existe ese aviso."}` | id desconocido |
| `400 {"error": "Ese aviso ya estaba respondido."}` | doble respuesta: **gana la primera** |
| `400 {"error": "Ese aviso ha caducado."}` | pasaron 24 h |
| `400 {"error": "Ese aviso no esperaba respuesta."}` | era informativo |
| `400 {"error": "La respuesta está vacía."}` | `respuesta` en blanco |
| `400 {"error": "La respuesta es demasiado larga (máximo 2000 caracteres)."}` | > 2000 caracteres |
| `400 {"error": "falta la respuesta"}` | `respuesta` ausente o no es texto |

`respuesta` es texto libre (no hace falta que coincida con una de las `opciones`). Se recorta de espacios.
Ante un `400` de «ya respondido/caducado/no existe», la app debe refrescar la lista.

```bash
curl -s -X POST http://100.64.0.5:18765/api/avisos/responder -H "Cookie: sid=$SID" -H "X-Jarvis: 1" -H "Content-Type: application/json" \
  -d '{"id":"3fa9c1d2","respuesta":"Sí"}'
# {"ok":true}
```

### Telegram (opcional, apagado por defecto)

Con `JARVIS_TG_RESPUESTAS=1` en `.env`, el mensaje de Telegram lleva botones con las opciones (`callback_data` `av:<id>:<n>`) y
Jarvis acepta la pulsación **solo del usuario autorizado (`JARVIS_ALLOWED_ID`)**. Sin esa variable los botones no existen y una
pulsación suelta no responde nada. Respondas por donde respondas, el mensaje de Telegram pasa a «✅ Respondido: X» (≤ 20 s).

---

## 2. Llamada por voz: un turno

### `POST /api/llamada/turno`

Un turno de la conversación hablada: David habla → Pedro contesta con texto **y** voz. Usa la **misma conversación** de Pedro
que el chat (misma continuidad), con el prefijo de voz («contesta en 1-3 frases cortas, sin markdown…»).

Se envía **una de dos cosas** en el cuerpo:

| Entrada | `Content-Type` | Cuerpo |
|---|---|---|
| Audio | `audio/*` (`audio/mp4`, `audio/x-m4a`, `audio/wav`, `audio/webm`, `audio/ogg`…) | los bytes del audio, **1 B – 6 000 000 B** (≈ 3-4 min). El PC lo transcribe con Whisper. |
| Texto ya transcrito (el dictado de iOS es más rápido) | `application/json` | `{"texto": "qué hora es"}` (máx. 4000 caracteres) |

**Parámetros** (misma semántica en los tres sitios; prioridad: query string → cabecera → campo del JSON):

| Parámetro | Query | Cabecera | Valores | Por defecto |
|---|---|---|---|---|
| cerebro | `?cerebro=` | `X-Cerebro` | `claude` · `kimi` · `agy` · `local` | `claude` |
| modo | `?modo=` | `X-Modo` | `ask` · `do` | `ask` |
| confirm | `?confirm=` | `X-Confirm` | `true` (o `1`, `si`, `yes`) | — |
| voz | `?voz=` | `X-Voz` | `es-ES-AlvaroNeural`, `es-ES-ElviraNeural`, `es-ES-ArnauNeural`, `es-MX-JorgeNeural`, `es-AR-TomasNeural` | `es-ES-AlvaroNeural` |

- **El cerebro lo elige siempre la app**: no hay enrutado automático. `cerebro=auto` o cualquier otro valor → `400`.
- `modo=do` (Pedro actúa en el PC sin pedir permisos) **exige `confirm=true`**, igual que el resto del panel; si no, `400`.
- Una voz desconocida cae a la de por defecto (no es error).

**Respuesta inmediata `200`:** `{"job": "<id>"}`. Se consulta con `GET /api/job/<id>` (como `/api/preguntar`; basta la cookie), cada ~1 s:

- `{"state": "running"}` mientras trabaja,
- `{"state": "none"}` si el PC se reinició y perdió la tarea,
- `{"state": "done", …}` con el resultado:

```json
{
  "state": "done",
  "oido": "qué hora es",            // lo que entendió (transcripción, o el texto que mandaste)
  "texto": "Son las tres y diez.",  // respuesta de Pedro
  "audio_b64": "SUQzBAAAAA…",       // MP3 de la voz en base64; null si falló la síntesis
  "ms": {"stt": 2100, "cerebro": 4800, "tts": 650}   // duración de cada fase (stt = 0 si mandaste {texto})
}
```

Si una fase falla el job termina igualmente, con un campo extra `error` y los demás campos coherentes (siempre hay `texto`):

| `error` | Qué pasó | Contenido |
|---|---|---|
| `"stt"` | no se pudo transcribir el audio | `oido: ""`, `texto: "No pude transcribir el audio."`, `audio_b64: null` |
| `"sin_voz"` | el audio no traía voz reconocible | `oido: ""`, `texto: "No te he oído bien. ¿Puedes repetirlo?"`, con voz; no molesta al cerebro |
| `"cerebro"` | falló el cerebro | `oido` conservado, `texto: "He tenido un fallo al pensar la respuesta."`, con voz |
| *(ninguno)* | falló **solo** la voz | `texto` correcto y `audio_b64: null`: muéstralo como texto |

Si Pedro estaba ocupado con otra tarea, `texto` es «Sigo con la tarea anterior, espera a que termine.» (un solo cerebro a la vez).

**Errores `400` al enviar** (no se crea job): `{"error": "audio no válido"}` (cuerpo vacío, > 6 MB, o `Content-Type` que no es `audio/*` ni
`application/json`), `{"error": "cuerpo no válido"}`, `{"error": "JSON no válido"}`, `{"error": "vacío"}` (`texto` en blanco),
`{"error": "cerebro desconocido"}`, `{"error": "modo desconocido"}`, `{"error": "falta confirmación"}`.

```bash
# audio grabado en el móvil
curl -s -X POST "http://100.64.0.5:18765/api/llamada/turno?cerebro=claude" -H "Cookie: sid=$SID" -H "X-Jarvis: 1" \
  -H "Content-Type: audio/mp4" --data-binary @turno.m4a
# {"job":"a1b2c3d4e5"}

# el móvil ya transcribió
curl -s -X POST "http://100.64.0.5:18765/api/llamada/turno" -H "Cookie: sid=$SID" -H "X-Jarvis: 1" \
  -H "Content-Type: application/json" -d '{"texto":"qué hora es"}'

curl -s http://100.64.0.5:18765/api/job/a1b2c3d4e5 -H "Cookie: sid=$SID"
```

### Medidas y modelo rápido

- Cada turno deja en `jarvis.log` una línea `llamada: <cerebro>/<modo> modelo=… entrada=… stt=… ms cerebro=… ms tts=… ms total=… ms …`
  (nunca el texto hablado). El Puente además registra `app: POST /api/llamada/turno <código> <ms>`.
- `JARVIS_MODELO_VOZ` en `.env` (p. ej. `haiku` o `sonnet`) hace que **las llamadas** de Claude usen ese modelo más rápido; el chat
  normal sigue con `JARVIS_MODELO`. Vacío = el de siempre. Sigue siendo la suscripción de Claude (coste cero). Solo afecta a `claude`.

---

## 3. Cómo se cuelga un agente

Todo escribe en `avisos.json` (con candado entre procesos) y **no necesita que Jarvis esté escuchando** en ese momento: Jarvis lo
entrega por Telegram en cuanto está en marcha (≤ 20 s). La respuesta de David llega al agente en ≤ 1 s por el propio fichero.

### Desde cualquier sesión (Claude Code, T3, Codex…): `avisar.py`

```bash
# informativo: lo registra y termina (código 0)
python C:\Dev\Jarvis\avisar.py "Terminé el despliegue de Gemsy"

# pregunta: espera la respuesta y la imprime SOLA por stdout
python C:\Dev\Jarvis\avisar.py --pregunta "¿Sigo con el despliegue?" --opciones "Sí|No" --esperar 900 --origen "Orquestador Gemsy"
```

| Opción | Significado |
|---|---|
| `texto` (posicional) | aviso informativo |
| `--pregunta TEXTO` | pregunta; se queda esperando |
| `--opciones "A\|B\|C"` | opciones sugeridas (vacío = libre) |
| `--esperar N` | segundos máximos de espera (por defecto 600) |
| `--origen TXT` | quién pregunta (por defecto «Agente») |
| `--urgente` | marca de urgente |
| `--consultar ID` | ¿ya contestó a aquella pregunta? (con `--esperar N` espera hasta N s) |

**Códigos de salida:** `0` respondido (o informativo registrado) · `2` sin respuesta a tiempo (la pregunta **sigue pendiente**: el id sale
por stderr y se puede volver con `--consultar ID`) · `1` error de uso (texto vacío, demasiadas preguntas pendientes…).
La salida es UTF-8; si la consola no lo es, usar `PYTHONUTF8=1`. Ante un `2`, **no supongas la respuesta de David**.

```bash
resp=$(python C:/Dev/Jarvis/avisar.py --pregunta "¿Borro la rama vieja?" --opciones "Sí|No" --esperar 600 --origen "Orquestador X")
case $? in 0) echo "David dijo: $resp";; 2) echo "Sin respuesta: sigo sin borrar";; esac
```

### Desde Pedro (herramientas MCP, modos `ask` y `do`)

- `avisar_a_david(texto, urgente=False)` — aviso sin respuesta.
- `preguntar_a_david(pregunta, opciones=[], esperar_s=600, urgente=False)` — **bloquea** hasta la respuesta o el timeout y devuelve la
  respuesta de David, o un texto «Sin respuesta en N s (id …)». `esperar_s` va de 5 a **840** (Pedro corta cada tarea a los 15 min).
  Mientras espera, Pedro está ocupado (un solo cerebro a la vez): no te contesta otra cosa hasta que respondas o venza el tiempo.

### Límites

Texto del aviso ≤ 2000 caracteres · ≤ 8 opciones de ≤ 80 caracteres · ≤ 25 preguntas pendientes a la vez · ≤ 60 avisos por hora
(`ValueError` → `avisar.py` sale con `1`; la herramienta MCP devuelve el motivo).

---

## 4. Pruebas

`python test_avisos.py` (módulo, CLI con códigos 0/2, candado entre procesos, MCP) · `python test_app.py` (rutas por el Puente con
sesión, 401/403/404, llamada con stt/brain/tts falsos) · `python test_cerebro.py` (parámetro `modelo`) · `python jarvis.py --selftest`
(entrega a Telegram con `tg` falso: no sale nada real).
