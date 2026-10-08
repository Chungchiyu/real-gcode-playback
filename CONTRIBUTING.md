# Contributing

Thanks for helping with Real G-code Playback. Issues and pull requests are welcome.

## Making changes

1. Edit the files in `src/` (never edit `dist/orca_playback.py` by hand; it is generated).
2. Rebuild: `npm install` once, then `python3 build.py`.
3. Run the tests: `test/run_all.sh`.
4. Commit your changes together with the rebuilt `dist/orca_playback.py`.

See the Development section of [README.md](README.md) for what each file does.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/) titles: `type: short description`, lower case, no version numbers.

| type | for |
|---|---|
| `feat` | a new feature users can see |
| `fix` | a bug fix |
| `perf` | faster or lighter, same behaviour |
| `refactor` | code changes that change no behaviour |
| `test` | tests only |
| `docs` | README, CONTRIBUTING, comments |
| `ci` | GitHub Actions workflows |
| `build` | build.py, package.json |
| `chore` | anything else, including releases (`chore: release v1.5.0`) |

Examples: `feat: colour by fan speed`, `fix: playback ran too fast after bed leveling`.

## Releases: changing the version releases it

**A push to `main` that changes `"version"` in `src/changelog.json` publishes that version.**
GitHub Actions then creates the GitHub release `v<version>` and uploads the plugin to Orca Cloud, where users get it as an update.
Commit messages play no part in this; pushes that leave the version alone never release anything.

- The release notes come from that version's entry in `src/changelog.json`.
- A release is refused if the version already has a release, is not higher than the latest one, has no changelog entry, or `dist/orca_playback.py` was not rebuilt.

To release:

1. Add an entry at the top of `src/changelog.json` with a higher version and short, user-facing notes, and set `"version"` at the top of the file to the same number:
   ```json
   { "version": "1.5.0", "date": "2026-10-20", "changes": ["Short description of what changed"] }
   ```
2. Run `python3 build.py`.
3. Commit (`chore: release v1.5.0`, or together with the change itself) and push to `main`.

To try a build before publishing it, leave the version alone while you work, and bump it only when you are ready.
If a version was bumped but not released, open **Actions → Release on push → Run workflow** to release it.

Pull requests: a merged pull request that changes the version releases it, so only maintainers should bump the version.
Pushes to forks don't release anything: they don't have the repository's `RELEASE_TOKEN` secret, and Orca Cloud only accepts uploads from this repository.

Full details, including the one-time setup, are in the Releasing section of [README.md](README.md#releasing).
