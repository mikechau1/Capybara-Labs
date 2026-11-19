"""audit: append-only record of who asked what and what they were shown.

- writer.py   the one helper every module uses to record events (card M3-07)
- router.py   GET /audit (card M4-03)
- models.py   table: audit_events (the app's database role may insert and read, never change)

App admins see every event. Department owners see only their department's part. Everyone
else gets 403.
"""
