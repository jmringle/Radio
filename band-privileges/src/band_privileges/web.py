"""bandcheck-web: a local web page for the rule engine (127.0.0.1 only)."""

from flask import Flask, render_template, request

from band_privileges.rules import LicenseClass, Mode, check, parse_choice, parse_frequency


# No scripts, frames, fonts or outside requests: only our own stylesheet and
# form submissions back to this page.
_CSP = (
    "default-src 'none'; style-src 'self'; form-action 'self'; "
    "base-uri 'none'; frame-ancestors 'none'"
)


def create_app() -> Flask:
    app = Flask(__name__)
    # DNS rebinding defense: a hostile site can point its own hostname at
    # 127.0.0.1, but the browser still sends that hostname in the Host header.
    app.config["TRUSTED_HOSTS"] = ["127.0.0.1", "localhost"]

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/")
    def home():
        form = {name: request.args.get(name, "") for name in ("freq", "mode", "class")}
        result, error = None, None
        if "freq" in request.args:
            try:
                result = check(
                    parse_frequency(form["freq"]),
                    parse_choice(Mode, "mode", form["mode"]),
                    parse_choice(LicenseClass, "class", form["class"]),
                )
            except ValueError as invalid:
                error = str(invalid)
        page = render_template(
            "index.html",
            modes=list(Mode),
            classes=list(LicenseClass),
            form=form,
            result=result,
            error=error,
        )
        return page, 400 if error else 200

    return app


def main() -> None:
    # Loopback only, debug off: see the README's threat model.
    create_app().run(host="127.0.0.1", port=8073, debug=False)
