"""Lanzador para hostings tipo Pterodactyl (Lunafy).

En cada arranque descarga la última versión de la rama `main` del repositorio
de GitHub, sobrescribe los archivos del bot (sin tocar .env ni data/) y
ejecuta punsbot.py. Si GitHub no responde, arranca con la versión que ya hay.

Variables opcionales en .env:
  UPDATE_REPO=Javim3tal/gongora-bot   repositorio de origen
  UPDATE_BRANCH=main                  rama
  AUTO_UPDATE=0                       desactiva la actualización
"""
import io
import os
import sys
import tarfile
import urllib.request
import functools

print = functools.partial(print, flush=True)  # que se vea antes de execv

BASE = os.path.dirname(os.path.abspath(__file__))
KEEP = {".env", "data", ".local", ".cache", ".git"}  # nunca se sobrescriben


def read_env():
    env = {}
    path = os.path.join(BASE, ".env")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def update(repo, branch):
    url = "https://codeload.github.com/%s/tar.gz/refs/heads/%s" % (repo, branch)
    print("Actualizando desde github.com/%s (%s)..." % (repo, branch))
    try:
        context = None
        try:
            import certifi  # viene con pyTelegramBotAPI (vía requests)
            import ssl
            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
        data = urllib.request.urlopen(url, timeout=30, context=context).read()
    except Exception as exc:
        print("No se pudo actualizar (%s). Arranco con la versión actual." % exc)
        return
    count = 0
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        commit = (tar.pax_headers or {}).get("comment", "?")
        for member in tar.getmembers():
            parts = member.name.split("/", 1)
            if len(parts) < 2 or not parts[1]:
                continue
            rel = parts[1]
            if rel.split("/")[0] in KEEP or not (member.isfile() or member.isdir()):
                continue
            member.name = rel
            tar.extract(member, BASE, filter="data")
            count += member.isfile()
    print("Actualizado a %s (%d archivos)" % (commit[:7], count))


def main():
    env = read_env()
    if env.get("AUTO_UPDATE", "1") != "0":
        update(env.get("UPDATE_REPO", "Javim3tal/gongora-bot"), env.get("UPDATE_BRANCH", "main"))
    bot = os.path.join(BASE, "punsbot.py")
    os.execv(sys.executable, [sys.executable, "-u", bot])


if __name__ == "__main__":
    main()
