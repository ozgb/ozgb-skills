# Spec: comment-cleanup skill (clean-room rewrite)

Behavioural spec for a skill that tidies code comments. The implementer writes
`skills/comment-cleanup/SKILL.md` from this document alone.

## Clean-room rules for the implementer

- Work only from this spec. Do not open the existing
  `skills/comment-cleanup/SKILL.md`, its git history, any installed copy (e.g.
  `~/.agents/skills/comment-cleanup`), or any gist or blog post on the topic.
- Use your own wording, structure, headings and examples. The behaviour below
  is the requirement; how it is phrased and organised is up to you.
- Target: a single `SKILL.md`, roughly 100–170 lines, written for an agent
  reader: imperative, concrete, no filler.

## Packaging

- Path: `skills/comment-cleanup/SKILL.md`, Agent Skills format.
- Frontmatter `name: comment-cleanup`.
- Frontmatter `description`: write fresh. It must make the skill trigger when a
  user asks to clean up, trim, prune, audit or review code comments, complains
  that comments are too verbose or read as AI-written, or asks for a comment
  pass on a file, diff or PR before committing. It must also make clear the
  skill can be invoked by name.

## Behaviour

### 1. Scope and invariants

- The skill edits **comments and docstrings only**. Executable code must come
  out byte-identical, apart from removing blank lines left orphaned by deleted
  comments.
- No renames, refactors or logic changes, even when a comment only exists to
  explain confusing code. Such a comment stays, and the confusing code is
  reported as a refactor candidate.
- Input can be one or more files, a staged/unstaged diff, or a PR. When given a
  diff, only comments in changed hunks are in scope.

### 2. Default stance

- A comment justifies itself by telling the reader something the code cannot:
  intent, a constraint, a hazard, a workaround, or why an obvious alternative is
  wrong.
- Uncertainty is asymmetric. Unsure whether a rationale comment is needed: keep
  it. Unsure whether a descriptive comment is needed: remove it. Losing a real
  warning is worse than keeping a mediocre comment.

### 3. Classification

Evaluate every in-scope comment. The first matching category decides.

| Category | Recognised by | Action |
|---|---|---|
| Describes the code | Paraphrases the next line(s), lists the steps, repeats identifiers or types, marks the end of a block | Remove |
| Addresses a reviewer | Talks about the change, not the code: "now uses X", "removed Y", "per review", "fixed bug in Z". Test: would it make sense to someone reading the file cold, years later? | Remove |
| Wrong | Describes behaviour the code no longer has | Correct it if the underlying point still matters, otherwise remove |
| Unstable reference | See §4 | State the substance inline, or remove |
| Rationale, but bloated or misplaced | See §5 | Trim, split or relocate |
| Anything else | | Keep unchanged |

Do not reword a comment that is already correct and minimal; rewording a good
comment just adds diff noise. "Correct but wordy" is not minimal, so it falls
under §5.

### 4. References

The question is whether the target can change while the comment still points at
it.

- **Stable, OK to cite:** ticket/issue IDs and links, wiki pages addressed by
  permanent URL, permalinks, docs maintained in the same repo at a fixed path,
  and published, versioned standards, *including their section numbers* (e.g.
  `RFC 9110 §8.3`, `ISO 8601`, `EIP-1559`, `CIP-30`).
- **Unstable, do not cite:** "the spec" or "the requirements" with no stable
  address, design docs (snapshots that get superseded), and section/heading
  numbers in any document that can be edited after the fact.
- A citation is supporting evidence, never the content. Every surviving comment
  must still say something useful if its link is removed. "See ABC-123" on its
  own must become a statement of the actual constraint, followed by `(ABC-123)`.
- If the code needed no comment at all (e.g. a note that it complies with a
  spec), remove the comment instead of rewriting it.
- These rules apply inside docstrings as well as line comments.

### 5. Tightening rationale comments

