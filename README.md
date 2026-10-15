# use-hemmingway

A skill for AI agents. Your agent hands text to [Hemmingway-1](https://hemmingway.io/model/), the model built to write
the way a person writes, and gets back only the finished text: humanized, edited, proofread, shortened, re-toned, or
checked for lines that sound like AI.

Works with Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot, OpenCode and any agent that reads `SKILL.md`
skills. Needs Python 3 and a Hemmingway API key; the skill walks you through getting one.

## Install

**Claude Code**

```
/plugin marketplace add lukeckprobierts/hemmingway-skills
/plugin install use-hemmingway@hemmingway
```

**Any other agent**

```bash
npx skills add lukeckprobierts/hemmingway-skills
```

**By hand**: download `use-hemmingway.zip` from [Releases](https://github.com/lukeckprobierts/hemmingway-skills/releases)
and unzip it into your agent's skills folder (`~/.claude/skills/` for Claude Code, `~/.agents/skills/` for Codex,
Gemini CLI and Copilot CLI).

Then ask your agent something like "make this sound less like AI" or "use Hemmingway to tidy this email".

## The API key

The first time, your agent will help you make one:

1. Sign in at [hemmingway.io/platform](https://hemmingway.io/platform/) with an email code or Google.
2. Billing: add credit, from $5. A short rewrite costs about $0.002, a page about a cent. On a Hemmingway Plus, Pro or
   Max plan you can skip this and draw on the plan instead.
3. API keys: create a key and copy it.
4. Save it: `python3 skills/use-hemmingway/scripts/hemmingway.py setup`

Nothing sent or written through the API is logged.

## What it does

| Mode | For |
|------|-----|
| `humanize` | Make text read like a person wrote it |
| `edit` | Clearer and easier to follow, same content |
| `proofread` | Grammar, spelling and punctuation only |
| `shorten` | Cut it down, keeping the point and every fact |
| `simplify` | Plain English for a general reader |
| `tone` | Same content, different tone |
| `email` | A clear, polite, professional email |
| `paraphrase` | Same meaning, different words |
| `expand` | Notes or bullet points into full sentences |
| `reply` | A reply to a message, from a few words on what to say |
| `check` | The lines that sound like AI or don't work, each with a better line |
| `rewrite` | Any other rewrite you describe |

Long texts are split and sent side by side. Markdown, links and code blocks come back untouched. After each run the
script flags any number, date or link that went missing or appeared.

It works without an agent too:

```bash
python3 skills/use-hemmingway/scripts/hemmingway.py humanize draft.md --for "readers of our blog"
python3 skills/use-hemmingway/scripts/hemmingway.py --help
```

To call the API from your own code, see [api.md](skills/use-hemmingway/api.md) and the
[API docs](https://hemmingway.io/docs/).

## Licence

The skill is MIT. Hemmingway-1's weights are separate: open weights under CC BY-NC 4.0 on
[Hugging Face](https://huggingface.co/Altworld/Hemmingway-1).
