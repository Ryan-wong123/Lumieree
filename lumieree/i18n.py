"""Language switching and the ``t()`` template helper."""

from flask import Blueprint, g, redirect, request, session, url_for

from .translations import translations
from .utils import is_safe_next

bp = Blueprint("i18n", __name__)

SUPPORTED = ("en", "zh")


def init_app(app):
    @app.before_request
    def _set_language():
        lang = session.get("lang", "en")
        g.lang = lang if lang in SUPPORTED else "en"

    @app.context_processor
    def _inject_translation():
        lang = g.get("lang", "en")
        table = translations[lang]
        return {"t": lambda key: table.get(key, key)}

    app.register_blueprint(bp)


@bp.post("/switch_language")
def switch_language():
    session["lang"] = "zh" if session.get("lang", "en") == "en" else "en"
    nxt = request.form.get("next")
    return redirect(nxt if is_safe_next(nxt) else url_for("patients.list_patients"))
