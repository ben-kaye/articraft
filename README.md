# articraft

Generate articulated 3D objects from prompts and inspect them locally.

## 1. Install Prerequisites

You need:

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- [`just`](https://github.com/casey/just)
- [`npm`](https://docs.npmjs.com/downloading-and-installing-node-js-and-npm) if you want the viewer and frontend hooks ready locally

If you do not have `just` yet:

```bash
# macOS with Homebrew
brew install just

# cross-platform installer
curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to ~/bin
export PATH="$PATH:$HOME/bin"
```

## 2. Run Setup

From the repo root:

```bash
just setup
```

This does the initial local setup:

- creates `.env` from `.env.example` if `.env` does not exist yet
- installs Python dev dependencies, including `pre-commit` and `ruff`
- installs `viewer/web` dependencies when `npm` is available
- installs the git `pre-commit` and `pre-push` hooks
- initializes local storage under `data/`
- builds the dataset manifest used by the viewer

## 3. Add Your API Key

Open `.env` and set one provider key:

```text
Set `OPENAI_API_KEY` to your OpenAI key in `.env`
```

or:

```text
Set `GEMINI_API_KEYS` to your Gemini keys in `.env`
```

## 4. Generate Your First Object

Run:

```bash
just wb "Create a realistic articulated desk lamp with a weighted base, two hinged arms, and an adjustable lamp head."
```

This saves a generated record into the local workbench.

If you do not pass a model or thinking level, `just wb` defaults to:

```bash
model=gpt-5.4
thinking=high
```

## 5. Try Another Model

Examples:

```bash
just wb "Create a folding office chair with rolling casters and a reclining backrest." model=gpt-5.4
just wb "Create a compact tabletop fan with an oscillating head and tilt adjustment." model=gemini-3-flash-preview
just wb "Create a tower crane with a rotating top and suspended hook." model=gpt-5.4 thinking=high
```

## 6. Open the Viewer

After you have generated something:

```bash
just viewer
```

This starts the local API, builds the web app if needed, and opens the viewer.

If you just cloned the repo and want to avoid first-click compile pauses in the viewer, precompile saved records first:

```bash
just compile-all
```

This walks the saved records, recompiles the ones that still need generated artifacts, and shows a progress bar while it runs.

For live frontend development:

```bash
just viewer-dev
```

## 7. A Few Useful Commands

List commands:

```bash
just
```

Rebuild the viewer search index:

```bash
just search-index
```

Recompile a saved record:

```bash
just compile data/records/<record-id>
```

Precompile all saved records that are still missing generated artifacts:

```bash
just compile-all
```
