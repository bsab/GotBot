# GotBot 🐺

Bot Telegram per ricevere meme casuali di **Game of Thrones** da un bucket Amazon S3, anche privato. Python 3.13, handler asincroni e nessun database necessario.

## Cosa fa

| Comando | Funzione |
| --- | --- |
| `/start` | Presentazione del bot |
| `/help` | Elenco dei comandi |
| `/gotmeme` | Invia un meme casuale |
| `/comment <messaggio>` | Inoltra feedback al manutentore, se configurato |

Funziona nelle chat private e nei gruppi, anche con `/gotmeme@NomeDelBot`. I comandi storici `/GoTMeme` e `/Comment` continuano a funzionare. Il menu comandi viene registrato automaticamente all'avvio. Le risposte del bot sono in inglese.

- Catalogo S3 paginato, filtrato e aggiornato automaticamente: non serve riavviare dopo aver caricato un meme.
- Download privati tramite credenziali AWS, senza rendere pubblico il bucket o esporre URL firmati agli utenti.
- Chiamate S3 fuori dall'event loop, massimo 8 aggiornamenti Telegram concorrenti, timeout e tentativi AWS limitati.
- Messaggi comprensibili quando la libreria è vuota, S3 non risponde o il feedback non può essere consegnato.
- Avvio locale in polling oppure webhook dietro HTTPS, senza dominio o destinatario hardcoded.

## Avvio rapido (PowerShell)

