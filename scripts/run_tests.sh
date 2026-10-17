#!/usr/bin/env bash
# Lance les tests automatisés Kode Agri sur une base de test neuve (ne touche pas à la base de démonstration).
# Usage : ./scripts/run_tests.sh
set -euo pipefail
cd "$(dirname "$0")/.."
DB="kode_test"
ODOO="docker compose run --rm -T odoo odoo -c /etc/odoo/odoo.conf -d $DB --no-http"
docker compose up -d db
docker compose run --rm -T odoo bash -c "dropdb -h db -U odoo --if-exists $DB" 2>/dev/null || true
$ODOO -i base --stop-after-init --without-demo=all >/dev/null 2>&1
$ODOO shell <<'PY'
xof = env['res.currency'].with_context(active_test=False).search([('name', '=', 'XOF')], limit=1)
xof.active = True
env.company.write({'country_id': env.ref('base.ci').id, 'currency_id': xof.id})
env.cr.commit()
PY
$ODOO -i l10n_ci --stop-after-init --without-demo=all >/dev/null 2>&1 || true
OK=$($ODOO shell <<'PY' 2>/dev/null | tail -n 1
print('oui' if env['ir.module.module'].search([('name', 'in', ('l10n_ci', 'l10n_syscohada')), ('state', '=', 'installed')]) else 'non')
PY
)
[ "$OK" = "oui" ] || $ODOO -i l10n_syscohada --stop-after-init --without-demo=all >/dev/null 2>&1 || true
# --test-tags /kode_agri : uniquement les tests Kode Agri
$ODOO -i kode_agri_demo --test-tags /kode_agri --stop-after-init --without-demo=all --log-level=test 2>&1 | tee /tmp/kode_tests.log | grep -E "FAIL|ERROR|Ran |tests? in|OK" || true
echo "Journal complet : /tmp/kode_tests.log"
