from flask import Blueprint, render_template, redirect, url_for
from flask_login import current_user

pages_bp = Blueprint('pages', __name__)


@pages_bp.route('/')
def landing():
    """Public front page. Signed-in users skip straight to their dashboard."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    return render_template('landing.html')


@pages_bp.route('/privacy')
def privacy():
    return render_template('legal/privacy.html')


@pages_bp.route('/terms')
def terms():
    return render_template('legal/terms.html')
