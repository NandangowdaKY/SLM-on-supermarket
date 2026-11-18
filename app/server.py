"""
SuperMart SLM - local chat web app.

Serves a chat page on http://localhost:8000 and forwards questions to the model running in Ollama
(http://localhost:11434). Python standard library only - no extra packages.

    ollama create supermart-slm -f ollama/Modelfile     # once
    python app/server.py                               # then open http://localhost:8000
    python app/server.py --port 9000 --model supermart-slm
"""
import argparse
import json
import os
import random
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OLLAMA = "http://localhost:11434"
MODEL = "supermart-slm"


def trained_questions():
    """One question per trained fact, so the suggestions are questions the model knows."""
    path = os.path.join(ROOT, "data", "sft_train.jsonl")
    if not os.path.exists(path):
        return []
    seen, out = set(), []
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        if r["group"] not in seen:
            seen.add(r["group"])
            out.append(r["messages"][1]["content"])
    return out


QUESTIONS = trained_questions()
FEATURED = [
    "Give me an overview of the SuperMart dataset.",
    "Which departments generate the most sales?",
    "What is the average basket size?",
    "What time of day do customers shop the most?",
    "How does spending vary by age group?",
    "What share of sales comes from private label brands?",
    "What is gross margin?",
    "Explain RFM analysis.",
]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter console
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if self.path == "/api/questions":
            featured = [q for q in FEATURED if q in QUESTIONS] or QUESTIONS[:8]
            more = random.sample(QUESTIONS, min(8, len(QUESTIONS)))
            return self._send(200, json.dumps({"featured": featured, "more": more, "total": len(QUESTIONS)}))
        if self.path == "/api/status":
            try:
                with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=3) as r:
                    names = [m["name"] for m in json.load(r).get("models", [])]
                ok = any(n.split(":")[0] == MODEL for n in names)
                return self._send(200, json.dumps({"ollama": True, "model": ok, "name": MODEL}))
            except Exception:
                return self._send(200, json.dumps({"ollama": False, "model": False, "name": MODEL}))
        self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path != "/api/chat":
            return self._send(404, json.dumps({"error": "not found"}))
        length = int(self.headers.get("Content-Length", 0))
        question = json.loads(self.rfile.read(length) or b"{}").get("question", "").strip()
        if not question:
            return self._send(400, json.dumps({"error": "empty question"}))

        # One question per request: the model was fine-tuned on single-turn Q&A with a 512-token
        # context. The system prompt comes from the Ollama Modelfile.
        payload = json.dumps({"model": MODEL, "stream": True,
                              "messages": [{"role": "user", "content": question}]}).encode()
        req = urllib.request.Request(f"{OLLAMA}/api/chat", data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            upstream = urllib.request.urlopen(req, timeout=120)
        except urllib.error.URLError as e:
            return self._send(502, json.dumps({"error": f"Ollama not reachable at {OLLAMA}: {e}"}))

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with upstream:
            for line in upstream:                       # relay tokens as they are generated
                if not line.strip():
                    continue
                chunk = json.loads(line)
                out = {"token": chunk.get("message", {}).get("content", ""), "done": chunk.get("done", False)}
                if chunk.get("done"):
                    out["tokens"] = chunk.get("eval_count")
                    out["seconds"] = round(chunk.get("total_duration", 0) / 1e9, 2)
                self.wfile.write((json.dumps(out) + "\n").encode())
                self.wfile.flush()


def main():
    global MODEL
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--model", default=MODEL)
    a = ap.parse_args()
    MODEL = a.model
    server = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"SuperMart SLM chat running at http://localhost:{a.port}  (model: {MODEL}, Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
