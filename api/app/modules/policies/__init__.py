"""policies: who may read what. The policy decision point.

- scope.py      resolve a user's readable pools (card M2-02)
- router.py     grants API (M4-01) and access requests API (M4-04)
- schemas.py    request and response shapes shared with the UI
- models.py     tables: grants, access_requests

Owners create and revoke grants only for their own department. App admins may revoke but
never create. Grants only add access; there are no deny rules.
"""
