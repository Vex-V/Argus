"""Per-account content profiling (C10).

Characterizes one account's posts: TF-IDF keywords (scikit-learn), hashtag
frequency, VADER sentiment distribution, and an Ollama-classified tone.
scikit-learn and vaderSentiment load lazily and degrade gracefully (empty
keywords / neutral sentiment) when unavailable; tone falls back to "unknown"
when Ollama is unreachable.
"""
import logging
import re
from collections import Counter

import httpx

from shared.config import settings

log = logging.getLogger("analyzer.content_profiler")

_vader = None
_vader_error = False

VALID_TONES = {
    "neutral", "aggressive", "promotional", "persuasive", "informative", "casual",
}


def _get_vader():
    global _vader, _vader_error
    if _vader is not None or _vader_error:
        return _vader
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

        _vader = SentimentIntensityAnalyzer()
    except Exception as exc:  # noqa: BLE001
        _vader_error = True
        log.warning("vaderSentiment unavailable: %s", exc)
    return _vader


def extract_keywords(texts: list[str], top_n: int = 15) -> list[str]:
    if not texts:
        return []
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        log.warning("scikit-learn not installed — keyword extraction skipped")
        return []
    try:
        tfidf = TfidfVectorizer(max_features=100, stop_words="english", max_df=0.8)
        matrix = tfidf.fit_transform(texts)
        names = tfidf.get_feature_names_out()
        scores = matrix.sum(axis=0).A1
        top = scores.argsort()[-top_n:][::-1]
        return [names[i] for i in top]
    except ValueError:
        # Empty vocabulary (all stop-words / too few docs)
        return []


def extract_hashtags(texts: list[str]) -> list[tuple[str, int]]:
    counter: Counter = Counter()
    for text in texts:
        counter.update(t.lower() for t in re.findall(r"#(\w+)", text))
    return counter.most_common(20)


def analyze_sentiment(texts: list[str]) -> dict:
    default = {"positive": 0.0, "negative": 0.0, "neutral": 1.0, "compound": 0.0}
    vader = _get_vader()
    if not texts or vader is None:
        return default
    scores = [vader.polarity_scores(t) for t in texts]
    n = len(scores)
    return {
        "positive": round(sum(s["pos"] for s in scores) / n, 3),
        "negative": round(sum(s["neg"] for s in scores) / n, 3),
        "neutral": round(sum(s["neu"] for s in scores) / n, 3),
        "compound": round(sum(s["compound"] for s in scores) / n, 3),
    }


async def classify_tone(texts: list[str]) -> str:
    if not texts:
        return "unknown"
    sample = "\n---\n".join(texts[:10])
    prompt = (
        "Classify the overall tone of these social media posts into EXACTLY ONE of: "
        "neutral, aggressive, promotional, persuasive, informative, casual. "
        "Return ONLY the single word classification, nothing else.\n\n"
        f"Posts:\n{sample}"
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.ollama_url}/api/generate",
                json={"model": settings.ollama_model, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            tone = resp.json().get("response", "unknown").strip().lower()
            return tone if tone in VALID_TONES else "unknown"
    except httpx.HTTPError:
        return "unknown"


async def profile_content(posts: list[str], platform: str = "") -> dict:
    return {
        "top_keywords": extract_keywords(posts),
        "top_hashtags": extract_hashtags(posts),
        "sentiment": analyze_sentiment(posts),
        "tone": await classify_tone(posts),
        "post_count": len(posts),
        "avg_post_length": round(sum(len(p) for p in posts) / max(len(posts), 1), 1),
        "platform": platform,
    }
