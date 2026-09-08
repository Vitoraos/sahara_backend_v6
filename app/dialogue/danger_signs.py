"""Candidate English safety phrases for the community-health triage gate.

This is a deterministic safety vocabulary, not a diagnostic protocol. It must be
clinically reviewed and locally validated before production deployment.
"""

DANGER_SIGN_PHRASES: tuple[str, ...] = (
    # Unconsciousness / markedly reduced responsiveness.
    "unconscious",
    "not conscious",
    "cannot wake up",
    "can't wake up",
    "won't wake up",
    "does not respond",
    "not responding",
    "passed out and won't wake up",
    # Severe breathing difficulty.
    "cannot breathe",
    "can't breathe",
    "struggling to breathe",
    "severe difficulty breathing",
    "severe trouble breathing",
    "gasping for air",
    "gasping",
    "choking and cannot breathe",
    "breathing is extremely difficult",
    # Severe chest pain / concerning associated symptoms.
    "severe chest pain",
    "crushing chest pain",
    "pressure in my chest",
    "heavy pressure in my chest",
    "chest pain with difficulty breathing",
    "chest pain and sweating",
    "chest pain and fainting",
    # Stroke warning patterns.
    "face is drooping",
    "one side of the face is weak",
    "one arm is weak",
    "one side of the body is weak",
    "sudden weakness on one side",
    "suddenly cannot speak",
    "speech suddenly became unclear",
    "sudden loss of vision",
    "sudden severe dizziness with weakness",
    # Seizure / convulsion.
    "having a seizure",
    "having a convulsion",
    "convulsing",
    "fitting",
    "having fits",
    "had a seizure",
    "had a convulsion",
    "uncontrolled shaking",
    # Major bleeding.
    "bleeding heavily",
    "heavy bleeding",
    "bleeding won't stop",
    "bleeding cannot stop",
    "cannot stop the bleeding",
    "blood is coming out heavily",
    "vomiting a lot of blood",
    "coughing up a lot of blood",
    "passing a lot of blood",
    # Severe allergic reaction.
    "throat is closing",
    "throat is swelling",
    "tongue is swelling",
    "face is swelling and cannot breathe",
    "suddenly cannot breathe after taking medicine",
    "severe allergic reaction",
    # Severe dehydration / inability to keep fluids down.
    "cannot drink",
    "unable to drink",
    "cannot keep any fluids down",
    "vomits everything",
    "has not been able to drink",
    "very weak and unable to drink",
    # Acute confusion.
    "suddenly confused",
    "does not know where they are",
    "acting strangely and not responding normally",
    "extremely confused",
    "suddenly became confused",
    # Major injury.
    "severe injury",
    "serious injury",
    "major accident",
    "severe head injury",
    "unconscious after an accident",
    "heavy bleeding after an accident",
    # Pediatric/community danger signs from the candidate protocol.
    "unable to breastfeed",
    "chest indrawing",
    "severe dehydration",
    "swelling of both feet",
    "severe malnutrition",
)

REQUIRED_TRIAGE_FIELDS: tuple[str, ...] = (
    "patient_age",
    "sex",
    "chief_complaint",
    "symptoms",
    "symptom_onset",
    "symptom_severity",
    "breathing_difficulty",
    "consciousness_status",
    "seizure_or_convulsion",
    "ability_to_drink",
    "bleeding",
)
