<p align="center">
  <img src="assets/logo-sombre.png" alt="Logo Onde2Vid" width="160">
</p>

# Onde2Vid

**Transformez votre musique (MP3, WAV, FLAC, M4A, OGG…) en vidéos MP4 animées, gratuitement et hors ligne.**

Onde2Vid crée des vidéos prêtes à publier sur YouTube, Instagram, TikTok ou ailleurs : ajoutez vos morceaux, choisissez un visualiseur et une jaquette, puis exportez un MP4 avec le son d’origine.

Tout le traitement est réalisé sur votre ordinateur. Aucun compte, abonnement ou téléversement de musique n’est nécessaire.

> Onde2Vid est actuellement en cours de développement. Les retours et signalements de bugs sont les bienvenus.

## Aperçu

Avec Onde2Vid, vous pouvez :

- convertir un ou plusieurs morceaux en MP4 : MP3, WAV, FLAC, M4A/AAC, OGG, Opus, AIFF, WMA… ;
- choisir parmi plusieurs visualiseurs : cercle, égaliseur, onde, spectrogramme, tunnel, aurore, etc. ;
- utiliser la pochette intégrée au fichier audio, une jaquette personnalisée ou une image de fond ;
- ajouter un titre, un sous-titre, une barre de progression et des effets de pulsation ;
- exporter au format paysage (16:9), vertical (9:16) ou carré (1:1) ;
- générer une vidéo en 720p, 1080p, 1440p ou 4K ;
- prévisualiser un extrait avant de lancer la conversion complète ;
- réunir plusieurs morceaux dans **une seule vidéo**, dans l’ordre de votre choix : chaque titre s’affiche au bon moment et les chapitres YouTube sont prêts à copier ;
- donner à chaque morceau ses propres réglages (visualiseur, jaquette, titre…), ou garder les mêmes pour toute la playlist ;
- faire alterner plusieurs visualiseurs pendant un long morceau (toutes les 1 à 30 minutes) ;
- convertir plus vite : les longs morceaux sont calculés en plusieurs parties en même temps, et la compression peut passer par la puce graphique sur Mac (réglage « Rapide ») ;
- convertir tout le dossier en mode batch, sans interface.

## Version autonome (sans Python)

