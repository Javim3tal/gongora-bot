# gongora-bot

Bot de Telegram que responde con rimas a la última palabra de los mensajes de un grupo
("He quedado a las cinco" → "Por el culo te la hinco").

Adaptación a Python 3 de [morenod/punsBot](https://github.com/morenod/punsBot) (GPL-3.0),
con las rimas de [morenod/defaultpuns](https://github.com/morenod/defaultpuns).

## 1. Crear el bot en Telegram

1. Habla con **@BotFather** → `/newbot` → elige el nombre visible y un username acabado en `bot`.
2. Copia el **token**.
3. `/setprivacy` → tu bot → **Disable** (si no, en grupos solo ve comandos y no rima).
4. Opcional: `/setuserpic`, `/setdescription` y `/setcommands` con:
   ```
   punshelp - Ayuda
   punlist - Lista las rimas
   punadd - Añade una rima (disparador|rima)
   punapprove - +1 a una rima
   punban - -1 a una rima
   pundel - Borra una rima
   punsilence - Silencia el bot X minutos
   punset - Probabilidad de responder (1-100)
   ```

## 2. Configurar

```bash
cp .env.example .env
```
Edita `.env`: pon tu `TOKEN` y el `BOT_NAME` que quieras.

## 3. Arrancar

En local (Mac/Linux):
```bash
./run.sh
```

Con Docker (servidor o Raspberry Pi):
```bash
docker compose up -d --build
```
La base de datos queda en `./data/punsdb.db`; haz copia de esa carpeta.

## Colaborar

Lee [CONTRIBUTING.md](CONTRIBUTING.md). Issues y Pull Requests bienvenidos.

## 4. Usarlo

Añade el bot a tu grupo y escribe `/help`. Las rimas propias se añaden con
`/punadd disparador|rima` (el disparador admite regex, p. ej. `^.*ado$|el que tengo aquí colgado`).

Para añadir rimas por defecto para todos los grupos, edita `defaultpuns/punsfiles/spanishpuns`
(una por línea, `disparador|rima`) y reinicia el bot.

## Mensaje diario

Cada día a las **05:30 (hora de Madrid)** el bot envía a cada grupo una frase al azar de
`defaultpuns/dailymessages` (una por línea; las que empiezan por `#` se ignoran).

- `/pundaily off` / `/pundaily on`: desactivarlo o activarlo en el grupo.
- `/pundaily test`: envía uno ahora para probar.
- La hora y la zona se cambian con `DAILY_TIME` y `TIMEZONE` en el `.env`; `DAILY_TIME=` vacío lo apaga.
- Solo se envía una vez al día aunque el bot se reinicie. Si a las 05:30 estaba parado, lo envía
  al arrancar si aún no son las 06:30; más tarde, ese día se lo salta.
- El bot conoce un grupo cuando alguien escribe en él o cuando lo añaden.

## Despliegue en Lunafy / Pterodactyl (actualización automática)

El servidor arranca `start.py` (variable *App py file* en **Startup**). En cada arranque:

1. descarga la última versión de la rama `main` de este repositorio,
2. sobrescribe los archivos del bot **sin tocar** `.env` ni `data/`,
3. ejecuta `punsbot.py`.

Así, para publicar un cambio basta con hacer merge a `main` y pulsar **Restart** en el panel.
Si cambia `requirements.txt`, `start.py` instala las dependencias nuevas al arrancar.
Para desactivarlo, pon `AUTO_UPDATE=0` en el `.env` del servidor.
