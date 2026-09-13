from __future__ import annotations

from flask import Blueprint, jsonify, render_template


takhfid_bp = Blueprint("takhfid", __name__, url_prefix="/takhfid")


@takhfid_bp.get("/")
def dashboard():
    """Small integration page for the Takhfid storefront backend."""
    return render_template("takhfid/index.html")


@takhfid_bp.get("/health")
def health():
    return jsonify({"ok": True, "service": "takhfid", "version": 1})
