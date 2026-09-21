#!/usr/bin/env python3
"""
Vérifie les clés ElevenLabs listées dans cles.txt (une par ligne, même compte)
et indique celles qui fonctionnent encore et combien de crédits il reste.

Usage :
    python check_cles.py            # affiche l'état de chaque clé
    python check_cles.py --best     # affiche en plus la première clé utilisable

Aucune dépendance : Python 3.8+ suffit. Les clés ne quittent jamais votre
ordinateur, sauf pour interroger api.elevenlabs.io.
La clé doit avoir la permission « Utilisateur » (User) en lecture.
"""
import argparse
import json
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


def main() -> int:
    p = argparse.ArgumentParser(description="Vérifie les clés ElevenLabs de cles.txt")
    p.add_argument("--fichier", default="cles.txt", help="fichier des clés (défaut : cles.txt)")
    p.add_argument("--best", action="store_true", help="affiche la première clé utilisable")
    args = p.parse_args()

    cles = lire_cles(Path(args.fichier))
    if not cles:
        sys.exit("Aucune clé trouvée dans le fichier.")

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
    return 0 if utilisables else 1


if __name__ == "__main__":
    sys.exit(main())
