---
name: use-hemmingway
description: Use when text needs to sound like a person wrote it, or needs rewriting, editing, proofreading, shortening, simplifying, a different tone, a polished email, a paraphrase, notes turned into prose, a reply drafted, or a check for lines that read as AI-written. Also use whenever the user mentions Hemmingway, hemmingway.io or Hemmingway-1.
---

# Use Hemmingway

Hemmingway-1 is a model built to write the way a person writes (hemmingway.io). This skill sends text to it through
its API and hands back the finished text: no commentary around it, ready to use.

Everything goes through one script, `scripts/hemmingway.py` in this skill's folder. It needs only Python 3, nothing to
install. The commands below are written from this skill's folder; from anywhere else, give the script's full path.
On Windows use `python` or `py` where this says `python3`.

## First time: the API key

Run `python3 scripts/hemmingway.py status`. If it says the key works, skip this section.

If there is no key, walk the user through this. Say it in these plain steps, one at a time if they are new to it:

1. Open https://hemmingway.io/platform/ and sign in with an email code or Google. Signing in makes the account.
2. **Billing**, then **Add credit**: any amount from $5. A short rewrite costs about $0.002, a page about a cent.
   If they pay for a Hemmingway plan (Plus, Pro or Max), they can skip this and choose **My plan** in step 3: it
   costs nothing extra and uses the same allowance as the app.
3. **API keys**, then **Create key**: any name, **Draws on: Credit** (or My plan), **Create**, then **Copy**. The
   key starts with `hemmingway_live_` and is shown only once.
4. Save it. Best: the user runs `python3 <this skill's folder>/scripts/hemmingway.py setup` in their own terminal
   and pastes the key when asked. If they paste the key to you instead, save it without echoing it:
   `printf '%s' 'hemmingway_live_...' | python3 scripts/hemmingway.py setup`

`setup` checks the key with one tiny request and saves it to `~/.config/hemmingway/api_key` (only the user can read
it). The `HEMMINGWAY_API_KEY` environment variable works too and wins over the file. Never put the key in a project
file, a commit or a message.

## Using it

```bash
python3 scripts/hemmingway.py humanize draft.md --for "readers of our blog"
python3 scripts/hemmingway.py email draft.txt --for "a client who owes us money" --tone "firm but friendly"
python3 scripts/hemmingway.py reply their-message.txt --note "yes to Saturday, Jess can't come"
cat notes.txt | python3 scripts/hemmingway.py expand --for "a short LinkedIn post"
```

Write the text to a file (or pipe it in) rather than quoting it on the command line. The result comes out on stdout,
or into a file with `--out result.md`.

Pick the most specific mode: an email gets `email`, a message to answer gets `reply`, bullet points get `expand`.
`humanize` is for everything else.

| Mode | For |
|------|-----|
| `humanize` | Make text read like a person wrote it. Posts, articles, docs, anything without its own mode. |
| `edit` | Clearer and easier to follow, same content. |
| `proofread` | Grammar, spelling and punctuation only. `--spelling "UK English"` |
| `shorten` | Cut it down, keeping the point and every fact. `--length "under 80 words"` |
| `simplify` | Plain English for a general reader. |
| `tone` | Same content, different tone. Needs `--tone`. |
| `email` | A clear, polite, professional email. |
| `paraphrase` | Same meaning, different words. |
| `expand` | Notes or bullet points into full sentences. `--for` says what they become. |
| `reply` | A reply to the message given. `--note` says what to answer, in a few words. |
| `check` | A list of the lines that sound like AI or don't work, each with a better line. Changes nothing. |
| `rewrite` | Any other rewrite. Needs `--ask "what to change"`. |

Options for every mode: `--for WHO` (who reads it), `--tone "how it should sound"`, `--keep "Brightline, #NewJob"`
(terms, names or slogans that must not change, comma-separated), `--length "target"`, `--ask "anything else, in plain
words"`, `--fast`. Use `--ask` sparingly: every extra instruction pulls the text back toward stiff.

**Always pass `--for`.** Who reads the text is the single thing that most improves the result. Use what you know
from the conversation ("the hiring manager at a bank", "my landlord", "developers reading our README"). Add `--tone`
when the user said how it should sound.

Long texts are split into parts and sent side by side. Markdown layout, links and `inline code` are kept, and fenced
code blocks are never sent: they come back exactly as they were.

Each request thinks first, so a short text takes about 10 to 20 seconds. `--fast` takes 2 to 5 seconds but is less
careful: it sometimes adds small details that weren't in the original. Use it only when the user wants speed.

## What comes back

- **stdout**: the text alone. Hand it to the user, or put it where it goes, as it is. Don't polish it again yourself:
  re-editing tends to put back the habits Hemmingway took out (long dashes, "seamless", tidy three-part lists).
- **`[brackets]`**: a detail Hemmingway didn't have, like `[Your name]` under an email. Fill it in from what you
  know, or ask the user. Never send text with brackets still in it.
- **stderr lines starting `hemmingway note:`**: a number, date, link or email address that went missing or appeared,
  or an AI habit left in. Look at each one. Fix it by hand, or run again with `--keep` naming what must stay.

## When something goes wrong

The script waits and tries again by itself when the model is busy or restarting (up to about 3 minutes). Anything
else it explains in one line, with what to do. The usual ones:

| Message | What to do |
|---------|-----------|
| No Hemmingway API key yet | The first-time steps above. |
| The API key was not accepted | The key was revoked or mistyped. Make a new one, run `setup` again. |
| The account is out of credit | Add credit on the Billing page at hemmingway.io/platform. |
| The plan's allowance is used up | A plan key waits until the time it gives; a credit key has no such limit. |
| did not answer after several tries | Hemmingway is down for now. Tell the user, try again later. |

Nothing sent or written through the API is logged. To call the API from your own code instead of the script, read
`api.md` in this folder: the endpoint, and how to prompt Hemmingway-1 so it writes well.
