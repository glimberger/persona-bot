"""
Configuration des logs et mode debug.

Deux niveaux :
- normal : seuls les événements importants (démarrage, accès refusé, erreurs) ;
- debug  : en plus, chaque appel de fonction décorée par @traced (arguments,
  résultat, durée) et le détail des actions internes (log.debug dans le code).

On active le mode debug avec `persona --debug <commande>` ou la variable
d'environnement PERSONA_DEBUG=1.

Seuls les loggers du projet ("persona_bot.*") passent en DEBUG. Les librairies
tierces restent en WARNING : leurs logs détaillés noieraient les nôtres, et
certaines écrivent des secrets (la librairie réseau httpx journalise les URL
de Telegram, qui contiennent le token du bot).
"""

import builtins
import functools
import inspect
import logging
import re
import reprlib
import time

# Formats des secrets du projet, masqués dans tout ce que @traced écrit. C'est une seconde
# ligne de défense : certains objets affichent un secret dans leur représentation texte
# (le Bot de python-telegram-bot s'affiche "ExtBot[token=...]").
SECRET_PATTERNS = [
    re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}"),  # token de bot Telegram : "123456789:AAH..."
    re.compile(r"sk-ant-[A-Za-z0-9_-]+"),  # clé d'API Anthropic
]


def mask_secrets(text):
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("***", text)
    return text


class _SafeRepr(reprlib.Repr):
    """
    reprlib produit des représentations tronquées : un long message ou un gros objet Telegram
    n'occupe qu'une ligne de log lisible. On masque les secrets AVANT de tronquer : sinon un
    token coupé en deux ne serait plus reconnu par le masque et fuirait en partie.
    """

    def _truncate(self, text, limit):
        if len(text) <= limit:
            return text
        head = max(0, (limit - 3) // 2)
        tail = max(0, limit - 3 - head)
        return text[:head] + "..." + text[len(text) - tail :]

    def repr_str(self, x, level):
        return self._truncate(mask_secrets(builtins.repr(x)), self.maxstring)

    def repr_instance(self, x, level):
        try:
            text = builtins.repr(x)
        except Exception:
            return f"<{type(x).__name__} instance>"
        return self._truncate(mask_secrets(text), self.maxother)


_short = _SafeRepr()
_short.maxstring = 120
_short.maxother = 120
_short.maxlist = 5
_short.maxdict = 5


def short_repr(value):
    return _short.repr(value)


def setup_logging(debug=False):
    logging.basicConfig(
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        level=logging.WARNING,  # niveau des librairies tierces
    )
    logging.getLogger("persona_bot").setLevel(logging.DEBUG if debug else logging.INFO)


def traced(func):
    """
    Décorateur : en mode debug, journalise chaque appel de `func`.

        → JCVDBot.respond(user_message='Salut', conversation_id=42)
        ← JCVDBot.respond = ('Ah tu vois...', [...]) (2315 ms)

    En mode normal, il appelle simplement la fonction : le test
    `isEnabledFor(DEBUG)` ne coûte presque rien.
    Fonctionne aussi pour les fonctions asynchrones (les handlers Telegram).
    """
    log = logging.getLogger(func.__module__)
    name = func.__qualname__
    signature = inspect.signature(func)

    def describe(args, kwargs):
        bound = signature.bind_partial(*args, **kwargs)
        return ", ".join(f"{k}={short_repr(v)}" for k, v in bound.arguments.items() if k != "self")

    def log_end(start, result=None, error=None):
        ms = (time.perf_counter() - start) * 1000
        if error is not None:
            log.debug("✗ %s a levé %s après %.0f ms", name, type(error).__name__, ms)
        else:
            log.debug("← %s = %s (%.0f ms)", name, short_repr(result), ms)

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not log.isEnabledFor(logging.DEBUG):
                return await func(*args, **kwargs)
            log.debug("→ %s(%s)", name, describe(args, kwargs))
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
            except Exception as error:
                log_end(start, error=error)
                raise
            log_end(start, result)
            return result

        return async_wrapper

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not log.isEnabledFor(logging.DEBUG):
            return func(*args, **kwargs)
        log.debug("→ %s(%s)", name, describe(args, kwargs))
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
        except Exception as error:
            log_end(start, error=error)
            raise
        log_end(start, result)
        return result

    return wrapper
