"""
MedLink Uganda — Mental Health Module
======================================
Anonymous mental health support with:
  - PHQ-9 depression screening (validated, WHO-endorsed)
  - GAD-7 anxiety screening
  - AI-powered supportive chat (Claude)
  - Crisis line integration (Befrienders Uganda, Butabika)
  - Zero stigma — fully anonymous, no name required

Uganda context:
  - 1 psychiatrist per 1.5 million people (WHO 2022)
  - Butabika Hospital is the only national referral psych facility
  - Befrienders Uganda crisis line: 0800 212 121 (toll-free)
  - Mental illness stigma is extremely high — anonymity is critical
  - Common presentations: depression, PTSD, alcohol/substance abuse, psychosis
"""
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from app import db
from app.models import MentalHealthSession
from datetime import datetime
import json, uuid

mh_bp = Blueprint('mentalhealth', __name__, url_prefix='/mental-health')

PHQ9_QUESTIONS = [
    'Little interest or pleasure in doing things',
    'Feeling down, depressed, or hopeless',
    'Trouble falling or staying asleep, or sleeping too much',
    'Feeling tired or having little energy',
    'Poor appetite or overeating',
    'Feeling bad about yourself — or that you are a failure or have let yourself or your family down',
    'Trouble concentrating on things, such as reading or watching TV',
    'Moving or speaking so slowly that other people could have noticed. Or the opposite — being so fidgety or restless that you have been moving around a lot more than usual',
    'Thoughts that you would be better off dead or of hurting yourself in some way',
]

GAD7_QUESTIONS = [
    'Feeling nervous, anxious, or on edge',
    'Not being able to stop or control worrying',
    'Worrying too much about different things',
    'Trouble relaxing',
    'Being so restless that it is hard to sit still',
    'Becoming easily annoyed or irritable',
    'Feeling afraid as if something awful might happen',
]

SCORE_OPTIONS = [
    (0, 'Not at all'),
    (1, 'Several days'),
    (2, 'More than half the days'),
    (3, 'Nearly every day'),
]

PHQ9_SEVERITY = [
    (0, 4, 'minimal', 'Your score suggests minimal depressive symptoms.'),
    (5, 9, 'mild', 'Your score suggests mild depression. Lifestyle support and monitoring recommended.'),
    (10, 14, 'moderate', 'Your score suggests moderate depression. A consultation with a doctor or counsellor is recommended.'),
    (15, 19, 'moderately_severe', 'Your score suggests moderately severe depression. Please speak to a mental health professional soon.'),
    (20, 27, 'severe', 'Your score suggests severe depression. Please seek professional help urgently.'),
]

GAD7_SEVERITY = [
    (0, 4, 'minimal', 'Minimal anxiety symptoms.'),
    (5, 9, 'mild', 'Mild anxiety. Relaxation techniques and monitoring may help.'),
    (10, 14, 'moderate', 'Moderate anxiety. A consultation with a counsellor is recommended.'),
    (15, 21, 'severe', 'Severe anxiety. Please seek professional help.'),
]

MH_SYSTEM_PROMPT = """You are a compassionate mental health support assistant for MedLink Uganda.
You provide a safe, non-judgmental space for people to talk about their feelings and mental health concerns.

CRITICAL RULES:
1. You are NOT a therapist or doctor. Never diagnose. Always encourage professional help.
2. If the user expresses suicidal thoughts, self-harm, or immediate crisis, ALWAYS provide crisis resources FIRST:
   - Befrienders Uganda (toll-free): 0800 212 121
   - Butabika Hospital: +256 41 4566 596
   - Emergency: 999
3. Respect cultural context — Uganda has high mental health stigma. Use gentle, non-clinical language.
4. Ask one question at a time. Listen actively.
5. Never shame, minimise, or dismiss feelings.
6. Responses should be warm, short (2-4 sentences), and conversational.
7. If someone shares severe symptoms (not eating, not sleeping, voices, extreme paranoia), gently encourage them to see a doctor.
8. Keep responses in plain English (or match the user's language if they write in Luganda/Runyankole).

You may acknowledge: grief, stress, relationship problems, work pressure, loneliness, anxiety, sadness, trauma.
Always end with an open, caring question or offer."""


@mh_bp.route('/')
def index():
    return render_template('mentalhealth/index.html')


@mh_bp.route('/phq9', methods=['GET', 'POST'])
def phq9():
    if request.method == 'POST':
        answers = []
        for i in range(9):
            val = int(request.form.get(f'q{i}', 0))
            answers.append(val)
        score = sum(answers)
        severity, label = _phq9_severity(score)
        crisis = answers[8] > 0 # Q9 is about self-harm

        # Save to session-based MH record
        tok = session.get('mh_token') or uuid.uuid4().hex
        session['mh_token'] = tok
        rec = MentalHealthSession.query.filter_by(session_token=tok).first()
        if not rec:
            rec = MentalHealthSession(session_token=tok)
            db.session.add(rec)
        rec.phq9_score = score
        rec.phq9_answers = json.dumps(answers)
        rec.phq9_severity = severity
        rec.crisis_flagged = crisis or (rec.crisis_flagged or False)
        db.session.commit()

        return render_template('mentalhealth/phq9_result.html',
                               score=score, severity=severity, label=label,
                               crisis=crisis, answers=answers)
    return render_template('mentalhealth/phq9.html',
                           questions=PHQ9_QUESTIONS, options=SCORE_OPTIONS)


