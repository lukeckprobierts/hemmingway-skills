#!/usr/bin/env python3
"""Hemmingway: send text to the Hemmingway-1 model and get it back humanized, edited, proofread, shortened and so on.

    python3 hemmingway.py setup                      save your API key (from https://hemmingway.io/platform/)
    python3 hemmingway.py status                     check the key works
    python3 hemmingway.py humanize draft.md          the text comes back on stdout, notes on stderr
    python3 hemmingway.py email draft.txt --for "a client" --tone "warm, direct"
    cat notes.txt | python3 hemmingway.py expand --for "a LinkedIn post"

Run `python3 hemmingway.py --help` for every mode and option. Standard library only: nothing to install.

The prompts follow what works for Hemmingway-1: one user message and no system message (a system message replaces the
model's own), the task first, then the text, then who reads it and the rules, ending "Only use the facts I gave. Give
me only the ..., ready to send." Thinking stays on; the model writes the text itself, not options around it.
"""

import argparse
import concurrent.futures
import getpass
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("HEMMINGWAY_BASE_URL", "https://hemmingway.io/v1").rstrip("/")
MODEL = os.environ.get("HEMMINGWAY_MODEL", "hemmingway-27b")
PLATFORM = "https://hemmingway.io/platform/"
KEY_FILE = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "hemmingway", "api_key")

CHUNK_OVER = 900      # words: longer texts go in parts, so nothing is dropped and the parts run side by side
CHUNK_WORDS = 600     # words per part
AT_ONCE = 3           # parts sent at the same time (an account may run 8 requests at once)
RETRY_WAITS = [5, 15, 30, 45, 60]   # seconds between tries when the model is busy or restarting (it can take ~90 s)


class Stop(Exception):
    """An error with a plain message for the person; the script prints it and exits."""


# ------------------------------------------------------------------ the key

def find_key():
    key = os.environ.get("HEMMINGWAY_API_KEY", "").strip()
    if key:
        return key, "the HEMMINGWAY_API_KEY environment variable"
    try:
        with open(KEY_FILE) as f:
            key = f.read().strip()
        if key:
            return key, KEY_FILE
    except OSError:
        pass
    return "", ""


def need_key():
    key, _ = find_key()
    if not key:
        raise Stop(
            "No Hemmingway API key yet. To get one:\n"
            f"  1. Open {PLATFORM} and sign in (an email code or Google; signing in makes the account).\n"
            "  2. Billing: add credit, from $5. (On a Plus, Pro or Max plan you can skip this and pick\n"
            "     \"My plan\" in the next step instead: it costs nothing extra.)\n"
            "  3. API keys: Create key, then copy it. It starts with hemmingway_live_ and is shown only once.\n"
            "  4. Save it here:  python3 " + script_path() + " setup")
    return key


def script_path():
    return os.path.abspath(__file__)


def save_key(key):
    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key + "\n")
    os.chmod(KEY_FILE, 0o600)


# ------------------------------------------------------------------ talking to the API

def explain(status, body):
    """A plain sentence for an API error, with what to do about it. None: worth trying again."""
    try:
        err = json.loads(body).get("error", {})
    except (ValueError, AttributeError):
        err = {}
    code, msg = err.get("code", ""), err.get("message", "") or body[:200]
    if status == 401:
        return ("The API key was not accepted (" + (code or "401") + "). Make a new key at " + PLATFORM
                + " (API keys) and save it with: python3 " + script_path() + " setup")
    if status == 402 and code == "no_plan":
        return "This key draws on a plan, and the account has no plan any more. Pick a plan, or make a key that draws on credit at " + PLATFORM
    if status == 402:
        return "The account is out of credit. Add credit on the Billing page at " + PLATFORM + " (from $5)."
    if status == 429 and code == "allowance":
        when = err.get("resets_at") or "later"
        return "The plan's allowance is used up for now. It starts again at " + str(when) + ". A key on credit has no such limit."
    if status == 413:
        return "The text is too big for one request (4 MB). Send it in smaller pieces."
    if status == 400:
        return "Hemmingway turned the request away: " + msg
    if status in (429, 500, 502, 503, 504):
        return None
    return f"Hemmingway answered {status}: {msg}"


