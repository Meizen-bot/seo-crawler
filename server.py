import json
import os
import threading
from flask import Flask, jsonify, request, send_from_directory
from flask_sock import Sock
from crawler import SEOCrawler

app = Flask(__name__, static_folder=".", static_url_path="")
sock = Sock(app)

DATA_FILE = os.path.join("data", "crawl.json")

_crawl_state = {
    "running": False,
    "crawled": 0,
    "total_queued": 0,
    "current_url": "",
    "robots_blocked": 0,
    "stopped": False,
    "error": "",
    "crawler": None,
    "stop_event": None,
}
_ws_clients: list = []
_ws_lock = threading.Lock()


def _broadcast(msg: dict):
    dead = []
    with _ws_lock:
        clients = list(_ws_clients)
    for ws in clients:
        try:
            ws.send(json.dumps(msg))
        except Exception:
            dead.append(ws)
    if dead:
        with _ws_lock:
            for ws in dead:
                if ws in _ws_clients:
                    _ws_clients.remove(ws)


@sock.route("/ws")
def ws_handler(ws):
    with _ws_lock:
        _ws_clients.append(ws)
    try:
        ws.send(json.dumps({"type": "state", **_crawl_state_snapshot()}))
        while True:
            msg = ws.receive(timeout=30)
            if msg is None:
                break
    except Exception:
        pass
    finally:
        with _ws_lock:
            if ws in _ws_clients:
                _ws_clients.remove(ws)


def _crawl_state_snapshot():
    return {
        "running": _crawl_state["running"],
        "crawled": _crawl_state["crawled"],
        "total_queued": _crawl_state["total_queued"],
        "current_url": _crawl_state["current_url"],
        "robots_blocked": _crawl_state["robots_blocked"],
        "stopped": _crawl_state["stopped"],
        "error": _crawl_state["error"],
    }


def _run_crawl(start_url: str, max_urls: int, delay: float, config: dict):
    stop_event = threading.Event()
    _crawl_state.update({
        "running": True,
        "crawled": 0,
        "total_queued": 0,
        "current_url": "",
        "robots_blocked": 0,
        "stopped": False,
        "error": "",
        "stop_event": stop_event,
    })

    def on_progress(crawled, total_queued, current_url, robots_blocked=0, stopped=False):
        _crawl_state["crawled"] = crawled
        _crawl_state["total_queued"] = total_queued
        _crawl_state["current_url"] = current_url
        _crawl_state["robots_blocked"] = robots_blocked
        _broadcast({
            "type": "progress",
            "crawled": crawled,
            "total_queued": min(total_queued, max_urls),
            "current_url": current_url,
            "robots_blocked": robots_blocked,
        })

    try:
        crawler = SEOCrawler(
            start_url,
            max_urls=max_urls,
            delay=delay,
            on_progress=on_progress,
            config=config,
            stop_event=stop_event,
        )
        _crawl_state["crawler"] = crawler
        data = crawler.crawl()

        os.makedirs("data", exist_ok=True)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        stopped = data["meta"].get("stopped", False)
        _broadcast({
            "type": "done",
            "meta": data["meta"],
            "stopped": stopped,
        })
    except Exception as e:
        _crawl_state["error"] = str(e)
        _broadcast({"type": "error", "message": str(e)})
    finally:
        _crawl_state["running"] = False
        _crawl_state["crawler"] = None
        _crawl_state["stop_event"] = None


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/crawl", methods=["POST"])
def start_crawl():
    if _crawl_state["running"]:
        return jsonify({"error": "Un crawl est déjà en cours"}), 409

    body = request.get_json(force=True)
    start_url = body.get("url", "").strip()
    max_urls = int(body.get("max_urls", 200))
    delay = float(body.get("delay", 0.5))
    config = body.get("config", {})

    if not start_url:
        return jsonify({"error": "URL manquante"}), 400

    t = threading.Thread(
        target=_run_crawl, args=(start_url, max_urls, delay, config), daemon=True
    )
    t.start()
    return jsonify({"status": "started"})


@app.route("/api/crawl/stop", methods=["POST"])
def stop_crawl():
    if _crawl_state["stop_event"]:
        _crawl_state["stop_event"].set()
    if _crawl_state["crawler"]:
        _crawl_state["crawler"].stop()
    return jsonify({"status": "stopping"})


@app.route("/api/status")
def status():
    return jsonify(_crawl_state_snapshot())


@app.route("/api/data")
def get_data():
    if not os.path.exists(DATA_FILE):
        return jsonify({"error": "Aucune donnée disponible"}), 404
    with open(DATA_FILE, encoding="utf-8") as f:
        return app.response_class(f.read(), mimetype="application/json")


@app.route("/api/upload", methods=["POST"])
def upload_json():
    if "file" not in request.files:
        return jsonify({"error": "Aucun fichier"}), 400
    f = request.files["file"]
    if not f.filename.endswith(".json"):
        return jsonify({"error": "Fichier JSON requis"}), 400
    os.makedirs("data", exist_ok=True)
    content = f.read()
    json.loads(content)
    with open(DATA_FILE, "wb") as out:
        out.write(content)
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    print("SEO Crawler  →  http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
