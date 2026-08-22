"""THE TERMINAL FRONTEND. All state work goes through `otaku2.backend`;
this package owns only the medium. Four rooms:

    chat/     the conversation surface: the loop (`chat.run`), the
              command bindings, the play-stream renderer, the screen
              ledger, and `Chat` — the terminal-side state
    prompt/   one submission in: the prompt session, the slash menus,
              multiline assembly, path completion
    screens/  the full-screen surfaces: the model picker, the story
              browser, the lore browser
    tty/      the medium itself, no chat knowledge: the escape
              vocabulary, theme, typesetter, turn rendering, row math,
              terminal queries, the pinned row, spinner, banner,
              clipboard

Inside: tty ← {prompt, screens} ← chat — the arrows never point the
other way.
"""
