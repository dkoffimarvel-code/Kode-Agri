from . import models


def post_init_hook(env):
    """Charge la démonstration à l'installation. Aucune erreur n'interrompt l'installation : le rapport est journalisé."""
    env['ka.demo'].charger()
