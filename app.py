from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import smtplib
import socket
import ssl
from collections import deque
from datetime import datetime, timezone
from email.message import EmailMessage
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from time import monotonic
from urllib.parse import parse_qs, unquote, urlsplit


ROOT = Path(__file__).resolve().parent
CONTACT_FILE = ROOT / "datos" / "contactos.jsonl"
SMTP_CONFIG_FILE = ROOT / "smtp.ini"
MAX_FORM_BYTES = 16_384
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 10
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
CONTACT_EMAIL = "info@ariki.group"
SUBMISSION_TIMES = deque()
SUBMISSION_LOCK = Lock()
CONTACT_FILE_LOCK = Lock()
SERVED_FILES = {
    "/index.html",
    "/privacy.html",
    "/styles.css",
    "/translations.js",
    "/translations.json",
    "/site.js",
    "/Recursos/SIGMA_Logo.png",
    "/Recursos/SIGMA_Logo_Mini.png",
    "/Recursos/Fondos/Campa.jpg",
    "/Recursos/Fondos/Recuperacion.png",
    "/Recursos/Fondos/Transporte.jpg",
    "/SIGMA_Quick_Tunnel_QR.png",
    "/Recursos/Centro_Control.png",
}


def sync_translations():
    json_path = ROOT / "translations.json"
    js_path = ROOT / "translations.js"
    if not json_path.exists():
        return None
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        js_content = "window.SIGMA_TRANSLATIONS = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n"
        js_path.write_text(js_content, encoding="utf-8")
        return data
    except Exception as error:
        print(f"[Aviso] No se pudo sincronizar translations.js: {error}")
        return None


def send_contact_email(record):
    config = configparser.ConfigParser(interpolation=None)
    config.read(SMTP_CONFIG_FILE, encoding="utf-8")
    smtp = config["smtp"] if config.has_section("smtp") else {}

    def setting(environment_name, config_name, default=""):
        return os.environ.get(environment_name) or smtp.get(config_name, default)

    host = setting("SMTP_HOST", "host").strip()
    username = setting("SMTP_USER", "username").strip()
    password = "".join(setting("SMTP_PASSWORD", "password").split())
    sender = setting("SMTP_FROM", "from", username).strip()
    if sender.lower() == "your-smtp-account":
        sender = username
    security = setting("SMTP_SECURITY", "security", "starttls").strip().lower()

    if not host or not username or not password or not sender:
        raise RuntimeError("SMTP is not configured")
    if security not in {"starttls", "ssl"}:
        raise RuntimeError("Unsupported SMTP security mode")

    try:
        port = int(setting("SMTP_PORT", "port", "587"))
    except ValueError as error:
        raise RuntimeError("Invalid SMTP port") from error

    message = EmailMessage()
    message["Subject"] = "Nueva consulta desde SIGMA Intelligence Group"
    message["From"] = sender
    message["To"] = CONTACT_EMAIL
    message["Reply-To"] = record["email"]
    message.set_content(
        "Se recibió una consulta desde el formulario web de SIGMA.\n\n"
        f"Nombre: {record['name']}\n"
        f"Correo: {record['email']}\n"
        f"Empresa: {record['company'] or 'No indicada'}\n"
        f"Consentimiento de privacidad: {'Sí' if record['privacy_consent'] else 'No'}\n"
        f"Comunicaciones comerciales: {'Sí' if record['marketing_consent'] else 'No'}\n\n"
        f"Mensaje:\n{record['message']}\n"
    )

    if security == "ssl":
        connection = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context())
    else:
        connection = smtplib.SMTP(host, port, timeout=20)

    with connection as server:
        if security == "starttls":
            server.starttls(context=ssl.create_default_context())
        server.login(username, password)
        server.send_message(message)


