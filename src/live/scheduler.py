"""
Scheduler Kill Zone — attend la prochaine session active et déclenche
le cycle de trading (fetch → pipeline → signaux → positions).

Fenêtres Kill Zone (EST) :
  London   : 02:00 – 05:00
  New York : 08:00 – 11:00
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

import pytz

logger = logging.getLogger(__name__)

_EST = pytz.timezone("America/New_York")

# Fenêtres (heure_debut, heure_fin) en EST
_KILL_ZONES: list[tuple[int, int, int, int]] = [
    (2, 0, 5, 0),    # London
    (8, 0, 11, 0),   # New York
]


def now_est() -> datetime:
    return datetime.now(timezone.utc).astimezone(_EST)


def in_kill_zone(dt: datetime | None = None) -> bool:
    """Retourne True si l'heure EST est dans une Kill Zone."""
    t = (dt or now_est())
    for h_start, m_start, h_end, m_end in _KILL_ZONES:
        start = t.replace(hour=h_start, minute=m_start, second=0, microsecond=0)
        end   = t.replace(hour=h_end,   minute=m_end,   second=0, microsecond=0)
        if start <= t < end:
            return True
    return False


def next_kill_zone_start() -> datetime:
    """Retourne le prochain début de Kill Zone en UTC."""
    t = now_est()
    candidates = []
    for h_start, m_start, h_end, m_end in _KILL_ZONES:
        start = t.replace(hour=h_start, minute=m_start, second=0, microsecond=0)
        if start <= t:
            start += timedelta(days=1)
        candidates.append(start)
    return min(candidates).astimezone(timezone.utc)


def seconds_until_next_kill_zone() -> float:
    nxt = next_kill_zone_start()
    now = datetime.now(timezone.utc)
    return max(0.0, (nxt - now).total_seconds())


def run_scheduler(
    callback: Callable[[], None],
    poll_seconds: int = 60,
    max_iterations: int | None = None,
    force_run_now: bool = False,
) -> None:
    """
    Boucle principale du scheduler.

    Args:
        callback:       Fonction appelée à chaque barre en Kill Zone.
        poll_seconds:   Intervalle de polling (défaut: 60s = 1 barre/min).
        max_iterations: Limite pour les tests (None = infini).
        force_run_now:  Si True, lance le callback immédiatement sans attendre.
    """
    iterations = 0

    logger.info("Scheduler démarré. Kill Zones: London 02-05h EST, NY 08-11h EST")

    if force_run_now:
        logger.info("Mode force_run_now — exécution immédiate")
        callback()
        iterations += 1
        if max_iterations and iterations >= max_iterations:
            return

    while True:
        if max_iterations and iterations >= max_iterations:
            break

        now_e = now_est()

        if in_kill_zone(now_e):
            logger.debug("Kill Zone active [%s EST] — exécution du cycle", now_e.strftime("%H:%M"))
            try:
                callback()
            except Exception as exc:
                logger.error("Erreur dans le cycle de trading: %s", exc, exc_info=True)
            iterations += 1
            time.sleep(poll_seconds)
        else:
            wait = seconds_until_next_kill_zone()
            next_kz = next_kill_zone_start()
            logger.info(
                "Hors Kill Zone [%s EST]. Prochain démarrage: %s UTC (dans %.0fmin)",
                now_e.strftime("%H:%M"),
                next_kz.strftime("%Y-%m-%d %H:%M"),
                wait / 60,
            )
            # Dormir jusqu'à 5 minutes avant la prochaine KZ (pour se réveiller à temps)
            sleep_time = max(30.0, wait - 300)
            time.sleep(min(sleep_time, 3600))
