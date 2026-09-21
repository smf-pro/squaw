#!/usr/bin/env python3
"""
Outil pour vos clés ElevenLabs (toutes du MÊME compte), listées dans cles.txt.

    python check_cles.py             vérifie chaque clé et affiche les crédits restants
    python check_cles.py --best      affiche en plus la première clé utilisable
    python check_cles.py --chiffrer  met vos clés dans index.html, CHIFFRÉES par un mot de passe
    python check_cles.py --integrer  crée squawk-perso.html avec les clés EN CLAIR (usage local)
    python check_cles.py --public    écrit la clé EN CLAIR dans index.html (site public, à vos risques)

--chiffrer (recommandé pour le site en ligne)
    Les clés sont chiffrées (AES-256-GCM, clé dérivée de votre mot de passe par PBKDF2).
    index.html peut alors être publié sur GitHub : sans le mot de passe, la clé reste illisible.
    Sur chaque appareil, on saisit le mot de passe une seule fois dans la page.
    Nécessite :  pip install cryptography
    Choisissez un mot de passe LONG (14 caractères ou plus, ou 5 mots au hasard) :
    le contenu chiffré étant public, un mot de passe faible pourrait être deviné.

--integrer
    Écrit les clés en clair dans squawk-perso.html. Ne l'envoyez JAMAIS sur GitHub.

--public
    Écrit les clés en clair dans index.html : toute personne qui ouvre le site utilisera votre clé
    (et peut la lire). À réserver à une clé DÉDIÉE, restreinte à « Synthèse vocale » + « Voix : lecture »,
    avec une limite de crédits fixée dans ElevenLabs.

--forcer
    Avec --chiffrer, --integrer ou --public : n'interroge pas ElevenLabs et intègre toutes les clés.
"""
import argparse
import base64
import getpass
import hashlib
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

API = "https://api.elevenlabs.io/v1/user/subscription"
PRESET_RE = re.compile(r"^const PRESET = \{ eleven: \[.*\] \};$", re.M)
MARQUEUR_COFFRE = re.compile(r"^const VAULT = .*;$", re.M)
ITERATIONS = 600_000
MDP_MIN = 12


def lire_cles(chemin: Path) -> list[str]:
    if not chemin.exists():
        sys.exit(f"Fichier introuvable : {chemin}\n"
                 "Copiez cles.exemple.txt en cles.txt et mettez-y vos clés.")
    cles = []
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#"):
            cles.append(ligne)
    return cles


def masquer(cle: str) -> str:
    if os.environ.get("GITHUB_ACTIONS"):      # journaux publics : ne rien montrer de la clé
        return "***"
    return f"{cle[:5]}…{cle[-4:]}" if len(cle) > 12 else "***"


