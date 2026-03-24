# Scenario Notes

This file captures scenario planning notes without turning them into runtime code.

## Inbox Spam Cleanup

Concerns:

- identification of obvious spam versus important mail;
- destructive deletion confirmation;
- mail provider-specific UI differences;
- risk of bulk actions.

Reusable runtime needs:

- page observation;
- list extraction;
- safe selection and deletion actions;
- confirmation before destructive changes.

## Food Ordering

Concerns:

- address and availability differences by location;
- cart mutations;
- payment sensitivity;
- high variability in restaurant UIs.

Reusable runtime needs:

- navigation and search;
- extraction of menu options;
- form filling;
- confirmation before checkout or payment.

## Job Search And Applications

Concerns:

- login and account state;
- multi-page flows;
- resume upload and form filling;
- submitting applications is a sensitive action.

Reusable runtime needs:

- navigation;
- extraction of job details;
- text entry and uploads;
- confirmation before final submission.

## Important Reminder

These scenario notes are for product and engineering planning only. They must not
be translated into hardcoded task-specific pipelines inside the runtime.
