# John Monash — User Guide

This guide is for the people who use the application: team members running a
project in it. It explains how to create an account, sign in, set up a project,
organise a team, run sprints and track work. You do not need to know anything
about programming to follow it.

If you are looking for installation, configuration or deployment information,
see the [technical guide](technical-guide.md) instead.

---

## Contents

1. [What this application does](#1-what-this-application-does)
2. [Before you start](#2-before-you-start)
3. [Creating your account](#3-creating-your-account)
4. [Signing in](#4-signing-in)
5. [If you forget your password](#5-if-you-forget-your-password)
6. [The projects dashboard](#6-the-projects-dashboard)
7. [Creating a project](#7-creating-a-project)
8. [Getting around inside a project](#8-getting-around-inside-a-project)
9. [The project description and status](#9-the-project-description-and-status)
10. [Members](#10-members)
11. [Roles and permissions](#11-roles-and-permissions)
12. [Sprints](#12-sprints)
13. [The sprint board (Kanban)](#13-the-sprint-board-kanban)
14. [Tasks in detail](#14-tasks-in-detail)
15. [The product backlog](#15-the-product-backlog)
16. [History, contributions and effort](#16-history-contributions-and-effort)
17. [Your account settings](#17-your-account-settings)
18. [Troubleshooting](#18-troubleshooting)

---

## 1. What this application does

John Monash is a small project-management tool for a team. In it you can:

- create a project and invite the people working on it;
- give each person a role that decides what they are allowed to do;
- plan work into sprints (short, dated blocks of work);
- move tasks across a Kanban board as they progress;
- record how much time each task took, and see who has contributed what.

Everything is stored on a server, so the same project can be opened from any
computer by anybody on the team.

---

## 2. Before you start

You need:

- **A web browser.** A current version of Chrome, Edge, Firefox or Safari. The
  application runs Python in the browser, so a very old browser will not work.
- **A working email address.** A six-character code is emailed to it when you
  sign up. Forgetting this step is the most common reason a new account cannot
  sign in.
- **The address of the application.** Your team will have given you a link; the
  deployed version is the one named `fit2101-frontend` on Render. Every page
  lives under `/src/views/`, and the first page you open should be `login.html`.

> **First load is slow.** The application downloads its Python runtime the first
> time you open it. Expect up to half a minute on a slow connection, and a short
> pause on later visits while it starts. A free Render service also goes to
> sleep when unused, so the very first request of the day can take a few seconds.

---

## 3. Creating your account

1. Open the login page and choose **Sign up** (or go to `signup.html`).
2. Fill in a **display name**, your **email address**, a **password** and the
   same password again to confirm it.
   - Your display name is what teammates see. It must be unique, so if the name
     is taken the form will say so.
   - The password must be at least 8 characters. It is used exactly as you type
     it, including any spaces at the start or end, so type it the same way every
     time.
3. Press **Sign up**. You are taken to a verification page.
4. **Check your email** for a message titled *Your Verification Code*. It
   contains a six-character code such as `K7QM2H`. Type it into the page. The
   code is not case-sensitive.
5. Press the button to verify. You are told the account is verified, and you can
   now sign in.

**If the email does not arrive**

- Wait a minute and check your spam or junk folder.
- On the verification page press **Send code** again. There is a 60-second
  cooling-off period between requests, so if you press it too early the page
  asks you to wait.
- A verification code is valid for 24 hours.

**If you did not verify in time**

An unverified account is deleted automatically 24 hours after it was created.
Simply sign up again with the same address; that restarts the clock and sends a
fresh code.

---

## 4. Signing in

1. Open `login.html`.
2. Type the email address and password you registered with.
3. Press **Log in**.

Things that can stop you:

| Message | What it means | What to do |
|---|---|---|
| *Email is not registered* | No account uses that address. | Sign up, or check for a typo. |
| *Incorrect password. 2 attempt(s) remaining…* | The password is wrong. The count tells you how many tries you have left. | Try again carefully. |
| *Account locked for 30 seconds* | Three wrong passwords in a row lock the account briefly. | Wait for the countdown on the login button, then try again. It grows with repeated failures. |
| *Account is unverified…* | You have not entered your email code yet. | You are taken to the verification page automatically. Enter the code, or request a new one. |

Email addresses are not case-sensitive: `Alex@Example.com` and `alex@example.com`
are the same account.

To sign out, use the sign-out control in the top bar. Closing the browser tab
signs you out of that tab.

---

## 5. If you forget your password

1. On the login page choose **Forgot password?**.
2. Enter your email address and press the button to request a code.
3. Check your email for *Password Reset Code* and type the six characters into
   the form along with a new password (at least 8 characters).
4. Press the reset button. You are returned to the login page and can sign in
   with the new password.

Notes:

- A reset code is valid for **15 minutes** and allows **five** guesses. After
  that it is discarded and you must request a new one.
- You can request a new code every 60 seconds.
- A successful reset also clears any lockout from earlier wrong passwords.
- The reset works even while the account is locked out.

---


## 6. The projects dashboard

After signing in you land on the dashboard, which lists every project you belong to.

**The sidebar**

- **All Projects** — show everything.
- **Project Status → Active / Completed** — show only projects in that state.
  Clicking the filter that is already on turns it off again.
- **Settings** at the bottom opens your account settings.

**The top of the page**

- **Search** filters the cards as you type. It looks at the project name and its
  description, and if you type several words every one of them has to match.
- **Sort** reorders the cards: *Newest first*, *Oldest first*, *Status*
  (Active before Completed) or *Name* (A–Z).

**A project card** shows the project name, its description, a status badge
(Active or Completed) and the date the project was created. Click anywhere on a
card to open that project.

If you are the Project Creator, a Scrum Master or a Product Owner, each card
also carries a small button in its bottom-right corner: **Mark completed**, or
**Reopen project** once it is completed. It changes the status without opening
the project.

---

## 7. Creating a project

1. On the dashboard press **Create** (the button beside the page title).
2. Give the project a **name** and a **description**.
3. Press **Create project**. The project is created and opened for you.

You start as its **Project Creator**, which is the highest role in the project:
you can do everything in it, including deleting it. Other members start empty —
invite them from the Members tab.

---

## 8. Getting around inside a project

Every project has the same sidebar:

| Item | What it shows |
|---|---|
| **Description** | The project description, who last edited it and when, and the status control. |
| **Members** | Everybody on the project and the role they hold. |
| **Roles** | The roles this project has, what each one may do, and the roles you can create yourself. |
| **Sprints** | The project's sprints, product backlog, change history, contributions and effort. |
| **Delete Project** | Only shown to a role that may delete the project (the Project Creator by default). |

The address of each page carries the project, for example
`project-page.html?project_id=4`. That means you can bookmark a page, or send the
link to a teammate who is a member of the same project.

---

## 9. The project description and status

**Description.** The Description tab shows the project's description and a small
line underneath it saying who last changed it and when. If you are a **Project
Creator, Scrum Master or Product Owner** you also see **Edit Description**: press
it, change the text, and press **Save**. The description cannot be left empty.
Everyone else sees the description but not the button.

**Status.** Next to the project title is a badge, either *Active* or *Completed*.
The same three roles see the button beside it:

- **End Project** marks the project Completed. You are asked to confirm first.
- **Reopen Project** puts a completed project back to Active.

Ending a project does not hide or delete anything: its sprints, boards and
history stay exactly where they were, and you can reopen it at any time.

---

## 10. Members

Open the **Members** tab to see who is on the project. People are listed by role,
most senior first, and each one shows the role they hold.

**Adding somebody**

1. Press **Add Member**.
2. Pick the person from the list, or type their username exactly.
3. Confirm. They are added straight away, in the **Employee** role.

Only people who already have an account can be added. If somebody is missing
from the list, ask them to sign up first.

**Removing somebody**

Removing needs the *manage_members* permission (Project Creator, Scrum Master
and Product Owner have it). Turn on **Remove** mode, then press **Remove** on the
person's card.

- You cannot remove somebody whose role ranks at or above your own. A Manager
  cannot remove a Scrum Master, and nobody can remove a peer.
- The only Project Creator cannot be removed. Give somebody else that role first.
- Removing a member takes them out of the project's roles and out of the sprints
  they were in. The tasks they were holding stay on the board but become
  unassigned, and the history keeps a note that they were removed.

---


## 11. Roles and permissions

Every action inside a project is allowed or refused by a **permission**. Permissions
are grouped into **roles**, and people hold roles. Somebody can hold more than one
role at a time and their permissions add up; the Members tab shows their most
senior role.

### The five preset roles

These exist in every project and cannot be deleted or edited, because the rest of
the application is built on them.

| Role | What it is for | Can do |
|---|---|---|
| **Project Creator** | The owner of the project; the person who created it. | Everything, including deleting the project. |
| **Scrum Master** | Runs the sprint cycle and the team. | Everything except deleting the project. |
| **Product Owner** | Owns the backlog and the sprint content. | Everything except deleting the project. |
| **Manager** | Runs sprints and tasks day to day. | Create/end sprints, move and manage tasks, review work. |
| **Employee** | A regular contributor. | Move tasks forward, create and edit tasks. |

### What each permission allows

| Permission | Allows |
|---|---|
| `edit_project` | Edit the project description and change its status (end / reopen). |
| `delete_project` | Delete the project and everything in it. |
| `manage_members` | Add members and remove them. |
| `manage_roles` | Create, edit and delete custom roles. |
| `assign_roles` | Give a role to a member, or take it away. |
| `manage_sprints` | Create, end and delete sprints. |
| `edit_sprints` | Move tasks forward along the board. |
| `manage_tasks` | Create, edit and delete tasks. |
| `review_tasks` | Move work into and out of Review and Completed, and post review feedback. |

### Creating your own role

1. Open the **Roles** tab and press **Create Role**.
2. Give it a **name**, a **colour** (used for its badge) and a **description**.
3. Tick the **permissions** it should have. Each one explains itself underneath.
4. Optionally tick **conflicting roles** — see below.
5. Save. The role now exists but has no members yet; assign it from the role's
   own page or from a member's card.

### Conflicting roles

Some roles should never be held by the same person — a *Reviewer* who must not
also be the *Author*, for example. When you tick a role under **Conflicting Roles
(Mutually Exclusive)**, the server refuses to give anybody both roles; the second
assignment fails with a message naming the two roles.

The check works in both directions, but the tick boxes are per role. If you want
the rule to read the same whichever page you look at, tick each role on the other
one as well.

### Editing, deleting and assigning

- **Edit** a role from its own page (colour, description, permissions, conflicts).
  Preset roles can be viewed but not changed.
- **Delete** a custom role. Everybody who held it simply loses those permissions;
  their other roles are untouched. You cannot delete a preset.
- **Assign** a role to a member from that role's page. *Project Creator, Scrum
  Master and Product Owner are single-seat roles* — only one person can hold each
  at a time, so remove the current holder first. Manager and Employee can have as
  many holders as you like.

---

## 12. Sprints

A **sprint** is a dated block of work with its own board. Open the **Sprints** tab
of a project to see the sprint cards, the product backlog, and the Change History,
Contributions and Effort views.

### Creating a sprint

Only a **Project Creator, Scrum Master, Product Owner or Manager** can create a
sprint; the button is hidden for everybody else.

1. Press **Create Sprint**.
2. Fill in a **name** and, if you like, **details** (a short description that is
   shown at the top of the sprint's own page).
3. Choose **start** and **end** dates. The end date cannot be before the start
   date, and cannot be in the past. A sprint is completed automatically once its
   end date has passed.
4. Pick a **priority** (High, Medium or Low) and optional **tags**.
5. Choose the **members**. Only people on the project are offered. The project's
   leadership — Project Creator, Scrum Master, Product Owner — is ticked and
   cannot be unticked, because they take part in every sprint.
6. Press **Create**.

### Working with sprints

- Click a sprint card to open its **board**.
- A sprint is **Active** until it is ended, either by pressing **End Sprint** or
  automatically when its end date passes.
- **End Sprint** freezes the board: nothing on it can be changed afterwards, and a
  sprint cannot be reopened. You are asked to confirm.
- **Delete Sprint** removes a sprint and everything on its board. It is not
  offered for an ended sprint, which is kept as the record of what was finished.

Ending and deleting need the *manage_sprints* permission.

---


## 13. The sprint board (Kanban)

Open a sprint card to see its board. Every sprint has four columns, and a task
moves left to right as it progresses:

| Column | Means |
|---|---|
| **Sprint Backlog** | In this sprint, not started yet. |
| **Active** | Somebody is working on it. |
| **Review** | Finished, waiting to be checked. |
| **Completed** | Done and accepted. |

**Moving a task.** Drag a card into another column, or use the arrow buttons on
the card. What you are allowed to do depends on your role:

- Moving a task **forward** needs *edit_sprints* — every preset role has it.
- Moving a task **into Review or Completed**, or **backwards**, needs
  *review_tasks* (Project Creator, Scrum Master, Product Owner and Manager).
- A completed task cannot be dropped from the board or moved back: it is the
  record of finished work.

The board is frozen once the sprint has ended, and every change is recorded in
the project's Change History.

---

## 14. Tasks in detail

Click a task to open it. From here you can change:

- **Title, tags, priority** (High, Medium, Low) and **description**.
  Tags are typed as a comma-separated list; they are tidied up for you.
  Only members of this sprint can edit a description, and it is limited to about
  1,000 characters.
- **Assignee** — who owns the task. Only people on the project can be assigned,
  and an unassigned task shows nobody.
- **Start and end date** — the end date cannot fall after the sprint's own end.
- **Checklist** — add as many items as you like and tick them off. A task cannot
  be completed while items are still unticked.
- **Review feedback** — visible to everyone, posted by people holding
  *review_tasks*.
- **Time** — use **Start**, **Pause**, **Resume** and **Log Time** to record work
  you did. Logged time is what appears in the contribution figures.
- **Delete Task** — needs *manage_tasks*, and is not offered for a completed task.
- **Return to Backlog** — puts a task back on the product backlog. Only available
  while the task is still in the *Sprint Backlog* column, only for members of the
  sprint, and never once work time has been logged against it.

---

## 15. The product backlog

The product backlog is the list of everything the project might do, before it is
planned into a sprint. It sits in the Sprints tab, listed on the left.

- **Add an item**: press **Create Task**, then give it a title, optional tags, a
  priority and a description. It joins the product backlog, not a sprint.
- **Plan it into a sprint**: drag the backlog item onto a sprint card. It becomes
  a card in that sprint's *Sprint Backlog* column.
- **Take it back out**: from the task window, press **Return to Backlog**.

---

## 16. History, contributions and effort

Three views in the Sprints tab read the same data in different ways.

**Change History** records what happened and when — tasks created, moved,
completed or deleted, sprints ended, members removed. It is newest first, and the
newest 500 entries per project are kept.

**Contributions** shows, for each member of the project: how many tasks they are
assigned, how many they have completed, and how many hours of work they logged.

**Effort** breaks the same logged time down in more detail, so you can see where
the hours went.

---


## 17. Your account settings

Open **Settings** from the sidebar of any page.

**Profile**

- Change your **display name**. It has to be unique across the application.
- Upload a **profile picture** (PNG, JPEG or WebP, up to about 300 KB — the page
  shrinks most phone photos for you). Press Remove to go back to the default
  avatar.

**Email address**

1. Type the new address.
2. Type your **current password**. This is required: it proves the change is
   being made by the account holder.
3. Press **Send verification email**. A confirmation link goes to the *new*
   address, and the page shows the pending address until you click it.
4. Open the link. Your address changes; until then nothing changes at all.

**Change password**

Enter your current password, then the new one twice. The new password must be at
least 8 characters. Changing your password does **not** sign you out elsewhere,
so change it from a device you trust.

**Delete account**

Under *Danger Zone*, press **Delete Account** and confirm with your password. This
is permanent. What happens to your work:

- you are removed from every project;
- projects where you were the only member are deleted entirely;
- your tasks stay on their boards, unassigned;
- if you held a role, the remaining members keep theirs, and a project left
  without a Project Creator promotes its most senior member;
- your history entries stay, so the project's record is not rewritten.

---

## 18. Troubleshooting

**I cannot sign in.**

- *Email is not registered* — there is no account with that address. Check for
  typos, or sign up.
- *Account is unverified* — you have not entered the six-character code from your
  email. The page takes you to the verification form; if the code is lost, press
  **Send code** again.
- *Account locked* — three wrong passwords lock the account for 30 seconds, and
  the wait grows if it keeps happening. Use the countdown, or reset the password.
- *Incorrect password* — passwords are matched exactly, including spaces. If you
  copied it from somewhere, check for a trailing space.

**The email never arrives.**

Check spam. Ask the person who runs the deployment whether email delivery is
configured — when it is not, the application still works but no messages are sent
and the codes only appear in the server log. Press **Send code** again after a
minute.

**A button is missing.**

Most controls only appear for the roles that may use them: *End Project* and
*Edit Description* need Project Creator, Scrum Master or Product Owner;
*Create Sprint* needs Manager or above; *Delete Project* needs the Project
Creator. If a teammate has the button and you do not, it is a role question —
ask somebody who can assign roles.

**"Access forbidden" or "Missing required permission".**

The same rule, seen from the server: your role does not include that permission
in this project. Nothing is broken and nothing was saved.

**The page looks out of date.**

Reload the page with **Ctrl+F5** (or Cmd+Shift+R). The application caches its
Python modules in the browser, and a hard reload is the reliable way to pick up a
new version.

**Everything is slow the first time.**

On the free hosting plan the API sleeps when nobody has used it for a while, and
the first request has to wake it. The first page load of a session also downloads
and starts the Python runtime. Give it a few seconds.

**My project disappeared from the dashboard.**

Check the sidebar: an *Active* or *Completed* filter may be on, or the search box
may still hold text. Click **All Projects** and clear the search.

**I was signed out.**

The session is kept in the browser tab. A new tab, a cleared cache or a different
browser needs a fresh sign-in.

---

## Getting help

If something does not behave as this guide describes, contact the team who runs
the deployment and tell them:

- the page you were on (copy the address — it contains `project_id`);
- what you clicked and what you expected;
- any message shown on screen.

That is enough for them to reproduce it. The technical guide explains how the
application is built and deployed, and is the next thing they will read.