@mh_bp.route('/gad7', methods=['GET', 'POST'])
def gad7():
    if request.method == 'POST':
        answers = [int(request.form.get(f'q{i}', 0)) for i in range(7)]
        score = sum(answers)
        severity, label = _gad7_severity(score)

        tok = session.get('mh_token') or uuid.uuid4().hex
        session['mh_token'] = tok
        rec = MentalHealthSession.query.filter_by(session_token=tok).first()
        if not rec:
            rec = MentalHealthSession(session_token=tok)
            db.session.add(rec)
        rec.gad7_score = score
        rec.gad7_answers = json.dumps(answers)
        rec.gad7_severity = severity
        db.session.commit()

        return render_template('mentalhealth/gad7_result.html',
                               score=score, severity=severity, label=label, answers=answers)
    return render_template('mentalhealth/gad7.html',
                           questions=GAD7_QUESTIONS, options=SCORE_OPTIONS)


@mh_bp.route('/chat')
def chat():
    """Anonymous AI-powered supportive chat."""
    tok = session.get('mh_token') or uuid.uuid4().hex
    session['mh_token'] = tok
    rec = MentalHealthSession.query.filter_by(session_token=tok).first()
    if not rec:
        rec = MentalHealthSession(session_token=tok)
        db.session.add(rec)
        db.session.commit()
    history = json.loads(rec.chat_history or '[]')
    return render_template('mentalhealth/chat.html', history=history, tok=tok)


@mh_bp.route('/chat/send', methods=['POST'])
def chat_send():
    """Handle a chat message — call Claude API and return response."""
    import os, urllib.request, urllib.error

    tok = session.get('mh_token')
    if not tok:
        tok = uuid.uuid4().hex
        session['mh_token'] = tok

    rec = MentalHealthSession.query.filter_by(session_token=tok).first()
    if not rec:
        rec = MentalHealthSession(session_token=tok)
        db.session.add(rec)

    data = request.get_json(force=True) or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'error': 'empty message'}), 400

    history = json.loads(rec.chat_history or '[]')

    # Crisis keyword detection (client-side safety net)
    crisis_words = ['kill myself', 'suicide', 'end my life', 'want to die',
                    'hurt myself', 'self harm', 'no reason to live', 'better off dead']
    crisis_detected = any(w in message.lower() for w in crisis_words)
    if crisis_detected:
        rec.crisis_flagged = True

    # Build messages for API
    history.append({'role': 'user', 'content': message, 'ts': datetime.utcnow().isoformat()})
    api_messages = [{'role': m['role'], 'content': m['content']}
                    for m in history if m['role'] in ('user', 'assistant')]

    api_key = os.getenv('ANTHROPIC_API_KEY', '')
    if api_key:
        payload = json.dumps({
            'model': 'claude-haiku-4-5-20251001',
            'max_tokens': 400,
            'system': MH_SYSTEM_PROMPT,
            'messages': api_messages,
        }).encode()
        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01',
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                resp_data = json.loads(r.read())
                reply = resp_data['content'][0]['text']
        except Exception as e:
            reply = ("I'm here to listen. It sounds like you're going through something difficult. "
                     "If you're in crisis, please call Befrienders Uganda: 0800 212 121 (toll-free).")
    else:
        # Demo fallback
        reply = ("Thank you for sharing that with me. I hear you. "
                 "Would you like to tell me more about how you're feeling, "
                 "or would you prefer to try one of our self-assessment tools?")

    # Always append crisis resources if detected
    if crisis_detected:
        reply += ("\n\n I'm concerned about what you've shared. "
                  "Please reach out for immediate support:\n"
                  "• Befrienders Uganda (free): 0800 212 121\n"
                  "• Emergency: 999\n"
                  "• Butabika Hospital: +256 41 4566 596")

    history.append({'role': 'assistant', 'content': reply, 'ts': datetime.utcnow().isoformat()})
    rec.chat_history = json.dumps(history)
    rec.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'reply': reply, 'crisis': crisis_detected})


def _phq9_severity(score):
    for lo, hi, sev, label in PHQ9_SEVERITY:
        if lo <= score <= hi:
            return sev, label
    return 'severe', PHQ9_SEVERITY[-1][3]

def _gad7_severity(score):
    for lo, hi, sev, label in GAD7_SEVERITY:
        if lo <= score <= hi:
            return sev, label
    return 'severe', GAD7_SEVERITY[-1][3]
