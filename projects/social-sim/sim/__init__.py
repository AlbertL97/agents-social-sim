"""Social-sim package: 4 parallel Concordia social simulations on a live dashboard.

Stateless cron-batch architecture (no always-on server): GitHub Actions fires an
ephemeral ``advance.py`` every ~10 minutes; each run loads persisted state,
advances whichever scenario/entity is DUE, and exits.
"""
