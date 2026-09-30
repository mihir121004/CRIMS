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
    transformed = vectorizer.transform([text])
    prediction = model.predict(transformed)[0]
    return prediction


def predict_confidence(text):
    """
    Returns the confidence (0-100) of the AI category prediction.
    Used by the AI command center to show classification confidence.
    """
    transformed = vectorizer.transform([text])
    probabilities = model.predict_proba(transformed)[0]
    return round(float(probabilities.max()) * 100)

def detect_priority(text):
    text = text.lower()

    for word in HIGH_PRIORITY_WORDS:
        if word in text:
            return 'High'
    return 'Medium'