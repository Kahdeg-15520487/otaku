# otaku — context building

## Settings

The settings live in `~/.otaku/configs/config.toml` under `[context]`. All numbers in this
document are the default values from the config and can be changed.

The **verbatim threshold** the cases below compare the message count against is the sum of the
`head_messages` and `min_tail_messages` settings — 20 + 150 = 170 by default.

The window the cases build:

    ┌──────────────┬──────────────────┬──────────────────┬─────────────────────────┐
    │ HEAD         │ HISTORY RECAP    │ SCENE SUMMARIES  │ TAIL                    │
    │ messages     │ story-so-far     │ the covered      │ everything after the    │
    │ 1–20         │ (case 4 only)    │ scenes (case 3)  │ last summarized scene   │
    └──────────────┴──────────────────┴──────────────────┴─────────────────────────┘

The system message, when the story has one, is sent at the very beginning — before the head.

## Case 1 — a short story

Condition: the story holds fewer messages than the verbatim threshold.

Context structure: all messages are placed in the context verbatim.

## Case 2 — no scene summaries

Condition: the story holds at least the verbatim threshold of messages, but no scene
summary exists yet.

Context structure: all messages are placed in the context verbatim.

## Case 3 — scenes cover the middle

Condition: the story holds at least the verbatim threshold of messages, and extracted
scene summaries exist.

Goal: limit context growth while maintaining the prose style, by:

- keeping the head (the start of the story lays the foundation);
- keeping the tail (the characters' voices; the latest details matter most for continuing
  the story);
- replacing the middle with summaries, so the context stops growing and the replies do not
  degrade.

### Option A

Suppose we have 220 messages, and scenes span the following messages:

- scene 1: 1–25
- scene 2: 26–42
- scene 3: 43–64
- scene 4: 65–95

Subtracting 150 (the `min_tail_messages` setting) from the 220 messages gives 70. The scene
that covers message 70 is scene 4, which starts at message 65.

Context structure:

- messages 1–20 (the `head_messages` setting) are passed verbatim;
- scene summaries 1–3 (covering messages 1–64);
- messages 65–220 are passed verbatim.

### Option B

Same as before, but only two scenes are summarized (up to message 42).

Context structure:

- messages 1–20 (the `head_messages` setting) are passed verbatim;
- scene summaries 1–2 (covering messages 1–42);
- messages 43–220 are passed verbatim.

### Special case — character cards

Consider option A of case 3, but with a character card added as message 47. By the
lore-extraction rules, cards never get into scene summaries.

Context structure:

- messages 1–20 (the `head_messages` setting) are passed verbatim;
- scene summaries 1–2 (covering messages 1–42);
- message 47 verbatim (the character card);
- scene summary 3 (covering messages 43–64);
- messages 65–220 are passed verbatim.

## Case 4 — the context outgrows the model's window

Condition: the context built by the case 3 mechanism exceeds the model's context size or
the `max_context` setting, minus a buffer reserved for the response. The setting exists
because the effective context for roleplay falls far short of the advertised one — models
get diffuse and the style drifts past ~32–64k tokens.

Goal: let the play continue by degrading the summaries.

Suppose we have 728 messages and 12 scenes. We build the context as in case 3 and find
that it exceeds the model's window. We iterate over the scenes from 1 to N − 1, where N
is the number of scenes, and drop their summaries until the context fits — suppose that
happens after we drop scene 3. Then we replace scene 4's summary with its history — that
is, a summary over the scene summaries 1 to 4.

Context structure:

- messages 1–20 (the `head_messages` setting) are passed verbatim;
- scene 4's history (the story summary from the beginning through the end of scene 4);
- scene summaries 5–12;
- messages according to the case 3 rules.

If character cards sit among the messages of the dropped scenes 1–4, they are not dropped
with them — they float to the front, in front of the history.

## Case 5 — the context outgrows the model's window and degrading summaries doesn't help

Condition: the context still exceeds the case 4 limit even after case 4 has degraded the
recap to just the last scene's history.

Goal: let the play continue by degrading the tail.

Solution: reduce the `min_tail_messages` setting in steps of 50 (e.g., 150 → 100 → 50; 50 is
the floor) and rebuild the context by the case 3 and 4 rules at each step, until it fits.

## Case 6 — the context outgrows the model's window even after degrading the tail

Condition: the context still exceeds the limit even at case 5's floor.

Solution: the assembler refuses to compose the context. The only way this happens is a very
small context window, so the remedy is to increase it — and the refusal says so.
