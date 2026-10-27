# Windows : double-clique sur ce fichier pour lancer Onde2Vid sans fenêtre de terminal.
# (Sur Mac, utilise Onde2Vid.app ; sous Linux, l'entrée « Onde2Vid » du menu des applications.)
import os
import runpy
import sys

script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Onde2Vid.py")
sys.argv = [script, "--app"]
runpy.run_path(script, run_name="__main__")
