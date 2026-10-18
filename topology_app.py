"""Flask server for the drag-and-drop topology builder.

Run:  python topology_app.py   then open http://127.0.0.1:5000
"""

from flask import Flask, jsonify, request, send_from_directory

from network_sim import TopologyError, simulate

app = Flask(__name__, static_folder="static")


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/simulate")
def api_simulate():
    body = request.get_json(silent=True) or {}
    try:
        result = simulate(body.get("topology", {}), rounds=body.get("rounds", 60))
    except (TopologyError, KeyError, ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
