#!/usr/bin/env bash
# Installs the wattprint nginx sites with Let's Encrypt certificates. Run with sudo once DNS points at this host:
#   sudo ./apply.sh [domain ...]     (default: every site in this folder)
set -euo pipefail
cd "$(dirname "$0")"
domains=("$@"); [ ${#domains[@]} -gt 0 ] || domains=(wattprint.ptitai.org auth.wattprint.ptitai.org api.wattprint.ptitai.org)
avail=/etc/nginx/sites-available enabled=/etc/nginx/sites-enabled

for d in "${domains[@]}"; do
  if [ ! -f "/etc/letsencrypt/live/$d/fullchain.pem" ]; then
    # HTTP-only block first so the ACME challenge can be answered.
    sed '/^# --- 443/,$d' "$d" > "$avail/$d"
    ln -sfn "$avail/$d" "$enabled/$d"
    nginx -t && systemctl reload nginx
    certbot certonly --webroot -w /var/www/letsencrypt -d "$d" --non-interactive --agree-tos --keep-until-expiring \
      --deploy-hook 'systemctl reload nginx'  # webroot certs: the renewal timer must reload nginx to serve the new cert
  fi
  cp "$d" "$avail/$d"
  ln -sfn "$avail/$d" "$enabled/$d"
done
nginx -t && systemctl reload nginx
echo "ok: ${domains[*]}"
