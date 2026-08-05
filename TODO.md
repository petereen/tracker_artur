# Project Task Tracker

## Current Milestone
- [x] Add interval-based remote and in-person work-time tracking across Telegram and admin panel

## Completed Tasks
- [x] Change daily check-in prompts to advance only after the previous step is completed (`backend/app/bot/handlers.py`, `backend/app/bot/work_report_handlers.py`)
- [x] Add coverage for sequential daily prompt delivery (`backend/tests/test_work_report_handlers.py`)
- [x] Replace daily start/end prompts with `/daystart` and `/dayend` commands (`backend/app/bot/work_report_handlers.py`)
- [x] Add the new work-time commands to the Telegram command menu and onboarding help (`backend/app/bot/menu.py`, `backend/app/bot/handlers.py`)

## Pending Subtasks
- [x] Store multiple remote/in-person work intervals with backward-compatible legacy data handling
- [x] Add remote work commands, mode validation, and Telegram work-time summaries
- [x] Expose aggregate and detailed work-time data in backend APIs
- [x] Display remote/in-person totals and intervals in the admin panel
- [x] Add focused work-time summary coverage and run available validation (Python syntax passed; pytest and frontend dependencies unavailable)
