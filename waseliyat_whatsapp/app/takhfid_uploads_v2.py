from flask import Blueprint, send_from_directory, current_app


takhfid_uploads_v2_bp = Blueprint('takhfid_uploads_v2', __name__)


@takhfid_uploads_v2_bp.get('/takhfid/uploads/payment-proofs/<order_id>/<filename>')
def serve_payment_proof(order_id: str, filename: str):
    root = current_app.instance_path + '/takhfid_uploads/payment-proofs/' + order_id
    return send_from_directory(root, filename, max_age=3600)