def chat(prompt, effort="xhigh", temperature=0.7):
    """One request, streamed. Returns the reply's text. Retries while the model is busy or restarting."""
    key = need_key()
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "temperature": temperature,
        "repetition_penalty": 1.02,
        # the thinking level goes in chat_template_kwargs: the server reads it there (a top-level one can be ignored)
        "chat_template_kwargs": {"reasoning_effort": effort},
    }
    data = json.dumps(body).encode()
    last = ""
    for attempt in range(len(RETRY_WAITS) + 1):
        if attempt:
            wait = RETRY_WAITS[attempt - 1]
            print(f"hemmingway: {last} Trying again in {wait} s.", file=sys.stderr)
            time.sleep(wait)
        req = urllib.request.Request(BASE_URL + "/chat/completions", data=data, method="POST", headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "use-hemmingway-skill/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=900) as resp:
                text, finish = read_stream(resp)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            why = explain(e.code, raw)
            if why:
                raise Stop(why)
            last = f"The model is busy or restarting ({e.code})."
            continue
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = f"Could not reach {BASE_URL} ({getattr(e, 'reason', e)})."
            continue
        if finish == "error" or not text.strip():
            last = "The model stopped without writing anything."
            continue
        if finish == "length":
            print("hemmingway: the reply hit the length limit and may be cut short; send the text in smaller pieces.",
                  file=sys.stderr)
        return text
    raise Stop(last + " Hemmingway did not answer after several tries. Try again in a few minutes.")


def read_stream(resp):
    """The reply's text from the server-sent events. Thinking arrives separately and is dropped."""
    parts, finish = [], None
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue          # keep-alive comments and blank lines
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
        except ValueError:
            continue
        if chunk.get("error"):
            return "".join(parts), "error"
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                parts.append(delta["content"])
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
    return "".join(parts), finish


# ------------------------------------------------------------------ the prompts

# Each mode: the task, the rules, and what it gives back. The wording is the one Hemmingway's own tools use on
# hemmingway.io/tools/, where it was tuned on this model. {for}, {tone}, {keep}, {length} and {note} are filled from the
# options; a sentence that needs an option left empty is dropped whole, so the model never reads "Tone: .".
MODES = {
    "humanize": dict(
        task="Rewrite this text so it reads like a person wrote it, keeping everything it says.",
        context=["It will be read by: {for}.", "Tone: {tone}.", "Keep these exactly as they are: {keep}.",
                 "Target length: {length}."],
        rules="Use plain words and natural sentences, and say each stock phrase or buzzword the plain way a person "
              "would. Keep it about the same length or shorter unless I gave a target. Change the words, not the "
              "facts: keep every fact, name, number, link and tag, keep what has happened as having happened, and "
              "add no facts, reasons, feelings or opinions of your own. No clichés and no dashes.",
        gives="the rewritten text", ready="ready to use", chunk=True),
    "edit": dict(
        task="Edit this text so it is clearer and easier to follow, keeping everything it says.",
        context=["It will be read by: {for}.", "Tone: {tone}.", "Keep these exactly as they are: {keep}.",
                 "Target length: {length}."],
        rules="Open each paragraph with its main point, put the other sentences in an order that follows from it, join "
              "them so each leads to the next, and cut anything said twice. Keep every fact, name and number. About "
              "the same length or shorter unless I gave a target.",
        gives="the edited text", ready="ready to use", chunk=True),
    "proofread": dict(
        task="Correct the grammar, spelling and punctuation in this text.",
        context=["Use this spelling: {spelling}.", "Leave these as they are: {keep}."],
        rules="Fix only what is wrong. Keep my words, my sentence order and my tone, informal ones included, and do "
              "not rephrase a sentence that is already correct. Do not change any fact or name.",
        gives="the corrected text", ready="ready to use", chunk=True, temperature=0.3),
    "shorten": dict(
        task="Shorten this text without losing its point.",
        context=["Target length: {length}.", "These must stay in: {keep}.", "It will be read by: {for}."],
        rules="Cut repetition, warm-up openings, hedges and background the reader does not need in order to act. Keep "
              "the main point and every date, number, name and request. Keep my wording where it already works, and "
              "add nothing. If I gave no target, aim for about half the length.",
        gives="the shorter text", ready="ready to use", chunk=True),
    "simplify": dict(
        task="Rewrite this text in plain English, keeping everything it says.",
        context=["It is for: {for}.", "Keep these terms and explain each in a few words the first time: {keep}."],
        rules="Use short sentences and everyday words, and say who does what. Replace jargon with the ordinary word, or "
              "explain it once if there is no ordinary word. Keep every fact, number, date, condition and warning, and "
              "everything the reader has to do. Do not add advice or opinions.",
        gives="the plain version", ready="ready to read", chunk=True),
    "tone": dict(
        task="Rewrite this text in a different tone, keeping what it says. The tone I want: {tone}.",
        context=["It is to: {for}.", "Keep these exactly as they are: {keep}."],
        rules="Change the word choice, the sentence length, the greeting and the sign-off to fit the tone. Keep every "
              "fact, request, date and number. Do not add reasons, apologies, deadlines, threats or promises that were "
              "not there. About the same length or shorter.",
        gives="the rewritten text", ready="ready to send", chunk=True, needs="tone"),
    "email": dict(
        task="Rewrite this email so it is clear, polite and professional, keeping what it says.",
        context=["It is to: {for}.", "How it should come across: {tone}.", "Keep these exactly as they are: {keep}."],
        rules="Put the request or the main point in the first two lines, give dates plainly, and end with what happens "
              "next if the email says it. Add a greeting and a sign-off if they are missing, and put the greeting, the "
              "body and the sign-off each on their own lines. Where a detail is missing, like my name under the "
              "sign-off, put it in [brackets] where it goes. Keep every fact, request and deadline, and do not add "
              "apologies, reasons or promises that were not there. No \"I hope this email finds you well\".",
        gives="the email", ready="ready to send"),
    "paraphrase": dict(
        task="Paraphrase this passage in different words and a different sentence structure, keeping exactly what it says.",
        context=["I will use it in: {for}.", "It should sound: {tone}."],
        rules="Change the wording and the order inside the sentences, not the meaning. Keep names, numbers and "
              "technical terms as they are. Add nothing and leave nothing out. About the same length.",
        gives="the paraphrase", ready="ready to use", chunk=True),
    "expand": dict(
        task="Turn these notes into full sentences. They are my notes to you, not the finished text: never hand them "
             "back as they are, and never just tidy them up.",
        context=["They should become: {for}.", "Tone: {tone}.", "Target length: {length}."],
        rules="Write every point in the notes as a complete, plain sentence, in an order that reads naturally, with "
              "the joining words that notes leave out. Do not add facts, examples, reasons, numbers, feelings or "
              "opinions that are not in the notes, and do not pad it to make it longer. Where a note is unclear, stay "
              "close to how I wrote it. Where a detail is missing, put it in [brackets] where it goes rather than "
              "making it up.",
        gives="the text", ready="ready to send"),
    "reply": dict(
        task="Write my reply to this message.",
        context=["My note for this reply: {note}. It is a note to you, not the message: never send it as it is, and "
                 "never just tidy it up.", "The person I am replying to is: {for}.", "Tone: {tone}."],
        rules="Answer their whole message the way a person would, even when my note is only a word or two, and match "
              "how they wrote: a short chat gets a short reply, an email gets an email with the greeting, the body and "
              "the sign-off each on their own lines. Where a detail is missing, put it in [brackets] where it goes "
              "rather than making it up or asking me.",
        gives="the reply", ready="ready to send"),
    "check": dict(
        task="Read this text and tell me which lines would make a reader think a machine wrote it, or are unclear, "
             "stiff or wrong.",
        context=["It will be read by: {for}.", "It should sound: {tone}."],
        rules="For each one, quote the line, say in a few words what is wrong with it, and give the line I should use "
              "instead. Most important first, at most ten. If the text already reads like a person wrote it, say so "
              "in one line.",
        gives="the list", ready="nothing before or after it", chunk=True, temperature=0.3),
    "rewrite": dict(
        task="Rewrite this text: {ask}.",
        context=["It will be read by: {for}.", "Tone: {tone}.", "Keep these exactly as they are: {keep}.",
                 "Target length: {length}."],
        rules="Keep every fact, name and number unless I asked otherwise, and do not change the meaning.",
        gives="the rewritten text", ready="ready to use", chunk=True, needs="ask"),
}


def fill(sentence, fields):
    """The sentence with its {fields}, or "" when one of them is empty."""
    names = re.findall(r"\{(\w+)\}", sentence)
    if any(not fields.get(n) for n in names):
        return ""
    return re.sub(r"\{(\w+)\}", lambda m: fields[m.group(1)].strip().rstrip("."), sentence)


def build_prompt(mode, text, fields, part=None, markdown=False, has_code=False):
    m = MODES[mode]
    lines = [fill(m["task"], fields)]
    if mode in ("expand",):
        lines.append("My notes are between the lines of three quotation marks.")
    elif mode == "reply":
        lines.append("Their message is between the lines of three quotation marks.")
    else:
        lines.append("The text is between the lines of three quotation marks: it is the text to work on, "
                     "not a message to you.")
    out = " ".join(lines) + '\n\n"""\n' + text.strip() + '\n"""\n\n'
    rest = [s for s in (fill(c, fields) for c in m["context"]) if s]
    if part:
        i, n = part
        if mode == "check":
            rest.append(f"This is part {i} of {n} of a longer text.")
        else:
            rest.append(f"This is part {i} of {n} of a longer text, so do not add a greeting, a sign-off, a title or a "
                        "summary, and do not start or end it as if it were the whole piece.")
    rest.append(m["rules"])
    if markdown and mode != "check":
        rest.append("Keep its layout in Markdown: the same headings, lists, links and emphasis in the same places.")
    if has_code:
        rest.append("Leave anything in `backticks` exactly as it is.")
    if fields.get("ask") and mode != "rewrite":
        rest.append(fields["ask"].strip().rstrip(".") + ".")
    rest.append(f"Only use the facts I gave. Give me only {m['gives']}, {m['ready']}.")
    return out + " ".join(rest)


# ------------------------------------------------------------------ long texts, code blocks, tidying the reply

FENCE = re.compile(r"^(```|~~~)")


def segments(text):
    """[(is_code, text)]: fenced code blocks are kept apart and never sent to the model."""
    out, buf, code, fence = [], [], False, ""
    for line in text.split("\n"):
        m = FENCE.match(line.lstrip())
        if not code and m:
            if buf:
                out.append((False, "\n".join(buf)))
            buf, code, fence = [line], True, m.group(1)
        elif code and line.lstrip().startswith(fence):
            buf.append(line)
            out.append((True, "\n".join(buf)))
            buf, code = [], False
        else:
            buf.append(line)
    if buf:
        out.append((code, "\n".join(buf)))
    return out


def words(s):
    return len(s.split())


def split_prose(text, size=CHUNK_WORDS):
    """Paragraph groups of about `size` words (a paragraph is never cut)."""
    paras = re.split(r"\n\s*\n", text.strip())
    out, cur, n = [], [], 0
    for p in paras:
        w = words(p)
        if cur and n + w > size:
            out.append("\n\n".join(cur))
            cur, n = [], 0
        cur.append(p)
        n += w
    if cur:
        out.append("\n\n".join(cur))
    return out


LEAD_IN = re.compile(r"^(here(?:'s| is| are)\b[^\n]*|sure[,!.][^\n]*|okay[,!.][^\n]*|certainly[,!.][^\n]*):\s*\n", re.I)


def tidy(reply, original):
    """Strips what the model sometimes puts around the text: blank lines, a lead-in line, our quotation-mark lines."""
    s = reply.strip()
    s = LEAD_IN.sub("", s, count=1).strip()
    if s.startswith('"""') and s.endswith('"""') and len(s) > 6:
        s = s[3:-3].strip()
    s = re.sub(r'^"""\s*\n|\n\s*"""$', "", s).strip()
    if len(s) > 2 and s[0] == s[-1] == '"' and '"' not in s[1:-1] and not original.strip().startswith('"'):
        s = s[1:-1].strip()
    return s


# ------------------------------------------------------------------ the checks after

NUM = re.compile(r"(?<![\w.])\$?\d[\d,.:/]*\s?(?:%|am|pm|k|m|bn)?(?![\w])", re.I)
URL = re.compile(r"https?://[^\s)>\]\"']+|www\.[^\s)>\]\"']+")
MAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
TICK = re.compile(r"`[^`\n]+`")
TELLS = [
    (re.compile(r"—|–"), "a long dash"),
    (re.compile(r"hope (this|you|the) [^.\n]{0,25}finds you well", re.I), '"hope this finds you well"'),
    (re.compile(r"\b(delve|delving|tapestry|testament to|seamless(ly)?|leverag(e|ing)|navigat(e|ing) the)\b", re.I),
     "stock AI words"),
    (re.compile(r"in today's (fast-paced|digital|ever)", re.I), '"in today\'s fast-paced..."'),
    (re.compile(r"\bit'?s (important|worth) (to note|noting)\b", re.I), '"it\'s worth noting"'),
    (re.compile(r"\bI wanted to reach out\b", re.I), '"I wanted to reach out"'),
]


NUMBER_WORDS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen twenty".split())}
NUMBER_WORD = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", re.I)


def facts(s):
    found = set()
    for rx in (URL, MAIL, TICK):
        found.update(x.rstrip(".,;:!?") for x in rx.findall(s))
    s = NUMBER_WORD.sub(lambda m: NUMBER_WORDS[m.group(1).lower()], s)   # "four years" and "4 years" are the same fact
    for x in NUM.findall(s):
        x = x.strip().rstrip(".,:/").lower().replace(" ", "")
        if re.search(r"\d", x):
            found.add(x)
    return found


def notes(mode, original, result):
    """Things for the caller to look at: facts that went missing or appeared, and AI habits left in the text."""
    out = []
    if mode not in ("check", "reply"):
        before, after = facts(original), facts(result)
        gone = sorted(before - after) if mode not in ("shorten", "expand") else []
        new = sorted(after - before)
        if gone:
            out.append("in the original but not in the result (check nothing was lost): " + ", ".join(gone[:15]))
        if new:
            out.append("in the result but not in the original (check nothing was made up): " + ", ".join(new[:15]))
    if mode != "check":
        left = [label for rx, label in TELLS if rx.search(result) and not rx.search(original if mode == "proofread" else "")]
        if left:
            out.append("still in the result: " + ", ".join(left))
    return out


# ------------------------------------------------------------------ running a mode

def run(mode, text, fields, effort):
    m = MODES[mode]
    markdown = bool(re.search(r"^\s{0,3}(#{1,6} |[-*+] |\d+[.)] |> )|\[[^\]]+\]\([^)]+\)", text, re.M))
    temperature = m.get("temperature", 0.7)
    segs = segments(text) if m.get("chunk") else [(False, text)]
    prose_words = sum(words(t) for code, t in segs if not code)
    jobs = []   # (segment index, part text)
    if m.get("chunk") and prose_words > CHUNK_OVER:
        for i, (code, t) in enumerate(segs):
            if not code and t.strip():
                for piece in split_prose(t):
                    jobs.append((i, piece))
    else:
        for i, (code, t) in enumerate(segs):
            if not code and t.strip():
                jobs.append((i, t))
    if not jobs:
        raise Stop("There is no text to work on (only code blocks, or nothing at all).")
    n = len(jobs)
    if n > 1:
        print(f"hemmingway: {prose_words} words, sent in {n} parts, {min(n, AT_ONCE)} at a time.", file=sys.stderr)

    def one(k):
        _, piece = jobs[k]
        has_code = bool(TICK.search(piece))
        prompt = build_prompt(mode, piece, fields, part=(k + 1, n) if n > 1 else None, markdown=markdown,
                              has_code=has_code)
        return tidy(chat(prompt, effort=effort, temperature=temperature), piece)

    with concurrent.futures.ThreadPoolExecutor(max_workers=AT_ONCE) as pool:
        results = list(pool.map(one, range(n)))

    if mode == "check":
        if n == 1:
            return results[0], []
        return "\n\n".join(f"Part {k + 1}:\n{r}" for k, r in enumerate(results)), []

    # put the parts back, code blocks where they were
    by_seg = {}
    for (i, _), r in zip(jobs, results):
        by_seg.setdefault(i, []).append(r)
    out = []
    for i, (code, t) in enumerate(segs):
        if code:
            out.append(t.strip("\n"))
        elif i in by_seg:
            out.append("\n\n".join(by_seg[i]))
    result = "\n\n".join(x for x in out if x.strip())
    prose_in = "\n\n".join(t for code, t in segs if not code)
    prose_out = "\n\n".join(results)
    return result, notes(mode, prose_in, prose_out)


# ------------------------------------------------------------------ commands

def cmd_setup(args):
    key = (args.key or "").strip()
    if not key and not sys.stdin.isatty():
        key = sys.stdin.read().strip()
    if not key:
        print(f"Paste your Hemmingway API key (from {PLATFORM}, API keys). It stays hidden as you paste:")
        key = getpass.getpass("Key: ").strip()
    if not key.startswith("hemmingway_live_"):
        raise Stop("That doesn't look like a Hemmingway key: keys start with hemmingway_live_. Make one at "
                   + PLATFORM + " (API keys, Create key).")
    os.environ["HEMMINGWAY_API_KEY"] = key
    print("Checking the key with one tiny request...", file=sys.stderr)
    reply = chat("Reply with the single word: ready", effort="low", temperature=0)
    save_key(key)
    print(f"Saved to {KEY_FILE} (only you can read it). The key works: Hemmingway said {reply.strip()[:40]!r}.")


def cmd_status(_args):
    key, where = find_key()
    if not key:
        need_key()
    print(f"Key: {key[:20]}... from {where}", file=sys.stderr)
    reply = chat("Reply with the single word: ready", effort="low", temperature=0)
    print(f"Hemmingway is reachable and the key works (it said {reply.strip()[:40]!r}).")


def read_input(args):
    if args.text is not None:
        return args.text
    if args.file and args.file != "-":
        try:
            with open(args.file, encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            raise Stop(f"Could not read {args.file}: {e.strerror}.")
    if sys.stdin.isatty():
        raise Stop("Give the text as a file path, with --text \"...\", or on stdin (cat file | ...).")
    return sys.stdin.read()


def cmd_mode(args):
    mode = args.command
    text = read_input(args)
    if not text.strip():
        raise Stop("The text is empty.")
    fields = {"for": args.for_, "tone": args.tone, "keep": args.keep, "length": args.length, "ask": args.ask,
              "note": args.note, "spelling": args.spelling}
    fields = {k: (v or "") for k, v in fields.items()}
    need = MODES[mode].get("needs")
    if need and not fields.get(need):
        raise Stop(f"The {mode} mode needs --{need} (" + {"tone": 'for example --tone "warm and casual"',
                                                          "ask": 'for example --ask "make it sound more confident"'}[need] + ").")
    result, found = run(mode, text, fields, "low" if args.fast else "xhigh")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(result + "\n")
        print(f"hemmingway: written to {args.out}", file=sys.stderr)
    else:
        print(result)
    if found and not args.quiet:
        for line in found:
            print("hemmingway note: " + line, file=sys.stderr)


HELP = {
    "humanize": "make text read like a person wrote it (the default choice)",
    "edit": "clearer and easier to follow, same content",
    "proofread": "fix grammar, spelling and punctuation only",
    "shorten": "cut it down without losing the point (--length)",
    "simplify": "plain English for a general reader",
    "tone": "same content, different tone (needs --tone)",
    "email": "a clear, polite, professional email",
    "paraphrase": "same meaning, different words",
    "expand": "notes into full sentences (--for says what they become)",
    "reply": "write a reply to the message given (--note says what to answer)",
    "check": "list the lines that sound like AI or don't work, with fixes",
    "rewrite": "any rewrite you describe (needs --ask)",
}


def main():
    p = argparse.ArgumentParser(prog="hemmingway.py", description="Humanize, edit, proofread or rewrite text with "
                                "Hemmingway-1 (hemmingway.io). The text comes back on stdout; notes go to stderr.")
    sub = p.add_subparsers(dest="command", metavar="command")
    s = sub.add_parser("setup", help="save your API key and check it works")
    s.add_argument("key", nargs="?", help="the key (or paste it when asked, or pipe it in)")
    sub.add_parser("status", help="check the saved key and that Hemmingway answers")
    for name, h in HELP.items():
        m = sub.add_parser(name, help=h, description=h)
        m.add_argument("file", nargs="?", help="a file with the text, or - for stdin (the default)")
        m.add_argument("--text", help="the text itself, instead of a file")
        m.add_argument("--for", dest="for_", metavar="WHO", help="who reads it (\"a client\", \"my team\"); for "
                       "expand, what it should become (\"a LinkedIn post\"); for reply, who they are")
        m.add_argument("--tone", help="how it should sound (\"warm, direct\")")
        m.add_argument("--keep", help="words, names or terms that must stay exactly as they are, comma-separated")
        m.add_argument("--length", help="target length (\"under 100 words\", \"two sentences\")")
        m.add_argument("--note", help="for reply: what to say back, in a few words")
        m.add_argument("--spelling", help="for proofread: \"US English\" or \"UK English\"")
        m.add_argument("--ask", help="anything else, in plain words (for rewrite: what to change)")
        m.add_argument("--fast", action="store_true", help="think less: quicker, a little less careful")
        m.add_argument("--out", help="write the result to this file instead of stdout")
        m.add_argument("--quiet", action="store_true", help="leave out the notes on stderr")
    args = p.parse_args()
    if not args.command:
        p.print_help()
        return 2
    try:
        if args.command == "setup":
            cmd_setup(args)
        elif args.command == "status":
            cmd_status(args)
        else:
            cmd_mode(args)
    except Stop as e:
        print("hemmingway: " + str(e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
