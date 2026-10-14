# Despliegue en una VM gratuita (Oracle Cloud + Tailscale Funnel)

Objetivo: el sistema funcionando 24/7 en un servidor gratuito y la web de GitHub Pages leyendo la
API por HTTPS. Coste: 0 €.

```
GitHub Pages (web) ──HTTPS──► https://trlavanda.<tailnet>.ts.net ──Tailscale Funnel──► gateway
                                                                         (VM de Oracle, sin puertos abiertos)
```

> Las cuentas las creas tú (piden datos personales y, Oracle, una tarjeta para verificar).
> Nada de lo que pide esta guía se sube a GitHub: las claves van en `.env`, que está en `.gitignore`.

## Probado antes de desplegar (2026-10-14)

- **Imágenes ARM**: compiladas con `docker buildx --platform linux/arm64` y arrancadas con emulación
  (`aarch64`): Polars, pyarrow, confluent-kafka, yfinance y statsmodels cargan; los binarios Go funcionan.
- **Arranque en limpio** con este mismo `compose.prod.yaml` y volúmenes vacíos (sin Tailscale): el
  scheduler lanza la ingesta, el gateway responde 503 hasta tener datos, ingest descarga todo en ~3 min,
  factors calcula en 6 s y el gateway sirve el ranking (491 empresas, mismo top 10 que en local).
  Encontró un bug del primer arranque (tabla de precios vacía sin tipos + Polars 2), ya corregido.
- **Memoria en reposo**: ~2,2 GB en total (ingest 1,1 GB, Kafka 0,4, gateway 0,4, factors 0,3).
- **Sin probar**: el contenedor de Tailscale (necesita tu clave). Si Funnel no arranca, mira
  `docker compose logs tailscale` (lo habitual: HTTPS no activado o falta el permiso `funnel`).

## 1. Tailscale (≈5 min)

1. Crea una cuenta en <https://login.tailscale.com> (con GitHub o Google). El plan *Personal* es gratis.
2. Consola → **DNS**: comprueba que **MagicDNS** está activado y pulsa **Enable HTTPS** (certificados).
   Apunta el nombre de tu tailnet, del tipo `tailXXXXX.ts.net`.
3. Consola → **Access controls**: en el *policy file* tiene que existir el permiso de Funnel. Si no está, añádelo:
   ```json
   "nodeAttrs": [{ "target": ["autogroup:member"], "attr": ["funnel"] }]
   ```
4. Consola → **Settings → Keys → Generate auth key**: sin *Reusable*, sin *Ephemeral*, con *Pre-approved*.
   Copia la clave `tskey-auth-...` (solo se ve una vez). Solo se usa en el primer arranque.

## 2. Oracle Cloud (≈20 min)

1. Alta en <https://signup.cloud.oracle.com>. Elige una **región de origen** cercana (p. ej. Madrid o
   Frankfurt): no se puede cambiar después. La tarjeta es solo para verificar; los recursos *Always Free*
   no se cobran. Ahora el límite gratuito de ARM es **2 OCPU y 12 GB de RAM** (Oracle lo redujo en 2026).
2. En tu PC, crea una clave SSH si no tienes: `ssh-keygen -t ed25519` (queda en `~/.ssh/id_ed25519.pub`).
3. **Compute → Instances → Create instance**:
   - *Image*: **Canonical Ubuntu 24.04** (la variante aarch64 aparece al elegir la *shape* ARM).
   - *Shape*: **Ampere → VM.Standard.A1.Flex**, **2 OCPU, 12 GB**.
   - *Networking*: la VCN por defecto, con IPv4 pública (solo para entrar por SSH).
   - *SSH keys*: pega tu clave pública (`id_ed25519.pub`).
   - Si sale *Out of capacity*: prueba otro *availability domain* o vuelve a intentarlo más tarde.
4. **No abras más puertos** que el 22 (SSH), que ya viene abierto. Funnel no necesita ninguno.

## 3. Instalar TrLavanda en la VM (≈15 min + la primera ingesta)

```bash
ssh ubuntu@IP_DE_LA_VM
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/heeriik/TrLavanda.git && cd TrLavanda
nano .env
```

Contenido de `.env`:

```bash
SEC_USER_AGENT="TrLavanda research tu_email@ejemplo.com"
TS_AUTHKEY=tskey-auth-...
COMPOSE_FILE=compose.yaml:deploy/compose.prod.yaml   # así basta con `docker compose ...`
```

Y después:

```bash
bash deploy/setup-vm.sh
```

El script instala Docker (repositorio oficial), construye las imágenes en la propia VM (ARM, sin
registro de imágenes) y arranca todo. Al arrancar, el scheduler lanza la primera ingesta completa
(~10 min: descarga el S&P 500 desde 2010).

Después, en la consola de Tailscale → **Machines → trlavanda → Disable key expiry** (si no, el nodo
caduca a los 180 días).

## 4. Comprobar

```bash
docker compose ps                                        # todo "healthy"
docker compose logs -f --no-log-prefix ingest factors    # progreso de la primera ingesta
curl -s https://trlavanda.tailXXXXX.ts.net/healthz       # desde cualquier sitio
curl -s https://trlavanda.tailXXXXX.ts.net/api/meta      # cuando haya datos
```

## 5. Publicar la web

Con la URL funcionando, en tu PC: poner `PROD_API_BASE = "https://trlavanda.tailXXXXX.ts.net"` en
`web/js/config.js` y `uv run trl-web --publish`. El gateway ya permite (CORS) el origen
`https://heeriik.github.io`.

## Mantenimiento

| Qué | Cómo (en la VM, dentro de `~/TrLavanda`) |
|---|---|
| Actualizar a la última versión del código | `bash deploy/setup-vm.sh` |
| Lanzar una ingesta a mano | `docker compose exec ingest trl-bus send cmd.ingest '{"run_id": "manual-1", "datasets": ["prices"]}'` |
| Seguir una ejecución | `docker compose logs --no-log-prefix \| grep daily-2026-10-15` |
| Ver mensajes fallidos | `docker compose exec ingest trl-bus tail cmd.ingest.dlq` |
| Ver la API sin pasar por internet | desde el PC: `ssh -L 8000:127.0.0.1:8000 ubuntu@IP` y abrir http://localhost:8000/api/meta |
| Kafka UI (no se arranca en producción) | `docker compose --profile dev up -d kafka-ui` + `ssh -L 8080:127.0.0.1:8080 ...` |