Servono **Python 3.13**, un token creato con [@BotFather](https://t.me/BotFather), un bucket S3 e credenziali AWS autorizzate.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Modifica `.env`, impostando almeno `TELEGRAM_TOKEN` e `AWS_STORAGE_BUCKET_NAME`. Per AWS, preferisci un profilo locale già configurato o un ruolo IAM. Sono supportate anche `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` e, per credenziali temporanee, `AWS_SESSION_TOKEN`, in ambiente o nel tuo `.env` locale.

```powershell
.\.venv\Scripts\python.exe bot.py
```

Apri il bot su Telegram e invia `/gotmeme`. Arrestalo con `Ctrl+C`. Usa **una sola istanza polling per token**; non avviare una copia locale con lo stesso token di un bot già in produzione.

Le variabili d'ambiente hanno precedenza sul file `.env` nella directory del progetto. Non committare `.env`, token o chiavi AWS. L'importazione dei moduli non legge la configurazione e non contatta Telegram, S3 o database.

## Configurazione

| Variabile | Default | Descrizione |
| --- | --- | --- |
| `TELEGRAM_TOKEN` | obbligatoria | Token Telegram |
| `AWS_STORAGE_BUCKET_NAME` | obbligatoria | Nome del bucket, non un URL |
| `AWS_REGION` | `eu-central-1` | Regione effettiva del bucket |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | opzionali | Coppia esplicita; se assente viene usata la catena credenziali standard di boto3 |
| `AWS_SESSION_TOKEN` | opzionale | Token per la coppia di credenziali temporanee |
| `MEME_PREFIX` | vuoto | Prefisso S3 da esplorare, ad esempio `got/` |
| `MEME_CACHE_TTL` | `300` | Secondi tra aggiornamenti del catalogo, da 1 a 86400 |
| `DEVELOPER_CHAT_ID` | vuoto | ID numerico destinatario del feedback; vuoto disabilita l'inoltro |
| `BOT_MODE` | `polling` | `polling` oppure `webhook` |
| `WEBHOOK_URL` | vuoto | URL HTTPS pubblico di base, obbligatorio in webhook |
| `WEBHOOK_SECRET` | vuoto | Segreto di verifica webhook, obbligatorio in webhook |
| `PORT` | `8080` | Porta HTTP interna; normalmente fornita dall'hosting |
| `LOG_LEVEL` | `INFO` | Livello dei log applicativi: DEBUG, INFO, WARNING, ERROR, CRITICAL |

`WEBHOOK_SECRET` accetta 1–256 lettere ASCII, cifre, `_` e `-`: usa un valore casuale lungo, diverso dal token del bot. I log applicativi non includono contenuti dei messaggi, credenziali o dettagli delle eccezioni di rete.

Il destinatario del feedback deve aver avviato il bot, oppure essere un gruppo in cui il bot può scrivere. `/comment` inoltra testo, username (oppure nome) e ID Telegram al manutentore; conferma l'invio soltanto dopo la consegna. Non inviare dati sensibili tramite questo comando.

## Libreria S3

Carica immagini `.jpg`, `.jpeg` o `.png`, non vuote e al massimo di 10 MiB. Cartelle, GIF, documenti e oggetti più grandi vengono ignorati. Le immagini devono rispettare anche i vincoli di `sendPhoto` di Telegram: somma di larghezza e altezza non superiore a 10.000 e rapporto tra i lati non superiore a 20. Il bot non modifica o ricodifica le immagini.

La cache contiene solo il catalogo, non le immagini. Ogni richiesta scarica al massimo 10 MiB più un byte di controllo e carica la foto su Telegram. Un oggetto cancellato invalida il catalogo: riprova il comando per effettuare una nuova selezione. Una libreria inizialmente vuota viene ricontrollata alla scadenza della cache.

Permessi IAM minimi, sostituendo `YOUR_BUCKET` e restringendo i percorsi se usi un prefisso:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::YOUR_BUCKET"
    },
    {
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::YOUR_BUCKET/*"
    }
  ]
}
```

Per oggetti cifrati con una chiave KMS gestita da te serve anche l'autorizzazione `kms:Decrypt` sulla chiave. Non sono necessari permessi di scrittura S3.

## Deploy webhook / Heroku

Il `Procfile` conserva `web: python bot.py`; `.python-version` seleziona Python 3.13. Configura le variabili dell'hosting (non caricare `.env`) e imposta:

```dotenv
BOT_MODE=webhook
WEBHOOK_URL=https://your-app.example.com
WEBHOOK_SECRET=replace-with-a-long-random-value
```

L'app ascolta HTTP su `0.0.0.0:$PORT`, percorso `/telegram`. L'hosting o il reverse proxy deve terminare HTTPS e inoltrare a quel percorso l'header `X-Telegram-Bot-Api-Secret-Token`. L'URL registrato su Telegram sarà `https://your-app.example.com/telegram`: il token del bot non compare nell'URL pubblico. La porta esterna deve essere supportata da Telegram (443, 80, 88 o 8443); quella interna è indipendente.

Se `WEBHOOK_URL` include un prefisso, il proxy deve rimuoverlo prima di inoltrare la richiesta al percorso interno `/telegram`. Gli aggiornamenti in attesa non vengono scartati all'avvio. Il polling rimuove un eventuale webhook precedente. Utilizza una sola istanza del bot: la cache è locale e non c'è deduplicazione distribuita. Gli aggiornamenti in esecuzione non sono persistiti; un arresto forzato può interromperli.

## Test e sviluppo

I test usano `unittest`, mock Telegram/S3 e stream locali: **nessuna credenziale o chiamata a servizi esterni**. Un test avvia brevemente un webhook su `127.0.0.1`, verifica il rifiuto di segreti errati e l'accettazione degli aggiornamenti autorizzati, poi arresta il server.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

GitHub Actions esegue gli stessi controlli su Python 3.13 a ogni push e pull request.

```text
bot.py                 Entry point compatibile con il deploy precedente
 gotbot\app.py         Creazione applicazione e lifecycle
 gotbot\config.py      Configurazione e validazione
 gotbot\handlers.py    Comandi e risposte Telegram
 gotbot\memes.py       Catalogo e download S3
 tests\                Test offline
```

## Migrazione dalla versione Python 2

1. Ricrea l'ambiente virtuale con Python 3.13 e reinstalla `requirements.txt`.
2. Mantieni token, bucket e credenziali AWS esistenti, verificando `AWS_REGION`.
3. Imposta esplicitamente `DEVELOPER_CHAT_ID`: il vecchio destinatario hardcoded non viene riutilizzato.
4. Per l'hosting web imposta `BOT_MODE=webhook`, `WEBHOOK_URL` e `WEBHOOK_SECRET`. Il polling è ora il default.
5. `DATABASE_URL` e PostgreSQL non servono più; il bot non legge o modifica il vecchio database.

Il codice degli alert giornalieri, già non registrato nella versione precedente, è stato rimosso insieme ai riferimenti alle foto di gatti. Alert giornalieri, modalità inline e invio di meme da parte degli utenti **non sono implementati** in questo revamp. I comandi attivi e la compatibilità con le chat di gruppo sono mantenuti.

