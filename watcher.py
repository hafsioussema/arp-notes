#!/usr/bin/env python3
"""Surveille les notes sur ARP Esprit et envoie une notification (ntfy) a chaque nouvelle note.

Variables d'environnement :
  ETUDIANT_ID         identifiant etudiant ARP
  NTFY_TOPIC          nom de topic ntfy secret (long et aleatoire)
  STATE_KEY           cle de chiffrement de l'etat (generee une fois)
  ARP_REFRESH_TOKEN   refresh token initial (utilise seulement si aucun etat n'existe)
  CURSUS_ID           optionnel, defaut 1
  STATE_FILE          optionnel, defaut state.bin
  NTFY_SERVER         optionnel, defaut https://ntfy.sh
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.fernet import Fernet, InvalidToken

_missing = [k for k in ("ETUDIANT_ID", "NTFY_TOPIC", "STATE_KEY") if not os.environ.get(k, "").strip()]
if _missing:
    print("Secrets manquants : " + ", ".join(_missing) + " -> rien a faire pour l'instant (voir README).")
    sys.exit(0)

API = os.environ.get("ARP_API", "https://arp.esprit.tn/gw/api")
ETUDIANT_ID = os.environ["ETUDIANT_ID"].strip()
NTFY_TOPIC = os.environ["NTFY_TOPIC"].strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
CURSUS_ID = os.environ.get("CURSUS_ID", "1").strip() or "1"
STATE_FILE = os.environ.get("STATE_FILE", "state.bin")
FERNET = Fernet(os.environ["STATE_KEY"].strip().encode())

FIELDS = {
    "noteCc": "CC",
    "noteTp": "TP",
    "noteExam": "Examen",
    "noteRattrapage": "Rattrapage",
}


class SessionExpired(Exception):
    pass


# ---------- etat chiffre ----------

def load_state():
    try:
        with open(STATE_FILE, "rb") as f:
            return json.loads(FERNET.decrypt(f.read()))
    except FileNotFoundError:
        return {}
    except InvalidToken:
        print("Etat illisible (cle STATE_KEY changee ?) -> on repart de zero")
        return {}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "wb") as f:
        f.write(FERNET.encrypt(json.dumps(state).encode()))
    os.replace(tmp, STATE_FILE)


# ---------- HTTP ----------

def http(method, url, token=None, data=None, headers=None, timeout=30):
    h = {"Accept": "application/json", "User-Agent": "arp-notes-watcher"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return json.loads(body) if body else None


def jwt_exp(token):
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part)).get("exp")
    except Exception:
        return None


def notify(title, message, priority="default", tags=""):
    headers = {"Title": title, "Priority": priority}
    if tags:
        headers["Tags"] = tags
    # Les en-tetes HTTP doivent etre en latin-1 : on encode le titre en RFC 2047 si besoin.
    try:
        title.encode("latin-1")
    except UnicodeEncodeError:
        headers["Title"] = "=?UTF-8?B?" + base64.b64encode(title.encode()).decode() + "?="
    http("POST", f"{NTFY_SERVER}/{urllib.parse.quote(NTFY_TOPIC)}",
         data=message.encode("utf-8"), headers=headers)


# ---------- session ----------

def get_access_token(state):
    access = state.get("access")
    exp = jwt_exp(access) if access else None
    if access and exp and exp - 60 > time.time():
        return access

    refresh = state.get("refresh") or os.environ.get("ARP_REFRESH_TOKEN", "").strip()
    if not refresh:
        raise SessionExpired("aucun refresh token")
    url = f"{API}/auth/refresh?" + urllib.parse.urlencode({"token": refresh})
    try:
        data = http("POST", url) or {}
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            raise SessionExpired(f"refresh refuse (HTTP {e.code})")
        raise
    if not data.get("accessToken"):
        raise SessionExpired("reponse de refresh sans accessToken")
    state["access"] = data["accessToken"]
    if data.get("refreshToken"):
        state["refresh"] = data["refreshToken"]
    elif "refresh" not in state:
        state["refresh"] = refresh
    state.pop("expired_notified", None)
    save_state(state)  # sauvegarde tout de suite : l'ancien refresh token peut etre invalide
    return state["access"]


def api_get(path, state):
    token = get_access_token(state)
    try:
        return http("GET", f"{API}{path}", token=token)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            state.pop("access", None)  # force un refresh puis reessaie une fois
            return http("GET", f"{API}{path}", token=get_access_token(state))
        raise


# ---------- notes ----------

def fetch_grades(state):
    annees = api_get(f"/setting/anneeUniv/liste?etudiant_id={ETUDIANT_ID}", state) or []
    current = [a for a in annees if a.get("etatAnnee")] or sorted(annees, key=lambda a: a.get("anneeDebut", 0))[-1:]
    grades = {}
    for annee in current:
        sems = api_get(f"/setting/semestre/liste?cursusId={CURSUS_ID}&anneeUniversitaireId={annee['id']}", state) or []
        for sem in sems:
            rows = api_get(f"/resultat/note-module/{ETUDIANT_ID}?idAnnee={annee['id']}&idSemestre={sem['id']}", state) or []
            for row in rows:
                key = f"{annee['id']}|{sem['id']}|{row.get('designation')}"
                grades[key] = {
                    "module": row.get("designation") or "?",
                    "semestre": sem.get("nom") or str(sem["id"]),
                    "enseignant": row.get("enseignant") or "",
                    "coef": row.get("coef"),
                    **{f: row.get(f) for f in FIELDS},
                }
    return grades


def is_set(v):
    return v not in (None, "", "-")


def diff(old, new):
    changes = []
    for key, g in new.items():
        before = old.get(key, {})
        for f, label in FIELDS.items():
            if is_set(g.get(f)) and g.get(f) != before.get(f):
                changes.append((g, label, before.get(f), g.get(f)))
    return changes


def main():
    state = load_state()
    try:
        grades = fetch_grades(state)
    except SessionExpired as e:
        print(f"Session expiree : {e}")
        if not state.get("expired_notified"):
            notify("ARP : reconnexion necessaire",
                   "Le surveillant de notes n'arrive plus a se connecter. "
                   "Connecte-toi sur arp.esprit.tn, recopie ton refreshToken dans le secret "
                   "ARP_REFRESH_TOKEN sur GitHub. La surveillance reprend toute seule ensuite.",
                   priority="high", tags="warning")
            state["expired_notified"] = True
            state.pop("access", None)
            state.pop("refresh", None)
            save_state(state)
        return 0  # deja notifie ; on evite un e-mail d'echec GitHub toutes les 5 minutes

    old = state.get("grades")
    if old is None:
        n = sum(1 for g in grades.values() for f in FIELDS if is_set(g.get(f)))
        notify("ARP : surveillance activee",
               f"{len(grades)} modules suivis, {n} notes deja publiees. "
               "Tu recevras une notification a chaque nouvelle note.",
               tags="white_check_mark")
    else:
        for g, label, before, after in diff(old, grades):
            what = "modifiee" if is_set(before) else "publiee"
            notify(f"Nouvelle note : {g['module']}",
                   f"{label} {what} : {after}" + (f" (avant : {before})" if is_set(before) else "")
                   + f"\n{g['semestre']} - coef {g['coef']}"
                   + (f" - {g['enseignant']}" if g['enseignant'] else ""),
                   priority="high", tags="mortar_board")
    state["grades"] = grades
    save_state(state)
    # Rien de personnel dans les logs (le depot peut etre public).
    print(f"OK : {len(grades)} modules verifies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
