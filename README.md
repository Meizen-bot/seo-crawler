# SEO Crawler — Force-Directed Graph

Outil de crawl SEO avec visualisation interactive des liens entre pages, inspiré de Screaming Frog SEO Spider.

## Installation

```bash
cd seo-crawler
pip install -r requirements.txt
```

## Démarrage

```bash
python server.py
```

Puis ouvrir **http://localhost:5000**

## Utilisation

1. Saisir l'URL de départ (ex : `https://example.com`)
2. Configurer le nombre max de pages et le délai entre requêtes
3. Cliquer sur **▶ Lancer** — la progression s'affiche en temps réel via WebSocket
4. Le graphe se construit automatiquement à la fin du crawl

## Crawl en ligne de commande

```bash
python crawler.py https://example.com 500
```

Le résultat est exporté dans `data/crawl.json`.

## Charger un crawl existant

Cliquer sur **📂 Charger JSON** pour visualiser un fichier `crawl.json` préexistant.

## Structure du JSON exporté

```json
{
  "meta": { "start_url": "...", "total_pages": 42, "total_edges": 150, "max_depth": 4 },
  "nodes": [
    {
      "id": 0,
      "url": "https://example.com/",
      "title": "Accueil",
      "meta_description": "...",
      "status_code": 200,
      "depth": 0,
      "inlinks_count": 5,
      "outlinks_count": 12,
      "word_count": 320,
      "h1": ["Bienvenue"]
    }
  ],
  "edges": [{ "source": 0, "target": 1 }]
}
```

## Fonctionnalités

- **Graphe interactif** : zoom, pan, drag des nœuds
- **Couleurs** : vert = 200, orange = 3xx, rouge = 4xx/5xx, gris = erreur
- **Taille des nœuds** proportionnelle au nombre d'inlinks
- **Tooltip** au survol : URL, titre, status, profondeur, inlinks, outlinks, mots, H1
- **Tableau filtrable/triable** : filtre par statut, profondeur, recherche texte
- **Highlight bidirectionnel** : clic nœud ↔ ligne tableau
- **Progression temps réel** via WebSocket
- **Respect du robots.txt**
