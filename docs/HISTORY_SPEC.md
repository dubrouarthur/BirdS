# Spécification : historique de conversation (issue de la revue)

FINAL SPEC v2: cache-stable, budgeted, cache-isolated history for Bird (vLLM v0.32, hybrid Gated DeltaNet, APC 'align' mode, 528-token blocks)

This revises draft v1 (the simplicity-first hysteresis window) at HEAD cae999a. It is read-only work for the implementer. Re-check line numbers before editing, because another engineer is changing these files now.

0. STARTING POINT (re-checked at HEAD cae999a)
0.1 Keep everything in v1 section 0 as it is:
- memo round-trip (app.js:932/819, server.py:50, history.py:94);
- the image and attachment notes are added in backends.run (backends.py:1010-1017);
- open bugs (a)-(f);
- pieces that are already stable: the template sha256 a4aee8af...f715, defang idempotent, redaction, no dates, fixed BIRD_TOOLS order.
0.2 Facts newly checked in the code. The fixes below depend on them.
- LLM client: CompletionsClient._post returns only (prompt_tokens, completion_tokens), via _usage at llm.py:65. finish_reason is never read anywhere in birds/. An answer cut by max_tokens is reported as stop_reason 'answer' (agent.py:341).
- Resume path: backends.run calls agent.run(resume=state) without building `user` (backends.py:1001-1004). state['messages'] holds the system message, the kept history and {'role':'user','content': guard.defang(user)} (agent.py:276-278). Tool turns come after it.
- Stop path: app.js:1055-1065 builds a 'stopped' answer on the client after the fetch is aborted. No server event is sent after the abort.
- Conversation ids: conv.id = uid('c') (core.js:249) is Date.now + counter + 4 base36 chars from Math.random. That is about 20 bits of randomness, so it is NOT fit to be a secret.
- detect_lang: _EN matches single function words ('to', 'of', 'is', 'can'; agent.py:41).
- Image transcription: capped at 700 TOKENS (backends.py:_read_images), not at a character count. There are at most 3 images (server.py:72) and at most 4 attachments (settings.py:82). Names are at most 160 chars.
- BIRD_TOKENIZER: build_server_backend renders through transformers AutoTokenizer (server.py:171-176), not through the vendored template.

1. CACHE MODEL. Unchanged from v1 section 1, with one addition:
1.1 vLLM folds cache_salt into the hash of the FIRST block. All later block hashes chain from it, so requests with different salts never share any block. Under retention=0, conversations already do not share blocks (v1 1(ii)). A per-conversation salt therefore costs about 0 hits and closes the cross-user TTFT probing channel.

2. INVARIANT. Same as v1 section 2, with these changes:
2.1 Exception (c) now reads: "an OLD client (no conv_lang field) changes the UI language".
2.2 New exception (f): a regenerate after a page reload of a turn whose images are no longer in memory. Section 3.3.6 makes even this case byte-stable whenever turn.sent exists.
2.3 Every byte rendered for messages 0..user k must be a pure function of the request body plus server constants. This now explicitly includes conversation_id and conv_lang.

3. FIXES BY FILE
3.1 Stable tools block (backends.py HarnessBackend._config)
- Delete lines 901-902, which filter out read_file when there is no attachment.
- allowed_tools varies per deployment only.
- read_file with no file raises ToolError (tools/files.py:76). That is the graceful outcome.

3.2 Conversation language, pinned by the client and with no detection on message 0
3.2.1 app.js
- On the first send of a conversation, set conv.lang = current UI lang (fr|en).
- Keep it in slim() and send it every turn as request.conv_lang.
- It never changes for that conversation.
3.2.2 server.py ChatRequest: add conv_lang: Literal['fr','en'] | None = None.
3.2.3 backends.py: add a pure helper conv_lang(request) -> request.conv_lang or ('en' if request.lang == 'en' else 'fr').
- Use it for DEFAULT_SYSTEM[...], window(..., lang=), the summary note and the interrupted marker.
3.2.4 backends.py: add a pure helper run_lang(raw_last, conv) -> str.
- Count n_fr = len(_FR.findall(raw_last)) and n_en = len(_EN.findall(raw_last)) on the RAW last message, before any notes are added.
- If max(n_fr, n_en) >= 3 and that count is >= 2 x the other, return that language. Otherwise return conv.
- Pass it to agent.run(lang=...) and _read_images(lang=...). It also selects the image/attachment note language and the untrusted note in 3.3.2.
- Its bytes either do not cross turns, or are frozen inside user_sent (3.3), so this is cache-neutral.
3.2.5 The persona already says to answer in the user's language.
3.2.6 Delete the 'user_lang = detect_lang(last["content"])' line (backends.py:1018).

