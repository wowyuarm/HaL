# HaL Desktop Status And Tauri Notes

Status: current working note
Date: 2026-04-07

Read this first before touching HaL desktop work again.

## Current Choice

Right now we are **not** using Tauri as the daily entry.

We are using:
- WSL to run `hal web --dev`
- Windows Edge app window to show `http://127.0.0.1:3000`

Reason:
- this is mostly for self-use
- we do not need packaging yet
- Edge app window already gives a separate work window
- this avoids the WSL-to-Windows Tauri friction for now

Chrome is not needed at the moment.
It could also do app mode, but Edge is already present and works for the current flow.

## Current Daily Flow

Keep the repo work in WSL.
Use the WSL-side launcher here:

`~/.local/bin/hal-desktop`

That script does two things:
- starts `hal web --dev` in WSL
- opens HaL in a Windows Edge app window

This is the current desktop workflow.

We tried moving this launcher fully to Windows-side scripts.
That turned out less stable because the WSL-side Node environment did not come through cleanly enough.
So for now the launcher stays user-local in WSL, not in the repo.

## What We Already Built

The desktop direction is not empty. We already have the main first step inside the web app:

- top thread tabs inside the current workspace
- each tab keeps its own selected thread and session
- changing thread inside a tab replaces that tab
- current live session flow still works

So even without Tauri as the daily entry, the web app already moved closer to a workbench.

## What Exists For Future Tauri Work

We already have a Tauri starting point in the repo:

- `web/src-tauri/`
- Tauri packages in `web/package.json`
- the current web app can already be built inside a thin Tauri shell

This means we are not starting from zero later.
The rough shell is there if we decide it is worth picking back up.

## Why Tauri Is Parked For Now

Tauri still matters later if we want:
- a real standalone desktop app
- deeper local file handling
- tray, notifications, or other system abilities
- less dependence on browser behavior

But for the current phase, it is not the best daily path because:
- the repo lives in WSL
- the main use is personal, not distribution
- Edge app window already gives most of the benefit we care about right now

## When To Resume Tauri

Pick Tauri back up when at least one of these becomes important:
- Edge app mode starts to feel limiting
- local file handling needs to be more native
- we want real desktop behavior, not just a separate window
- Windows-native packaging becomes worth the extra work

## First Resume Steps

If we come back to Tauri later, start here:

1. Re-check `web/src-tauri/`
2. Re-check `web/package.json`
3. Verify `cd web && npm run tauri build`
4. Decide whether daily dev should move off Edge app mode

## Simple Picture

```text
Now
Windows Edge app window
        ^
        |
WSL runs hal web --dev

Later if needed
Tauri shell
   |
current web app
```
