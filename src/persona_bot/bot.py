"""
Étape 3b : le bot conversationnel (RAG = Retrieval-Augmented Generation).

Un PersonaBot fait parler une persona (voir personas.py). À chaque message :
  1. Retrieval    : on cherche les citations de la persona les plus proches du message.
  2. Augmentation : on les ajoute au message envoyé au modèle de langage.
  3. Generation   : le modèle (Claude ou un modèle local via Ollama, voir llm.py)
                    répond dans le style de la persona en s'en inspirant.

Une persona sans citations saute les étapes 1 et 2 : le message part tel quel, et le
modèle ne s'appuie que sur le prompt système. Ce n'est plus du RAG, juste un modèle de
langage à qui on a donné un rôle (voir docs/GUIDE_RAG.md, section 9).

L'historique est renvoyé à chaque appel (l'API ne garde aucune mémoire),
ce qui permet une vraie conversation sur plusieurs tours. Le bot garde un
historique séparé par conversation (une par utilisateur Telegram, par exemple).
"""

import logging

from persona_bot import llm
from persona_bot.config import LLM_BACKEND, MAX_HISTORY_TURNS
from persona_bot.logs import traced

log = logging.getLogger(__name__)


@traced
def format_citations(citations):
    if not citations:
        return "(Aucune citation proche trouvée : improvise dans son style.)"
    return "\n".join(f'- "{c["text"]}"' for c in citations)


class PersonaBot:
    @traced
    def __init__(self, persona, retriever=None, client=None, backend=LLM_BACKEND):
        # Les dépendances peuvent être injectées (c'est l'"injection de dépendances") : les
        # tests passent des faux objets pour ne charger ni le modèle d'embeddings ni appeler
        # la vraie API.
        self.persona = persona
        if retriever is None and persona.has_citations:
            # Import ici et pas en haut du fichier : retriever.py charge Chroma et PyTorch
            # (plusieurs secondes). Une persona sans citations n'en a pas besoin.
            from persona_bot.retriever import Retriever

            retriever = Retriever(persona)
        self.retriever = retriever  # None : pas de citations, donc pas de RAG
        self.backend = backend
        self.client = client or llm.create_client(backend)
        self.histories = {}  # identifiant de conversation -> liste de messages
        self.last_response = None  # réponse brute du modèle, pour les mesures de `persona ask`
        log.debug(
            "Persona %s, backend %s, modèle %s, %s",
            persona.slug,
            backend,
            llm.model_name(backend),
            "avec RAG" if self.retriever is not None else "sans RAG",
        )

    @traced
    def reset(self, conversation_id):
        removed = self.histories.pop(conversation_id, None)
        log.debug("Conversation %s effacée (%d messages)", conversation_id, len(removed or []))

    @traced
    def respond(self, user_message, conversation_id="terminal"):
        history = self.histories.setdefault(conversation_id, [])
        log.debug("Conversation %s : %d messages en historique", conversation_id, len(history))
        if self.retriever is not None:
            citations = self.retriever.search(user_message)
            content = (
                f"<citations>\n{format_citations(citations)}\n</citations>\n\n"
                f"Message de l'utilisateur : {user_message}"
            )
        else:
            # Sans citations, rien à ajouter : on n'envoie pas de bloc <citations> vide, qui
            # pousserait le modèle à se demander d'où il vient.
            citations, content = [], user_message
        messages = history + [{"role": "user", "content": content}]
        log.debug(
            "Appel à %s : %d messages, %d caractères de prompt système, message envoyé :\n%s",
            llm.model_name(self.backend),
            len(messages),
            len(self.persona.system_prompt),
            content,
        )

        response = llm.generate(self.client, self.backend, self.persona.system_prompt, messages)
        self.last_response = response

        log.debug(
            "Réponse de %s : stop_reason=%s, %d tokens lus (dont %d nouveaux), %d écrits",
            response.model,  # avec Claude, peut différer du modèle demandé si un modèle de repli a répondu
            response.stop_reason,
            llm.total_input_tokens(response.usage),
            response.usage.input_tokens,
            response.usage.output_tokens,
        )

        if response.stop_reason == "refusal":
            answer = self.persona.messages["refusal"]
        else:
            answer = "".join(b.text for b in response.content if b.type == "text")

        # On garde en historique le message SANS les citations, pour ne pas gonfler le contexte.
        history += [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": answer},
        ]
        # On coupe par paires (question + réponse) : l'historique commence ainsi toujours
        # par un message "user", comme l'exige l'API.
        overflow = max(0, len(history) - 2 * MAX_HISTORY_TURNS)
        if overflow:
            log.debug("Historique trop long : %d anciens messages oubliés", overflow)
        del history[:overflow]
        return answer, citations
