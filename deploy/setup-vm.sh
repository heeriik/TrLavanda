#!/usr/bin/env bash
# Prepara la VM (Ubuntu 24.04, ARM) y arranca TrLavanda. Se puede repetir sin problema.
#
#   bash setup-vm.sh          # la primera vez (instala Docker, clona, arranca)
#   bash setup-vm.sh          # después: actualiza el código y reconstruye lo que haya cambiado
#
# Antes: crear ~/TrLavanda/.env con SEC_USER_AGENT y TS_AUTHKEY (ver docs/DESPLIEGUE.md).
set -euo pipefail

REPO=https://github.com/heeriik/TrLavanda.git
DIR="$HOME/TrLavanda"

# 1) Docker, desde el repositorio oficial de Docker para Ubuntu (incluye el plugin compose).
if ! command -v docker >/dev/null; then
  echo ">> Instalando Docker..."
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl git
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" |
    sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo usermod -aG docker "$USER"
fi

# 2) Código.
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  git clone "$REPO" "$DIR"
fi
cd "$DIR"

# 3) Secretos: nunca en git.
if [ ! -f .env ]; then
  cat <<'EOF'
Falta ~/TrLavanda/.env. Créalo con (sustituyendo los valores):

  SEC_USER_AGENT="TrLavanda research tu_email@ejemplo.com"
  TS_AUTHKEY=tskey-auth-...

y vuelve a ejecutar este script.
EOF
  exit 1
fi
chmod 600 .env

# 4) Arrancar (sudo hasta que el usuario vuelva a entrar y tenga el grupo docker).
COMPOSE="docker compose -f compose.yaml -f deploy/compose.prod.yaml"
if ! docker info >/dev/null 2>&1; then COMPOSE="sudo $COMPOSE"; fi
$COMPOSE up -d --build
$COMPOSE ps
echo
echo ">> Listo. La primera ingesta completa tarda ~10 min (el scheduler la lanza al arrancar)."
echo ">> Estado:  $COMPOSE logs -f --no-log-prefix scheduler ingest factors gateway"
