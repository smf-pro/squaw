#!/usr/bin/env python3
"""
Vérifie les clés ElevenLabs listées dans cles.txt (une par ligne, même compte)
et indique celles qui fonctionnent encore et combien de crédits il reste.

Usage :
    python check_cles.py                  # affiche l'état de chaque clé
    python check_cles.py --best           # affiche en plus la première clé utilisable
    python check_cles.py --integrer       # crée squawk-perso.html avec les clés utilisables intégrées
    python check_cles.py --integrer --forcer   # intègre toutes les clés sans les vérifier

ATTENTION : squawk-perso.html contient vos clés en clair. Gardez-le sur votre
ordinateur, ne l'envoyez JAMAIS sur GitHub (index.html, lui, reste sans clé).

Aucune dépendance : Python 3.8+ suffit. Les clés ne quittent jamais votre
ordinateur, sauf pour interroger api.elevenlabs.io.
La clé doit avoir la permission « Utilisateur » (User) en lecture.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

API = "https://api.elevenlabs.io/v1/user/subscription"


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


MARQUEUR = "const PRESET = { eleven: [] };"


def integrer(cles: list[str], entree: Path, sortie: Path) -> None:
    if sortie.name.lower() == "index.html" or sortie.resolve() == entree.resolve():
        sys.exit("Refusé : la version avec clés ne doit pas écraser index.html (la version publique).")
    if not entree.exists():
        sys.exit(f"Fichier introuvable : {entree}")
    src = entree.read_text(encoding="utf-8")
    if MARQUEUR not in src:
        sys.exit(f"{entree} ne contient pas l'emplacement prévu pour les clés. Utilisez la dernière version de la page.")
    liste = json.dumps(cles).replace("</", "<\\/")
    sortie.write_text(src.replace(MARQUEUR, f"const PRESET = {{ eleven: {liste} }};"), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="Vérifie les clés ElevenLabs de cles.txt")
    p.add_argument("--fichier", default="cles.txt", help="fichier des clés (défaut : cles.txt)")
    p.add_argument("--best", action="store_true", help="affiche la première clé utilisable")
    p.add_argument("--integrer", action="store_true", help="crée la page personnelle avec les clés intégrées")
    p.add_argument("--forcer", action="store_true", help="avec --integrer : intègre toutes les clés sans les vérifier")
    p.add_argument("--entree", default="index.html", help="page de départ (défaut : index.html)")
    p.add_argument("--sortie", default="squawk-perso.html", help="page créée (défaut : squawk-perso.html)")
    args = p.parse_args()

    cles = lire_cles(Path(args.fichier))
    if not cles:
        sys.exit("Aucune clé trouvée dans le fichier.")

    resultats = []
    if args.integrer and args.forcer:
        integrer(cles, Path(args.entree), Path(args.sortie))
        print(f"{len(cles)} clé(s) intégrée(s) sans vérification dans {args.sortie}.")
        print("Ne mettez JAMAIS ce fichier sur GitHub : il contient vos clés en clair.")
        return 0
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
    if args.integrer:
        if not utilisables:
            print("\nAucune clé utilisable à intégrer. Si vos clés fonctionnent mais n'ont pas la "
                  "permission « Utilisateur », relancez avec --integrer --forcer.")
            return 1
        integrer(utilisables, Path(args.entree), Path(args.sortie))
        print(f"\n{len(utilisables)} clé(s) intégrée(s) dans {args.sortie}.")
        print("Ouvrez ce fichier directement dans votre navigateur. Ne l'envoyez JAMAIS sur GitHub :")
        print("il contient vos clés en clair. Le site public reste index.html (sans clé).")
    return 0 if utilisables else 1


if __name__ == "__main__":
    sys.exit(main())
