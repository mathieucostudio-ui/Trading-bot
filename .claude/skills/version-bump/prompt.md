# Skill: version-bump

Bump the project version, update the changelog, and tag the release.

## Steps

1. **Determine bump type** from argument or context:
   - `major`: breaking change to strategy logic (e.g. new entry model)
   - `minor`: new feature, new pair, new session filter
   - `patch`: bug fix, parameter tweak, documentation

2. **Read current version** from `pyproject.toml` or `src/__init__.py`

3. **Compute new version** following semver: `MAJOR.MINOR.PATCH`

4. **Update version** in:
   - `pyproject.toml` (if present): `version = "X.Y.Z"`
   - `src/__init__.py` (if present): `__version__ = "X.Y.Z"`

5. **Update CHANGELOG.md**:
   - Run `/trading-changelog` to generate the new section
   - Ensure the version header matches the new version number

6. **Commit and tag**:
   ```bash
   git add pyproject.toml src/__init__.py CHANGELOG.md
   git commit -m "chore: bump version to X.Y.Z"
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   ```

7. **Report**: Print the new version and the list of changes included in this release.

## Do not

- Do not push to remote (user must explicitly push)
- Do not bump version if there are uncommitted changes unrelated to this release
- Do not create a GitHub release (user decides when to publish)
