"""chat: question in, cited answer out.

- pipeline.py   the fixed pipeline: scope, plan, retrieve, answer, audit (cards M3-03..M3-05)
- answering.py  the answer step: calls the model, keeps only real citations (M3-04)
- router.py     POST /chat (M3-05), conversations (M3-06)
- schemas.py    the contract the chat page renders
- models.py     tables: conversations, messages
"""
