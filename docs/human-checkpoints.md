# Human Checkpoints

## Why this exists

Some browser tasks should be semi-autonomous instead of fully autonomous.

Typical examples:

- login on a real website;
- captcha or anti-bot challenge;
- SMS or email verification;
- final review before a sensitive external submission;
- any page state the agent cannot safely continue from.

For these cases, the runtime should not degrade everything into a generic `ask_user` prompt.
It should emit a typed browser handoff and pause in a dedicated `waiting_for_intervention`
state so the operator can act directly in the open browser window and then resume.

## Runtime contract

The runtime now has a first-class `HumanInterventionRequest` model with:

- `kind`: structured reason such as `login`, `captcha`, `two_factor`, `site_handoff`, or `review`;
- `instruction`: what the operator should do in the browser;
- `prompt`: why the agent paused;
- `resume_hint`: how the operator should resume;
- `allowed_actions`: bounded list of acceptable manual actions.

This keeps the browser handoff explicit in:

- `RuntimeSession.pending_human_intervention`
- `PlannerSessionState.pending_human_intervention`
- `FinalReport.pending_human_intervention`
- `HumanInterventionRequested` UI event

## UX shape

For a demo or product shell with the browser visible on the left and agent console on the
right, the intended behavior is:

1. The browser stays open in the same live session.
2. The agent pauses with a clearly labeled "Needs your action" panel.
3. The operator performs the bounded manual step directly in the browser.
4. The operator resumes the run from the console or host UI.
5. The agent continues from the same page and session state.

The human checkpoint panel should answer four things:

- what happened;
- what the operator is allowed to do;
- what the agent is waiting for;
- how to resume.

## hh.ru job-apply flow

For a task such as "find 3 relevant AI engineer vacancies on hh.ru and apply using the
resume from my profile", the recommended state sequence is:

1. `open_site`
2. `check_auth`
3. `waiting_for_intervention(kind=login)` if the user is not signed in
4. `read_profile_resume`
5. `search_jobs`
6. `extract_job_details`
7. `rank_jobs`
8. `draft_cover_letters`
9. `waiting_for_intervention(kind=review)` for user review of the shortlist
10. `waiting_for_confirmation` before each external submission, if product policy requires it
11. `submit_application`
12. `done`

If the site shows anti-bot friction at any point, the runtime should pause again with:

- `waiting_for_intervention(kind=captcha)`
- `waiting_for_intervention(kind=two_factor)`

## Recommended planner policy

The planner should prefer a human checkpoint over a generic question when:

- the browser state contains a credential flow;
- the website asks for a captcha or challenge response;
- continuing would require a user identity assertion;
- the submission affects the user's real account or reputation;
- the page has become ambiguous after a redirect, popup, or challenge flow.

## Product guidance

For real job platforms, the safest default is:

- the agent may search, read, extract, compare, and draft;
- the user handles login, captcha, and 2FA;
- the user reviews the shortlist and generated cover letter;
- the agent only submits after an explicit approval policy is satisfied.