3.3 Persist exactly the user text that was sent
3.3.1 New constants in backends.py:
- IMAGE_TEXT_CHARS = 2400.
- NOTE_OVERHEAD = 2 + max(len of _IMAGE_NOTE values) + 4 + 160 + 1 + max(len of UNTRUSTED_NOTE values) + 1.
- ATTACH_OVERHEAD = 1 + max(len of _ATTACH_NOTE values) + 4 + len(ATTACH_DIR) + 1 + 160 + 1.
- USER_SENT_EXTRA = 3 * (IMAGE_TEXT_CHARS + NOTE_OVERHEAD) + s.max_attachments * ATTACH_OVERHEAD. This comes to about 8.3k chars. It is DERIVED, not guessed.
3.3.2 Build the image note on the server, once:
- t = guard.truncate(text, IMAGE_TEXT_CHARS) (hard cap, applied before the text is used anywhere);
- note = f"\n\n[{_IMAGE_NOTE[rl]} : {name}]\n{guard.UNTRUSTED_NOTE[rl]}\n{t or '(illisible)'}".
- The transcription is model output that reproduces untrusted image text. It therefore always carries the untrusted wrapper, and it is capped and defanged.
- Attachment notes keep their current format.
3.3.3 user_sent = guard.defang(raw + image notes + attachment notes).
- Always send the defanged form. defang is idempotent, so the next turn renders exactly the bytes P_N held.
- agent.run receives exactly that string. Re-defanging it inside agent.run is a no-op.
3.3.4 New SSE event {'type':'user','content': user_sent}.
- Emit it once per request, right before agent.run, after the images are read and the notes are added.
- On the RESUME path, emit it at the start of the resume from the signed state: user_sent = state['messages'][state_ui]['content']. state_ui is a new integer field in the confirm token payload, set to len(kept) + 1 (the index of the turn's user message, after the system message).
- The token is signed, so this value cannot be forged.
- Answer, confirm and error events do NOT need to carry it.
3.3.5 app.js
- On a 'user' event, write ev.content to the USER turn that precedes the streaming assistant turn: userTurn.sent = ev.content. Do not write it to the assistant turn object.
- apiMessages sends content = turn.sent ?? <current behaviour> for every user turn except the last one.
- slim() keeps turn.sent.
- With this, a stopped turn (abort after the 'user' event) and a resumed (confirmed) turn both keep the exact text.
3.3.6 Stale or missing sent (app.js)
- editLast(), and any change to a user turn's content, set turn.sent = undefined before the request is sent.
- regenerate:
  - if lastImages is still in memory: clear turn.sent and resend the raw content + images;
  - otherwise, if turn.sent exists: send content = turn.sent with no images and no attachments. The server adds nothing, so user_sent == turn.sent and the transcription the answer relied on is kept;
  - otherwise: today's behaviour.
3.3.7 Stop passing image= to memo(). Old cached clients keep today's behaviour and see no error.
3.3.8 server.py validation
- Every user message: len(content) <= max_message_chars + USER_SENT_EXTRA.
- When the request carries images or attachments, the LAST message must also be <= max_message_chars. That is raw input, so it gets the strict limit.
- max_request_chars = 400k is unchanged. State plainly in the docs and the 413 text that image-heavy conversations reach "start a new conversation" sooner.
3.3.9 user_sent is text the client holds and sends back as content. It is defanged again on the server and covered by the digest (3.4). It gains no authority it did not already have: the same bytes were already in the user role on turn N.

3.4 Confirm digest (server.py about line 503)
- Digest each message as {'role','content','memo','interrupted'}.
- Also include conversation_id and conv_lang.
- On resume, reject if request.conversation_id differs from the token's value.

3.5 Skip dangling user turns (app.js apiMessages)
- Leave out a user turn that has no assistant answer and is not the turn being sent or retried.

3.6 Interrupted answers
3.6.1 llm.py
- _post / _usage also return finish_reason from choices[0].finish_reason (streaming: the last chunk that carries it; non-streaming: choices[0]).
- generate() returns it in its dict as 'finish_reason' (None when the engine does not report it).
- Also read usage.prompt_tokens_details.cached_tokens when present and return it as 'cached_tokens' (None otherwise).
3.6.2 agent.py: if the final answer generation has finish_reason == 'length' and content is non-empty, set run.stop_reason = 'length'. Empty content keeps 'empty_output'.
3.6.3 app.js: send interrupted: true on an assistant message whose stop_reason is 'stopped' or 'length'.
3.6.4 server.py Message: add interrupted: bool = False.
3.6.5 history._render appends '\n\n[réponse interrompue]' or '\n\n[answer interrupted]', chosen by conv_lang. Append it once, after the memo and before the cap (4.1).

3.7 Server mode honours the budget (server.py build_server_backend)
- Pass history_tokens=s.history_tokens and msg_cap_tokens=s.history_msg_tokens to BOTH HarnessBackend(...) calls (lines 164 and 177).
- /api/health reports both values.

3.8 Cache isolation, shipped in this phase (backends.py, llm.py, app.js, server.py)
3.8.1 app.js
- conv.cid = crypto.randomUUID() when a conversation is created (122 random bits).
- Keep it in slim(). Send it every turn as request.conversation_id.
- Never show it and never put it in a URL.
3.8.2 server.py: conversation_id: str | None, pattern ^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$.
3.8.3 backends.cache_salt(cid):
- cid present: sha256(b'bird-cache-salt-v1\0' + cid).hexdigest(). This is deterministic across Vercel instances and needs no secret.
- cid absent (old client): secrets.token_hex(16) per request. That gives no reuse and no leak.
3.8.4 Send cache_salt on every /v1/completions body of the run and on every /v1/chat/completions image call. Pass it through CompletionsClient extra per call, not on the shared client object.
3.8.5 Startup self-check, once per process:
- send one 1-token completion with cache_salt;
- on HTTP 400 or 422, set health cache_isolation = 'unsupported' and fail /api/health loudly.
- The operator then either upgrades or disables --enable-prefix-caching on the endpoint. Privacy wins over energy.
- When the check passes, report cache_isolation = 'salted'.
3.8.6 Log id: log_id = sha256(b'bird-log-v1\0' + cid).hexdigest()[:16]. It uses a different label, so it cannot be linked to the salt. It is derived from the random id, not from content.

3.9 Template fidelity on the BIRD_TOKENIZER path (server.py)
- When s.tokenizer is set, render a fixed golden conversation at startup with both renderers:
  - the vendored birds/harness/template.py;
  - tok.apply_chat_template(..., tokenize=False, add_generation_prompt=True).
  The golden conversation is system + tools, then 2 user/assistant turns, one assistant with reasoning_content, and a final user.
- If the strings differ, refuse to start, with the first differing offset in the error.
- /api/health reports template = 'vendored' | 'tokenizer-verified'.

4. WINDOW (birds/harness/history.py, window(history, budget_tokens, *, lang, msg_cap_tokens))
4.1 Per-message cap, identical to v1 4.1
- cap_chars = int(msg_cap_tokens * CHARS_PER_TOKEN). The default is 3168 tokens, about 11,088 chars.
- Keep the head 2/3 and the tail 1/3, joined by '\n[…]\n'.
- Apply it to EVERY history message, after the memo and the interrupted marker.
- Delete the kept[-1] truncation (lines 132-137).
- The current message is not capped.
- The one-time cap event, when a message over the cap first becomes history, remains allowed exception (e).
4.2 Hysteresis cut, identical to v1 4.2
- HIGH = budget_tokens, LOW = HIGH // 2.
- Replay with a running sum in O(n).
- drop is monotone and the newest turn is always kept.
- stats.cut_moved is reported.
4.3 Estimator: tokens() = int(len/3.5) + 4. It is never fed server token counts. Only the calibration ratio is logged.
4.4 Summary note: unchanged from v1 4.4. It is built from turns[:drop], at the end of the system message, with 12 lines, 120 + 160 chars per line, and 2,100 chars in total.
4.5 Memo: unchanged from v1 4.5. Cap 2,400. No tool output and no excerpts. _plain strips '<' and '>'. The image transcription is no longer in the memo (3.3.7).

5. CONFIG (birds/web/settings.py)
5.1 New settings:
- BIRD_HISTORY_TOKENS: default 6000, min 1056.
- BIRD_HISTORY_MSG_TOKENS: default 3168, min 528.
5.2 Unchanged: max_tokens 1536, max_messages 60, max_message_chars 24000, max_request_chars 400000, max_context_chars 24000, max_result_chars 6000, max_steps 6.
5.3 Worst-case prompt, about 28k. Acceptance: it must be at or below max_model_len, read from /v1/models at startup. Health fails loudly if it is lower.
5.4 Ceiling, stated plainly in the docs: max_messages = 60 means 413 after 30 turns, and max_request_chars may stop a conversation earlier.
- The window matters only inside that ceiling.
- The UI keeps the "start a new conversation" message. It does not promise unlimited memory.
5.5 Do not raise HIGH without the replay eval (7.4). Do not enable YaRN.

6. SERVER (HF Inference Endpoint, vLLM v0.32)
6.1 Keep these:
- --enable-prefix-caching
- chunked prefill (required by 'align')
- --prefix-caching-hash-algo sha256 (the default)
6.2 Add --enable-prompt-tokens-details. It is needed for per-generation cached_tokens (7.2).
6.3 Do not set:
- --prefix-match-unit
- --enable-mamba-shared-prefix-checkpoint
- YaRN
- any flag seen only on docs.vllm.ai/latest
6.4 Optional A/B: --prefix-cache-retention-interval 1584. Adopt it only if the token hit ratio rises, preemptions do not rise, kv_cache_usage_perc stays below 90% at p95, and the L4 check passes.
6.5 cache_salt is shipped now (3.8), not deferred.

7. ACCEPTANCE TESTS
7.1 Unit tests (new file tests/test_history_cache.py)
Extract a pure helper backends.prepare_turn(messages, conv_lang, ui_lang, attachment_names, image_texts, history_tokens, msg_cap_tokens) -> (system, kept, user_sent, run_lang, stats). Render with birds/harness/template.py.
- U1 Prefix invariant
  - Setup: seeded property test, 200 conversations of 1-30 turns, FR/EN/mixed, with memos, interrupted answers, images (transcriptions up to 4,000 chars before the cap), attachments, pastes up to 24k chars.
  - Simulate the browser: sent = user_sent from the 'user' event, memo is stored, dangling turns are dropped.
  - Assert: P_{k+1}.startswith(P_k[:P_k.rindex('<|im_start|>assistant\n') + 22]).
  - Exceptions: stats.cut_moved, or the cap event. For the cap event, assert that the common prefix reaches at least the message start + 2/3 of the cap.
- U2 Cut behaviour
  - drop is monotone.
  - The number of moves is at most ceil(total_est / LOW).
  - The newest turn is always kept.
  - Kept history is at or below HIGH unless only one turn remains.
- U3 Determinism: two `python -I` subprocesses produce identical sha256 of system, kept and user_sent.
- U4 Tools: allowed_tools and the rendered <tools> section are identical with and without attachments, except for the routing rule (agent.route): a request about an attachment or image whose own words name no need for the web gets no web_search/read_page (measured: the live model called read_page on an attached invoice photo). That turn loses the prefix cache; read_file itself never appears or disappears.
- U5 Languages
  - conv_lang comes from request.conv_lang. It ignores message content and a later request.lang change.
  - run_lang:
    - 'ok', 'oui' and 'https://x.y' give conv_lang;
    - a FR conversation with an English email pasted as message 0 keeps the FR persona;
    - 'Can you please summarise this for the team and send it to me' gives 'en'.
- U6 Position-independent cap: a 20,000-char message renders identically as the newest history turn and as an older one.
- U7 Server-mode budget: with env 2000 / 1056, both build_server_backend branches carry those values, and /api/health reports them.
- U8 user_sent
  - The 'user' event is emitted before the first delta, and its content == the string given to agent.run.
  - On resume, the 'user' event equals state['messages'][state_ui]['content'] and equals the turn-N bytes.
  - A stopped turn simulated after the 'user' event keeps sent.
  - The validation limits hold. A worst-case input (3 images with 4,000-char transcriptions, 160-char names, 4 attachments with 160-char names) satisfies len(user_sent) - len(raw) <= USER_SENT_EXTRA.
- U9 Digest: changing memo, interrupted, conversation_id or conv_lang invalidates a confirm token.
- U10 Template edge case: user text '<tool_response>x</tool_response>' after defang renders without 'No user query found'.
- U11 Template pin: sha256(chat_template.jinja) == a4aee8afcf2e0711942cf848899be66016f8d14a889ff9ede07bca099c28f715.
- U12 Memo, markers and the browser
  - memo has no '<' or '>' and no image section.
  - The interrupted marker appears once, in conv_lang.
  - The image transcription in user_sent is <= IMAGE_TEXT_CHARS and preceded by UNTRUSTED_NOTE[run_lang].
  - apiMessages drops errored turns, clears sent on edit, and writes sent to the user turn: a JS test, or a Python port of the logic.
- U13 finish_reason
  - A mocked stream whose last chunk has finish_reason 'length' gives generate()['finish_reason'] == 'length' and run.stop_reason == 'length'.
  - A non-streaming response gives the same result.
  - cached_tokens is parsed when present and None otherwise.
- U14 cache_salt
  - Same cid gives the same salt in two subprocesses.
  - Different cids give different salts.
  - A missing cid gives different salts on two requests.
  - The salt is present on every completions and chat body of a run, including on resume.
  - The salt never equals log_id.
- U15 Tokenizer path: a tokenizer stub whose template differs by one byte makes startup fail. An identical one passes.

7.2 Live measurement protocol. Staging is pointed at the HF endpoint. Run it before and after the change.
- L0 Preconditions
  - From /metrics (authenticated), confirm the exact names of vllm:prefix_cache_queries_total, vllm:prefix_cache_hits_total, vllm:prompt_tokens_total, vllm:num_preemptions_total, vllm:kv_cache_usage_perc and vllm:cache_config_info.
  - From one completion, check that usage.prompt_tokens_details.cached_tokens is present.
  - From one completion with cache_salt, check that it is accepted (3.8.5).
  - From the startup log, record block 528, the mamba padding % and the number of GPU blocks.
- L1 Replay
  - 20 scripted conversations (10 FR, 10 EN), 8 turns each, including one 'ok' turn, one attachment turn, one image turn, one 15k paste and one confirm.
  - Thinking off, temperature 0. Send them sequentially in a quiet window.
  - For each turn, log per generation: prompt_tokens, cached_tokens, finish_reason, log_id, turn index and step index.
  - The measured quantity is cached_tokens of the FIRST generation of each turn. Metrics deltas are used only as a cross-check, never per turn.
- L2 Pass criteria, for turns k >= 2 with no cut move, edit or cap event
  - Definitions:
    - n = prompt_tokens of turn k-1's first generation;
    - c = floor((n-1)/528) * 528 (its only checkpoint under retention=0);
    - L = the token length of the common prefix of P_{k-1} and P_k, tokenized with the model tokenizer by the measurement script.
  - Expected hit E = c if c <= L, else 0. The else case is the checkpoint falling inside the generation-prompt suffix, roughly 1-2% of turns. It is expected, not a miss.
  - Pass if cached_tokens == E in at least 90% of eligible turns.
  - Every miss must coincide with a preemption increment or with kv_cache_usage_perc above 90%.
  - Before the change, the 'ok' and attachment turns are expected to have E > 0 but cached ≈ 0. After it, they must pass.
- L3 Fleet, 7 days before and 7 days after
  - token hit ratio rate(hits[5m]) / rate(queries[5m]);
  - prompt tokens per answer;
  - median and p90 energy_wh per answer for turns >= 3.
  - Report candidly: gains come from multi-turn traffic only, within the 30-turn ceiling (5.4).
- L4 Cache correctness, compared against a noise floor
  - Use 50 prompts of more than 1,600 tokens, temperature 0, logprobs = 1, max_tokens = 32.
  - Baseline: send each prompt twice with two FRESH random salts (cold vs cold). Record the first-32-token agreement and the max |Δ logprob| of the chosen tokens. That is the noise floor.
  - Test: send each prompt twice with the SAME salt (cold, then warm). Confirm cached_tokens > 0 on the warm request.
  - Pass if:
    - warm-vs-cold agreement >= baseline agreement minus 1 prompt;
    - the warm-vs-cold p95 |Δ logprob| <= 2 x the baseline p95;
    - the first token is identical in 50/50.
  - Do not use prompt_logprobs: vLLM skips the prefix cache for requests that ask for prompt logprobs.
- L5 App invariants, from per-request logs keyed by log_id (no content)
  - distinct tools_hash per deployment = 1;
  - conv_lang changes per log_id = 0;
  - cut moves per log_id at most about 1 per 3,000 estimated history tokens;
  - calibration ratio prompt_tokens / est_prompt_tokens, by language;
  - share of requests without a cid (old clients). It should fall to about 0 within 1 week.

7.3 Privacy check: from a second browser session, send a document prefix that session A already sent. Its first-generation cached_tokens must be 0.

7.4 Quality gate before changing defaults
- Replay transcripts with HIGH = 3000, 6000 and 12000 on at least 50 real FR/EN multi-turn sessions.
- Call prepare_turn directly, so the HTTP limits do not mask the window. Also report how many sessions would hit 413 under the current max_messages and max_request_chars.
- Score: constraint retention, ordinal-source follow-ups, sheet edits, follow-ups after a cut.
- Keep 6000 unless 3000 is not worse (frugal) or 12000 is clearly better within the 30-turn ceiling.

## Mesures

Checked read-only in /home/user/BirdS at HEAD cae999a. Nothing was run against the endpoint.
1. finish_reason is absent from all of birds/. llm.py:_usage (line 65) returns only (prompt_tokens, completion_tokens), and agent.py:341 sets stop_reason 'answer' whenever content is non-empty. The reviewer's 'length never exists' claim is confirmed.
2. The resume path calls agent.run(resume=request.resume['state']) without building `user` (backends.py:1001-1004). The user message is stored as guard.defang(user) in state['messages'] (agent.py:276-278). So it can be read back from signed state with an index, and that is byte-identical because defang is idempotent (guard.py:184: _CONTROL.sub('&lt;')).
3. The stop path builds the 'stopped' answer on the client only (app.js:1055-1065), and lastImages lives in memory only (app.js:1109, 1120, 1130).
4. conv.id = uid('c') (core.js:249) is Date.now base36 + counter + 4 Math.random base36 chars, about 20 random bits. It is not usable as a salt secret, which is why the spec adds crypto.randomUUID().
5. _EN (agent.py:41) matches single 'to', 'of', 'is', 'can', and detect_lang only needs FR count >= EN count. The weak-marker pinning concern is confirmed.
6. Image transcription is limited to 700 tokens (backends.py _read_images, llm.chat(messages, 700)). There are at most 3 images (server.py:72), at most 4 attachments (settings.py:82), and names are at most 160 chars (server.py:54/59). USER_SENT_EXTRA is computed from these limits. UNTRUSTED_NOTE and wrap_untrusted already exist (guard.py:42, 188).
7. read_file filtering at backends.py:901-902 and user_lang detection at backends.py:1018 are confirmed. The BIRD_TOKENIZER path uses AutoTokenizer (server.py:171-176).
8. Not verified here, and therefore left as spec checks:
- cache_salt acceptance on the v0.32 /v1/completions route (L0, 3.8.5);
- the prompt_tokens_details flag;
- the exact metric names;
- whether vLLM skips prefix caching for prompt_logprobs requests (from memory of the V1 scheduler; it is the reason L4 uses generation logprobs).

## Sources

- /home/user/BirdS/birds/web/backends.py (lines 895-905 _config, 906-950 _read_images, 952-1060 run, 805/831 note constants)
- /home/user/BirdS/birds/harness/agent.py (38-45 _FR/_EN/detect_lang, 255-282 resume and new-run state, 286-345 stop_reason assignment)
- /home/user/BirdS/birds/harness/llm.py (65-80 _usage, 227-300 CompletionsClient.generate)
- /home/user/BirdS/birds/harness/guard.py (40-45 UNTRUSTED_NOTE, 184-189 defang/wrap_untrusted)
- /home/user/BirdS/birds/web/server.py (47-72 Message/ImageIn/Attachment/ChatRequest, 160-180 build_server_backend, 470-500 validation)
- /home/user/BirdS/birds/web/settings.py (79-83, 102)
- /home/user/BirdS/birds/web/static/app.js (63, 71 slim, 1032-1065 stop path, 1093-1130 send/regenerate, 1187 editLast)
- /home/user/BirdS/birds/web/static/core.js:249 (uid)
- vLLM docs: automatic prefix caching design (block hash chaining, cache_salt folded into the first block hash), OpenAI-compatible server extra params (cache_salt, prompt_logprobs), --enable-prompt-tokens-details

## Idées écartées

- Deriving cache_salt as HMAC(configured signing secret, conversation id) (both the draft and the reviewer proposed it). Rejected: the attacker would have to send the victim's id to our own server, which would compute the same HMAC, so the secret adds no protection. It also adds the ephemeral-secret cache-split problem. A labelled sha256 of a 122-bit crypto.randomUUID gives the same isolation, is deterministic across instances and needs no secret. Using the raw conversation id (the reviewer's fallback) is also rejected, because the endpoint would see and could log a client identifier.
- Reusing the existing conv.id as the salt or log key (implied by the reviewer's 'random conversation id stored with the conversation'). Rejected: uid() has about 20 bits of Math.random entropy plus a timestamp, so it is guessable. A separate conv.cid = crypto.randomUUID() is added instead.
- Using a hash of message 0 as the conversation id for metrics. Rejected, as the reviewer noted: it is derived from content and can be dictionary-attacked.
- Carrying user_sent only on the answer, confirm and error events (draft 3.3). Replaced by one early 'user' event, also emitted from signed state on resume. That single event covers stop, confirm and resume, and the other events stay unchanged.
- Putting a full copy of user_sent into the confirm token. Rejected: it would double the token size (up to about 33k chars), since state['messages'] already holds the defanged text. An index (state_ui) into the signed state is enough.
- Pinning the persona language on markers in message 0 (draft conv_lang). Rejected, as the reviewer showed: weak _EN markers misfire on pasted English. Detecting with a minimum count was considered and also rejected in favour of a client-pinned conv.lang set at the first send. That involves no detection, is equally cache-stable, and removes exception (c) for new clients.
- Pinning on request.lang alone (reviewer option). Rejected: a mid-conversation UI language switch would then break the prefix every time. conv.lang fixes the value once per conversation.
- Leaving the image transcription unwrapped in user_sent (draft) or moving it back into the memo. Rejected. It stays in the user turn, where it was already present on turn N, but it is hard-capped at IMAGE_TEXT_CHARS = 2400 on the server and prefixed with UNTRUSTED_NOTE, as the reviewer asked.
- A guessed +9000 allowance for non-last user messages. Replaced by USER_SENT_EXTRA, derived from the code constants and pinned by a unit test.
- L4 'identical generations in at least 48/50' and the reviewer's prompt_logprobs comparison. The first is rejected because it measures numerical nondeterminism. The prompt_logprobs variant is rejected because vLLM skips the prefix cache for requests that ask for prompt logprobs, so it cannot exercise the warm path. Instead: 32 tokens with generation logprobs, compared cold vs warm against a cold-vs-cold baseline obtained with two fresh cache_salts.
- Per-web-request Δhits from /metrics as the L2 measure (draft). Rejected, as the reviewer showed: it mixes up to 6 generations plus image calls and other traffic. Per-generation usage cached_tokens is used instead, and /metrics only as a cross-check.
- The draft L2 bound 528*floor((n-8)/528). Rejected: it is not exact when the checkpoint falls inside the generation-prompt suffix. Replaced by E = c if c <= common-prefix tokens, else 0.
- Forbidding BIRD_TOKENIZER outright. Rejected in favour of a startup golden-render equality check, which keeps the option and fails closed.
- Deferring cache_salt until 'multi-tenant exposure' (draft). Rejected, as the reviewer showed: the public web app is already multi-tenant, and under retention=0 the salt costs about 0 hits.
- Re-reading images after a reload so regenerate can work. Rejected as unnecessary: regenerate resends turn.sent, which already holds the capped, wrapped transcription, so no extra GPU call is needed (frugal).
