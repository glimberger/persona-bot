"""
Étape 4 : brancher le bot sur Telegram.

Ce module n'est qu'un adaptateur : il reçoit les messages Telegram, les passe
à JCVDBot (le même que dans le terminal) et renvoie la réponse.

Le bot fonctionne en "long polling" : c'est lui qui demande sans arrêt à Telegram
s'il y a de nouveaux messages. Il ne fait que des connexions sortantes : aucun
port à ouvrir, il fonctionne derrière n'importe quelle box.
"""

import asyncio
import logging

import anthropic
from telegram import Update
from telegram.constants import ChatAction, MessageLimit
from telegram.error import Conflict, NetworkError, TelegramError
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


@traced
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update, context):
        return
    await update.message.reply_text(
        "Salut ! Moi c'est Jean-Claude. Pose-moi une question, on va parler de la vie, "
        "de l'awareness... Tu comprends ?\n\n/reset pour recommencer une conversation."
    )


@traced
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update, context):
        return
    context.bot_data["jcvd"].reset(update.effective_chat.id)
    await update.message.reply_text("OK, on repart de zéro. Nouveau cycle, nouvelle roue !")


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
            context.bot_data["jcvd"].respond, update.message.text, update.effective_chat.id
        )
    # Claude et Ollama passent par le même SDK (voir llm.py) : les exceptions sont les mêmes.
    except anthropic.RateLimitError:
        log.warning("Limite de débit du modèle de langage atteinte (%s)", LLM_BACKEND)
        answer = "Doucement, doucement... Laisse-moi respirer une minute et réessaie."
    except anthropic.APIStatusError as e:
        log.error("Erreur du modèle de langage (%s, HTTP %s) : %s", LLM_BACKEND, e.status_code, e.message)
        answer = "Aïe, mon cerveau a fait un grand écart. Réessaie dans un moment."
    except anthropic.APIConnectionError:
        # Avec Ollama : le serveur est arrêté, ou OLLAMA_BASE_URL est fausse.
        log.error("Impossible de joindre le modèle de langage (%s)", LLM_BACKEND)
        answer = "Je n'arrive pas à me connecter... comme l'air, ça existe et ça n'existe pas."
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
def build_application(token, allowed_users, jcvd):
    app = Application.builder().token(token).build()
    # bot_data est un dictionnaire partagé par tous les handlers.
    app.bot_data["jcvd"] = jcvd
    app.bot_data["allowed_users"] = allowed_users
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_error_handler(on_error)
    log.debug("Application Telegram prête, %d utilisateur(s) autorisé(s)", len(allowed_users))
    return app
