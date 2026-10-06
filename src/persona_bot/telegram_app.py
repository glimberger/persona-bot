"""
Étape 4 : brancher les personas sur Telegram.

Ce module n'est qu'un adaptateur : il reçoit les messages Telegram, les passe
au PersonaBot (le même que dans le terminal) et renvoie la réponse.

Un bot Telegram par persona : chacune a son propre token (créé avec @BotFather), donc son
propre nom, sa propre photo et sa propre conversation dans Telegram. Tous ces bots tournent
dans un seul processus Python (voir run_all), qui partage le modèle d'embeddings.

Chaque bot fonctionne en "long polling" : c'est lui qui demande sans arrêt à Telegram
s'il y a de nouveaux messages. Il ne fait que des connexions sortantes : aucun
port à ouvrir, il fonctionne derrière n'importe quelle box.
"""

import asyncio
import logging
import signal

import anthropic
from telegram import Update
from telegram.constants import ChatAction, MessageLimit
from telegram.error import Conflict, InvalidToken, NetworkError, TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from persona_bot.config import LLM_BACKEND
from persona_bot.logs import traced

log = logging.getLogger(__name__)

# Telegram efface l'indicateur « en train d'écrire… » au bout d'environ 5 secondes. On le
# renvoie un peu plus souvent pour qu'il reste affiché sans clignoter.
TYPING_REFRESH_SECONDS = 4


@traced
def parse_allowed_users(value):
    """ "123, 456" -> {123, 456}"""
    return {int(user_id) for user_id in value.split(",") if user_id.strip()}


@traced
def split_message(text, limit=MessageLimit.MAX_TEXT_LENGTH):
    """Telegram refuse les messages de plus de 4096 caractères : on découpe au besoin."""
    return [text[i : i + limit] for i in range(0, len(text), limit)]


@traced
def is_allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Sans liste blanche, n'importe qui trouvant le bot dépenserait tes crédits API."""
    user = update.effective_user
    log.debug(
        "Message reçu de %s (id %s) dans la conversation %s (%s)",
        user.full_name,
        user.id,
        update.effective_chat.id,
        getattr(update.effective_chat, "type", "?"),
    )
    if user.id in context.bot_data["allowed_users"]:
        return True
    # L'identifiant est journalisé pour que tu puisses t'ajouter à TELEGRAM_ALLOWED_USERS.
    log.warning("Accès refusé à %s (id %s)", user.full_name, user.id)
    return False


def message(context, name):
    """Phrase `name` de la persona servie par ce bot Telegram (voir persona.toml, [messages])."""
    return context.bot_data["bot"].persona.messages[name]


@traced
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update, context):
        return
    await update.message.reply_text(message(context, "welcome"))


@traced
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update, context):
        return
    context.bot_data["bot"].reset(update.effective_chat.id)
    await update.message.reply_text(message(context, "reset"))


@traced
async def keep_typing(context: ContextTypes.DEFAULT_TYPE, chat_id):
    """
    Affiche « en train d'écrire… » dans Telegram jusqu'à ce qu'on annule cette tâche.

    Un seul envoi suffit avec Claude (environ 7 s par réponse), mais pas avec Ollama sur le
    Pi, où une réponse prend environ une minute : l'indicateur disparaîtrait au bout de 5 s
    et la personne croirait le bot planté. On le renvoie donc en boucle, dans une tâche
    asyncio qui tourne en parallèle de la génération.
    """
    while True:
        try:
            await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
        except TelegramError as error:
            # Un indicateur perdu n'a pas d'importance : on n'interrompt pas la réponse pour ça.
            log.debug("Indicateur « en train d'écrire » non envoyé : %s", error)
        await asyncio.sleep(TYPING_REFRESH_SECONDS)


@traced
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update, context):
        return

    # Affiche "en train d'écrire..." dans Telegram pendant que le modèle génère la réponse.
    typing = asyncio.create_task(keep_typing(context, update.effective_chat.id))

    try:
        # respond() est bloquant (recherche + appel à Claude, plusieurs secondes) :
        # on l'exécute dans un thread pour ne pas figer la boucle asynchrone de Telegram.
        answer, citations = await asyncio.to_thread(
            context.bot_data["bot"].respond, update.message.text, update.effective_chat.id
        )
    # Claude et Ollama passent par le même SDK (voir llm.py) : les exceptions sont les mêmes.
    except anthropic.RateLimitError:
        log.warning("Limite de débit du modèle de langage atteinte (%s)", LLM_BACKEND)
        answer = message(context, "rate_limit")
    except anthropic.APIStatusError as e:
        log.error("Erreur du modèle de langage (%s, HTTP %s) : %s", LLM_BACKEND, e.status_code, e.message)
        answer = message(context, "api_error")
    except anthropic.APIConnectionError:
        # Avec Ollama : le serveur est arrêté, ou OLLAMA_BASE_URL est fausse.
        log.error("Impossible de joindre le modèle de langage (%s)", LLM_BACKEND)
        answer = message(context, "connection_error")
    else:
        log.info("Réponse envoyée (%d citations utilisées)", len(citations))
    finally:
        # Réponse prête (ou erreur) : on arrête l'indicateur avant d'envoyer le message.
        typing.cancel()

    parts = split_message(answer)
    log.debug("Envoi de la réponse en %d message(s) Telegram", len(parts))
    for part in parts:
        await update.message.reply_text(part)


