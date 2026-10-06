"""
Point d'entrée en ligne de commande : `persona <commande>`.

    persona list                         les personas disponibles
    persona ingest [slug]                étape 1  : citations.md -> data/<slug>/citations.json
    persona index [slug]                 étape 2  : citations.json -> index Chroma
    persona search <slug> "question"     étape 3a : afficher les citations les plus proches
    persona eval [slug]                  étape 3a : mesurer la qualité de la recherche
    persona ask <slug> "question"        étape 3b : une seule réponse, avec des mesures
    persona chat <slug>                  étape 3b : discuter avec une persona dans le terminal
    persona telegram                     étape 4  : lancer un bot Telegram par persona

<slug> est l'identifiant d'une persona, le nom de son dossier dans personas/ (par exemple
"jcvd"). Sans slug, ingest, index et eval traitent toutes les personas qui ont des citations.

Ajoute --debug (avant la commande) ou PERSONA_DEBUG=1 pour des logs détaillés :
    persona --debug search jcvd "J'ai peur d'échouer"

Le modèle de langage (Claude ou Ollama) se choisit avec LLM_BACKEND, voir llm.py.

Les imports lourds (Chroma, PyTorch, Anthropic) sont faits dans chaque commande :
`persona ingest` reste ainsi instantané.
"""

import argparse
import asyncio
import logging
import os
import re
import time

from persona_bot import config
from persona_bot.logs import setup_logging, traced
from persona_bot.personas import PersonaError, list_personas, load_persona

log = logging.getLogger("persona_bot.cli")


def persona_or_exit(slug):
    """Charge une persona ; en cas d'erreur, affiche un message clair au lieu d'une trace Python."""
    try:
        return load_persona(slug)
    except PersonaError as error:
        raise SystemExit(str(error)) from error


def personas_with_citations(slug):
    """
    Les personas concernées par les étapes 1 à 3a (ingest, index, eval) : celle demandée, ou
    toutes celles qui ont des citations. Ces étapes n'ont pas de sens sans citations.
    """
    if slug is None:
        return [p for p in map(persona_or_exit, list_personas()) if p.has_citations]
    persona = persona_or_exit(slug)
    if not persona.has_citations:
        raise SystemExit(
            f"La persona {slug!r} n'a pas de citations ({persona.citations_md} n'existe pas) : "
            "elle n'utilise pas le RAG, il n'y a rien à indexer ni à chercher."
        )
    return [persona]


def relative(path):
    return path.relative_to(config.PROJECT_ROOT)


def cmd_list(args):
    for slug in list_personas():
        persona = persona_or_exit(slug)
        sources = "avec citations (RAG)" if persona.has_citations else "sans citations"
        # On dit seulement si le token existe, sans jamais l'afficher.
        token = "token Telegram ✅" if os.environ.get(telegram_token_variable(slug)) else "pas de token"
        print(f"{slug:12s} {persona.name:20s} {sources:22s} {token}")


def cmd_ingest(args):
    from persona_bot.ingest import run

    for persona in personas_with_citations(args.slug):
        raw_count, citations = run(persona)
        print(f"[{persona.slug}] 🔍 {raw_count} citations brutes trouvées")
        print(
            f"[{persona.slug}] 🧹 {raw_count - len(citations)} doublons supprimés "
            f"→ {len(citations)} citations uniques"
        )
        print(f"[{persona.slug}] 💾 {relative(persona.citations_json)}")


def cmd_index(args):
    from persona_bot.index import build_index

    for persona in personas_with_citations(args.slug):
        print(f"[{persona.slug}] 🔄 Vectorisation avec {config.EMBEDDING_MODEL}...")
        count = build_index(persona)
        print(
            f"[{persona.slug}] ✅ {count} citations indexées dans {relative(config.CHROMA_DB_PATH)} "
            f"(collection {persona.collection_name})"
        )


