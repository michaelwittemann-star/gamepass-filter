# Game Pass Filter

Website, die die Kataloge von Xbox Game Pass, PlayStation Plus, Amazon Luna, Netflix Games sowie Epic-/Prime-Gratisspiele (Deutschland) nach allem filtert, was die Xbox-App nicht kann:
Erscheinungsjahr, Metascore, Spielzeit (HowLongToBeat), Genre, Spielmodi, Spieleranzahl, Online/Offline,
Open World, Produktionsgröße (AAA/AA/Indie), Steam-Tags, Technik, Altersfreigabe. Klick aufs Cover öffnet die Store-Seite auf xbox.com.

## Datenquellen

| Wert | Quelle |
|---|---|
| Spieleliste, Plattform (Konsole/PC/Cloud/EA Play), Neu/Verlässt bald | `catalog.gamepass.com/sigls` |
| Cover, Genre, Spielmodi, Spieleranzahl, Technik, Altersfreigabe, Xbox-Bewertung | `displaycatalog.mp.microsoft.com` |
| Metascore, Original-Erscheinungsjahr | Metacritic (Such-API der Website) |
| Spielzeit Story / +Extras / 100 % | HowLongToBeat (`howlongtobeatpy`) |
| Steam-Tags, Open World, Steam-Preis | Steam-Suche + SteamSpy (Open World zusätzlich aus Metacritic-Genre) |
| Luna-Spiele (Prime / Premium), Cover, Genre, Freigabe | interne Schnittstelle von luna.amazon.de (ohne Anmeldung, inoffiziell) |
| Prime-Spiele zum Abholen (mit Frist und Shop) | GraphQL der Luna-Claims-Seite (csrf-key aus dem HTML, ohne Anmeldung) |
| PS Plus Essential / Extra / Premium (Katalog, Cover, Genre, PS4/PS5, USK) | `playstation.com/bin/imagic/gameslist` (öffentlich) |
| Epic-Gratisspiele (jetzt / demnächst) | `freeGamesPromotions` des Epic Games Store |
| Netflix-Spiele (Handy / TV) | Liste von whats-on-netflix.com, Verfügbarkeit in DE + Bild über netflix.com/de/games/<id> (Cache `data/cache/netflix_de.json`) |
| Steam: kostenlos / bis 5 € (Regeln `STEAM_RULES`, ab 100 Bewertungen) | Steam-Shop-Suche (Free to Play / bis 5 €, nach Bewertung sortiert; Euro-Preis, Rabatt, % positiv); große F2P (60–79 %) zusätzlich aus Steams Meistgespielt-Liste + SteamSpy-Top-1000, geprüft per `appdetails`/`is_free` |
| AAA / AA / Indie | **geschätzt** in `classify_tier()`: Publisher-Listen, Steam-Tag „Indie“, Zahl der Metacritic-Kritiken, Steam-Preis |

Die Zuordnung zu Metacritic/HLTB/Steam läuft automatisch über den (englischen) Titel. Falsche Treffer
in `data/overrides.json` korrigieren (Produkt-ID aus der xbox.com-URL):

```json
{ "9NPDN9R45JX4": { "metacritic": "1000xresist", "hltb": 143595, "steam": null, "tier": "AA" } }
```

`null` = keine Zuordnung. Luna-Spiele haben die ID `luna-<ASIN>`. Gleiche Spiele aus Konsole/PC/Luna werden über deutschen/englischen Titel oder Metacritic-Eintrag zusammengeführt. Danach `npm run data`.

## Befehle

- `npm run data` – Katalog holen und anreichern (Cache in `data/cache/enrich.json`, nur Neues wird nachgeschlagen; `-- --refresh` holt alles neu)
- `npm run dev` – lokale Vorschau
- `npm run build` – Seite nach `dist/`

Python-Abhängigkeit: `pip install -r requirements.txt`.

`.github/workflows/update.yml` aktualisiert die Daten täglich und veröffentlicht auf GitHub Pages
(braucht ein öffentliches Repo oder GitHub Pro).
