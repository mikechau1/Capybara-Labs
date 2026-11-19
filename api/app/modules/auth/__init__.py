"""auth: turns a request into a verified Principal. Cards M1-06 (OIDC) and M1-05 (demo users).

Every endpoint gets the user through `CurrentUser` from `dependencies.py`. Never read identity
from anything the UI sends except a validated token (or, in dev mode, the X-Dev-User header).
"""
