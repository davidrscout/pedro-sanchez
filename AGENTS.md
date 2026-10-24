# Jarvis / Pedro

Asistente personal Python para Windows controlado por Telegram y panel móvil: voz, control remoto, agenda, memoria, lanzadores y vigilancia del PC.

- Modo Leer: mirar y proponer sin tocar. Modo Actuar: cambios solo según la confirmación/flujo previsto del proyecto.
- Seguridad: obedecer solo la cuenta autorizada; enlace revocable con `/caducar`, PIN/TOTP y túnel de salida sin abrir puertos.
- No leer ni exponer `.env`, tokens de Telegram o credenciales. No abrir ventanas ni interferir con la sesión de David salvo que una prueba lo requiera y se avise.
- Pruebas existentes: `python test_web.py`, `python test_nuevo.py`, `python test_kimi.py`, `python test_kimi_guard.py` y `python jarvis.py --selftest`. Ejecutar las que correspondan al cambio.
