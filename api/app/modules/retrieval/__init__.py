"""retrieval: the ONLY code that reads chunks. The policy enforcement point. Card M2-07.

Internal only, so it has no router. Every search takes a Scope, and the scope goes inside the
SQL WHERE clause. Changes here need review from two teammates and must keep the leakage tests
(card M2-08) green.
"""
