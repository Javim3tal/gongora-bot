# -*- coding: utf-8 -*-
"""Bot de Telegram que responde con rimas a la última palabra de cada mensaje.

Adaptación a Python 3 de https://github.com/morenod/punsBot (GPL-3.0),
original de David Sanz, Karim Boumedhel y Raul Sevilla.
"""
import datetime
import os
import random
import re
import sqlite3
import string
import threading
import time
import unicodedata
import uuid
from zoneinfo import ZoneInfo

import telebot


def load_dotenv(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")):
    """Carga KEY=valor de .env (sin pisar variables ya definidas). Útil en hostings tipo Pterodactyl."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

VERSION = "1.1.0"

BOT_NAME = os.environ.get("BOT_NAME", "PunsBot")
REQUIRED_VALIDATIONS = int(os.environ.get("REQUIRED_VALIDATIONS", "5"))
MAX_SILENCE_MINUTES = 60
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUNS_DIR = os.path.join(BASE_DIR, "defaultpuns", "punsfiles")

# Mensaje diario: a DAILY_TIME (hora de TIMEZONE) envía una frase al azar de DAILY_FILE
# a cada grupo que lo tenga activado. DAILY_TIME vacío lo desactiva del todo.
DAILY_TIME = os.environ.get("DAILY_TIME", "05:30").strip()
DAILY_FILE = os.path.join(BASE_DIR, "defaultpuns", "dailymessages")
DAILY_WINDOW_MINUTES = 60  # si el bot arranca tarde, aún envía hasta 1 h después
# Probabilidad (%) de que un grupo reciba el mensaje un día concreto: no sale todos los días.
DAILY_PROBABILITY = max(0, min(100, int(os.environ.get("DAILY_PROBABILITY", "30"))))
try:
    TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Madrid"))
except Exception as exc:  # sin datos de zonas horarias: hora del servidor
    print("Aviso: zona horaria no disponible (%s); uso la hora del servidor" % exc)
    TZ = None

ALLOWED_CHARS_PUNS = string.ascii_letters + " " + string.digits + "áéíóúàèìòùäëïöüñ"
ALLOWED_CHARS_TRIGGERS = ALLOWED_CHARS_PUNS + "^$.*+?(){}\\[]<>=-|"

bot = None   # se crea en main()
punsdb = None


# ---------------------------------------------------------------- utilidades

def strip_accents(text):
    """'canción' -> 'cancion' (la ñ pasa a n, igual que en el bot original)."""
    return unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("ASCII")


def is_valid_regex(regexp=""):
    try:
        re.compile(regexp)
        return True
    except re.error:
        return False


def get_args(message):
    """Texto tras el comando. Soporta '/punadd@MiBot loquesea' en grupos."""
    parts = (message.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def connect():
    return sqlite3.connect(punsdb)


def member_count(chatid):
    try:
        return bot.get_chat_member_count(chatid)
    except Exception:
        return 1  # chat privado o error de la API


def karma_of(cursor, punid, chatid):
    row = cursor.execute(
        "SELECT SUM(karma) FROM validations WHERE punid = ? AND chatid = ?", (punid, chatid)
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def is_enabled(karma, members):
    if members >= REQUIRED_VALIDATIONS:
        return karma >= REQUIRED_VALIDATIONS
    return karma > 0


# ------------------------------------------------------------- base de datos

def load_default_puns(punsfile):
    db = connect()
    cursor = db.cursor()
    with open(punsfile, "r", encoding="utf-8") as staticpuns:
        for number, line in enumerate(staticpuns, start=1):
            if not line.strip():
                continue
            if len(line.split("|")) != 2:
                print("Línea %s incorrecta en %s. No se añade" % (number, punsfile))
                continue
            trigger, pun = (x.strip() for x in line.split("|"))
            trigger = strip_accents(trigger.lower())  # "liñan" -> "linan", igual que el mensaje
            if not is_valid_regex(trigger):
                print("Regex %s incorrecta en la línea %s de %s. No se añade" % (trigger, number, punsfile))
                continue
            exists = cursor.execute(
                "SELECT count(trigger) FROM puns WHERE pun = ? AND trigger = ? AND chatid = 0", (pun, trigger)
            ).fetchone()[0]
            if exists == 0:
                cursor.execute(
                    "INSERT INTO puns(uuid,chatid,trigger,pun) VALUES(?,?,?,?)",
                    (str(uuid.uuid4()), 0, trigger, pun),
                )
                print('Rima por defecto "%s" añadida para "%s"' % (pun, trigger))
    db.commit()
    db.close()


def db_setup():
    db = connect()
    cursor = db.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS puns (uuid text, chatid int, trigger text, pun text)")
    cursor.execute("CREATE TABLE IF NOT EXISTS validations (punid text, chatid int, userid text, karma int)")
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS chatoptions (chatid int, silence int, efectivity int, unique (chatid))"
    )
    # Grupos en los que está el bot (para el mensaje diario) y estado global
    cursor.execute("CREATE TABLE IF NOT EXISTS chats (chatid int PRIMARY KEY, title text, daily int DEFAULT 1)")
    cursor.execute("CREATE TABLE IF NOT EXISTS meta (key text PRIMARY KEY, value text)")
    # Grupos que ya usaban el bot antes de existir la tabla chats (ids de grupo < 0)
    cursor.execute(
        "INSERT OR IGNORE INTO chats(chatid) "
        "SELECT chatid FROM puns WHERE chatid < 0 UNION SELECT chatid FROM validations WHERE chatid < 0 "
        "UNION SELECT chatid FROM chatoptions WHERE chatid < 0"
    )
    db.commit()
    db.close()
    for name in sorted(os.listdir(PUNS_DIR)):
        load_default_puns(os.path.join(PUNS_DIR, name))


def load_chat_options(chatid):
    db = connect()
    row = db.execute("SELECT silence, efectivity FROM chatoptions WHERE chatid = ?", (chatid,)).fetchone()
    db.close()
    return {
        "chatid": chatid,
        "silence": row[0] if row else None,
        "efectivity": row[1] if row else None,
    }


def set_chat_options(opts):
    db = connect()
    db.execute(
        "INSERT OR REPLACE INTO chatoptions(chatid,silence,efectivity) VALUES(?,?,?)",
        (opts["chatid"], opts["silence"], opts["efectivity"]),
    )
    db.commit()
    db.close()


def is_chat_silenced(chatid):
    silence = load_chat_options(chatid)["silence"]
    return silence is not None and int(silence) > time.time()


def silence_until(chatid):
    silence = load_chat_options(chatid)["silence"]
    if silence is not None and int(silence) > time.time():
        return time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(int(silence)))
    return "nunca"


def efectivity(chatid):
    value = load_chat_options(chatid)["efectivity"]
    return 100 if value is None else int(value)


def is_efective(chatid):
    return efectivity(chatid) >= random.randint(1, 100)


def remember_chat(message):
    """Apunta los grupos en los que está el bot (los chats privados no reciben el mensaje diario)."""
    if message.chat.type not in ("group", "supergroup"):
        return
    db = connect()
    db.execute("INSERT OR IGNORE INTO chats(chatid, title) VALUES(?, ?)", (message.chat.id, message.chat.title))
    db.execute("UPDATE chats SET title = ? WHERE chatid = ?", (message.chat.title, message.chat.id))
    db.commit()
    db.close()


def get_meta(key, default=None):
    db = connect()
    row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    db.close()
    return row[0] if row else default


def set_meta(key, value):
    db = connect()
    db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, value))
    db.commit()
    db.close()


def now_local():
    return datetime.datetime.now(TZ) if TZ else datetime.datetime.now()


def daily_messages():
    if not os.path.isfile(DAILY_FILE):
        return []
    with open(DAILY_FILE, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]


def daily_due(now, last_sent):
    """¿Toca enviar? Solo dentro de la ventana [DAILY_TIME, +DAILY_WINDOW_MINUTES) y una vez al día."""
    if not DAILY_TIME:
        return False
    hour, minute = (int(x) for x in DAILY_TIME.split(":"))
    start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    in_window = start <= now < start + datetime.timedelta(minutes=DAILY_WINDOW_MINUTES)
    return in_window and last_sent != now.date().isoformat()


def send_daily(chatids=None, probability=100):
    """Envía una frase al azar a cada grupo activo (o a chatids), cada uno con `probability` % de
    posibilidades. Devuelve cuántos envíos salieron bien."""
    messages = daily_messages()
    if not messages:
        print("Mensaje diario: el archivo dailymessages está vacío")
        return 0
    if chatids is None:
        db = connect()
        chatids = [r[0] for r in db.execute("SELECT chatid FROM chats WHERE daily = 1").fetchall()]
        db.close()
    sent = 0
    for chatid in chatids:
        if random.randint(1, 100) > probability:
            continue  # hoy no le toca a este grupo
        text = random.choice(messages)
        try:
            bot.send_message(chatid, text)
            sent += 1
        except telebot.apihelper.ApiTelegramException as exc:
            print("Mensaje diario: no se pudo enviar a %s (%s)" % (chatid, exc.description))
            if exc.error_code in (400, 403):  # el bot ya no está en el grupo
                db = connect()
                db.execute("UPDATE chats SET daily = 0 WHERE chatid = ?", (chatid,))
                db.commit()
                db.close()
        except Exception as exc:
            print("Mensaje diario: error enviando a %s: %s" % (chatid, exc))
        time.sleep(0.1)
    return sent


def daily_loop():
    while True:
        try:
            now = now_local()
            if daily_due(now, get_meta("daily_last_sent")):
                set_meta("daily_last_sent", now.date().isoformat())  # antes de enviar: nunca duplica
                # El sorteo se hace una vez al día: reiniciar no da otra oportunidad
                print("Mensaje diario (%s%%): enviado a %s grupos" % (DAILY_PROBABILITY, send_daily(probability=DAILY_PROBABILITY)))
        except Exception as exc:
            print("Mensaje diario: error inesperado: %s" % exc)
        time.sleep(30)


def find_pun(message):
    words = "".join(c for c in message.text.lower() if c in ALLOWED_CHARS_PUNS).split()
    if not words:
        return None
    last_clean = strip_accents(words[-1])
    chatid = message.chat.id
    db = connect()
    cursor = db.cursor()
    answers = []
    members = None
    rows = cursor.execute(
        "SELECT uuid, pun, chatid, trigger FROM puns WHERE chatid = ? OR chatid = 0", (chatid,)
    ).fetchall()
    for punid, pun, pun_chat, trigger in rows:
        if not is_valid_regex(trigger) or not re.match("^(?:" + trigger + ")$", last_clean):
            continue
        if strip_accents(pun.split()[-1].lower()) == last_clean:
            continue  # la rima acabaría con la misma palabra
        if pun_chat == 0:
            answers.append(pun)
            continue
        if members is None:
            members = member_count(chatid)
        if is_enabled(karma_of(cursor, punid, chatid), members):
            answers.append(pun)
    db.close()
    return random.choice(answers) if answers else None


# ------------------------------------------------------------------ comandos

def cmd_help(message):
    text = (
        "Comandos de %(name)s:\n"
        "/punadd disparador|rima  Añade una rima\n"
        "/pundel uuid  Borra una rima de este chat\n"
        "/punlist  Lista las rimas (/list, /punslist)\n"
        "/punapprove uuid  +1 a una rima\n"
        "/punban uuid  -1 a una rima\n"
        "/punsilence minutos  Silencia el bot (máx. %(max)s)\n"
        "/punset 1-100  Probabilidad de responder\n"
        "/pundaily on|off  Mensaje sorpresa de las %(daily)s\n"
        "/punshelp  Esta ayuda (/help)\n\n"
        "Silenciado hasta: %(until)s\n"
        "Probabilidad de responder: %(eff)s%%\n"
        "Mensaje diario: %(daily_state)s\n\n"
        "Las rimas nuevas se activan con karma %(req)s en grupos de %(req)s o más personas; "
        "en grupos más pequeños basta con karma positivo.\n\n"
        "Versión %(ver)s"
    ) % {
        "name": BOT_NAME,
        "max": MAX_SILENCE_MINUTES,
        "until": silence_until(message.chat.id),
        "eff": efectivity(message.chat.id),
        "daily": DAILY_TIME or "--:--",
        "daily_state": daily_state(message.chat.id),
        "req": REQUIRED_VALIDATIONS,
        "ver": VERSION,
    }
    bot.reply_to(message, text)


def vote(message, karma):
    punid = get_args(message)
    command = "/punapprove" if karma > 0 else "/punban"
    if not punid:
        bot.reply_to(message, "Falta el uuid. Uso: %s uuid" % command)
        return
    chatid, userid = message.chat.id, str(message.from_user.id)
    db = connect()
    cursor = db.cursor()
    exists = cursor.execute(
        "SELECT count(uuid) FROM puns WHERE chatid = ? AND uuid = ?", (chatid, punid)
    ).fetchone()[0]
    if exists != 1:
        bot.reply_to(message, "No encuentro la rima " + punid)
    elif cursor.execute(
        "SELECT count(punid) FROM validations WHERE chatid = ? AND punid = ? AND userid = ? AND karma = ?",
        (chatid, punid, userid, karma),
    ).fetchone()[0] >= 1:
        bot.reply_to(message, "Ya has votado eso en " + punid + ". Solo un voto por persona.")
    else:
        cursor.execute(
            "INSERT INTO validations(punid,chatid,userid,karma) VALUES(?,?,?,?)", (punid, chatid, userid, karma)
        )
        db.commit()
        bot.reply_to(message, "Voto registrado. Karma de %s: %s" % (punid, karma_of(cursor, punid, chatid)))
    db.close()


def cmd_approve(message):
    vote(message, 1)


def cmd_ban(message):
    vote(message, -1)


def cmd_add(message):
    args = get_args(message)
    if "|" not in args:
        bot.reply_to(message, "Uso: /punadd disparador|rima\nEjemplo: /punadd carlos|el de los cojones largos")
        return
    trigger, pun = (x.strip() for x in args.rsplit("|", 1))
    trigger = strip_accents(trigger.lower())
    if not trigger or not pun:
        bot.reply_to(message, "Ni el disparador ni la rima pueden estar vacíos")
        return
    for character in trigger:
        if character not in ALLOWED_CHARS_TRIGGERS:
            bot.reply_to(message, "Carácter no permitido en el disparador: " + character)
            return
    if not is_valid_regex(trigger):
        bot.reply_to(message, "El disparador no es una expresión regular válida: " + trigger)
        return
    chatid = message.chat.id
    db = connect()
    cursor = db.cursor()
    exists = cursor.execute(
        "SELECT count(trigger) FROM puns WHERE trigger = ? AND chatid = ? AND pun = ?", (trigger, chatid, pun)
    ).fetchone()[0]
    if exists:
        bot.reply_to(message, "Esa rima ya existe para ese disparador")
    else:
        punid = str(uuid.uuid4())
        cursor.execute("INSERT INTO puns(uuid,chatid,trigger,pun) VALUES(?,?,?,?)", (punid, chatid, trigger, pun))
        cursor.execute(
            "INSERT INTO validations(punid,chatid,userid,karma) VALUES(?,?,?,1)",
            (punid, chatid, str(message.from_user.id)),
        )
        db.commit()
        if member_count(chatid) >= REQUIRED_VALIDATIONS:
            extra = "Necesita %s aprobaciones (/punapprove %s) para activarse." % (REQUIRED_VALIDATIONS, punid)
        else:
            extra = "Ya está activa (karma positivo)."
        bot.reply_to(message, "Rima %s añadida. %s" % (punid, extra))
        print('Rima "%s" con disparador "%s" añadida en el chat %s' % (pun, trigger, chatid))
    db.close()


def cmd_delete(message):
    punid = get_args(message)
    if not punid:
        bot.reply_to(message, "Falta el uuid. Uso: /pundel uuid")
        return
    chatid = message.chat.id
    db = connect()
    cursor = db.cursor()
    exists = cursor.execute(
        "SELECT count(uuid) FROM puns WHERE chatid = ? AND uuid = ?", (chatid, punid)
    ).fetchone()[0]
    if exists != 1:
        bot.reply_to(message, "No encuentro la rima " + punid + " (las rimas por defecto no se pueden borrar)")
    else:
        cursor.execute("DELETE FROM puns WHERE chatid = ? AND uuid = ?", (chatid, punid))
        cursor.execute("DELETE FROM validations WHERE chatid = ? AND punid = ?", (chatid, punid))
        db.commit()
        bot.reply_to(message, "Rima borrada")
        print('Rima "%s" borrada del chat %s' % (punid, chatid))
    db.close()


def cmd_silence(message):
    arg = get_args(message)
    if not arg.isdigit() or int(arg) == 0:
        bot.reply_to(message, "Uso: /punsilence minutos (1-%s)" % MAX_SILENCE_MINUTES)
        return
    minutes = int(arg)
    now = int(time.time())
    opts = load_chat_options(message.chat.id)
    start = int(opts["silence"]) if opts["silence"] is not None and int(opts["silence"]) > now else now
    until = start + 60 * minutes
    if until - now > 60 * MAX_SILENCE_MINUTES:
        bot.reply_to(message, "Callarme más de una hora no tiene gracia 😢")
        return
    opts["silence"] = until
    set_chat_options(opts)
    bot.reply_to(message, "Me callo hasta las " + time.strftime("%H:%M:%S del %d/%m/%Y", time.localtime(until)))


def cmd_set(message):
    arg = get_args(message)
    if not arg.isdigit() or not 0 <= int(arg) <= 100:
        bot.reply_to(message, "Uso: /punset probabilidad (1-100)")
        return
    if int(arg) == 0:
        bot.reply_to(message, "La probabilidad no puede ser 0; para callarme un rato usa /punsilence")
        return
    opts = load_chat_options(message.chat.id)
    opts["efectivity"] = int(arg)
    set_chat_options(opts)
    bot.reply_to(message, "Responderé el %s%% de las veces" % arg)


def cmd_list(message):
    chatid = message.chat.id
    db = connect()
    cursor = db.cursor()
    rows = cursor.execute(
        "SELECT uuid, chatid, trigger, pun FROM puns WHERE chatid = ? OR chatid = 0 ORDER BY chatid", (chatid,)
    ).fetchall()
    members = None
    lines = []
    for punid, pun_chat, trigger, pun in rows:
        if pun_chat == 0:
            lines.append("| por defecto | %s | %s" % (trigger, pun))
            continue
        if members is None:
            members = member_count(chatid)
        karma = karma_of(cursor, punid, chatid)
        state = "activa" if is_enabled(karma, members) else "inactiva"
        goal = "/%s" % REQUIRED_VALIDATIONS if members >= REQUIRED_VALIDATIONS else ""
        lines.append("| %s | %s (%s%s) | %s | %s" % (punid, state, karma, goal, trigger, pun))
    db.close()
    header = "| uuid | estado (karma) | disparador | rima\n"
    chunk = ""
    for line in lines:
        if len(header + chunk + line) + 1 > 4000:
            bot.reply_to(message, header + chunk)
            chunk = ""
        chunk += line + "\n"
    bot.reply_to(message, header + (chunk or "(sin rimas)"))


def cmd_start(message):
    bot.reply_to(message, "¡Vamos a hacer rimas! Usa /punshelp para ver la ayuda")


def daily_enabled(chatid):
    if not DAILY_TIME:
        return False
    db = connect()
    row = db.execute("SELECT daily FROM chats WHERE chatid = ?", (chatid,)).fetchone()
    db.close()
    return bool(row and row[0])


def cmd_daily(message):
    if message.chat.type not in ("group", "supergroup"):
        bot.reply_to(message, "El mensaje diario solo funciona en grupos")
        return
    if not DAILY_TIME:
        bot.reply_to(message, "El mensaje diario está desactivado en este bot")
        return
    arg = get_args(message).lower()
    chatid = message.chat.id
    if arg in ("on", "off"):
        db = connect()
        db.execute("UPDATE chats SET daily = ? WHERE chatid = ?", (1 if arg == "on" else 0, chatid))
        db.commit()
        db.close()
    elif arg == "test":
        if not send_daily([chatid]):
            bot.reply_to(message, "No hay mensajes en defaultpuns/dailymessages")
        return
    elif arg:
        bot.reply_to(message, "Uso: /pundaily on | off | test")
        return
    bot.reply_to(message, "Mensaje sorpresa de las %s: %s" % (DAILY_TIME, daily_state(chatid)))


def daily_state(chatid):
    if not daily_enabled(chatid):
        return "desactivado"
    return "activado (sale al azar, un %s%% de los días)" % DAILY_PROBABILITY


def on_text(message):
    chatid = message.chat.id
    if is_chat_silenced(chatid) or not is_efective(chatid):
        return
    rima = find_pun(message)
    if rima is not None:
        bot.reply_to(message, rima)


def on_added(message):
    """Si el que entra es el propio bot (o se crea el grupo con él), reactiva el mensaje diario."""
    me = bot.get_me().id
    if message.content_type != "new_chat_members" or any(u.id == me for u in message.new_chat_members):
        db = connect()
        db.execute("UPDATE chats SET daily = 1 WHERE chatid = ?", (message.chat.id,))
        db.commit()
        db.close()


def remembering(handler):
    """Envuelve un handler para apuntar el grupo antes de procesar el mensaje."""
    def wrapper(message):
        try:
            remember_chat(message)
        except Exception as exc:
            print("No se pudo apuntar el chat %s: %s" % (message.chat.id, exc))
        handler(message)
    return wrapper


def register_handlers():
    def on(handler, **kwargs):
        bot.register_message_handler(remembering(handler), **kwargs)

    on(cmd_help, commands=["punshelp", "help"])
    on(cmd_approve, commands=["punapprove"])
    on(cmd_ban, commands=["punban"])
    on(cmd_add, commands=["punadd"])
    on(cmd_delete, commands=["pundel"])
    on(cmd_silence, commands=["punsilence"])
    on(cmd_set, commands=["punset"])
    on(cmd_list, commands=["list", "punlist", "punslist"])
    on(cmd_daily, commands=["pundaily"])
    on(cmd_start, commands=["start"])
    # Mensajes de texto normales (no comandos)
    on(on_text, func=lambda m: m.text and not m.text.startswith("/"))
    # Al añadir el bot a un grupo, apuntarlo ya (sin esperar a que alguien escriba)
    on(on_added, content_types=["new_chat_members", "group_chat_created", "supergroup_chat_created"])


def main():
    global bot, punsdb
    if "TOKEN" not in os.environ:
        raise SystemExit("Falta la variable TOKEN")
    if "DBLOCATION" not in os.environ:
        raise SystemExit("Falta la variable DBLOCATION")
    punsdb = os.path.expanduser(os.environ["DBLOCATION"])
    os.makedirs(os.path.dirname(os.path.abspath(punsdb)), exist_ok=True)
    db_setup()
    bot = telebot.TeleBot(os.environ["TOKEN"])
    register_handlers()
    if DAILY_TIME:
        threading.Thread(target=daily_loop, daemon=True).start()
        print("Mensaje diario programado a las %s (%s)" % (DAILY_TIME, TZ or "hora del servidor"))
    print("%s %s listo para rimar" % (BOT_NAME, VERSION))
    bot.infinity_polling(skip_pending=True)


if __name__ == "__main__":
    main()