Des versions prêtes à l’emploi, avec FFmpeg inclus, sont publiées dans les [Releases](https://github.com/ulrikadam/Onde2Vid/releases) : rien d’autre à installer.

| Système | Fichier | Lancement |
|---|---|---|
| Windows | `Onde2Vid-…-Windows.zip` | décompressez, puis double-cliquez sur `Onde2Vid.exe` |
| macOS (Apple Silicon : M1 et suivants) | `Onde2Vid-…-macOS-AppleSilicon.zip` | décompressez, puis double-cliquez sur `Onde2Vid.app` (vous pouvez la glisser dans Applications) |
| macOS (Intel) | `Onde2Vid-…-macOS-Intel.zip` | idem |
| Linux | `Onde2Vid-…-Linux.tar.gz` | décompressez, puis lancez `Onde2Vid` |

À la première ouverture :

- **macOS** : l’app est signée et vérifiée par Apple (depuis la v1.0.1). Elle s’ouvre normalement ; le Mac peut simplement demander de confirmer l’ouverture d’une app téléchargée sur Internet ;
- **Windows** : la version Windows n’est pas signée. Si SmartScreen affiche « Windows a protégé votre ordinateur », cliquez sur « Informations complémentaires », puis « Exécuter quand même ».

La version autonome range vos fichiers dans le dossier `Documents/Onde2Vid` (sous-dossiers `input/` et `output/`).

Pour publier une nouvelle version, créez une étiquette `v…` (par exemple `git tag v1.0.0` puis `git push --tags`) : GitHub fabrique alors les quatre versions et les joint à une Release.

Les versions Mac sont signées et notarisées par Apple (plus aucun blocage à l’ouverture) quand ces secrets sont configurés dans le dépôt (*Settings → Secrets and variables → Actions*) : `MACOS_CERTIFICATE` (certificat « Developer ID Application » exporté en .p12, encodé en base64), `MACOS_CERTIFICATE_PASSWORD`, `APPLE_ID`, `APPLE_APP_PASSWORD` (mot de passe pour app) et `APPLE_TEAM_ID`.

## Prérequis

Pour utiliser directement le script Python (au lieu de la version autonome) :

- Python 3.9 ou une version plus récente
- [FFmpeg](https://ffmpeg.org/), avec l’encodeur vidéo `libx264` (sur Mac, l’encodeur `h264_videotoolbox` de la puce graphique est utilisé s’il est disponible)

Aucune bibliothèque Python supplémentaire n’est requise.

### Installer FFmpeg

Installez FFmpeg avec le gestionnaire de paquets de votre système, ou placez le binaire `ffmpeg` (`ffmpeg.exe` sous Windows) dans le même dossier que `Onde2Vid.py`.

Sur macOS, par exemple :

```bash
brew install ffmpeg
```

Sur Windows, vous pouvez l’installer avec Winget :

```powershell
winget install ffmpeg
```

Utilisez uniquement un binaire FFmpeg provenant d’une source fiable.

## Démarrage rapide

1. Téléchargez ou clonez ce dépôt.
2. Installez FFmpeg.
3. Lancez le programme :

```bash
python3 Onde2Vid.py
```

Une interface s’ouvre automatiquement dans votre navigateur. Elle est servie uniquement sur votre ordinateur à l’adresse `127.0.0.1`.

### Lancer Onde2Vid sans terminal

Au premier lancement, Onde2Vid crée lui-même son raccourci, avec son icône :

| Système | La première fois | Les fois suivantes |
|---|---|---|
| macOS | `python3 Onde2Vid.py` dans le Terminal | double-clic sur **Onde2Vid.app**, créée dans le dossier (vous pouvez la glisser dans le Dock) |
| Windows | double-clic sur **Onde2Vid.pyw** (aucune fenêtre noire ne s’ouvre) | **Onde2Vid** dans le menu Démarrer, ou `Onde2Vid.pyw` |
| Linux | `python3 Onde2Vid.py` dans un terminal | **Onde2Vid** dans le menu des applications |

Lancé de cette façon, Onde2Vid s’arrête tout seul une vingtaine de secondes après la fermeture de son onglet (jamais pendant une conversion). S’il est déjà ouvert, un nouveau double-clic ramène simplement son onglet. Les messages sont enregistrés dans `onde2vid.log`.

Déposez vos morceaux dans l’interface, choisissez vos réglages, puis cliquez sur **Convertir**.

### Réglages de chaque morceau

La case **« Mêmes réglages pour toute la playlist »**, au-dessus de la liste, est cochée par défaut. Décochez-la pour régler chaque morceau séparément : cliquez sur un morceau, puis changez son visualiseur, sa jaquette ou son titre. Le bouton « Reprendre les réglages communs » annule les réglages propres au morceau sélectionné.

Pour les longs morceaux, cochez **« Changer de visualiseur pendant le morceau »**, choisissez plusieurs visualiseurs et la durée de chacun : la vidéo passe de l’un à l’autre avec un court fondu.

### Une seule vidéo avec plusieurs morceaux

1. Cochez les morceaux à réunir.
2. En bas, cochez **« Une seule vidéo avec les morceaux cochés »** et donnez un nom à la vidéo.
3. Réglez l’ordre avec les flèches ▲▼, puis cliquez sur **Créer 1 vidéo**.

Le son s’enchaîne sans coupure. Chaque passage garde son titre, sa jaquette et son visualiseur ; le format, la résolution et la qualité sont les mêmes pour toute la vidéo. Les chapitres sont intégrés au MP4, et un fichier texte du même nom est créé à côté (par exemple `0:00 Titre 1`, `5:02 Titre 2`…) : collez-le dans la description YouTube pour obtenir les chapitres (YouTube en demande au moins trois de 10 secondes ou plus).

## Organisation des fichiers

Ces dossiers sont créés automatiquement à côté du script :

```text
Onde2Vid/
├── Onde2Vid.py
├── input/                 # vos fichiers audio et éventuelles images de fond
│   └── jaquettes/         # jaquettes ajoutées depuis l’interface
├── output/                # vidéos MP4 générées (et chapitres .txt des compilations)
├── reglages.json          # derniers réglages utilisés
└── reglages_morceaux.json # réglages propres à certains morceaux
```

Pour chaque morceau, la jaquette est choisie dans cet ordre :

1. une jaquette ajoutée depuis l’interface ;
2. une image du même nom que le morceau dans `input/` ;
3. la pochette intégrée au fichier audio ;
4. la jaquette par défaut choisie dans les réglages.

## Mode batch

Placez vos fichiers audio dans le dossier `input/`, puis lancez :

```bash
python3 Onde2Vid.py --batch
```

Les vidéos déjà présentes dans `output/` sont ignorées. Pour tout reconvertir :

```bash
python3 Onde2Vid.py --batch --force
```

## Confidentialité et fichiers

- Les fichiers audio, les images et les vidéos générées restent sur votre machine.
- Onde2Vid n’envoie pas vos fichiers vers un service en ligne.
- Les fichiers temporaires de rendu sont supprimés quand le programme se ferme.
- L’option permettant d’intégrer une jaquette dans un MP3 (réservée aux MP3) modifie ce MP3 : conservez une copie de l’original avant de l’utiliser.

## Contribuer

Les idées, rapports de bugs et contributions sont les bienvenus. Avant d’ouvrir une demande de modification, décrivez le problème ou l’amélioration proposée dans une issue.

## Licence

Onde2Vid est distribué sous la licence [GNU GPL v3.0](LICENSE).

Vous pouvez l’utiliser, l’étudier, le modifier et le redistribuer. Toute version modifiée distribuée doit rester sous la même licence et rendre son code source disponible.
