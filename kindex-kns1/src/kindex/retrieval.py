import re

def tokens(text):
    terms = re.findall(r"[a-zA-Z0-9_./-]+", text.lower())
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        terms.extend(run[i:i+2] for i in range(len(run)-1))
        if len(run) == 1:
            terms.append(run)
    return sorted(set(terms))


def values(value):
    """Flatten trusted structured fields into retrieval text without inventing claims."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ' '.join(values(item) for item in value)
    if isinstance(value, dict):
        return ' '.join(values(item) for item in value.values())
    return ''
