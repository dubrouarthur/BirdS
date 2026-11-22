# Liste de corrections UI/UX (revue à six auditeurs, défauts sérieux vérifiés)

BIRD UI/UX IMPLEMENTATION BACKLOG (merged from the six audits, 62 findings become 46 items)

Screenshot root: UX = /tmp/claude-0/-home-user-BirdS/27eb98ec-b9ba-5cf1-a125-8008c93c0d55/scratchpad/ux. I checked that every screenshot cited below exists under it. A few files named in the findings were never saved, and the closest real capture is cited instead.

Duplicates merged:
- Empty state opening scrolled to the bottom (first-run and layout audits).
- The .keys class collision (composer and a11y audits).
- The three display typefaces (first-run and a11y audits).
- The forced-dark welcome and the .w-deal box in dark mode.
- The photo menu clipping and the photo sheet's Escape/scrim problems.
- The two welcome a11y findings (close control and aria-labelledby).

Shared Playwright setup: `.venv/bin/python scripts/serve.py --demo --port N`, then chromium.launch(). Use devices['iPhone 14'] and devices['Pixel 7'] for phones and 1280x800 for desktop. Seed state with an addInitScript that sets localStorage bird.prefs.

==================== P0: broken or blocking, fix now ====================

P0-1 Welcome readable when the user picks Dark on a light OS (also fixes the "Le marché" box in dark)
- Change, in birds/web/static/app.css (the .welcome block, about lines 3634-3725):
  - Add tokens on .welcome: --w-muted, --w-surface, --w-line, --w-chip, --w-cta-bg, --w-cta-ink, --w-warn-bg, --w-warn-ink, --w-warn-line.
  - Use them in .w-lead/.w-ptext, .w-pillar, .w-tag, .w-ex/.w-picon, .btn-cta and .w-deal. The .w-deal colours (#f8ecc8 / #734700) are hard-coded today.
  - Override only the tokens, in both `@media (prefers-color-scheme: dark) :root:not([data-theme=light]) .welcome` and `:root[data-theme=dark] .welcome`. Dark warn values: #2a2410 / #f1d58a / #6b5a22.
  - Delete the component-level dark @media copy. Drop the dead selectors .w-stat, .w-scene and .w-note.
- Accept: colorScheme 'light' with prefs {theme:'dark', welcomed:false}. Check that #welcome-start has a background different from its text colour, with contrast of at least 4.5:1. Check that the .w-pillar title and the .w-lead text are each at least 4.5:1 against their own background. Repeat with colorScheme 'dark' and theme 'system'.
- Shots: UX/verify-first-run/desk-forceddark.png, UX/first-run/desk-forceddark-w1.png, UX/first-run/desk-forceddark-w2.png, UX/first-run/desk-dark-w2.png (.w-deal).

P0-2 The empty chat opens at the top
- Change: in app.js scrollToEnd() (about line 527), return early when the view is 'chat' and the conversation has no turns: `if (!(state.conv?.turns||[]).length){ stick=true; scroller().scrollTop=0; updateJump(); return; }`. This covers init (about 1549), openConv (170), new chat/Ctrl+K (1158/1172) and btn-jump.
- Accept: welcomed:true and no conversation, on iPhone 14, Pixel 7, 360x740 and 1280x800. Check #scroll.scrollTop === 0 and that #empty's getBoundingClientRect().top is at least 0. Repeat after Ctrl+K.
- Shots: UX/verify/desk-empty.png, UX/verify-first-run/iphone-empty.png, UX/verify-first-run/pixel-empty.png, UX/a11y-visual/31-360-light-empty.png. The target look is UX/first-run/iphone-empty-top.png.

P0-3 The first example must not open the prompt-injection approval scenario
- Change:
  - i18n.js:45 ex.email.prompt (FR and EN): a self-contained prompt, e.g. "Réponds à Camille : son offre nous convient, demande le délai de livraison et les conditions de paiement."
  - birds/web/backends.py: add a safe scripted answer that matches the new text.
  - Move the injection demo to a separately labelled entry "Voir comment Bird se protège", in About or as a secondary fifth example.
- Accept: click [data-example=email] in the welcome and in the empty state. Wait for the stream to finish. Check there is no [data-confirm-deny] and no step-flagged, and that an answer is rendered.
- Shots: UX/verify-first-run/desk-after-mail.png, UX/first-run/desk-after-example.png.

P0-4 A long answer ends at its start, not at the receipt
- Change, in app.js scrollToEnd(false) (paintSoon at about 913 and the finally block at about 1114):
  - Compute the anchor from the user turn: `el.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop`. Do not use offsetTop.
  - Set target = min(scrollHeight, anchor - 8).
  - When the target is reached, set a separate `pinned` flag that the scroll listener (about 1401) must not undo.
  - While pinned and the answer is still growing, show btn-jump labelled "Suite de la réponse". Revert to "Aller à la fin" once the stream is idle.
  - Keep scrollToEnd(true) for send and for jump clicks.
- Accept: iPhone 14, /api/chat routed to a long SSE answer (25 paragraphs). After the done event, the user turn's top is between 0 and 80 px from #scroll's top and #btn-jump is visible. A short answer still ends at the bottom.
- Shots: UX/reading/long-iphone-end.png, UX/verify/desk-long-end.png.

P0-5 Mobile drawer is modal and returns focus
- Change, in app.js setSidebar() (374-383) plus the Escape branch (1444) and the backdrop/close handlers (1380-1381):
  - Focus #btn-menu before setting `sidebar.inert = !open` when the sidebar holds focus.
  - When the viewport is 900px or narrower and the drawer is open, set inert on the content behind it: .main or its siblings, but not the controls that close the drawer.
  - Clear inert when matchMedia crosses 900px.
- Accept: 360x740. Open the drawer and press Tab 20 times; every activeElement stays inside #sidebar. Press Escape; activeElement.id === 'btn-menu'. Open the drawer, resize to 1280; .main.inert === false.
- Shots: UX/a11y-visual/33-360-light-drawer.png, UX/a11y-visual/33-iphone-light-drawer.png.

P0-6 Photo sheet: regression test, Escape and scrim
- Change:
  - Keep .photo-menu position:fixed (app.css about 2942). Better still, move it to the popover attribute or a <dialog> so it sits in the top layer.
  - In app.js bind() (about 1308-1321), handle keydown Escape on #photo-menu: hide it, set aria-expanded=false, focus #btn-photo, and stopPropagation so a streaming answer is not stopped.
  - Add a .backdrop scrim that only closes the sheet. An outside tap must not activate the element under it.
  - Arrow-key roving between the two menuitems.
- Accept: iPhone 14 and Pixel 7 with /api/health mocked to images:true. Tap #btn-photo, then #photo-pick, and expect a 'filechooser' event. Escape gives menu.hidden === true and focus on #btn-photo. Tapping where an example card sits under the scrim sends no /api/chat request.
- Shots: UX/composer-mobile/iPhone14-10-photomenu.png (before), UX/composer-mobile/P7-20-photomenu.png, UX/verify/Pixel7-3-after-outside.png.

P0-7 Focus is kept after removing an attachment
- Change: app.js renderAttachments() and attach.js removeImage. Give each card a stable data-att id. After replaceChildren, focus the "Retirer" button of the card now at the same index, else the previous card's, else #composer-input.
- Accept: add 2 images and 1 .txt, focus the first card's remove button and press Enter. activeElement is the remove button of the new first card. Remove all three; activeElement is #composer-input.
- Shot: UX/composer-mobile/iPhone14-13-mixed.png.

P0-8 No raw Python exceptions in error cards
- Change:
  - turns.js renderError: map code 'internal' and any unknown code to an i18n message ("Une erreur interne est survenue." / "Something went wrong on our side."). Put the raw text in a collapsed <details> "Détails techniques".
  - server.py worker() (591-596): send a generic message plus `detail: guard.redact(str(exc))[:400]`.
  - Mention "N étape(s) terminée(s) avant l'erreur" only when there are steps.
- Accept: fulfil /api/chat with {type:'error', code:'internal', message:"KeyError: 'choices'"}. The visible card text does not contain "KeyError". The <details> holds it while closed. "Réessayer" is present.
- Shots: UX/agent-feedback/desk-internal.png, UX/repro/internal.png.

P0-9 The dock hint fits on one line (.keys collision)
- Change: index.html dock-note `<span class="keys">` becomes `class="dock-keys"`. Update app.css:2525 to `.dock-note .dock-keys{display:none}`. Scope app.css:2399 to `#shortcuts-body .keys`. Put the " · " separator in `.dock-keys::before`.
- Accept: at 1280x800, .dock-note height is 30px or less and its innerText has no "\n". The shortcuts dialog still renders its grid.
- Shots: UX/verify/desktop-docknote.png, UX/composer-mobile/desktop-06-done.png, UX/a11y-visual/04-main-focus.png.

P0-10 Settings shows a full web-search description
- Change: server.py:214 tools_info(). When the search label is empty, use a full fallback sentence: "Cherche sur le web et cite ses sources" / "Searches the web and cites its sources". Keep the state 'on'.
- Accept: GET /api/health in demo; no tool fr/en string ends with ":" or ": ". The Réglages first tool row text does not end with ":".
- Shots: UX/a11y-visual/20-light-settings-tall.png, UX/a11y-visual/13-dark-settings.png.

P0-11 Table cells no longer split on escaped or code-span pipes, and no content is dropped
- Change:
  - markdown.js:100 splitRow becomes a character scanner. `\|` becomes a literal pipe. Pipes inside matching backtick spans do not split. Add a comment noting this deliberately deviates from GFM.
  - markdown.js:196-205: rejoin extra cells into the last cell with " | ".
  - Add unit tests: escaped pipe, code-span pipe, short row, long row.
- Accept: render `| a | b |\n|---|---|\n| x \\| y | \`c|d\` |`. The tbody tr has 2 tds, with texts "x | y" and "c|d".
- Shots: UX/verify/desk-table.png. The case was reproduced in the DOM; no dedicated screenshot exists.

P0-12 Footprint: stop making wrong honesty claims (brand-critical)
- Change, in views.js:
  - (a) comparison() (312) and splits() (282): average completion_tokens only. Exclude answers with tool_calls>0 from both groups. Require at least 2 per group, else show "pas assez de réponses comparables".
  - (b) Merge (a) with the save.lever.think line so the page gives one figure.
  - (c) In Répartition, the Réflexion row shows written tokens and the Outils row shows total tokens. Label each row's unit.
  - (d) savings() (about 395) and i18n.js:525: build the energy label from the entries. Use "mesuré" if all are measured, "borne haute" only if all are power_time, otherwise "estimé". Add "sur k réponses sur n". Make "à puissance maximale" in save.energy.scope conditional on power_time.
- Accept:
  - Demo: a tool turn with Réflexion on, plus 2 plain turns. The comparison ratio matches the lever ratio, about 2.4x not 10x, or the panel shows the "pas assez" text.
  - Seed a ledger of 5 nvidia_smi + 9 calibration entries. The text does not contain "borne haute" or "puissance maximale".
- Shots: UX/eco/desk-fp-2.png, UX/eco-verify/desk-energy.png, UX/eco/desk-energy-1.png.

==================== P1: biggest UX gains ====================

P1-1 Phone empty state is compact (follows P0-2)
- Change: index.html:79-89 and the .empty CSS.
  - Under 700px height: a 40px mark instead of the 132px lockup, a one-line title, and the candid line only.
  - Examples in a 2x2 grid of title-only chips under 520px wide. Hide .chip-prompt; the full prompt goes in title and aria-label.
- Accept: on iPhone 14, the title, the "Relisez ce qui compte" line and all 4 chips sit above the dock top (rect.bottom < .dock rect.top).
- Shots: UX/first-run/iphone-empty-top.png, UX/first-run/iphone-light-empty-full.png.

P1-2 English locale detection plus a language toggle in the welcome
- Change:
  - core.js:42: when no bird.prefs is stored, set lang = /^fr/i matches any navigator.languages entry ? 'fr' : 'en'.
  - Add an FR/EN toggle in .w-head that sets the pref, calls applyStrings() and openWelcome(), and keeps focus inside the dialog.
- Accept: locale 'en-US' gives html lang=en and an English welcome title. Locale 'fr-FR' gives fr. A stored lang:'fr' with locale en-US stays fr. Clicking the toggle changes the title, and the activeElement stays inside #welcome.
- Shots: UX/verify-first-run/desk-enlocale.png, UX/first-run/desk-en-w1.png.

P1-3 The welcome can be reopened and closed, and is accessible
- Change:
  - Add a "Revoir la présentation" / "See the introduction" button in views.js renderAbout that calls openWelcome(). Optionally add a sidebar-foot link.
  - Add a 44x44 close button in .w-head (aria-label "Fermer").
  - Make .w-actions sticky at the bottom on phones.
  - Set aria-labelledby to a real heading id (never ''). Drop the aria-label juggling (views.js:1065-1066).
- Accept:
  - After dismissing, About > the button gives #welcome.open === true.
  - Clicking the close button gives open === false.
  - On iPhone 14, #welcome-start is in the viewport without scrolling.
  - getAttribute('aria-labelledby') resolves to an existing element.
- Shots: UX/first-run/iphone-light-w2.png, UX/verify-first-run/iphone-welcome.png.

P1-4 The textarea respects the viewport, and the keyboard is handled
- Change:
  - app.js autosize() (541-545): height = min(scrollHeight, round((visualViewport?.height||857)*0.28), 240).
  - CSS: max-block-size: min(240px, 28dvh).
  - While the textarea is focused on narrow screens, hide .dock-note and collapse .att-note.
  - index.html viewport meta: add interactive-widget=resizes-content.
  - Set --vvh from visualViewport resize/scroll and use `.app{block-size:var(--vvh,100dvh)}`.
- Accept: iPhone 14 at 390x340, type 2,000 characters; #scroll.clientHeight ≥ 120. At 412x420 with 2 attachments, #scroll.clientHeight ≥ 80. The page contains `interactive-widget=resizes-content`.
- Shots: UX/composer-mobile/kb-02-long.png, UX/composer-mobile/P7-22-kb-tray.png, UX/verify/iP14-340-grow.png.

P1-5 Attachment errors are readable on phones
- Change:
  - app.css: inside @media (max-width:640px), .att-tray uses flex-wrap:wrap. Put error cards first, with `.att-card.is-error{flex-wrap:wrap;max-inline-size:100%} .st-err{flex-basis:100%}`.
  - Call announce() with the error.
  - In onFiles, compute the room left before the loop and show one coalesced toast ("2 images ignorées : 3 au plus par message."). toast() dedupes identical text.
- Accept:
  - Pixel 7: attach 4000x3000, 200x150 and .xlsx files. Every .att-card has rect.right ≤ innerWidth, and the error card's full text is visible.
  - With 2 images attached, add 3 more; exactly 1 .toast appears.
- Shots: UX/composer-mobile/P7-21-tray.png, UX/composer-mobile/iPhone14-13-mixed.png, UX/composer-mobile/iPhone14-14-many.png.

P1-6 Code blocks get a header with the language and a copy button, plus an overflow cue
- Change:
  - markdown.js:168: emit `<div class="code-head"><span>{escapeHtml(lang)}</span><button type="button" data-copy-code aria-label="Copier le code {lang}">`.
  - Add a delegated click handler on #conversation that copies pre>code.textContent.
  - Make sure the streaming block cache does not rebuild the button mid-copy.
  - CSS scroll-shadow on .md pre (app.css:1235): background local plus scroll shadows.
- Accept: render ```python with a long line. Exactly one [data-copy-code] appears. Clicking it puts the code-only text on the clipboard (grant clipboard-read). Computed background-image on the pre includes a gradient.
- Shots: UX/verify/desk-code.png, UX/reading/long-iphone-s1.png, UX/reading/long-deskdark-s1.png.

P1-7 Action row: fewer, clearer, bigger buttons
- Change: turns.js:870-935 renderActions.
  - Keep Copy, Regenerate, thumbs up, thumbs down and "Plus".
  - "Plus" is <button aria-haspopup="menu" aria-expanded> opening a menu that supports arrow keys and Escape and returns focus to the trigger. Its items carry text: "Copier en Markdown", "Exporter la réponse en Word (.docx)", "Télécharger la réponse (.md)".
  - Under @media (pointer:coarse), .actions-row buttons are at least 44x44 with gaps of 4px or more.
- Accept:
  - iPhone 14: the row has ≤5 direct buttons, each ≥44x44, and the row fits within 390px.
  - Plus, then ArrowDown, then Escape: focus returns to Plus.
- Shots: UX/reading/files-iphone-s3.png, UX/reading/files-iphone-s6.png.

P1-8 Regenerate can be undone
- Change: app.js regenerate (about 1150-1180).
  - Keep the replaced turn and show a toast with "Annuler" for 8 s.
  - Undo aborts state.abort, restores the old turn and calls saveConv(). Do not refund the ledger.
  - Later: turn.variants plus a "‹ 2/2 ›" switcher (aria-label "Réponse 2 sur 2"), capped and following the KEEP_FILE_B64 rules.
- Accept: after a docx turn, click [data-act=regenerate] then "Annuler". The old answer text and its file card are back, and they survive a reload.
- Shot: UX/reading/files-iphone-s3.png. The "iphone-regen-start" capture was not saved.

P1-9 Only the last answer shows the full receipt
- Change: turns.js:762 renderReceipt and app.css:1563.
  - Earlier turns get a one-line <button aria-expanded> chip with the leaf SVG (no emoji) that expands the receipt in place.
  - The latest turn keeps the full card.
- Accept: iPhone 14 after 4 turns. Earlier receipts are each ≤44px tall. Clicking a chip gives aria-expanded=true and shows "non mesurée".
- Shots: UX/reading/files-iphone-s1.png, UX/reading/files-iphone-s2.png, UX/eco/iphone-receipt.png.

P1-10 Wide tables and the sheet preview scroll visibly
- Change:
  - app.css:1259-1275: `.md table{inline-size:max-content;min-inline-size:100%} th,td{min-inline-size:9ch}`. Do not use max-width on td.
  - Add background-attachment:local scroll shadows on .table-wrap and on the turns.js:432 filePreview wrapper, with transparent cell backgrounds.
- Accept:
  - iPhone 14, 5-column table: every row ≤60px tall, and the wrap's scrollWidth > clientWidth with a gradient background-image.
  - "COÛT UNITAIRE" is not cut inside a word: the header's scrollWidth ≤ its clientWidth.
- Shots: UX/reading/long-iphone-s2.png, UX/reading/files-iphone-s6.png.

P1-11 Waiting copy tells the truth
- Change: turns.js:81 liveLine, the tick() function and i18n.
  - Show live.first only when there are no steps, no thinking, and the request started less than 3 s ago.
  - Add data-sub-stage so tick() changes the sub-line: hidden at 3 s, "Plus long que d'habitude…" at 8 s, and later a sentence pointing to the Arrêter button.
  - After a step completes, the main line becomes "Bird lit les résultats et rédige…".
- Accept:
  - /api/chat delayed 25 s: at 18 s the .live text does not contain "moins de 2 secondes".
  - With Réflexion on: never.
  - "cherche des sources et compare" at 2.2 s: the main line contains "rédige".
- Shots: UX/agent-feedback/desk-slow18.png, UX/agent-feedback/desk-think-600.png, UX/repro/slow18.png.

P1-12 Approval flow states are honest
- Change, in turns.js renderSteps and app.js:
  - (a) When turn.status==='confirm', render a running step as "awaiting": shield icon in the warn colour, status.awaiting "attend votre accord", and the summary says "En attente de votre accord".
  - (b) Show #send-why as a visible muted line, not .sr-only (index.html:152), with a "Voir la demande" link that focuses [data-confirm-deny].
  - (c) Add a "Refuser et préciser…" button in the sheet that denies and keeps the composer text.
- Accept:
  - During the email confirm: 0 .step-running, 1 .step-awaiting.
  - Type and press Enter: a visible (width >1px) #send-why line contains "autorisation".
  - "Refuser et préciser" gives a denied turn, and the composer value is kept.
- Shots: UX/agent-feedback/desk-confirm-steps.png, UX/agent-feedback/desk-confirm-typed.png, UX/repro/email-typed.png, UX/agent-feedback/phone-confirm-steps.png.

P1-13 Stopping is not shown as a refusal, and the run can be restarted
- Change:
  - app.js runTurn finally (about 1098): use a new status "stopped" (pause icon, muted colour, .step-stopped, status.stopped "interrompu" / "stopped").
  - The stopped notice names the step that was running and gets a "Relancer" button wired to onRetry, shown when isLast && !state.busy.
- Accept: "cherche des sources", then Arrêter at 1.2 s. Steps are [step-done, step-stopped], and a "Relancer" button is present. Clicking it sends a new /api/chat request.
- Shots: UX/agent-feedback/desk-stop-clean.png, UX/repro/stop.png.

P1-14 The injection warning quotes what was ignored
- Change:
  - Server: add a flagged_excerpt field (160-300 chars around the match) passed through guard.redact, in backends.py scenario_email and the harness preview.
  - Client: render it as plain text with h(...,{text}), never through markdown.js and never linkified. Show the host from step.arguments.url.
  - In the confirm sheet, add a "Phrase ignorée" block, collapsible on phones.
- Accept: in the email scenario, the step body contains the full flagged sentence including its target, with 0 <a> elements inside the excerpt. The sheet contains "Phrase ignorée".
- Shots: UX/agent-feedback/desk-confirm-steps.png, UX/agent-feedback/phone-confirm-steps.png.

P1-15 Waking the model: countdown, plain words, and a trace
- Change: turns.js waking branch.
  - Use retry_in for "Nouvel essai dans N s", clamped at 0, then "Nouvel essai en cours…".
  - Prefix document.title while the tab is hidden.
  - Store the wake duration on the turn and add a receipt line "dont X s de réveil".
  - Replace "endpoint" with "serveur du modèle" in i18n error.waking, live.* and endpoint.py MESSAGES. Keep "Mon endpoint" in Réglages.
- Accept: "réveil": the text matches /dans \d+ s|en cours/ and never shows a negative number. The final receipt contains "réveil". The waiting and error strings do not contain "endpoint".
- Shots: UX/agent-feedback/desk-wake-2000.png, UX/agent-feedback/desk-wake-6000.png, UX/agent-feedback/phone-wake-2000.png.

P1-16 Chart fits its width, is touch and keyboard friendly, and has a scale
- Change: views.js:85-160 chart().
  - barW = clamp(3, (W-gap)/n - gap, 24), from the figure's clientWidth. Re-render through a debounced ResizeObserver. Left-align the bars.
  - Add one top gridline labelled fmtInt(max)+" tokens".
  - Roving tabindex (last bar 0, others -1) with ArrowLeft/Right/Home/End on the svg. The readout gets aria-live=polite.
  - Add a pointerdown handler for touch. New hint text: "Touchez ou survolez une barre, ou utilisez les flèches".
- Accept:
  - 55 answers on desktop and iPhone 14: svg width ≤ scroller clientWidth.
  - Exactly 1 g.chart-bar has tabindex=0. ArrowRight moves focus.
  - From the scope toggle, 2 Tab presses reach "Voir le tableau".
- Shots: UX/eco-verify/desk-chart-55.png, UX/eco-verify/iphone-chart-55.png, UX/eco-verify/desk-chart-4.png.

P1-17 Scripted and estimated numbers are labelled everywhere
- Change:
  - turns.js:762 receipt tokens: '≈' prefix for estimated, a .tag.tag-scripted "scripté" for scripted, nothing for counted. Keep the "lus · écrits" sub-label.
  - views.js renderFootprint (465-620): compute stats and savings from real entries only. Add a line "dont N réponses de démo, exclues des totaux".
  - When every entry in scope is scripted, show the values with a SCRIPTÉ tag and put demo.note under the scope toggle.
  - Choose why.energy.demo from the entries, not from scope.
  - Drop or tag the FLOP line when its tokens are scripted.
- Accept:
  - Demo receipt: the collapsed meter contains "scripté".
  - Footprint in "Tout l'historique": the energy reason contains "démo", and the Tokens stat has a scripté tag.
  - A seeded mixed ledger: totals equal the sum of the non-scripted entries.
- Shots: UX/eco-verify/desk-receipt.png, UX/eco/iphone-receipt.png, UX/eco/desk-fp-0.png, UX/eco/iphone-fp-all.png.

P1-18 Control boundaries meet 3:1 contrast
- Change: app.css. Add --control-line: #80848f light / #64739a dark, in the prefers-color-scheme block (line 65) and in the [data-theme=dark] block (line 102). Apply it only to .field input/select/textarea (2208, 2233), the off .switch-track (1826), checkbox/radio and the resting .composer border (1715). Leave the other --line-strong uses as they are.
- Accept: computed border colour against the page background is ≥3:1 for the Settings select, the composer border and the off switch track, in both themes.
- Shots: UX/a11y-visual/13-light-settings.png, UX/a11y-visual/13-dark-settings.png.

P1-19 Settings puts real preferences first
- Change: views.js renderSettings.
  - New order: Général (Langue, Thème, Réflexion), then Modèle, then Outils (in a collapsed <details> whose summary is the "En démo…" text), then Données last.
  - Show the endpoint fieldset only when "Mon endpoint" is chosen and the server allows it. Otherwise show one explanatory line.
  - Replace the opacity dimming (app.css 2244, 2275, 3342) with muted text plus an "Indisponible" tag. Move the "À savoir : le jeton…" note outside the disabled block.
- Accept:
  - At 1280x800 the Langue select's rect.top < 800.
  - No element under #settings has computed opacity < 1.
  - The "À savoir" text is at least 4.5:1.
- Shots: UX/a11y-visual/20-light-settings-tall.png, UX/a11y-visual/34-iphone-light-settings.png, UX/verify/desk-settings.png.

==================== P2: polish ====================

P2-1 One display voice
- Change: add --display-font and --display-weight tokens and apply them to the welcome h1, .empty-title (app.css:679), .page-title, .top-title (602) and the settings headings. Use one tagline in the empty state, with "Petit par conviction" only as the sub-line.
- Accept: the computed font-family of .w-title and .empty-title is identical.
- Shots: UX/first-run/desk-light-w1.png, UX/first-run/desk-empty-top.png, UX/a11y-visual/02-welcome-focus.png.

P2-2 Composer row on phones
- Change: .composer-count moves to its own row (order:-1; flex-basis:100%; text-align:end), or is shortened to "1 599 car. · ~400 tok". On (pointer:coarse), .switch and .btn-send are 44px tall. While Réflexion is on, show a "+énergie" tag next to the label.
- Accept: on iPhone 14 after pasting 1,600 characters, .composer-count is ≤1 line (height <24px), and send and switch are both ≥44px tall.
- Shot: UX/composer-mobile/iPhone14-02-long.png.

P2-3 Landscape safe areas
- Change: `.column{padding-inline:max(var(--gutter),var(--safe-l)) max(var(--gutter),var(--safe-r))}` (about line 662). The photo sheet uses inset-inline-start with --safe-l and inset-inline-end with --safe-r.
- Accept: CSS check only, because Chromium cannot emulate the notch.
- Shot: none.

P2-4 Copy as plain text keeps the structure
- Change: turns.js:865 plainText. Derive the text from answer.content: keep "1." and "- " markers, render citations as "[1]", and append "[1] Titre — url".
- Accept: the clipboard text contains "1. " and "[1]".
- Shot: UX/reading/long-iphone-copy.png.

P2-5 Markdown fixes
- Change:
  - markdown.js:174: # to h3, ## to h4, ### and deeper to h5.
  - An indented paragraph after a blank line stays inside the previous <li> (214-245).
  - ~~x~~ becomes <del>. [ ] and [x] become disabled checkboxes.
  - app.css:1248: `.md blockquote{margin-inline:0}`.
- Accept: "# A\n## B" gives h3 + h4. The list case gives 1 <ol> with a <p> inside li. A blockquote after a list has margin-top > 0.
- Shots: UX/reading/long-iphone-s0.png, UX/reading/long-deskdark-s0.png.

P2-6 Citation targets and a way back
- Change: .cite gets a 24x24 hit area through ::before (app.css:1325-1345). In renderSources (turns.js:361), add a "↩" button per source that returns to the last clicked citation.
- Accept: the .cite hit box is ≥24x24. Click a citation, then ↩; focus is back on the citation.
- Shot: UX/reading/long-iphone-cite.png.

P2-7 The jump button says when an answer is still arriving
- Change: app.js:532 updateJump. While state.busy && !stick, label it "Réponse en cours ↓" with a dot (static under prefers-reduced-motion). Hide it while a confirm is pending. Add bottom padding so it does not cover the last line.
- Accept: scroll up 300px mid-stream; the label contains "en cours".
- Shots: UX/reading/stream-b-scrolledup.png, UX/reading/stream-c-end.png.

P2-8 Expired approval
- Change: in answerConfirm, on confirm_invalid, clear the decision and show one notice, "Cette demande d'autorisation a expiré (15 min). Rien n'a été fait.", with a "Redemander" button. The gated step reads "non exécuté".
- Accept: mock a 403 confirm_invalid; the text does not contain "Vous avez autorisé", and there is no step-error.
- Shot: UX/agent-feedback/desk-expired.png.

P2-9 Confirmation sheet on phones
- Change: .sheet-actions is sticky at the bottom. Remove max-block-size on .sheet .kv-box (no nested scroll). "Ce qui se passe ensuite" becomes a one-line note.
- Accept: Pixel 7; the Autoriser button is in the viewport when the sheet title is at the top. The .kv-box scrollHeight equals its clientHeight.
- Shots: UX/agent-feedback/phone-email-4000.png, UX/agent-feedback/desk-email-1500.png.

P2-10 Live status line wording and layout
- Change:
  - Do not repeat the step target in the live line while the step row shows it.
  - target() shows host plus a short path, with no trailing "…".
  - `.live-time{white-space:nowrap;flex:none}` and a non-breaking space in elapsed().
  - `.live{align-items:flex-start}` and spinner margin-block-start: 0.3em.
- Accept: .live-time is a single line (height < 1.5em) on iPhone 14.
- Shots: UX/agent-feedback/desk-search-300.png, UX/agent-feedback/phone-wake-2000.png, UX/agent-feedback/phone-seq-3.png.

P2-11 Footprint presentation
- Change, across views.js savings() and the stats, i18n fp.time, core.js:168 and app.css 35-36 and 2170:
  - Partial coverage goes in the value line ("≈ 1,12 Wh pour 14 réponses") with a dashed marker.
  - savings(): one unit per column (GFLOP/token), the caveat only when the bars render, the eyebrow heading style, and the title "Bird face aux grands modèles".
  - fp.time becomes "Durée totale". fmtSeconds gives "4 min 32 s" at 60 s or more.
  - Series colours: read #9DB3E0 (dark #2B4475), written #1E5BD8. Répartition bars in a neutral --ink-2 tint.
- Accept: text checks for "pour 14 réponses", "min", and no "× plus" in the value column.
- Shots: UX/eco/desk-energy-0.png, UX/eco/desk-fp-1.png, UX/eco/desk-fp-0.png.

P2-12 Receipt meter grid and tags
- Change:
  - .figs becomes `grid-template-columns:repeat(auto-fit,minmax(7.5rem,1fr))`, value over label in every cell including energy (app.css 1591-1637).
  - Sans font for .receipt-chips. Drop the model chip when it duplicates the header.
  - .tag 0.72rem in sentence case. tag-scripted gets a dotted border, distinct from unavailable.
  - <summary> elements 44px tall on coarse pointers (24px otherwise), .seg buttons 44px on mobile.
- Accept: .tag font-size ≥11.5px. The summaries' height is ≥44 on iPhone 14.
- Shots: UX/eco/iphone-receipt.png, UX/eco/pixel-dark-receipt.png.

P2-13 Small a11y fixes
- Change:
  - Footprint scope seg() (views.js:485-499): use aria-pressed buttons, or a real radiogroup with arrow keys.
  - `.composer:focus-within{box-shadow:var(--shadow),0 0 0 2px var(--accent)}` (app.css:1720).
- Accept: the ArrowRight behaviour matches the roles chosen. The focused composer has a box-shadow with 2px spread.
- Shot: UX/a11y-visual/04-main-focus.png.

P2-14 Mobile header chips
- Change: #btn-model and #btn-footprint get short labels ("Démo", the token count) at 360px or wider, sized 40-44px. Drop btn-new-top on phones if space is short.
- Accept: on iPhone 14 both chips have non-empty innerText and are ≥40px tall.
- Shots: UX/a11y-visual/31-360-light-empty.png, UX/a11y-visual/40-pixel-chat.png.

P2-15 Destructive actions look destructive
- Change: "Tout effacer" in Réglages > Données gets --danger-ink and --danger-line. Remove #btn-clear from the sidebar foot.
- Accept: the computed colour of the erase button equals the --danger-ink value. #btn-clear is absent.
- Shots: UX/a11y-visual/20-light-settings-tall.png, UX/a11y-visual/11-light-chat.png.

Suggested order: P0-2, P0-9 and P0-10 are one-line wins, so do them first. Then P0-1, P0-3, P0-4, P0-5, P0-6, P0-7, P0-8, P0-11 and P0-12. Within P1, start with P1-1, P1-4 and P1-12 (phones and approval). No repo files were edited.