def cmd_search(args):
    from persona_bot.retriever import Retriever

    [persona] = personas_with_citations(args.slug)
    results = Retriever(persona).search(args.query, k=args.k)
    if not results:
        print("(aucune citation au-dessus du seuil)")
    for r in results:
        print(f"{r['similarity']:.3f}  {r['text']}")


def cmd_eval(args):
    from persona_bot.evaluation import evaluate, load_eval_set, summarize
    from persona_bot.retriever import Retriever

    for persona in personas_with_citations(args.slug):
        if not persona.eval_json.exists():
            print(f"[{persona.slug}] pas de jeu d'évaluation ({relative(persona.eval_json)}) : ignorée\n")
            continue
        print(f"[{persona.slug}]")
        results = evaluate(Retriever(persona), load_eval_set(persona.eval_json))
        for entry, rank in results:
            ok = rank is not None and rank <= config.RETRIEVE_K
            print(f"{'✅' if ok else '❌'} rang {rank or '>10':>3}  [{entry['level']}] {entry['question']}")
        print()
        for level, s in summarize([(e["level"], r) for e, r in results]).items():
            print(f"{level:9s}  hit@{config.RETRIEVE_K} = {s['hit']}/{s['total']}   MRR = {s['mrr']:.2f}")
        print()


def answer_metrics(text):
    """
    Mesures simples pour vérifier qu'une réponse respecte le prompt système.
    Le découpage en phrases est approximatif : une fin de phrase est un ".", "!" ou "?"
    suivi d'une majuscule. Les "..." suivis d'une minuscule, fréquents chez JCVD, ne coupent pas.
    """
    sentences = [s for s in re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Ý])", text.strip()) if s]
    return {
        "mots": len(text.split()),
        "phrases": len(sentences),
        "finit par une question": text.rstrip().endswith("?"),
    }


def cmd_ask(args):
    from persona_bot import llm
    from persona_bot.bot import PersonaBot

    bot = PersonaBot(persona_or_exit(args.slug))
    start = time.perf_counter()
    answer, citations = bot.respond(args.question)
    duration = time.perf_counter() - start

    print(f"{answer}\n")
    print(f"— modèle : {bot.last_response.model} ({bot.backend}, demandé : {llm.model_name(bot.backend)})")
    for name, value in answer_metrics(answer).items():
        print(f"— {name} : {'oui' if value is True else 'non' if value is False else value}")
    print(f"— durée : {duration:.1f} s (recherche des citations comprise)")
    usage = bot.last_response.usage
    print(
        f"— tokens : {llm.total_input_tokens(usage)} lus (dont {usage.input_tokens} nouveaux, "
        f"le reste venant du cache), {usage.output_tokens} écrits"
    )
    if bot.retriever is None:
        print("— citations utilisées : aucune (persona sans citations)")
    else:
        print(f"— citations utilisées : {len(citations)}")


