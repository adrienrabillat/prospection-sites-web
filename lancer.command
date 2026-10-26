#!/bin/zsh
# Double-clique sur ce fichier dans le Finder pour ouvrir l'interface de prospection.
cd "$(dirname "$0")"
echo "Interface de prospection : http://localhost:8501  (ferme cette fenêtre pour l'arrêter)"
.venv/bin/streamlit run app.py
