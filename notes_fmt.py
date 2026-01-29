def format_notes(raw: str) -> str | None:
    """Format notes: '-' means no notes, commas become bullet points."""
    text = raw.strip()
    if text == "-":
        return None
    if "," in text:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        return "\n".join(f"— {p}" for p in parts)
    return text