@traced
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """
    Erreurs qui ne viennent pas de nos handlers mais de la communication avec Telegram.
    Sans ce gestionnaire, la librairie affiche une trace technique de plusieurs dizaines de lignes.
    """
    error = context.error
    if isinstance(error, Conflict):
        # Telegram n'accepte qu'un seul programme à la fois pour lire les messages d'un bot.
        log.error(
            "Une autre instance du bot tourne déjà avec le même token (dans un autre terminal, "
            "sur le Pi...). Telegram n'en accepte qu'une : arrête l'autre."
        )
    elif isinstance(error, NetworkError):
        # La librairie réessaie d'elle-même : une coupure passagère n'est pas grave.
        log.warning("Problème réseau avec Telegram (%s) : nouvel essai automatique.", error)
    else:
        log.error("Erreur inattendue", exc_info=error)


# Pas de @traced ici : le décorateur journalise les arguments, et `token` est un secret.
def build_application(token, allowed_users, bot):
    """Une Application Telegram (un bot BotFather) qui sert un PersonaBot."""
    app = Application.builder().token(token).build()
    # bot_data est un dictionnaire partagé par tous les handlers de CETTE application : chaque
    # bot Telegram retrouve ainsi sa propre persona.
    app.bot_data["bot"] = bot
    app.bot_data["allowed_users"] = allowed_users
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_error_handler(on_error)
    log.debug(
        "Application Telegram prête pour la persona %s, %d utilisateur(s) autorisé(s)",
        bot.persona.slug,
        len(allowed_users),
    )
    return app


# Signaux qui demandent l'arrêt : Ctrl+C (SIGINT), systemctl stop (SIGTERM) et SIGABRT,
# les mêmes que ceux qu'écoute run_polling().
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGABRT)


@traced
async def run_all(applications, stop=None):
    """
    Fait tourner plusieurs bots Telegram dans le même processus, jusqu'à un signal d'arrêt.

    Avec un seul bot, `app.run_polling()` suffit. Mais cette méthode prend la main sur toute la
    boucle asyncio (la boucle d'événements qui fait avancer les tâches asynchrones) et ne rend
    la main qu'à l'arrêt : impossible d'en lancer une deuxième à côté. On refait donc à la main
    ce qu'elle fait, dans le même ordre, pour chaque application :
      démarrage : initialize() -> updater.start_polling() -> start()
      arrêt     : updater.stop() -> stop() -> shutdown(), dans l'ordre inverse.

    Pourquoi un seul processus plutôt qu'un service par persona ? Le modèle d'embeddings,
    qui occupe la plus grosse part de la mémoire, n'est alors chargé qu'une fois (voir
    index.py). Sur un Raspberry Pi, ça compte.

    `stop` : un asyncio.Event à déclencher pour arrêter. Les tests le fournissent ; sinon, on
    en crée un que les signaux d'arrêt déclenchent.
    """
    loop = asyncio.get_running_loop()
    own_signals = stop is None
    if own_signals:
        stop = asyncio.Event()
        # add_signal_handler : à la réception du signal, asyncio appelle stop.set() au lieu de
        # tuer le programme. L'arrêt se fait ainsi proprement, dans le bloc finally ci-dessous.
        for sig in STOP_SIGNALS:
            loop.add_signal_handler(sig, stop.set)

    launched = []
    try:
        for app in applications:
            # Ajouté avant initialize() : si elle échoue à mi-chemin, shutdown() libère quand même
            # ce qui a été ouvert (comme run_polling ; shutdown ne fait rien si rien n'a démarré).
            launched.append(app)
            # initialize() contacte Telegram (getMe) : un token faux ou un réseau absent échoue ici.
            try:
                await app.initialize()
            except InvalidToken:
                # Le message d'origine de la librairie contient le token en clair : il finirait
                # dans le terminal ou le journal systemd. "from None" empêche Python de
                # l'afficher comme cause de notre erreur.
                slug = app.bot_data["bot"].persona.slug
                raise SystemExit(
                    f"Token Telegram refusé pour la persona {slug} : vérifie TELEGRAM_TOKEN_{slug.upper()} "
                    "dans .env (copie-le à nouveau depuis @BotFather)."
                ) from None

            # Les erreurs de récupération des messages (réseau, Conflict...) passent par nos
            # gestionnaires d'erreurs (on_error), comme le fait run_polling().
            def error_callback(error, app=app):
                app.create_task(app.process_error(error=error, update=None))

            await app.updater.start_polling(error_callback=error_callback)
            await app.start()
            log.info("Bot @%s démarré (persona %s)", app.bot.username, app.bot_data["bot"].persona.slug)

        log.info("%d bot(s) en attente de messages (Ctrl+C pour arrêter)", len(launched))
        await stop.wait()
        log.info("Arrêt demandé")
    finally:
        if own_signals:
            # Le signal a fait son travail : on rend leur effet normal aux suivants. Si l'arrêt
            # se bloque, un second Ctrl+C interrompt alors vraiment le programme.
            for sig in STOP_SIGNALS:
                loop.remove_signal_handler(sig)
        # Même si le démarrage d'un bot a échoué, ceux déjà lancés sont arrêtés proprement :
        # les derniers messages sont marqués comme lus et ne seront pas traités deux fois.
        for app in reversed(launched):
            if app.updater.running:
                await app.updater.stop()
            if app.running:
                await app.stop()
            await app.shutdown()
