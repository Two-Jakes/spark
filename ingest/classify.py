"""Classify Hacker News headlines with transparent keyword rules."""

from __future__ import annotations

import re


AI_KEYWORDS = (
    "ai", "llm", "machine learning", "deep learning", "neural network",
    "artificial intelligence", "language model", "inference", "transformer",
    "openai", "anthropic", "claude", "gemini", "gpt", "model weights",
)
SECURITY_KEYWORDS = (
    "security", "cybersecurity", "vulnerability", "exploit", "ransomware",
    "malware", "phishing", "breach", "cve", "zero day", "zeroday",
    "authentication bypass", "credential theft", "supply chain attack",
    "remote code execution", "rce", "privilege escalation", "xss", "ssrf",
    "unauthenticated", "code injection",
)


def has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    """Find a whole-word keyword; text and keyword list are inputs; return whether any match."""
    lowered = text.lower()
    return any(re.search(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", lowered) is not None for keyword in keywords)


def classify_hn(title: str) -> str:
    """Classify a HN title; title is the headline; return a Spark category."""
    if has_keyword(title, SECURITY_KEYWORDS):
        return "Cyber Security"
    if has_keyword(title, AI_KEYWORDS):
        return "AI"
    return "Development"
