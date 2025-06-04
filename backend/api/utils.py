import uuid
def is_valid_uuid(s: str) -> bool:
    try:
        uuid_obj = uuid.UUID(s)
        return str(uuid_obj) == s.lower()
    except ValueError:
        return False
