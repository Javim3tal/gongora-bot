#!/usr/bin/env bash
# Despliega el bot en un servidor Ubuntu (p. ej. Oracle Cloud Free Tier) con Docker.
#
# Uso:  ./deploy.sh ubuntu@IP_DEL_SERVIDOR [ruta/a/clave_ssh]
#
# - La primera vez instala Docker en el servidor.
# - Copia el código, tu .env y (solo si en el servidor aún no hay) tu base de datos.
# - Construye y arranca el contenedor; se reinicia solo si el servidor se reinicia.
set -euo pipefail
cd "$(dirname "$0")"

HOST="${1:?Uso: ./deploy.sh ubuntu@IP [clave_ssh]}"
KEY="${2:-}"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
[ -n "$KEY" ] && SSH_OPTS+=(-i "$KEY")
REMOTE_DIR="gongora-bot"

[ -f .env ] || { echo "Falta .env (cópialo de .env.example y pon tu TOKEN)"; exit 1; }
ssh_run() { ssh "${SSH_OPTS[@]}" "$HOST" "$@"; }

echo "==> Comprobando Docker en el servidor"
ssh_run 'command -v docker >/dev/null || { curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER; }'

echo "==> Copiando código y .env"
ssh_run "mkdir -p $REMOTE_DIR/data"
rsync -az --delete -e "ssh ${SSH_OPTS[*]}" \
  --exclude .git --exclude .venv --exclude data --exclude __pycache__ --exclude .DS_Store \
  ./ "$HOST:$REMOTE_DIR/"

if [ -f data/punsdb.db ] && ! ssh_run "test -f $REMOTE_DIR/data/punsdb.db"; then
  echo "==> Primera vez: subiendo tu base de datos local (rimas añadidas y votos)"
  rsync -az -e "ssh ${SSH_OPTS[*]}" data/punsdb.db "$HOST:$REMOTE_DIR/data/"
fi

echo "==> Construyendo y arrancando"
ssh_run "cd $REMOTE_DIR && sudo docker compose up -d --build && sleep 5 && sudo docker compose logs --tail 3"
echo "==> Listo. Logs en vivo:  ssh ${SSH_OPTS[*]} $HOST 'cd $REMOTE_DIR && sudo docker compose logs -f'"
