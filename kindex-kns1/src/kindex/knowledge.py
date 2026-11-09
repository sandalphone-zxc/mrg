import hashlib,json

def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()
