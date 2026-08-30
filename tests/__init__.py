# Regulaeres Paket, absichtlich: nemo_toolkit (Rest des verworfenen
# NeMo-Conformer-Versuchs, 28.08.2026) legt ein eigenes top-level "tests"
# in die globalen site-packages — als Namespace-Paket verlor unser Ordner
# die Aufloesung (ModuleNotFoundError in lauf_bianca und beim
# Autoloesch-Import in bianca/server.py). Mit __init__.py gewinnt das Repo.