def cmd_chat(args):
    from persona_bot.bot import PersonaBot

    persona = persona_or_exit(args.slug)
    bot = PersonaBot(persona)
    print(f"🎬 {persona.name} — tape 'exit' pour quitter\n")
    while True:
        try:
            user_input = input("Toi : ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.lower() in {"exit", "quit"}:
            break
        if not user_input:
            continue

        answer, citations = bot.respond(user_input)
        print(f"\n{persona.name} : {answer}\n")
        if citations:
            print("📚 Citations utilisées :")
            for c in citations:
                print(f"   [{c['similarity']:.2f}] {c['text'][:80]}...")
        print()
    print(f"\n{persona.name} : {persona.messages['farewell']}")


@traced
def telegram_token_variable(slug):
    """Nom de la variable d'environnement qui contient le token du bot de cette persona."""
    return f"TELEGRAM_TOKEN_{slug.upper()}"


# Pas de @traced : la fonction renvoie des tokens, qui finiraient dans les logs.
def telegram_tokens(slugs, environ):
    """
    Associe chaque persona à son token Telegram : [(slug, token), ...].

    Une persona sans token est simplement ignorée : tu peux préparer une persona et l'essayer
    dans le terminal avant de lui créer un bot. Deux personas ne peuvent pas partager un token :
    Telegram n'autorise qu'un programme à la fois à lire les messages d'un bot.
    """
    pairs = []
    for slug in slugs:
        token = environ.get(telegram_token_variable(slug), "").strip()
        if token:
            pairs.append((slug, token))
        else:
            log.info("Persona %s : pas de %s, pas de bot Telegram", slug, telegram_token_variable(slug))

    if not pairs:
        if environ.get("TELEGRAM_BOT_TOKEN"):
            # Ancienne configuration (une seule persona, JCVD), d'avant le passage aux personas.
            raise SystemExit(
                "TELEGRAM_BOT_TOKEN n'est plus lu : il y a maintenant un token par persona. "
                "Renomme la variable en TELEGRAM_TOKEN_JCVD dans .env (voir .env.example)."
            )
        variables = ", ".join(telegram_token_variable(s) for s in slugs)
        raise SystemExit(f"Aucun token Telegram trouvé ({variables}) : voir .env.example")

    tokens = [token for _, token in pairs]
    if len(set(tokens)) != len(tokens):
        raise SystemExit("Deux personas ont le même token Telegram : il faut un bot BotFather par persona.")
    return pairs


def cmd_telegram(args):
    from persona_bot.bot import PersonaBot
    from persona_bot.telegram_app import build_application, parse_allowed_users, run_all

    allowed_users = parse_allowed_users(os.environ.get("TELEGRAM_ALLOWED_USERS", ""))
    if not allowed_users:
        log.warning("TELEGRAM_ALLOWED_USERS est vide : les bots refuseront tout le monde.")

    applications = [
        build_application(token, allowed_users, PersonaBot(persona_or_exit(slug)))
        for slug, token in telegram_tokens(list_personas(), os.environ)
    ]
    asyncio.run(run_all(applications))


def main():
    parser = argparse.ArgumentParser(prog="persona", description="Bots à personas (RAG, Telegram)")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="logs détaillés : chaque fonction appelée et chaque action (aussi : PERSONA_DEBUG=1)",
    )
    commands = parser.add_subparsers(required=True, metavar="commande")

    commands.add_parser("list", help="les personas disponibles").set_defaults(func=cmd_list)

    # nargs="?" : le slug est facultatif. Sans lui, toutes les personas avec citations.
    for name, func, help_text in (
        ("ingest", cmd_ingest, "étape 1 : citations.md -> citations.json"),
        ("index", cmd_index, "étape 2 : citations.json -> index Chroma"),
        ("eval", cmd_eval, "étape 3a : mesurer la qualité de la recherche"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("slug", nargs="?", help="la persona (par défaut : toutes celles avec citations)")
        command.set_defaults(func=func)

    search = commands.add_parser("search", help="étape 3a : chercher les citations proches d'une question")
    search.add_argument("slug", help="la persona, par exemple jcvd")
    search.add_argument("query", help="la question, entre guillemets")
    search.add_argument("-k", type=int, default=config.RETRIEVE_K, help="nombre de citations")
    search.set_defaults(func=cmd_search)

    ask = commands.add_parser("ask", help="étape 3b : une réponse avec des mesures (comparer des modèles)")
    ask.add_argument("slug", help="la persona, par exemple jcvd")
    ask.add_argument("question", help="la question, entre guillemets")
    ask.set_defaults(func=cmd_ask)

    chat = commands.add_parser("chat", help="étape 3b : discuter dans le terminal")
    chat.add_argument("slug", help="la persona, par exemple jcvd")
    chat.set_defaults(func=cmd_chat)

    commands.add_parser("telegram", help="étape 4 : lancer un bot Telegram par persona").set_defaults(
        func=cmd_telegram
    )

    args = parser.parse_args()
    debug = args.debug or os.environ.get("PERSONA_DEBUG", "").lower() in {"1", "true", "yes"}
    setup_logging(debug)
    log.debug("Mode debug activé, commande : %s", args.func.__name__)
    args.func(args)
