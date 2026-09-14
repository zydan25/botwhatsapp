from flask import Blueprint, current_app, send_from_directory, make_response
from pathlib import Path


takhfid_admin_pwa_bp = Blueprint("takhfid_admin_pwa", __name__)


@takhfid_admin_pwa_bp.get("/takhfid/admin/sw.js")
def service_worker():
    root = Path(current_app.static_folder) / "takhfid-admin"
    response = make_response(send_from_directory(root, "sw.js"))
    response.headers["Service-Worker-Allowed"] = "/takhfid/admin/"
    response.headers["Cache-Control"] = "no-cache"
    return response
