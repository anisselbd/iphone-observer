"""Sources de donnees du collector.

Chaque source est une coroutine `run(rsd, bus, **opts)` qui boucle et publie des
events (enveloppe unique) sur le bus. Le collector supervise les sources et les
relance apres une coupure de tunnel.
"""
