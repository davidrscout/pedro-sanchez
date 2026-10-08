@echo off
cd /d "%~dp0"
python -c "import getpass,re,webpanel;p=getpass.getpass('Nuevo PIN: ');q=getpass.getpass('Repite: ');assert p==q and len(p)>=4,'No coinciden o muy corto';s=open('.env',encoding='utf-8').read();h='JARVIS_PIN_HASH='+webpanel.make_hash(p);s=re.sub(r'(?m)^JARVIS_PIN_HASH=.*$',h,s) if 'JARVIS_PIN_HASH=' in s else s.rstrip()+chr(10)+h+chr(10);open('.env','w',encoding='utf-8').write(s);print('PIN cambiado.')"
pause
