"""
Point d'entrée en ligne de commande : `persona <commande>`.

    persona ingest              étape 1  : Markdown -> data/citations.json
    persona index               étape 2  : citations.json -> index Chroma
    persona search "question"   étape 3a : afficher les citations les plus proches
    persona eval                étape 3a : mesurer la qualité de la recherche
    persona ask "question"      étape 3b : une seule réponse, avec des mesures (comparer des modèles)
    persona chat                étape 3b : discuter avec le bot dans le terminal
    persona telegram            étape 4  : lancer le bot Telegram

Ajoute --debug (avant la commande) ou PERSONA_DEBUG=1 pour des logs détaillés :
    persona --debug search "J'ai peur d'échouer"

Le modèle de langage (Claude ou Ollama) se choisit avec LLM_BACKEND, voir llm.py.

Les imports lourds (Chroma, PyTorch, Anthropic) sont faits dans chaque commande :
`persona ingest` reste ainsi instantané.
"""

import argparse
import logging
import os
import re
import time

from persona_bot import config
from persona_bot.logs import setup_logging

log = logging.getLogger("persona_bot.cli")


def cmd_ingest(args):
    from persona_bot.ingest import run

    raw_count, citations = run(config.CITATIONS_MD, config.CITATIONS_JSON)
    print(f"🔍 {raw_count} citations brutes trouvées")
    print(f"🧹 {raw_count - len(citations)} doublons supprimés → {len(citations)} citations uniques")
    print(f"💾 {config.CITATIONS_JSON.relative_to(config.PROJECT_ROOT)}")


def cmd_index(args):
    from persona_bot.index import build_index

    print(f"🔄 Vectorisation avec {config.EMBEDDING_MODEL}...")
    count = build_index(config.CITATIONS_JSON)
    print(f"✅ {count} citations indexées dans {config.CHROMA_DB_PATH.relative_to(config.PROJECT_ROOT)}")


def cmd_search(args):
    from persona_bot.retriever import Retriever

    results = Retriever().search(args.query, k=args.k)
    if not results:
        print("(aucune citation au-dessus du seuil)")
    for r in results:
        print(f"{r['similarity']:.3f}  {r['text']}")


def cmd_eval(args):
    from persona_bot.evaluation import evaluate, load_eval_set, summarize
    from persona_bot.retriever import Retriever

    results = evaluate(Retriever(), load_eval_set(config.EVAL_SEARCH_JSON))
    for entry, rank in results:
        ok = rank is not None and rank <= config.RETRIEVE_K
        print(f"{'✅' if ok else '❌'} rang {rank or '>10':>3}  [{entry['level']}] {entry['question']}")
    print()
    for level, s in summarize([(e["level"], r) for e, r in results]).items():
        print(f"{level:9s}  hit@{config.RETRIEVE_K} = {s['hit']}/{s['total']}   MRR = {s['mrr']:.2f}")


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
    from persona_bot.bot import JCVDBot

    bot = JCVDBot()
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
    print(f"— citations utilisées : {len(citations)}")


def cmd_chat(args):
    from persona_bot.bot import JCVDBot

    bot = JCVDBot()
    print("🎬 JCVD Bot — tape 'exit' pour quitter\n")
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
        print(f"\nJCVD : {answer}\n")
        if citations:
            print("📚 Citations utilisées :")
            for c in citations:
                print(f"   [{c['similarity']:.2f}] {c['text'][:80]}...")
        print()
    print("\nJCVD : Au revoir... et reste aware !")


def cmd_telegram(args):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN manquant (voir .env.example)")

    from persona_bot.bot import JCVDBot
    from persona_bot.telegram_app import build_application, parse_allowed_users

    allowed_users = parse_allowed_users(os.environ.get("TELEGRAM_ALLOWED_USERS", ""))
    if not allowed_users:
        log.warning("TELEGRAM_ALLOWED_USERS est vide : le bot refusera tout le monde.")

    app = build_application(token, allowed_users, JCVDBot())
    log.info("Bot démarré, en attente de messages (Ctrl+C pour arrêter)")
    app.run_polling()


def main():
    parser = argparse.ArgumentParser(prog="persona", description="Bots à personas (RAG, Telegram)")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="logs détaillés : chaque fonction appelée et chaque action (aussi : PERSONA_DEBUG=1)",
    )
    commands = parser.add_subparsers(required=True, metavar="commande")

    commands.add_parser("ingest", help="étape 1 : Markdown -> citations.json").set_defaults(func=cmd_ingest)
    commands.add_parser("index", help="étape 2 : citations.json -> index Chroma").set_defaults(func=cmd_index)

    search = commands.add_parser("search", help="étape 3a : chercher les citations proches d'une question")
    search.add_argument("query", help="la question, entre guillemets")
    search.add_argument("-k", type=int, default=config.RETRIEVE_K, help="nombre de citations")
    search.set_defaults(func=cmd_search)

    commands.add_parser("eval", help="étape 3a : mesurer la qualité de la recherche").set_defaults(
        func=cmd_eval
    )

    ask = commands.add_parser("ask", help="étape 3b : une réponse avec des mesures (comparer des modèles)")
    ask.add_argument("question", help="la question, entre guillemets")
    ask.set_defaults(func=cmd_ask)

    commands.add_parser("chat", help="étape 3b : discuter dans le terminal").set_defaults(func=cmd_chat)
    commands.add_parser("telegram", help="étape 4 : lancer le bot Telegram").set_defaults(func=cmd_telegram)

    args = parser.parse_args()
    debug = args.debug or os.environ.get("PERSONA_DEBUG", "").lower() in {"1", "true", "yes"}
    setup_logging(debug)
    log.debug("Mode debug activé, commande : %s", args.func.__name__)
    args.func(args)
