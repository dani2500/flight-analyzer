"""Flask app: one page and a chat endpoint.

    python app.py     ->  http://localhost:5000

Missing datasets are downloaded into data/ in the background; until they are all there the
page shows a preparation message and the chat is locked.
"""
import threading

from flask import Flask, jsonify, render_template, request

import config
from airdata import sources, store
from analysis import metrics, scoring
from assistant import agent

app = Flask(__name__)
app.json.sort_keys = False  # keep the tools' column order in the tables


@app.get("/")
def index():
    return render_template("index.html", model=config.OLLAMA_MODEL, ready=sources.ready(),
                           metrics={**metrics.LABELS, **scoring.CONGESTION_INPUTS})


def _body():
    """The request's JSON object, or {} when it is missing, malformed or not an object."""
    body = request.get_json(force=True, silent=True)
    return body if isinstance(body, dict) else {}


def _session_id(body):
    return str(body.get("session_id") or "default")[:64]


@app.post("/api/chat")
def chat():
    body = _body()
    message = body.get("message")
    message = message.strip() if isinstance(message, str) else ""
    if not message:
        return jsonify(error="Empty message."), 400
    if not sources.ready():
        return jsonify(error="Data is still being downloaded. Try again in a few minutes."), 503
    try:
        return jsonify(agent.ask(_session_id(body), message))
    except agent.ModelError as e:  # the message is written for the user
        return jsonify(error=str(e)), 502
    except Exception:  # keep the details in the server log, not in the browser
        app.logger.exception("chat failed")
        return jsonify(error="Something went wrong while answering. Please try again."), 500


@app.get("/api/data")
def data_status():
    return jsonify(sources.status())


@app.post("/api/reset")
def reset():
    agent.reset(_session_id(_body()))
    return jsonify(ok=True)


if __name__ == "__main__":
    # The first start takes minutes; the page stays locked and shows progress meanwhile.
    threading.Thread(target=store.prepare, daemon=True).start()
    app.run(port=config.PORT, debug=False)