class SiteHandler(SimpleHTTPRequestHandler):
    def _is_local_request(self):
        client_ip = self.client_address[0]
        local_ips = {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}
        try:
            local_ips.update(
                info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None)
            )
        except Exception:
            pass
        if client_ip not in local_ips:
            return False
        # Si la petición pasa por un túnel (Cloudflare, ngrok, proxy inverso), se añaden estas cabeceras
        if self.headers.get("CF-Connecting-IP") or self.headers.get("X-Forwarded-For"):
            return False
        return True

    def send_head(self):
        request_path = unquote(urlsplit(self.path).path)
        if request_path == "/":
            request_path = "/index.html"

        # Interfaz de administración: accesible exclusivamente desde localhost
        if request_path in {"/admin", "/admin.html"}:
            if not self._is_local_request():
                self.send_error(404, "File not found")
                return None
            sync_translations()
            self.path = "/admin.html"
            return super().send_head()

        if request_path in {"/translations.json", "/translations.js", "/index.html", "/privacy.html"}:
            sync_translations()

        if request_path not in SERVED_FILES:
            self.send_error(404, "File not found")
            return None

        self.path = request_path
        return super().send_head()

    def end_headers(self):
        req_p = getattr(self, "path", "")
        if req_p.endswith((".json", ".js", ".html", ".png", ".jpg", ".jpeg", ".gif", ".webp")) or req_p in {"/", "/index.html", "/admin"}:
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

    def _send_json(self, status, payload):
        response = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(response)

    def do_POST(self):
        post_path = urlsplit(self.path).path

        # Guardado de traducciones: accesible exclusivamente desde localhost
        if post_path == "/api/admin/guardar":
            if not self._is_local_request():
                self._send_json(404, {"error_code": "not_found"})
                return

            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._send_json(415, {"error_code": "format"})
                return

            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_json(400, {"error_code": "invalid_request"})
                return

            if content_length <= 0 or content_length > 2_000_000:
                self._send_json(413, {"error_code": "size"})
                return

            try:
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(400, {"error_code": "invalid_json"})
                return

            translations_data = payload.get("translations") if isinstance(payload, dict) else None
            if not isinstance(translations_data, dict) or not translations_data:
                self._send_json(400, {"error_code": "invalid_data"})
                return

            try:
                json_path = ROOT / "translations.json"
                json_path.write_text(json.dumps(translations_data, ensure_ascii=False, indent=2), encoding="utf-8")
                sync_translations()
            except OSError as error:
                self.log_error(f"Failed to write translations.json: {error}")
                self._send_json(500, {"error_code": "save_failed"})
                return

            self._send_json(200, {"ok": True, "message": "Traducciones guardadas correctamente."})
            return

        if post_path != "/api/contacto":
            self._send_json(404, {"error_code": "invalid_request"})
            return

        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/x-www-form-urlencoded":
            self._send_json(415, {"error_code": "format"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error_code": "invalid_request"})
            return

        if content_length <= 0 or content_length > MAX_FORM_BYTES:
            self._send_json(413, {"error_code": "size"})
            return

        try:
            submitted = parse_qs(self.rfile.read(content_length).decode("utf-8"), keep_blank_values=True)
        except UnicodeDecodeError:
            self._send_json(400, {"error_code": "text"})
            return

        def get_value(field):
            return submitted.get(field, [""])[0].strip()

        if get_value("website"):
            self._send_json(201, {"message": "Gracias. Tu consulta quedó registrada."})
            return

        name = get_value("name")
        email = get_value("email")
        company = get_value("company")
        message = get_value("message")
        privacy_consent = get_value("privacy_consent") == "yes"
        marketing_consent = get_value("marketing_consent") == "yes"

        if not name or len(name) > 120:
            self._send_json(400, {"error_code": "name"})
            return
        if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
            self._send_json(400, {"error_code": "email"})
            return
        if len(company) > 160:
            self._send_json(400, {"error_code": "company"})
            return
        if not message or len(message) > 4000:
            self._send_json(400, {"error_code": "message"})
            return
        if not privacy_consent:
            self._send_json(400, {"error_code": "privacy"})
            return

        now = monotonic()
        with SUBMISSION_LOCK:
            while SUBMISSION_TIMES and now - SUBMISSION_TIMES[0] >= RATE_LIMIT_WINDOW:
                SUBMISSION_TIMES.popleft()
            if len(SUBMISSION_TIMES) >= RATE_LIMIT_MAX:
                self._send_json(429, {"error_code": "rate_limit"})
                return
            SUBMISSION_TIMES.append(now)

        record = {
            "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "name": name,
            "email": email,
            "company": company,
            "message": message,
            "privacy_consent": privacy_consent,
            "marketing_consent": marketing_consent,
        }

        try:
            CONTACT_FILE.parent.mkdir(parents=True, exist_ok=True)
            with CONTACT_FILE_LOCK:
                with CONTACT_FILE.open("a", encoding="utf-8") as contacts:
                    contacts.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            self.log_error("Could not write contact submission")
            self._send_json(500, {"error_code": "save"})
            return

        try:
            send_contact_email(record)
        except (OSError, RuntimeError, configparser.Error, smtplib.SMTPException) as error:
            self.log_error(f"Contact email delivery failed ({type(error).__name__})")
            self._send_json(202, {
                "email_sent": False,
                "error_code": "email_config" if isinstance(error, (RuntimeError, configparser.Error)) else "email_delivery",
            })
            return

        self._send_json(201, {
            "email_sent": True,
            "message": "Gracias. Tu consulta se envió correctamente.",
        })


def main():
    parser = argparse.ArgumentParser(description="Serve la web de SIGMA en la red local.")
    parser.add_argument("--host", default="0.0.0.0", help="Interfaz de red (por defecto: todas).")
    parser.add_argument("--port", type=int, default=8000, help="Puerto HTTP (por defecto: 8000).")
    args = parser.parse_args()

    data = sync_translations()
    if data:
        langs = list(data.keys())
        keys_count = len(data.get("es", {}))
        print(f"[Traducciones] Cargadas {keys_count} claves para {len(langs)} idiomas ({', '.join(langs)}) desde translations.json")
    handler = partial(SiteHandler, directory=str(ROOT))
    with ThreadingHTTPServer((args.host, args.port), handler) as server:
        port = server.server_address[1]
        print(f"Web SIGMA: http://localhost:{port}")
        try:
            addresses = sorted({
                info[4][0]
                for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
                if not info[4][0].startswith("127.")
            })
        except socket.gaierror:
            addresses = []

        for address in addresses:
            print(f"Red local: http://{address}:{port}")
        if not addresses:
            print("Para otros dispositivos, usa la IP local de este equipo.")
        print("Pulsa Ctrl+C para detener el servidor.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor detenido.")


if __name__ == "__main__":
    main()
