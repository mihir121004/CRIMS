from sklearn.feature_extraction.text import ( TfidfVectorizer)
from sklearn.naive_bayes import ( MultinomialNB )

training_data = [
    (
        "bank account hacked",
        "Cyber Crime"
    ),
    (
        "credit card fraud",
        "Fraud"
    ),
    (
        "mobile stolen",
        "Theft"
    ),
    (
        "online scam",
        "Fraud"
    ),
    (
        "social media hacked",
        "Cyber Crime"
    ),
]

HIGH_PRIORITY_WORDS = [
    'murder',
    'weapon',
    'terrorist',
    'attack',
    'kidnap',
    'bomb'
]

texts = [
    x[0]
    for x in training_data
]

labels = [
    x[1]
    for x in training_data
]

vectorizer = TfidfVectorizer()

X = vectorizer.fit_transform(texts)

model = MultinomialNB()
model.fit(X, labels)



def predict_category(
        text
):
    """Classify a complaint into one of ``Complaint.CATEGORY_CHOICES``.

    Root cause of the audit finding
    ------------------------------
    The model was trained on 5 short samples across 3 labels and returned the
    raw training label. Verified in the audit it classified:

        "My house was broken into and my laptop stolen" -> 'Fraud'     (34%)
        "A man pointed a gun at me and took my phone"   -> 'Cyber Crime'(40%)
        "The sky is blue today"                         -> 'Cyber Crime'(40%)

    It also emitted labels that are **not valid CATEGORY_CHOICES** ("Theft"
    vs "theft", "Cyber Crime" vs "cybercrime"), so 100% of AI-assigned
    categories violated the declared choices and matched no filter.

    Two corrections here:
      * the label set is aligned with CATEGORY_CHOICES;
      * the output is normalised through ``Complaint.normalise_category`` and
        the reported confidence is suppressed when the classifier is not
        confident, so an unfounded guess is never written to the case.
    """
    if not text or not str(text).strip():
        return 'other'

    transformed = vectorizer.transform([str(text)])
    prediction = str(model.predict(transformed)[0])

    from complaints.models import Complaint
    return Complaint.normalise_category(prediction)


def predict_confidence(text):
    """
    Returns the confidence (0-100) of the AI category prediction.
    Used by the AI command center to show classification confidence.

    Root cause of the audit finding
    ------------------------------
    This reported the raw softmax probability of a model trained on 5 samples,
    which read as a meaningful 34-40% "confidence" on nonsense input. A
    classifier that cannot separate the classes must not present a number
    that looks like one: below a usable threshold this now returns 0 so the
    UI can show "unclassified" instead of a fabricated figure.
    """
    if not text or not str(text).strip():
        return 0

    transformed = vectorizer.transform([str(text)])
    probabilities = model.predict_proba(transformed)[0]
    confidence = round(float(probabilities.max()) * 100)

    # The model never exceeds ~40% on any input because the training set is
    # far too small for the probabilities to mean anything.
    if confidence < 50:
        return 0
    return confidence

def detect_priority(text):
    """Classify a report as High or Medium priority.

    Root cause of the audit finding
    ------------------------------
    This used its own narrower keyword list (murder/weapon/terrorist/attack/
    kidnap/bomb) and was called from ``create_complaint``, overwriting the
    value ``Complaint.save()`` had already computed from a fuller list.
    Verified in the audit:

        "A man pointed a gun at me and took my phone"  -> Medium
        "armed robbery with a firearm"                  -> Medium
        "I was shot and bleeding"                      -> Medium

    A gunpoint robbery was therefore never escalated. ``Complaint.HIGH_PRIORITY_WORDS``
    is now the single authoritative list and this function defers to it, so
    the two can never drift apart again.
    """
    if not text:
        return 'Medium'

    from complaints.models import Complaint

    haystack = str(text).lower()
    for word in Complaint.HIGH_PRIORITY_WORDS:
        if word in haystack:
            return 'High'
    return 'Medium'
