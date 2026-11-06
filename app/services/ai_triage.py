"""
MedLink AI Triage Service
=========================
Uses the Claude API to assess patient symptoms and give intelligent,
Uganda-context-aware guidance (malaria, typhoid, TB, etc.).

Set ANTHROPIC_API_KEY in .env for live AI responses.
Falls back to the rule-based system if no key is configured.
"""
import os, json, urllib.request, urllib.error

ANTHROPIC_KEY = os.getenv('ANTHROPIC_API_KEY', '')
ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages'
AI_ENABLED = bool(ANTHROPIC_KEY)

SYSTEM_PROMPT = """You are a medical triage assistant for MedLink Uganda, a health platform
serving patients across Uganda. Your role is to assess symptom descriptions and provide
guidance on urgency and appropriate next steps.

Uganda-specific context you must consider:
- Malaria is endemic; fever + headache + chills is always malaria risk until ruled out
- Typhoid is common; prolonged fever + abdominal pain should raise suspicion
- TB is prevalent; persistent cough > 2 weeks + weight loss + night sweats = TB screening
- Sickle cell disease is common; severe pain crisis needs urgent care
- Snake bites and animal bites need immediate attention
- Obstetric emergencies (eclampsia, postpartum haemorrhage) are leading causes of maternal death

You must respond ONLY with a valid JSON object, no preamble or explanation outside the JSON.
The JSON must have exactly these fields:
{
  "severity": "<one of: emergency, high, medium, low>",
  "recommendation": "<2-3 sentences of clear, actionable guidance for the patient>",
  "specialisation": "<most appropriate medical specialisation from this list: General Practice, Paediatrics, Obstetrics & Gynaecology, Internal Medicine, Surgery, Dermatology, Psychiatry & Mental Health, Ophthalmology, ENT, Orthopaedics, Cardiology, HIV/AIDS & Infectious Disease, Nutrition & Dietetics>",
  "red_flags": ["<any warning signs that need immediate attention, or empty list []>"],
  "home_care": "<one sentence of safe home care advice if severity is low or medium, else null>"
}"""

def assess_symptoms(symptoms: str, duration: str, severity_self: str,
                    fever: bool, breathing: bool, chest_pain: bool,
                    pregnancy: bool, child: bool) -> dict:
    """
    Call Claude to assess the patient's symptoms.
    Returns a dict with: severity, recommendation, specialisation, red_flags, home_care.
    Falls back to rule-based if AI is not configured.
    """
    if not AI_ENABLED:
        return _rule_based(symptoms, severity_self, fever, breathing, chest_pain, pregnancy, child)

    flags = []
    if fever: flags.append('fever')
    if breathing: flags.append('difficulty breathing')
    if chest_pain: flags.append('chest pain')
    if pregnancy: flags.append('currently pregnant')
    if child: flags.append('patient is a child under 5')

    user_message = f"""Patient symptom report:
- Symptoms: {symptoms}
- Duration: {duration}
- Self-assessed severity: {severity_self}
- Additional flags: {', '.join(flags) if flags else 'none'}

Please assess the urgency and provide guidance."""

    payload = json.dumps({
        'model': 'claude-haiku-4-5-20251001',
        'max_tokens': 600,
        'system': SYSTEM_PROMPT,
        'messages': [{'role': 'user', 'content': user_message}]
    }).encode()

    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'x-api-key': ANTHROPIC_KEY,
            'anthropic-version': '2023-06-01',
        },
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            text = data['content'][0]['text'].strip()
            # Strip markdown fences if model wraps in them
            if text.startswith('```'):
                text = text.split('```')[1]
                if text.startswith('json'):
                    text = text[4:]
            result = json.loads(text)
            # Validate required fields are present
            result.setdefault('severity', 'medium')
            result.setdefault('recommendation', 'Please consult a doctor for a proper assessment.')
            result.setdefault('specialisation', 'General Practice')
            result.setdefault('red_flags', [])
            result.setdefault('home_care', None)
            result['ai_powered'] = True
            return result
    except urllib.error.HTTPError as e:
        # Log but fall back gracefully
        print(f'[ai_triage] API error {e.code}: {e.read().decode()[:200]}')
        return _rule_based(symptoms, severity_self, fever, breathing, chest_pain, pregnancy, child)
    except Exception as e:
        print(f'[ai_triage] Error: {e}')
        return _rule_based(symptoms, severity_self, fever, breathing, chest_pain, pregnancy, child)


def _rule_based(symptoms, severity_self, fever, breathing, chest_pain, pregnancy, child) -> dict:
    """Original rule-based fallback — used when no API key is set."""
    s = (symptoms or '').lower()

    if breathing or chest_pain:
        return {
            'severity': 'emergency',
            'recommendation': ('Difficulty breathing or chest pain requires immediate hospital care. '
                               'Go to the nearest emergency room NOW or call 999.'),
            'specialisation': 'Internal Medicine',
            'red_flags': ['Difficulty breathing', 'Chest pain'],
            'home_care': None,
            'ai_powered': False,
        }
    if fever and child:
        return {
            'severity': 'high',
            'recommendation': ('Fever in a child under 5 needs prompt attention within 4–6 hours '
                               'to rule out malaria. Book a consultation or go to a clinic now.'),
            'specialisation': 'Paediatrics',
            'red_flags': ['Fever in child under 5 — malaria risk'],
            'home_care': None,
            'ai_powered': False,
        }
    if fever and pregnancy:
        return {
            'severity': 'high',
            'recommendation': ('Fever during pregnancy needs urgent evaluation. '
                               'Book an immediate consultation with an OB/GYN or midwife.'),
            'specialisation': 'Obstetrics & Gynaecology',
            'red_flags': ['Fever in pregnancy'],
            'home_care': None,
            'ai_powered': False,
        }
    if severity_self == 'severe':
        return {
            'severity': 'high',
            'recommendation': ('Your symptoms sound severe. A same-day consultation is recommended. '
                               'Book an appointment or visit a clinic today.'),
            'specialisation': 'General Practice',
            'red_flags': [],
            'home_care': None,
            'ai_powered': False,
        }

    spec = 'General Practice'
    if any(w in s for w in ['rash','skin','itch','acne']): spec = 'Dermatology'
    elif any(w in s for w in ['eye','vision','blind']): spec = 'Ophthalmology'
    elif any(w in s for w in ['sad','depress','anxious','mental']):spec = 'Psychiatry & Mental Health'
    elif any(w in s for w in ['child','baby','infant','toddler']): spec = 'Paediatrics'
    elif any(w in s for w in ['pregnan','menstrual','period']): spec = 'Obstetrics & Gynaecology'
    elif any(w in s for w in ['hiv','aids','tb','malaria']): spec = 'HIV/AIDS & Infectious Disease'

    if severity_self == 'moderate' or fever:
        return {
            'severity': 'medium',
            'recommendation': ('You should see a doctor within 24–48 hours. '
                               'An online consultation may be sufficient.'),
            'specialisation': spec,
            'red_flags': [],
            'home_care': 'Rest, stay hydrated, and monitor your temperature.',
            'ai_powered': False,
        }
    return {
        'severity': 'low',
        'recommendation': ('Symptoms appear mild. Monitor at home and stay hydrated. '
                           'If symptoms worsen or new symptoms appear, book a consultation.'),
        'specialisation': spec,
        'red_flags': [],
        'home_care': 'Rest well, drink plenty of fluids, and eat light meals.',
        'ai_powered': False,
    }
