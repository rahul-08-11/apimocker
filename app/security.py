import secrets


def new_user_id() -> str:
    # short-ish, URL-safe
    return secrets.token_urlsafe(10)


def new_admin_token() -> str:
    return secrets.token_urlsafe(32)

