import type { docsMn } from './mn'

/** In-app documentation (`/docs`), English. */
export const docsEn: { [K in keyof typeof docsMn]: string } = {
  'docs.kicker': 'OYUNS ERP · DOCS',
  'docs.title': 'Documentation',
  'docs.subtitle': 'How to use and configure every part of the platform. Pick a topic or search the guide.',
  'docs.home': 'Home',
  'docs.featured': 'Start here',
  'docs.allTopics': 'All topics',
  'docs.read': 'Read',
  'docs.openPage': 'Open page',
  'docs.previous': 'Previous',
  'docs.next': 'Next',
  'docs.outline': 'On this page',
  'docs.breadcrumbs': 'Location',
  'docs.nav.label': 'Guide sections',
  'docs.nav.jump': 'Choose a topic',
  'docs.search.label': 'Search the guide',
  'docs.search.placeholder': 'Search the guide…',
  'docs.search.results': '{{n}} results',
  'docs.search.emptyTitle': 'No results',
  'docs.search.emptyDescription': 'Try different words, or pick a section instead.',
  'docs.audience.everyone': 'All employees',
  'docs.audience.managers': 'Management',
  'docs.audience.admins': 'Admin',

  'docs.group.start.title': 'Getting started',
  'docs.group.start.description': 'How the platform is organized, signing in, menus and your profile.',
  'docs.group.daily.title': 'Daily work',
  'docs.group.daily.description': 'Time tracking, tasks, calendar, chat and reports.',
  'docs.group.ai.title': 'OYUNS AI & Telegram',
  'docs.group.ai.description': 'The AI assistant, voice calls, the Telegram bot and Mini App.',
  'docs.group.management.title': 'Management',
  'docs.group.management.description': 'HR, performance analytics and contracts.',
  'docs.group.erp.title': 'ERP modules',
  'docs.group.erp.description': 'CRM, budget, chart of accounts and payroll.',
  'docs.group.admin.title': 'Administration',
  'docs.group.admin.description': 'Organization, access, workflows, integrations and security.',
  'docs.group.help.title': 'Help',
  'docs.group.help.description': 'Frequently asked questions and troubleshooting.',

  'docs.article.overview.title': 'OYUNS overview',
  'docs.article.overview.summary': 'What the platform includes, the channels it runs on, and who sees what.',
  'docs.article.overview.body': `## What is OYUNS

OYUNS is a single workspace for your organization's day-to-day work. Time tracking, tasks, calendar, chat, reports, contracts, HR, CRM, budget, payroll and the OYUNS AI assistant all share one account and one permission system.

## Channels

Every channel works on the same data, so a change made in one place shows up everywhere at once.

| Channel | Best for |
|---|---|
| Web workspace | Every module, settings, reports and table-heavy work |
| Mobile app (iOS, Android) | Time tracking, automatic time tracking, push notifications, biometric lock |
| Telegram bot | Notifications, reminders, chatting with the AI assistant, voice messages |
| Telegram Mini App | The task board and quick actions inside Telegram |

## Roles and permissions

What you can see and do depends on the roles your organization gives you.

- **Employee** — your own time, tasks, reports, calendar and chat.
- **Team lead, manager** — review and approve your team's tasks and reports, and see performance.
- **HR** — employee records, attendance, leave and payroll settings.
- **Admin** — every organization setting, permissions, license and integrations.

Admins can also create custom roles with fine-grained permissions for ERP modules (for example Accountant or Sales). See [People & access](/docs/admin-people) for details.

## Manager and member view

Users with management rights can switch between the **Manager view** and the **Personal view**. In the personal view every page shows only your own data, which is handy for focusing on your own work without management information. The switch sits in the sidebar (on a phone, in the **More** menu).

## Modules and licensing

Modules such as Contracts, CRM, Budget and Payroll are on or off depending on your organization's license and admin settings. If a module is missing from your menu, it has not been enabled for your organization or you have not been given access.`,

  'docs.article.sign-in.title': 'Signing in and security',
  'docs.article.sign-in.summary': 'Ways to sign in, resetting your password, two-step verification and the app’s biometric lock.',
  'docs.article.sign-in.body': `## Signing in

The sign-in page offers two options:

- **Username and password** — enter the username and password you received from your admin or HR.
- **Continue with Telegram** — if your Telegram ID is linked to your employee record, sign in with one tap.

You may be asked to replace a temporary password the first time you sign in. New passwords need at least 10 characters.

## Forgot your password

1. On the sign-in page, click **Forgot your password?**.
2. Enter the email address on your account.
3. Use the one-time link from the email to set a new password.

If the email doesn't arrive, check your spam folder; if it is still missing, contact your admin.

## Two-step verification

If your organization requires two-step verification, you will be asked for an extra code after your password.

1. The first time: scan the on-screen QR code with Google Authenticator, Microsoft Authenticator, Authy or 1Password.
2. Enter the 6-digit code from the app.
3. Store the 10 recovery codes somewhere safe — they are shown only once.

On every later sign-in, enter either a code from the app or one of your recovery codes. After 5 wrong codes the account is locked for 15 minutes.

> **Lost your phone?** Your admin can reset your two-step verification. You then set it up again on the new phone.

## Biometric app lock

In the mobile app, you can turn on a fingerprint or Face ID lock with the **App lock** card under **Profile**. Once on, the app asks you to confirm it's you every time it opens and after it has been in the background for more than a minute. If biometrics are unavailable, your phone's screen lock is used instead.

## Logging out

Click your name at the bottom of the sidebar and choose **Log out**. On a phone, it is at the very bottom of the **More** menu.`,

  'docs.article.navigation.title': 'Interface and navigation',
  'docs.article.navigation.summary': 'The sidebar, global search, notifications, the account menu and mobile navigation.',
  'docs.article.navigation.body': `## Sidebar

The sidebar on the left reflects your permissions and the modules that are switched on. Daily tools (Today, Worktime, Chat, Calendar) come first, then tasks and reports, projects and plans, contracts, analytics, the ERP modules, and **Settings** at the end. **Company files** and your account button sit at the bottom of the sidebar.

## Global search

Press **Ctrl + K** (**⌘ + K** on a Mac) or click the search icon in the header. From one window you can:

- search tasks, people and files;
- jump to any part of the menu;
- run quick actions such as **Create task**, **Create contract** and **Upload file**.

## Header

The top of each page shows the page title, the notification bell, search, the OYUNS AI assistant and the employee list. The number on the bell is your unread notification count; clicking a notification opens the related page.

## Account menu

Click your name at the bottom of the sidebar to open:

- **Profile** — personal details, language and notification settings;
- **Docs** — this documentation;
- the light and dark mode switch;
- **Log out**.

## On a phone

On screens narrower than 800 pixels the sidebar is hidden and a five-button bar appears at the bottom: Today, Calendar, Tasks, Chat and **More**. The **More** menu holds every module, the view switch, the employee list, dark mode, the guide and log out. Pull a page down to refresh it.

## Language

The interface is available in Mongolian, Russian and English. Change your language in [Profile](/docs/profile); the choice is saved for all your devices.`,

  'docs.article.profile.title': 'Profile and notifications',
  'docs.article.profile.summary': 'Personal details, language, username and password, and notification settings.',
  'docs.article.profile.body': `## Opening your profile

Click your name at the bottom of the sidebar and choose **Profile**. On a phone, tap the avatar at the top.

## Personal details

Update your name, photo, phone, direction, office and similar details in your profile. Organizational details such as job title, department and roles are changed by HR or an admin.

## Language

Choose Mongolian, Russian or English in the **Language** field and save. The interface switches straight away and stays that way the next time you sign in.

## Username and password

Change your username and password in your profile. If you signed in with Telegram, you can set a new username and password without entering a current password — this lets you sign in to the web workspace without Telegram.

## Notification settings

On the **Notifications** card, choose for each category (tasks, reports, work time, calendar, contracts, HR, CRM, payroll, digests and so on) whether to receive notifications, and whether on the platform or via Telegram. If your organization has locked a category, it appears disabled.

## Mobile app settings

In the app, your profile shows two more cards:

- **Automatic work time** — your work time starts and stops automatically when you enter and leave the office zone. See [Worktime](/docs/worktime) for details.
- **App lock** — the app asks for a fingerprint or Face ID every time it opens.`,

  'docs.article.today.title': 'Today',
  'docs.article.today.summary': 'Build your home page from widgets and follow your day from one screen.',
  'docs.article.today.body': `## Home page

**Today** is your personal dashboard, opened right after you sign in. It is made of widgets whose position and size you arrange yourself. Your layout is saved to your account and looks the same on other devices.

## Available widgets

| Widget | Shows |
|---|---|
| World clock | Current time in chosen cities |
| Work time | Today's record with start and stop buttons |
| Performance indicators, Single indicator | KPIs for this or last week |
| Quick actions | Search, the AI assistant and common actions |
| Tasks | Tasks assigned to you; for managers, organization tasks too |
| News and announcements | News published by your organization |
| Calendar | Upcoming events |
| Timer, Notes | Personal tools |

## Editing

1. Click **Edit** at the top of the page (on a phone, long-press a widget).
2. Drag a widget to move it; drag its bottom-right corner to resize it.
3. From the **Add a widget** panel, drag a new widget onto the page or press **+**.
4. Use a widget's **Settings** button to change its options (for example the KPI period or time zones) and its size.
5. Click **Done** when finished.

**Reset layout** returns the page to the default layout.

## Keyboard shortcuts

In edit mode, select a widget and use the arrow keys to move it, **Shift + arrow** to resize it, and **Delete** to remove it.`,

  'docs.article.worktime.title': 'Worktime',
  'docs.article.worktime.summary': 'Starting your workday, breaks, checking in by QR or location, and automatic time tracking.',
  'docs.article.worktime.body': `## Starting your workday

Start your workday from the **Worktime** page or from the widget on **Today**. Depending on your organization's settings, these methods are available:

- **Office QR** — scan the QR code on the office display. The code refreshes every 30 seconds, so it can only be scanned on site.
- **By location** — inside the office zone, press **Start by location**. Your browser or the app will ask for location permission.
- **Remote** — start in remote mode when working from home or elsewhere.
- **Simple** — if your organization has turned off both QR and location, a button press is enough.

## Breaks and finishing

While working, take a **Break** and resume when you are back. To end the day, press the finish button; if you started with a QR code, scan the office QR again to finish. During a break, you need to end the break first.

If you are working remotely and then scan the QR in the office, remote time is closed and office time begins.

## Automatic time tracking (mobile app)

If your organization has enabled it, you can turn on **Automatic work time** under **Profile** in the app.

- Your work time starts automatically when you enter the office zone.
- When you leave, it stops at the moment you left, after a grace period (10 minutes by default). Come back within that period and nothing changes.
- The phone only reports the moments you enter and leave the zone; your coordinates are not stored.
- Each user can track automatically from one phone only.
- With a mocked location or poor accuracy, your time is left unchanged and the record is flagged for review.

> **Test mode:** while your organization is trialling automatic tracking, the phone detects the zone but your time is not changed — keep recording your time as usual.

## History and statistics

The lower part of the page shows daily records, total hours worked and the office/remote split. Managers and HR can download employee statistics as CSV or Excel.`,

  'docs.article.tasks.title': 'Tasks',
  'docs.article.tasks.summary': 'Create and assign tasks and follow progress on the kanban board.',
  'docs.article.tasks.body': `## The task board

The **Tasks** page is a kanban board with **Backlog**, **To do**, **In progress**, **In review** and **Done** columns. Drag a card to change its status. Besides the **Board**, there are **List** and **Calendar** views.

## Creating a task

1. Click **Create task**, or press **Ctrl + K** → **Create task**.
2. Enter a title, description, assignee, start and due dates, and priority (1 — Urgent, 2 — Normal, 3 — Low urgency).
3. Add a place (office or remote), subtasks and attachments if needed.

Employees can create tasks for themselves; which roles may assign tasks to others is set by an admin under **Settings → People & access → Roles & permissions**.

## Review and approval

When the assignee finishes, they move the task to **In review**. The person who assigned it checks the work and marks it **Done** or sends it back. Overdue tasks trigger a reminder to the assignee and, depending on settings, a notice to management.

## Notifications

You are notified on the platform, on your phone and in Telegram when a task is assigned to you, someone comments, or a deadline approaches. You can also create and list tasks through the Telegram bot — see [Telegram bot](/docs/telegram).

## Management view

In the manager view you see all of your team's tasks, and the **Organization** tab shows organization-wide tasks. The personal view keeps only tasks assigned to you or created by you.`,

  'docs.article.calendar.title': 'Calendar',
  'docs.article.calendar.summary': 'Meetings, events, task deadlines and public holidays in one calendar.',
  'docs.article.calendar.body': `## Views

The **Calendar** has day, week and month views. Events, task deadlines, leave and the public holidays your organization has configured all appear together. Use the filters to hide or show each type.

## Creating an event

1. Click an empty slot in the calendar, or the create button.
2. Choose a title, date, time and participants.
3. For the location, enter a Google Meet or Zoom link, or an office address.

Participants are notified and the event appears in their calendars.

## Checking availability

Before scheduling a meeting, look at the participants' schedules for that day to avoid conflicts.

## On a phone

On a phone the calendar is shown as a list and you swipe between days. Add the calendar widget to **Today** to see upcoming events at a glance.`,

  'docs.article.chat.title': 'Chat',
  'docs.article.chat.summary': 'Direct and group chats, sharing tasks and reports, voice and video calls.',
  'docs.article.chat.body': `## Starting a conversation

On the **Chat** page, start a new message and pick a colleague, or several people to create a group. You can also click a name in the employee list (in the header) and choose **Chat**.

## Unread messages

The number on **Chat** in the menu is your unread message count. Opening a conversation marks it as read.

## Sharing work (the / menu)

Type **/** in the message box to open a list of active tasks, plans, contract drafts and reports. The item you choose is sent as a card.

- The list only shows items you are allowed to see.
- If the recipient may not open the item, the card says **You do not have permission to open this** — a card never grants access by itself.

## Calls

Use the phone and camera buttons in the conversation header to start voice and video calls. Your browser will ask for microphone and camera permission.

## Chatting with OYUNS AI

The chat list includes an **OYUNS Agent** conversation. Talk to it in writing or start a voice call with the 📞 button — see [OYUNS AI assistant](/docs/assistant).`,

  'docs.article.reports.title': 'Reports',
  'docs.article.reports.summary': 'Writing, submitting and approving periodic reports, and overdue reports.',
  'docs.article.reports.body': `## Report types

Your organization decides how often employees report: daily, weekly, monthly, quarterly, half-yearly, yearly, or a custom period (for example a two-week sprint). Departments can have their own frequency, and the department report is written by the department head.

## Writing a report

1. On the **Reports** page, the report for the current period is created for you, or you open a new one with the create button.
2. The report period is calculated from the date you choose.
3. Write the content and click **Submit**.

You get a reminder a few days before the period ends.

## Overdue reports

After a period ends, you can still submit its report for the number of days your organization allows. It is marked as **previous period** in the list.

## Statuses

| Status | Meaning |
|---|---|
| Draft | Being written, not submitted |
| Pending | Submitted, waiting for approval |
| Editing | Returned for changes |
| Approved | Approved by management |

## Approval (management)

In the manager view you see your team's reports. Open a report to **Approve** it or send it back. Admins and managers can use **Download report** to export many reports (Markdown or ZIP) and get an OYUNS AI summary. The AI works only from the report text — it does not invent figures that are not in the reports.`,

  'docs.article.plans-projects.title': 'Plans and projects',
  'docs.article.plans-projects.summary': 'The company plan, employee suggestions, project management and team capacity.',
  'docs.article.plans-projects.body': `## Company plan

The **Plans** page shows each month's company plan on three levels: strategic objectives, quarterly objectives and this month's work. Management adds and edits items; employees see the approved plan.

## Employee suggestions

On the **Employee suggestions** tab, employees submit ideas for next month's plan. When management approves a suggestion it becomes an item in the company plan; similar suggestions can be merged.

## Projects

On the **Projects** page every project has **Overview**, **Tasks** and **Settings** tabs. Project tasks are the same data as the main task board, so you can edit them from either place.

## Team capacity

**Team capacity** (for management) compares planned work with each person's available hours for the chosen period, showing who is overloaded or free and where leave overlaps.`,

  'docs.article.news-files.title': 'News and company files',
  'docs.article.news-files.summary': 'Publishing organization news and using the internal file library.',
  'docs.article.news-files.body': `## Reading news

Published news appears in the **News and announcements** widget on **Today**. Featured posts stay at the top.

## Publishing news (management)

Admins, managers and team leads open the news page from the icon in the news widget header.

1. Click **Add news** and enter a title, a short summary and a category.
2. Format the text with the Markdown toolbar and check the preview.
3. Add a cover image and up to 12 images (PNG, JPEG or WebP, up to 8 MB).
4. Save as a draft or publish straight away.

Admins and managers can edit and feature any post; team leads edit only their own. Archive posts that are out of date.

## Company files

**Company files**, at the bottom of the sidebar, is your organization's shared library of folders and files.

- Create folders and upload files (**Ctrl + K** → **Upload file**).
- Set access permissions for each folder.
- Deleted files go to the trash, where you can restore them.`,

  'docs.article.assistant.title': 'OYUNS AI assistant',
  'docs.article.assistant.summary': 'Ask the AI assistant about your organization’s data, have it draft tasks, or talk to it by voice.',
  'docs.article.assistant.body': `## Opening it

Open the assistant from the OYUNS AI icon in the header, the **Quick actions** widget, or the **OYUNS Agent** conversation in chat.

## What it can do

Within your permissions, the assistant reads your organization's data:

- your own and your team's tasks, including overdue work;
- work time and attendance;
- reports, plans, projects and suggestions;
- HR information, CRM customers and interactions, contracts;
- payroll summaries for users who are allowed to see them;
- the company knowledge base maintained by your admin.

It also helps plan your day, write and summarize text, and prepare task drafts for you to confirm.

## Example questions

- “Which of my tasks are overdue this week?”
- “How many hours did I work yesterday?”
- “Create a task for Bat: report meeting tomorrow at 10.”
- “Summarize last month's CRM interactions.”

## Permissions and privacy

The assistant never gives you access you don't have — it only uses data you can already see. Admins can restrict what the assistant may read or create in each module. Payroll information is not shown in group chats. Every organization's data is kept separate.

## Voice calls

Use the 📞 button in the OYUNS Agent chat to talk to the assistant. The call starts in your interface language; for Mongolian it uses Chimege speech recognition and synthesis. During a call the assistant only reads data and does not change anything.`,

  'docs.article.telegram.title': 'Telegram bot and Mini App',
  'docs.article.telegram.summary': 'Connecting to your organization’s Telegram bot, getting notifications and working through the bot.',
  'docs.article.telegram.body': `## Connecting to the bot

Each organization has its own Telegram bot. When HR registers you, they send an invite link — open the bot with it and press **Start** to link your Telegram account to your employee record. HR can also enter your Telegram ID directly; send **/myid** to the bot to find yours.

Unregistered Telegram users, or users from another organization, cannot use the bot — it shows the organization's name and your Telegram ID and suggests contacting an admin or HR.

## What the bot does

- Sends notifications about tasks, reports, work time, the calendar and more, with an **Open** button.
- Reminds you about report and task deadlines.
- Lets you talk to the OYUNS AI assistant with free text and voice messages; it can reply by voice too.
- Shows a menu based on your role: management sees extra commands.

The bot's permissions come only from your roles in the ERP.

## Common commands

| Command | Action |
|---|---|
| /task | Create a task, e.g. “/task @name prepare report tomorrow” |
| /mytasks | Tasks assigned to me |
| /assigned | Tasks I assigned to others |
| /myid | Show your Telegram ID |

## Mini App

The bot's menu button opens the task board (Overdue, Open, In progress, Done) inside Telegram.

## Quiet hours

Notifications are sent on the workdays and hours your organization has set; anything created during quiet hours is delivered at the next allowed time.`,

  'docs.article.hr.title': 'HR',
  'docs.article.hr.summary': 'Employee records, departments, attendance, leave and employee statistics.',
  'docs.article.hr.body': `## Employee directory

The **Employee directory** tab on the **HR** page lists every employee. HR and admins add new employees and edit their details: name, job title, department, registration number, contact details and Telegram ID.

- The Telegram ID can only be entered once the organization's Telegram bot is connected.
- The **Inactive** status disables sign-in and excludes the employee from payroll and daily questionnaires.

## Employee menu

Use the **⋯** menu on an employee row to edit, grant sign-in access, change roles or deactivate. The employee panel shows payroll settings, platform access and work-time statistics (download as CSV or Excel).

## Departments and units

Add and edit departments and assign their heads. Deactivate departments that still have employees instead of deleting them. The department head writes the department report.

## Leave and attendance

- **Leave** — leave requests and approvals, and setting annual leave balances.
- **Attendance** — the daily attendance grid, office and remote hours, and the location log of automatic time tracking (admins and HR only).

## Seat limit

You can still register employees when all license seats are in use, but to grant new sign-in access you need to upgrade the plan or deactivate unused accounts.`,

  'docs.article.analytics.title': 'Analytics and reporting',
  'docs.article.analytics.summary': 'Performance metrics, the work hour hierarchy and report exports.',
  'docs.article.analytics.body': `## Analytics page

The **Analytics** page shows team performance for a chosen period: task completion, overdue work, report submission and work time.

## Work hour hierarchy

The **Work Hour Hierarchy** chart breaks down hours worked into office and remote at organization, department and employee level. Click a level to drill down.

## KPI details

Click a metric card to open the tasks and employees behind it.

## Report export and AI summary

With **Download report** on the **Reports** page, admins and managers can:

- filter by period, employee and department (optionally approved reports only);
- preview, then download one report as Markdown or many as a ZIP (folders by employee or department);
- get an OYUNS AI summary based on KPIs and report text, and ask follow-up questions.

Every export and summary is recorded in the audit log.`,

  'docs.article.contracts.title': 'Contracts and archive',
  'docs.article.contracts.summary': 'Drafting contracts, review, signing, the contract register and the archive.',
  'docs.article.contracts.body': `## Contract workflow

A contract moves through steps from draft to signature: write the draft, send it to reviewers, collect comments and revise, approve, sign, and archive. A contract can be opened by its author, its reviewers and admins.

## Creating a contract

1. On the **Contracts** page, click the create button or press **Ctrl + K** → **Create contract**.
2. Write the contract text in the editor and add attachments.
3. Fill in the **Contract register** section: internal code (generated if left blank), official number, group, counterparty (from CRM), signing date, quantity, unit price, amount, currency, penalty and payment terms.
4. Send it to reviewers.

## Register and filters

Filter the contract list by counterparty, group, active status and period, and search by code, number or counterparty. Each row shows days overdue and the number of files. The **Contracts** tab on a CRM customer card lists all of that customer's contracts.

The number, active status, links and notes can be edited at any stage. Inactive contracts get no deadline reminders.

## Printing

Open the print version from the contract page; it prints in your interface language.

## Archive

The **Contract archive** keeps signed contracts and older contract files uploaded by hand. Admins and legal counsel can complete the **Contract register** details for each archive entry.`,

  'docs.article.crm.title': 'CRM',
  'docs.article.crm.summary': 'Customer records, interactions, imports and reminders.',
  'docs.article.crm.body': `## Layout

**CRM** has three tabs: **Interactions**, **Customers** and **Settings**. Access is granted by an admin through ERP roles (for example Sales).

## Customers

When adding a customer, enter the name, registration number or tax ID, group, responsible person and tags (comma-separated). If the code is left blank, one is assigned automatically starting at 10001. You are warned if a customer with the same tax ID or registration number exists — if you are adding a branch of a multi-branch organization, check and continue.

A customer card has **Overview**, **Contacts**, **Bank accounts**, **Interactions**, **Contracts**, **Documents**, **Files** and **History** tabs.

## Interactions

Record meetings, calls, emails and other interactions, with time spent, outcome and next step. Select several customers to add one interaction to all of them. The responsible person is reminded about scheduled interactions.

## Import

In **Import customers**, download the template, fill it in as an Excel (.xlsx) or CSV file, and upload it. In the group column, enter the name of an existing group.

## Settings

The **Settings** tab manages lookups such as customer groups, interaction types and statuses.`,

  'docs.article.budget.title': 'Budget and performance',
  'docs.article.budget.summary': 'Building budgets, comparing them with recorded actuals, and variance analysis.',
  'docs.article.budget.body': `## Budget

The **Budget** page holds the list of budgets, an editor for each one, **Analysis** and **Budget accounts**. Access is granted through ERP roles (accountants and admins; managers and team leads can view, create and edit).

## Sign rules

- Enter income as positive (+) and cost of sales and expenses as negative (−). Amounts with the wrong sign are rejected.
- Actual = credit − debit on the linked accounts.
- So **variance = actual − expected** is always good when positive.

The “expected” amount is prorated by the number of days up to the selected date.

## Budget accounts

Link each budget account to one or more accounts in the chart of accounts. An account from the chart can be linked to only one budget account. Income budget accounts are offered only income accounts, and expense budget accounts only expense accounts.

## Analysis

**Analysis** compares plan, expected amount, actuals and variance by account and period.`,

  'docs.article.accounts.title': 'Chart of accounts',
  'docs.article.accounts.summary': 'Adding and grouping accounts, bank details, and seeing where an account is used.',
  'docs.article.accounts.body': `## Layout

The **Accounts** page shows the chart of accounts as a tree (group → sub-account). Filter by class (assets, liabilities, equity, income, expenses) and status.

## Adding an account

1. Click **Add account** on the right of the filter row.
2. Choose the code, name, class, purpose, currency and parent group.
3. For cash and bank accounts, add bank details such as the bank name and account number.

The parent must be an active group of the same class. The account's internal type is derived automatically from its purpose.

## Usage

Select an account and open **Usage** to see which modules use it (ledger, documents, parties, tax, settings, budget, payroll).

## Protection

The code, class, purpose, currency and group flag of an account used in transactions or settings cannot be changed. Such an account is archived rather than deleted. The name can still be changed.`,

  'docs.article.payroll.title': 'Payroll',
  'docs.article.payroll.summary': 'Monthly payroll runs, inputs, Excel import, approval and settings.',
  'docs.article.payroll.body': `## Who uses it

The **Payroll** module is available to admins and HR, and the organization must have it switched on.

## Monthly payroll flow

1. Create the month's run — base salaries of active employees and hours worked are pulled from time tracking.
2. Enter inputs such as overtime, allowances, deductions and advances in the table.
3. Social insurance, personal income tax and the remaining salary are calculated automatically.
4. Review, approve, and generate the accounting entries.

Hover over a **Hours worked** cell to see the day-by-day breakdown.

## Excel input

Download the spreadsheet template — its columns follow the payroll table and it is pre-filled with current values. Edit and upload it; only the cells you changed are updated.

## Settings

The **Payroll settings** page has cards for general settings, overtime and social insurance, advances, deductions and account mapping. Salary expense and employer social insurance map to expense accounts; advances map to an asset or expense account. Click **Save settings** after making changes.

## Employee payroll settings

Each employee's base salary, pay dates and advance terms are set from the employee panel on the **HR** page.`,

  'docs.article.admin-organization.title': 'Organization settings',
  'docs.article.admin-organization.summary': 'Profile and branding, modules, and a custom domain.',
  'docs.article.admin-organization.body': `## Profile and branding

Under **Settings → Organization → Profile & branding**, set the organization's name, logo, favicon and primary color. Branding applies to the sign-in page and the whole interface.

## Modules and features

Turn the CRM, Budget and Payroll modules on or off under **Modules & features**. Each enabled module adds its own menu item. Modules not included in your license cannot be selected.

## Custom domain

Under **Custom domain**, set up the platform to open on your own domain (for example erp.company.mn).

1. Add the domain name.
2. Add the CNAME and TXT records shown to your domain's DNS.
3. When the domain and SSL certificate are active, the status changes to **verified** (this can take a few minutes).

## Public holidays

Under **Work time & workflows**, choose the country whose public holidays appear in the calendar.`,

  'docs.article.admin-people.title': 'People and access',
  'docs.article.admin-people.summary': 'Creating users, assigning roles, and setting up custom roles and module permissions.',
  'docs.article.admin-people.body': `## Employees and users

Under **Settings → People & access → Employees & users**, manage the accounts that can sign in: grant access, set temporary passwords, lock and restore. An account is active, invited or locked.

## Seats

The license limits the number of active, invited and locked accounts. Used and total seats are shown at the top of the page. When the limit is reached, you need to upgrade the plan to grant new access or restore inactive users.

## Platform roles

| Role | Main permissions |
|---|---|
| Employee | Own work |
| Team lead | Team tasks and reports |
| Manager | Organization-wide oversight |
| HR | Employees, attendance, leave, payroll |
| Legal counsel | Contracts and archive |
| Admin | All settings |

## Building roles

Create custom roles (for example “Accountant” or “Sales”) under **Roles & permissions**:

1. Enter the role name and description.
2. Optionally add platform roles (employee, manager, HR and so on — anything except admin).
3. Choose module permissions (view, create, edit, approve).
4. Assign it to employees or whole teams and save.

Roles without holders can be deleted or deactivated.

## Task assignment

This section also sets which roles may assign tasks to others.`,

  'docs.article.admin-worktime.title': 'Work time and workflows',
  'docs.article.admin-worktime.summary': 'Time tracking methods, the QR display, office zones, automatic time tracking and the report policy.',
  'docs.article.admin-worktime.body': `## Time tracking methods

Under **Settings → Work time & workflows**, turn QR and location check-in on separately:

- QR on, location off — office time can only be started by QR.
- Both off — office time starts without any check.

## Connecting a QR display

1. Under **Work Time QR display**, enter a display name and click **Create pairing code**.
2. On the office screen or tablet, open **erp.oyuns.mn/worktimeqr**.
3. Enter the 8-character code. The display shows a new QR every 30 seconds.

Each code works for one display only. If the connection drops, click **Pair again** to get a new code.

## Office zones

Set the office location on the map or with **Use current location**, and enter a radius (25–5000 m). You can have up to 20 active zones.

## Automatic time tracking

The **Automatic work time** mode can be **Off**, **Test** (records only, never changes time) or **On**. Before switching it on, confirm the employer notice. You also set the grace period after leaving, the location accuracy threshold and how many days the log is kept. Only admins and HR can see the location log.

## Report settings

Under **Report settings**, configure:

- employee report frequencies (daily, weekly, monthly, quarterly, half-yearly, yearly, custom periods);
- for each frequency, the start (for example a month starting on the 26th or a fiscal year starting in July), reminder days and hour, and how many days overdue reports are still accepted;
- a different frequency per department, and the department report written by its head.

## Check-in and schedules

The daily check-in questions and employee schedules are set up in this section too.`,

  'docs.article.admin-integrations.title': 'Integrations and notifications',
  'docs.article.admin-integrations.summary': 'Connecting the Telegram bot, the organization’s notification policy and management notifications.',
  'docs.article.admin-integrations.body': `## Connecting the Telegram bot

1. In Telegram, create a new bot with @BotFather and copy its token.
2. Enter the token under **Settings → Automation & integrations → Telegram bot**.
3. Open the bot with the link shown and press **Start** — the bot becomes active and is linked to your Telegram admin account.

Once the bot is connected, HR can enter employees' Telegram IDs and send invites. The token is stored encrypted.

## Notification settings

Under **Notification settings (all users)**, for each category (tasks, reports, work time, calendar, contracts, HR, CRM, payroll, digests, check-in, system):

- turn notifications on or off;
- choose the platform and Telegram channels;
- decide whether employees may change it themselves.

## Management Telegram notifications

Choose who receives management digests and overdue alerts from the employees who have Telegram. This list only decides who receives notifications — it grants no permissions.

## Quiet hours and digests

Under **Notifications & Telegram**, set workdays, quiet hours and the times of the morning and evening digests. Notifications created during quiet hours are delivered at the next allowed time.`,

  'docs.article.admin-ai.title': 'OYUNS AI settings',
  'docs.article.admin-ai.summary': 'AI model and key, access permissions, the knowledge base and voice technology.',
  'docs.article.admin-ai.body': `## Model and API key

Under **Settings → OYUNS AI & learning** (admins only), enter an OpenAI API key and choose a model. The key is stored encrypted, and **Test connection** checks it. Changes take effect within a minute.

## Access permissions

The **AI assistant access** matrix sets, for each module, whether the assistant may **Read** and **Create & edit**. This setting can only narrow a user's own permissions — never widen them. Sections you have not configured are treated as allowed.

## Knowledge base

Add company policies, answers to common questions and similar material to the knowledge base (PDF, Office documents, TXT, CSV, images, up to 20 MB). The assistant uses active articles when answering.

## Voice technology

- **Chimege · Mongolian speech** — tokens for Mongolian speech recognition and synthesis, each with its own switch. **Test Chimege** synthesizes a sentence and recognizes it back.
- **ElevenLabs** — API key, voice and model.
- **Call engine** — Auto (Chimege for Mongolian, OpenAI Realtime for other languages), OpenAI, Chimege or ElevenLabs.`,

  'docs.article.admin-security.title': 'Security and license',
  'docs.article.admin-security.summary': 'Requiring two-step verification, resetting a user’s codes and activating the license.',
  'docs.article.admin-security.body': `## Requiring two-step verification

Under **Settings → System & security → Sign-in & administration → Two-step verification**, require two-step verification for every user in the organization. The card shows the total number of accounts and how many have set it up.

- Once on, each user is asked for a code on their next request.
- Turning it off does not delete users' setups.

## Resetting a user's 2FA

If a user loses their phone, select them on the same card and click **Reset**. Every active session of that user loses its verification, and they set it up again at their next sign-in.

> **If your only admin has lost access,** contact OYUNS support — they can remove 2FA or issue a temporary password.

## License and activation

**License & activation** shows the active license's expiry, plan and seat count. Enter a new license key here to activate it. When the license expires, only the activation page is available.`,

  'docs.article.faq.title': 'Frequently asked questions',
  'docs.article.faq.summary': 'Common problems and how to solve them.',
  'docs.article.faq.body': `## A module is missing from my menu

The module may not be enabled for your organization, not included in your license, or you may not have access. Also check whether the **Personal view** is active. Ask your admin about permissions.

## I can't start my work time

- When starting **by location**, check the browser or app location permission.
- You may be outside the office zone — use the QR code instead.
- If the QR code **has already been used**, wait for the display to show a new code and scan again.
- If you are on a break, end the break first.

## The QR display is offline

Check the internet connection and reload the **/worktimeqr** page. If the connection does not recover, an admin creates a new pairing code.

## Automatic time tracking isn't working

- Has your organization set the mode to **On**? (Test mode never changes your time.)
- Does the app have “Always” location permission?
- On Android, is the app excluded from battery optimization?
- Have you registered another phone? Each user can use one phone.

## The Telegram bot doesn't respond

If the bot does not recognize you, your Telegram ID is not on your employee record. Send **/myid** to the bot and give the ID to HR.

## I'm not getting notifications

Check the notification settings in your [Profile](/docs/profile) and your organization's quiet hours. On a phone, OYUNS notifications must be allowed in the system settings.

## My two-step verification code doesn't work

Make sure your phone's clock is set automatically — the codes depend on the time. You can use a recovery code. If you lost your phone, your admin can reset your 2FA.

## Need more help

Contact your organization's admin or HR. For platform issues, write to info@oyuns.mn.`,
}
