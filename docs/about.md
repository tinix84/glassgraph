# About

## The author

Riccardo Tinivella. Based in Italy. Power electronics & EV powertrain research.

Day job: engineering work in the power electronics industry. This site, the [glassgraph repo](https://github.com/tinix84/glassgraph), and the wiki that motivated it are all **personal projects** — not corporate output, not affiliated with my employer.

## How to follow

- **GitHub** — [tinix84/glassgraph](https://github.com/tinix84/glassgraph) for the code, releases, and roadmap.
- **Issues** — [glassgraph issues](https://github.com/tinix84/glassgraph/issues) — feature requests, bug reports, design discussions welcome.
- **Substack** — the journey series in this docs site will be published as episodes there. Link to be added.

## Reproducing the work

Everything in the journey series is reproducible from public materials *except* the wiki content itself (which is private personal research). The tooling, the schema, the lint module, the entity linker, the comparison framework — all open-source under MIT in the glassgraph repo.

To replicate the architecture on your own corpus:

1. Set up a markdown vault with `/raw` (immutable clippings) and `/wiki` (curated layer).
2. Define a schema in `CLAUDE.md` (or equivalent for your LLM tool).
3. Use the LLM to ingest /raw into /wiki, structured per the schema.
4. Run the lint module periodically to catch drift.
5. Run glassgraph (Stage 1 + optional Stage 2) for deterministic entity linking.
6. Run graphify on cold material for discovery.
7. Run the comparison framework when you want to evaluate either tool.

The schema and lint will need adaptation to your domain; the tooling shouldn't.

## Acknowledgements

- **Anthropic** — Claude Code is the host LLM for the wiki-curation work. Honest plug: the project would not be feasible without it at the scale I'm operating.
- **The [graphify project](https://github.com/safishamsi/graphify)** — both as benchmark target and as inspiration for the god-nodes / surprising-connections / suggested-questions outputs that glassgraph's roadmap now aims to match.
- **BAAI** — for the open-source BGE-M3 multilingual embedding model.
- **Andrej Karpathy** — for the "second brain" framing applied to LLM-native software, which is what tipped me from "I should organize my reading" to "I should build a system."

## Contact

GitHub issues are the best channel. Substack comments work too. Direct contact via the email on my GitHub profile.

## License

The glassgraph tool and the comparison framework are MIT licensed. The journey writeups on this site are CC BY 4.0 — attribution required, commercial use allowed, modifications allowed.

The wiki content itself (not published here) is unpublished personal research and not licensed for redistribution.
