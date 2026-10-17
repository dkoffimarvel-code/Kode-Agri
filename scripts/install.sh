#!/usr/bin/env bash
# Installe Odoo 19 + les addons Kode Agri + la démonstration dans une base neuve, puis affiche le rapport de démonstration.
# Usage : ./scripts/install.sh [nom_base]      (défaut : kode_demo)
set -euo pipefail
cd "$(dirname "$0")/.."
DB="${1:-kode_demo}"
ODOO="docker compose run --rm -T odoo odoo -c /etc/odoo/odoo.conf -d $DB --no-http"

echo "==> 1/6 Base de données PostgreSQL"
docker compose up -d db
docker compose run --rm -T odoo odoo -c /etc/odoo/odoo.conf --stop-after-init -d "$DB" --no-http -i base --without-demo=all 2>&1 | tail -n 3

echo "==> 2/6 Société en Côte d'Ivoire, devise XOF (avant toute écriture comptable)"
$ODOO shell <<'PY'
ci = env.ref('base.ci')
xof = env['res.currency'].with_context(active_test=False).search([('name', '=', 'XOF')], limit=1)
xof.active = True
env.company.write({'name': 'KODE Caoutchouc SA', 'country_id': ci.id, 'currency_id': xof.id})
env.ref('base.user_admin').password = 'admin'
env.cr.commit()
print('Société :', env.company.name, env.company.currency_id.name)
PY

echo "==> 3/6 Plan comptable SYSCOHADA (Côte d'Ivoire)"
$ODOO -i l10n_ci --stop-after-init --without-demo=all 2>&1 | tail -n 3 || true
# Odoo sort avec le code 0 même si le module est introuvable : on vérifie l'état réel
INSTALLE=$($ODOO shell <<'PY' 2>/dev/null | tail -n 1
m = env['ir.module.module'].search([('name', 'in', ('l10n_ci', 'l10n_syscohada')), ('state', '=', 'installed')])
print('oui' if m else 'non')
PY
)
if [ "$INSTALLE" != "oui" ]; then
  echo "   l10n_ci indisponible : repli sur l10n_syscohada"
  $ODOO -i l10n_syscohada --stop-after-init --without-demo=all 2>&1 | tail -n 3 || true
fi

echo "==> 4/6 Addons Kode Agri + démonstration (peut durer plusieurs minutes)"
$ODOO -i kode_agri_demo --stop-after-init --without-demo=all 2>&1 | tee "/tmp/kode_install_$DB.log" | grep -E "ERROR|CRITICAL|WARNING.*[Dd]émo|Traceback" || true

echo "==> 5/6 Rapport de démonstration"
$ODOO shell <<'PY'
print(env['ir.config_parameter'].sudo().get_param('kode_agri.demo_rapport') or "(aucun rapport : l'installation n'a pas abouti)")
PY

echo "==> 6/6 Démarrage"
docker compose up -d odoo
echo
echo "Odoo : http://localhost:8069   base : $DB   identifiant : admin   mot de passe : admin"
echo "Journal d'installation complet : /tmp/kode_install_$DB.log"