def interroger(cle: str) -> dict:
    req = urllib.request.Request(
        API,
        headers={"xi-api-key": cle, "User-Agent": "squawk-check/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return {"ok": True, **json.load(r)}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            j = json.loads(e.read().decode("utf-8", "replace"))
            d = j.get("detail", "")
            detail = d.get("message", "") if isinstance(d, dict) else str(d)
        except Exception:
            pass
        if e.code == 401:
            detail = detail or "clé invalide, révoquée, ou permission « Utilisateur » manquante"
        return {"ok": False, "erreur": f"HTTP {e.code}", "detail": detail[:120]}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"ok": False, "erreur": "réseau", "detail": str(e)[:120]}


def date_fr(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%d/%m/%Y")
    except (TypeError, ValueError, OSError):
        return "?"


def integrer(cles: list[str], entree: Path, sortie: Path, public: bool = False) -> None:
    if not public and (sortie.name.lower() == "index.html" or sortie.resolve() == entree.resolve()):
        sys.exit("Refusé : la version avec clés EN CLAIR ne doit pas écraser index.html (la version publique).\n"
                 "Si c'est vraiment ce que vous voulez, utilisez --public.")
    if not entree.exists():
        sys.exit(f"Fichier introuvable : {entree}")
    src = entree.read_text(encoding="utf-8")
    if not PRESET_RE.search(src):
        sys.exit(f"{entree} ne contient pas l'emplacement prévu pour les clés. Utilisez la dernière version de la page.")
    liste = json.dumps(cles).replace("</", "<\\/")
    nouveau = PRESET_RE.sub(lambda m: f"const PRESET = {{ eleven: {liste} }};", src, count=1)
    sortie.write_text(nouveau, encoding="utf-8")


def demander_mot_de_passe() -> str:
    print(f"\nChoisissez le mot de passe du coffre ({MDP_MIN} caractères minimum, plus c'est long mieux c'est).")
    print("Vous le saisirez une fois par appareil dans la page. Si vous l'oubliez, relancez simplement ce script.")
    while True:
        m1 = getpass.getpass("Mot de passe : ")
        if len(m1) < MDP_MIN:
            print(f"Trop court ({len(m1)} caractères). Minimum : {MDP_MIN}.")
            continue
        if getpass.getpass("Confirmez     : ") != m1:
            print("Les deux saisies sont différentes, recommencez.")
            continue
        return m1


def chiffrer(cles: list[str], mdp: str, entree: Path, sortie: Path) -> None:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        sys.exit("Module manquant. Tapez :  pip install cryptography   puis relancez la commande.")
    if not entree.exists():
        sys.exit(f"Fichier introuvable : {entree}")
    src = entree.read_text(encoding="utf-8")
    if not MARQUEUR_COFFRE.search(src):
        sys.exit(f"{entree} ne contient pas l'emplacement du coffre. Utilisez la dernière version de la page.")
    sel, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    cle_aes = hashlib.pbkdf2_hmac("sha256", mdp.encode("utf-8"), sel, ITERATIONS, dklen=32)
    chiffre = AESGCM(cle_aes).encrypt(iv, json.dumps(cles).encode("utf-8"), None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    coffre = {"v": 1, "iter": ITERATIONS, "salt": b64(sel), "iv": b64(iv), "ct": b64(chiffre)}
    nouveau = MARQUEUR_COFFRE.sub(lambda m: "const VAULT = " + json.dumps(coffre) + ";", src, count=1)
    sortie.write_text(nouveau, encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="Outil pour les clés ElevenLabs de cles.txt")
    p.add_argument("--fichier", default="cles.txt", help="fichier des clés (défaut : cles.txt)")
    p.add_argument("--best", action="store_true", help="affiche la première clé utilisable")
    p.add_argument("--chiffrer", action="store_true", help="chiffre les clés dans index.html (publiable)")
    p.add_argument("--integrer", action="store_true", help="crée squawk-perso.html avec les clés en clair (local)")
    p.add_argument("--public", action="store_true", help="écrit la clé EN CLAIR dans index.html (site public)")
    p.add_argument("--forcer", action="store_true", help="intègre toutes les clés sans les vérifier")
    p.add_argument("--entree", default="index.html", help="page de départ (défaut : index.html)")
    p.add_argument("--sortie", default=None,
                   help="page créée (défaut : index.html pour --chiffrer, squawk-perso.html pour --integrer)")
    args = p.parse_args()

    if sum([args.chiffrer, args.integrer, args.public]) > 1:
        sys.exit("Choisissez une seule option parmi --chiffrer, --integrer, --public.")

    cles = lire_cles(Path(args.fichier))
    if not cles:
        sys.exit("Aucune clé trouvée dans le fichier.")
    entree = Path(args.entree)

    def ecrire(liste: list[str]) -> None:
        if args.chiffrer:
            sortie = Path(args.sortie) if args.sortie else entree
            chiffrer(liste, demander_mot_de_passe(), entree, sortie)
            print(f"\n{len(liste)} clé(s) chiffrée(s) dans {sortie}.")
            print("Ce fichier ne contient aucune clé lisible : vous pouvez le mettre sur GitHub.")
            print("Ne publiez jamais le mot de passe, ni cles.txt.")
        elif args.public:
            print("\nATTENTION : la clé va être écrite EN CLAIR dans " + str(entree) + ".")
            print("Une fois le fichier sur GitHub, tout le monde pourra la lire et l'utiliser,")
            print("et GitHub / ElevenLabs peuvent la détecter et la désactiver automatiquement.")
            if input("Tapez OUI pour confirmer : ").strip() != "OUI":
                sys.exit("Annulé, rien n'a été modifié.")
            integrer(liste, entree, Path(args.sortie) if args.sortie else entree, public=True)
            print(f"\n{len(liste)} clé(s) écrite(s) EN CLAIR dans {args.sortie or entree}.")
        else:
            sortie = Path(args.sortie or "squawk-perso.html")
            integrer(liste, entree, sortie)
            print(f"\n{len(liste)} clé(s) intégrée(s) EN CLAIR dans {sortie}.")
            print("Ne l'envoyez JAMAIS sur GitHub : il contient vos clés lisibles.")

    if (args.chiffrer or args.integrer or args.public) and args.forcer:
        ecrire(cles)
        return 0

    resultats = []
    for i, cle in enumerate(cles, 1):
        r = interroger(cle)
        resultats.append((cle, r))
        if not r["ok"]:
            print(f"{i}. {masquer(cle)}  ÉCHEC  {r['erreur']} {r['detail']}")
            continue
        utilise = r.get("character_count", 0)
        limite = r.get("character_limit", 0)
        reste = max(0, limite - utilise)
        print(f"{i}. {masquer(cle)}  OK  {utilise}/{limite} utilisés, "
              f"reste {reste}  (renouvellement le {date_fr(r.get('next_character_count_reset_unix'))})")

    valides = [(c, r) for c, r in resultats if r["ok"]]
    if len(valides) > 1:
        signatures = {(r.get("character_count"), r.get("character_limit"),
                       r.get("next_character_count_reset_unix")) for _, r in valides}
        if len(signatures) == 1:
            print("\nRemarque : ces clés affichent exactement le même compteur. "
                  "Elles partagent le quota du compte : changer de clé n'ajoute aucun crédit.")

    utilisables = [c for c, r in valides if max(0, r.get("character_limit", 0) - r.get("character_count", 0)) > 0]
    if args.best:
        if utilisables:
            print(f"\nClé à utiliser : {utilisables[0]}")
        else:
            print("\nAucune clé utilisable (invalide ou quota du mois épuisé).")
    if args.chiffrer or args.integrer or args.public:
        if not utilisables:
            print("\nAucune clé utilisable à intégrer. Si vos clés fonctionnent mais n'ont pas la "
                  "permission « Utilisateur », relancez avec --forcer.")
            return 1
        ecrire(utilisables)
    return 0 if utilisables else 1


if __name__ == "__main__":
    sys.exit(main())
