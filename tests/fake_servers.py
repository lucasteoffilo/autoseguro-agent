"""Servidor HTTP LOCAL que imita as APIs de LLM (OpenAI-compativel/OpenRouter e Anthropic). Sem rede, sem chave real."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Chave de MENTIRA no formato do OpenRouter, montada em tempo de execucao: o literal completo nao pode existir na fonte (o scanner de segredos
# do repo reprovaria). Os testes de seguranca usam este valor como "canario": se ele aparecer em qualquer saida, o teste reprova.
CANARY_KEY = "sk-or" + "-v1-" + "CANARY0123456789abcdefABCDEF"

GOOD = {"slots": [{"slot": "idade", "value": "42", "uncertain": False}], "intent": "provide_info", "facts_used": [],
        "reply": "Anotado! Qual o seu CEP?"}


def chat_json(content: str | None, *, finish_reason: str = "stop", model: str = "vendor/model:free", prompt_tokens: int = 2400,
              completion_tokens: int = 130, reasoning_tokens: int = 0, cached_tokens: int = 0) -> dict:
    """Resposta no formato de chat completions do OpenRouter."""
    return {"id": "gen-test-123", "object": "chat.completion", "model": model,
            "choices": [{"index": 0, "finish_reason": finish_reason, "native_finish_reason": finish_reason,
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                      "prompt_tokens_details": {"cached_tokens": cached_tokens},
                      "completion_tokens_details": {"reasoning_tokens": reasoning_tokens}}}


def anthropic_json(text: str, stop_reason: str = "end_turn") -> dict:
    """Resposta no formato da API de mensagens da Anthropic."""
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": "claude-haiku-5-5", "stop_reason": stop_reason,
            "stop_sequence": None, "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 2400, "output_tokens": 130, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}


def error_json(code: int, message: str, **metadata) -> dict:
    return {"error": {"code": code, "message": message, **({"metadata": metadata} if metadata else {})}}


class FakeServer:
    """Fila de respostas (consumida em ordem) + resposta padrao. Registra toda requisicao recebida."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.default: tuple[int, dict, object] = (200, {}, {})
        self.delay = 0.0
        self._queue: list[tuple[int, dict, object]] = []
        self._routes: dict[tuple[str, str], list[tuple[int, dict, object]]] = {}  # (metodo, caminho) -> respostas na ordem; vence a fila geral
        srv = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self, method: str) -> None:
                raw = self.rfile.read(int(self.headers.get("content-length") or 0))
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = None
                srv.requests.append({"method": method, "path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                time.sleep(srv.delay)
                routed = srv._routes.get((method, self.path))
                status, headers, payload = routed.pop(0) if routed else (srv._queue.pop(0) if srv._queue else srv.default)
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                try:
                    self.send_response(status)
                    self.send_header("content-type", "application/json")
                    self.send_header("content-length", str(len(data)))
                    for k, v in headers.items():
                        self.send_header(k, v)
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass  # o cliente ja desistiu (timeout)

            def do_POST(self) -> None:
                self._handle("POST")

            def do_GET(self) -> None:
                self._handle("GET")

            def log_message(self, *a) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()  # shutdown() espera esse intervalo

    def reply(self, status: int = 200, payload: object = None, headers: dict | None = None) -> None:
        self.default = (status, headers or {}, {} if payload is None else payload)

    def queue(self, status: int, payload: object, headers: dict | None = None) -> None:
        self._queue.append((status, headers or {}, payload))

    def route(self, method: str, path: str, status: int, payload: object, headers: dict | None = None) -> None:
        """Resposta especifica de (metodo, caminho), consumida em ordem. Serve para o GET /key, chamado antes e depois do smoke."""
        self._routes.setdefault((method, path), []).append((status, headers or {}, payload))

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
