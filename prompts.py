"""Prompt construction (versioned so runs are reproducible)."""
PROMPT_VERSION = "1.0"
STYLES = ("direct", "cot", "calibration_hint")

_FORMAT = ("Reply in exactly this format:\nAnswer: <your answer>\n"
           "Confidence: <an integer from 0 to 100: your probability, in percent, that your answer is correct>")
SYSTEM = {
    "direct": "You answer questions. " + _FORMAT,
    "cot": ("You answer questions. You may reason step by step first, but end your reply with exactly these two lines:\n"
            "Answer: <your answer>\nConfidence: <an integer from 0 to 100: your probability, in percent, that your answer is correct>"),
    "calibration_hint": ("You answer questions. Your confidence must be well calibrated: across many questions where you say 70, "
                         "about 70 percent of your answers should be correct, so do not default to high numbers. " + _FORMAT),
}


def build_messages(question: dict, style: str = "direct") -> list:
    if style not in STYLES:
        raise ValueError(f"style must be one of {list(STYLES)}")
    return [{"role": "system", "content": SYSTEM[style]}, {"role": "user", "content": question["question"]}]