Keeping a comment and keeping its wording are separate decisions. For every
comment that survives:

- Reduce it to the one fact the reader needs at that line, in as few words as
  will carry it. Remove anything the code already shows, downstream
  consequences, restated names and context the reader already has. Sometimes
  the answer is to remove it entirely.
- A long header block covering several points should become short comments
  placed next to the lines each point governs.
- **System-level narrative** (architecture choices, benchmark results, lifecycle
  overviews):
  - If a stable doc already covers it, remove it inline; do not leave a
    "see doc" pointer.
  - If no doc covers it, keep it and report it as a candidate for moving into
    one. Writing the doc is out of scope.
  - What stays inline is only the local constraint, e.g. "must stay below the
    health-check interval" or "keep in sync with Y". A comment that is nothing
    but a pointer to a doc is removed.
- Length is fine when every part is load-bearing (e.g. a workaround, the bug it
  works around, and when it can be removed). Never shorten by dropping
  information.

### 6. Protected comments

These look removable but must be kept:

- **Sync obligations:** "mirrors X", "same rule as Y", "keep in sync with Z".
  The link is what stops the copies drifting apart.
- **Meaning of literals:** units, ordering or encoding of a constant or table
  ("cents", "(lat, lon)", "big-endian").
- **Output contracts:** format pinned to an external consumer ("matches the
  CSV header the finance export expects").
- **Section dividers** (`# ---- Parsing ----` style): navigation, so keep them
  unless the user asks otherwise. Any substance in them is protected like other
  rationale.

### 7. TODO / FIXME

- Keep them; no issue ID is required.
- If the work is visibly done, it is wrong → remove.
- If it looks like work that should already be in scope (e.g. "TODO: validate
  input" on an input path), keep it and report it. Removing it would hide
  unfinished work.

### 8. Docstrings

- All of the above applies.
- A docstring that only restates the name and parameter types is description →
  remove or reduce.
- A docstring that gives the contract (units, valid ranges, side effects,
  failure behaviour, invariants, preconditions, what has already been done to
  the inputs) is kept. Shrinking it to a one-line summary is only allowed if no
  contract is lost.
- A one-line summary on a public function, endpoint or API surface is always
  acceptable: consumers read it without reading the body.

### 9. Report

After editing, give a short report:

1. Per file: counts of comments removed / rewritten / kept.
2. Flags for things outside the skill's scope: refactor candidates, TODOs that
   may hide unfinished work, comments kept because their correctness couldn't
   be verified, and narrative worth moving into a doc.
3. Judgement calls: one line per borderline decision, so the user can override.

Do not list each removed descriptive comment.

## Acceptance cases

The implementer writes their own examples for the skill. These cases are for
checking the result. Run the finished skill on each snippet and compare the
output with the expected result.

1. `i += 1  # increment i` → comment removed, code unchanged.
2. `# switched to the async client` above a call → removed.
3. `# see design doc §4.2` above a retry loop whose backoff is non-obvious →
   replaced with the actual rule (e.g. "backoff capped at 30s: upstream drops
   clients retrying faster") or removed if the loop is self-explanatory.
4. `# Per RFC 9110 §15.5.2, 404 here, not 403` → kept verbatim.
5. `# keep in sync with validate_order() in api/orders.py` → kept.
6. `TIMEOUT = 1500  # ms` → kept.
7. A five-line comment block whose only non-obvious content is "must run before
   the cache warms" → reduced to about one line saying that.
8. `# TODO: add caching` above code that already caches → removed.
9. `# TODO: handle errors` on a network call with no error handling → kept and
   flagged.
10. A cryptic one-liner with a comment explaining it → comment kept, line
    flagged as a refactor candidate, code untouched.
11. Any run: `git diff` shows only comment and blank-line changes.

## Out of scope

- Adding new comments where there are none.
- Writing or editing docs that rationale is extracted to.
- Enforcing a house style for comment syntax (capitalisation, punctuation).
