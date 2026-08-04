# Project Task Tracker

## Current Milestone
- [ ] Verify command-based work-time check-in/out with the backend test suite

## Completed Tasks
- [x] Change daily check-in prompts to advance only after the previous step is completed (`backend/app/bot/handlers.py`, `backend/app/bot/work_report_handlers.py`)
- [x] Add coverage for sequential daily prompt delivery (`backend/tests/test_work_report_handlers.py`)
- [x] Replace daily start/end prompts with `/daystart` and `/dayend` commands (`backend/app/bot/work_report_handlers.py`)
- [x] Add the new work-time commands to the Telegram command menu and onboarding help (`backend/app/bot/menu.py`, `backend/app/bot/handlers.py`)
