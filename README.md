# Surveillant de notes ARP Esprit

Vérifie tes notes sur arp.esprit.tn **toutes les 5 minutes, 24h/24**, sur les serveurs de GitHub
(ton PC peut être éteint), et t'envoie une **notification sur ton téléphone** dès qu'une note
(CC, TP, Examen, Rattrapage) est publiée ou modifiée.

## Comment ça marche
- La connexion ARP a un reCAPTCHA : impossible de se connecter automatiquement avec le mot de passe.
  Le script utilise donc le **refresh token** de ta session (comme le site lui-même) et le renouvelle
  à chaque passage. Ton mot de passe n'est jamais utilisé ni stocké.
- L'état (jeton + dernières notes) est **chiffré** avec ta clé `STATE_KEY` avant d'être sauvegardé.
- Rien de personnel n'est écrit dans les logs.
- Si la session expire, tu reçois une notification « reconnexion nécessaire » (voir étape 6).

## Installation (≈ 10 minutes, une seule fois)

### 1. L'app de notification : ntfy
Installe **ntfy** (gratuit, sans compte) sur ton téléphone : App Store / Google Play.
Choisis un nom de topic **secret et impossible à deviner** (n'importe qui connaissant le nom peut lire
les messages). Génère-le dans le Terminal :

```bash
echo "arp-notes-$(openssl rand -hex 12)"
```

Dans l'app ntfy : **+** → colle ce nom → *Subscribe*.

### 2. La clé de chiffrement
```bash
openssl rand -base64 32 | tr '+/' '-_'
```
Garde le résultat, c'est `STATE_KEY`.

### 3. Crée le dépôt GitHub
Crée un compte sur github.com si besoin, puis un **nouveau dépôt public** (ex. `arp-notes`).
Public = minutes GitHub Actions illimitées et gratuites (en privé, le quota gratuit ne suffit pas
pour une vérification toutes les 5 minutes). Aucune donnée sensible n'est visible : tout passe par les secrets
et l'état chiffré.

Envoie-y les fichiers de ce dossier (`watcher.py`, `.github/workflows/watch.yml`, ce README),
via *Add file → Upload files* (le dossier `.github` doit être inclus), ou en ligne de commande.

### 4. Récupère ton refresh token
1. Dans Chrome, connecte-toi normalement sur https://arp.esprit.tn/online
2. Ouvre la console : `Cmd + Option + J`
3. Tape : `copy(sessionStorage.getItem("refreshToken"))` puis Entrée → le jeton est copié.
4. **Ferme l'onglet sans cliquer « Se déconnecter »** (la déconnexion pourrait invalider le jeton).

### 5. Ajoute les secrets
Dans le dépôt : *Settings → Secrets and variables → Actions → New repository secret*. Crée :

| Nom | Valeur |
|---|---|
| `ETUDIANT_ID` | ton identifiant étudiant (celui qui apparaît dans l'URL de ton profil ARP) |
| `NTFY_TOPIC` | le nom de topic de l'étape 1 |
| `STATE_KEY` | la clé de l'étape 2 |
| `ARP_REFRESH_TOKEN` | le jeton de l'étape 4 |

### 6. Lance-le
Onglet **Actions** → accepte d'activer les workflows → *Surveiller les notes ARP* → **Run workflow**.
Tu dois recevoir « ARP : surveillance activée » sur ton téléphone. Ensuite ça tourne tout seul.

## Si tu reçois « reconnexion nécessaire »
Refais l'étape 4 et remplace le secret `ARP_REFRESH_TOKEN` (*Update*). C'est tout.

## Bon à savoir
- GitHub lance les tâches planifiées avec parfois quelques minutes de retard : compte 5 à 15 minutes
  entre la publication et la notification.
- GitHub met en pause les tâches planifiées d'un dépôt public sans activité depuis 60 jours : il
  t'envoie un e-mail, il suffit de cliquer pour réactiver (ou de modifier un fichier du dépôt).
- Le jeton de session dure 7 jours et est renouvelé à chaque passage. Si ARP impose une durée maximale
  de session, il faudra refaire l'étape 4 de temps en temps. La notification te prévient.
