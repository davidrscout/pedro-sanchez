' Rearma el despertador WoL del router (se pierde si el router se reinicia). Sin ventana.
CreateObject("WScript.Shell").Run "C:\Windows\System32\OpenSSH\ssh.exe -i C:\Users\ADMIN\.ssh\asus_router -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new admin@IP_DEL_ROUTER /jffs/wol/start.sh", 0, False
