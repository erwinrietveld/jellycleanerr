# Development Setup

This repository is your public fork (`origin`) and tracks upstream Sanitarr (`upstream`).

## 1. One-time setup

```bash
git clone https://github.com/erwinrietveld/jellycleanerr.git
cd jellycleanerr
git remote add upstream https://github.com/serzhshakur/sanitarr.git
git fetch upstream
```

Verify:

```bash
git remote -v
```

## 2. Local dev prerequisites

- Docker
- Git

Rust does not need to be installed locally. The `Makefile` runs Rust tooling inside a dev container.

## 3. Daily workflow

Sync your fork with upstream:

```bash
git checkout master
git fetch upstream
git rebase upstream/master
git push origin master
```

Create a feature branch:

```bash
git checkout -b feat/<short-name>
```

Run checks:

```bash
make lint
make test
```

Build runtime image:

```bash
make image
```

Run one-shot dry run:

```bash
make run-dry CONFIG=/absolute/path/to/config.toml
```

Run one-shot force delete:

```bash
make run-force CONFIG=/absolute/path/to/config.toml
```

## 4. Push and PR

```bash
git add .
git commit -m "feat: <message>"
git push -u origin feat/<short-name>
```

Open a PR from your branch into `master`.

## 5. Release flow (GitHub + GHCR)

The repository already has a workflow that publishes Docker images and creates a GitHub release on tags.

1. Bump `version` in `Cargo.toml`.
2. Merge into `master`.
3. Tag the release:

```bash
git checkout master
git pull
git tag v<version>
git push origin v<version>
```

This triggers image publishing to `ghcr.io/<owner>/<repo>` and a GitHub release.
