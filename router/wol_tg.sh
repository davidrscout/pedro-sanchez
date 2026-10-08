#!/bin/sh
# Despertador del PC por Telegram (corre en el router ASUS).
# Con el PC apagado, el router atiende el bot de Jarvis: /encender manda el paquete WoL.
# Con el PC encendido no toca Telegram (lo atiende Jarvis).
DIR=/jffs/wol
. $DIR/env            # TOKEN, ALLOWED, MAC, PCIP
API="https://api.telegram.org/bot$TOKEN"
LOG=$DIR/wol.log
OFF=0

log() { echo "$(date '+%F %T') $*" >> $LOG; [ $(wc -c < $LOG) -gt 50000 ] && tail -n 200 $LOG > $LOG.t && mv $LOG.t $LOG; }
send() { curl -s -m 15 "$API/sendMessage" --data-urlencode "chat_id=$ALLOWED" --data-urlencode "text=$1" >/dev/null; }
pc_on() { arping -c2 -w3 -I br0 $PCIP 2>/dev/null | grep -qi "$MAC"; }

wake() {
  ether-wake -b -i br0 $MAC; sleep 1; ether-wake -b -i br0 $MAC
  log "WoL enviado"
  send "⚡ Encendiendo el PC… te aviso cuando esté listo."
  i=0
  while [ $i -lt 36 ]; do sleep 5; i=$((i+1)); pc_on && break; done
  if pc_on; then
    log "PC encendido tras $((i*5)) s"
    send "✅ PC encendido ($((i*5)) s). Jarvis tarda unos 30-60 s en conectarse; luego manda /web CÓDIGO."
  else
    log "PC NO respondió"
    send "⚠️ El PC no ha respondido en 3 min. Revisa la BIOS (Power On By PCI-E) y que el cable esté conectado."
  fi
}

log "arranque"
while true; do
  if pc_on; then sleep 20; continue; fi
  R=$(curl -s -m 60 "$API/getUpdates" -d "offset=$OFF" -d "timeout=45" -d "limit=1" -d 'allowed_updates=["message"]')
  if [ -z "$R" ]; then sleep 10; continue; fi
  if echo "$R" | grep -q '"error_code":409'; then log "409: otro proceso lee el bot, espero"; sleep 300; continue; fi
  echo "$R" | grep -q '"update_id"' || continue
  UID_=$(echo "$R" | sed -n 's/.*"update_id":\([0-9]*\).*/\1/p')
  FROM=$(echo "$R" | sed -n 's/.*"from":{"id":\([0-9]*\).*/\1/p')
  TXT=$(echo "$R" | sed -n 's/.*"text":"\([^"]*\)".*/\1/p' | tr 'A-Z' 'a-z')
  MID=$(echo "$R" | sed -n 's/.*"message_id":\([0-9]*\).*/\1/p')
  OFF=$((UID_+1))
  [ "$FROM" = "$ALLOWED" ] || { log "ignorado de $FROM"; continue; }
  CMD=$(echo "$TXT" | cut -d' ' -f1 | cut -d@ -f1)
  case "$CMD" in
    /encender|/on|/wake|enciende|encender|/web|[0-9][0-9][0-9]*)
      # borra tu mensaje al momento: si lleva el código del Authenticator no se queda visible
      [ -n "$MID" ] && curl -s -m 15 "$API/deleteMessage" -d "chat_id=$ALLOWED" -d "message_id=$MID" >/dev/null
      wake ;;
    *) send "💤 El PC está apagado (te contesta el router). Manda /encender para encenderlo." ;;
  esac
done
